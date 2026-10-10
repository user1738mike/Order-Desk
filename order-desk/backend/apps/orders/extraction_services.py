"""Short authorized job transitions; parsing never holds tenant/database locks."""

from datetime import timedelta
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.orders import selectors
from apps.orders.csv_extraction import PARSER_VERSION, ExtractionFailure, extract_csv
from apps.orders.models import DocumentExtractionJob, ExtractionJobStatus
from apps.orders.pdf_extraction import extract_pdf
from apps.orders.private_documents import open_document
from apps.orders.services import _locked_order, _require_editable_order, _require_writer
from apps.organizations.transactions import tenant_scope

LEASE_SECONDS = 120
PDF_RETRYABLE_ERRORS = frozenset(
    {"source_unavailable", "parser_unavailable", "parser_timeout"}
)


def parser_version(content_type):
    return {"text/csv": PARSER_VERSION, "application/pdf": "order-text-pdf-v1"}.get(
        content_type
    )


def can_retry(job):
    return (
        job.status == ExtractionJobStatus.FAILED
        and job.attempts < 3
        and (
            job.parser_version == PARSER_VERSION
            or job.error_code in PDF_RETRYABLE_ERRORS
        )
    )


def enqueue_extraction(*, actor, organization_id, order_id, document_id, materialize):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        _require_editable_order(
            _locked_order(organization_id=organization_id, order_id=order_id)
        )
        document = selectors.get_private_document(
            organization_id, order_id, document_id
        )
        if (
            parser_version(document.content_type) is None
            or not document.file.name.startswith("intake/")
            or not document.source_sha256
        ):
            raise ValidationError(
                {
                    "document": "Extraction requires a verified private "
                    "CSV or PDF source."
                }
            )
        job, created = DocumentExtractionJob.objects.get_or_create(
            organization_id=organization_id,
            document=document,
            source_sha256=document.source_sha256,
            parser_version=parser_version(document.content_type),
            defaults={"requested_by": actor},
        )
        return materialize(job), created


def retry_extraction(*, actor, organization_id, order_id, document_id, materialize):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        _require_editable_order(
            _locked_order(organization_id=organization_id, order_id=order_id)
        )
        job = selectors.get_extraction_job(organization_id, order_id, document_id)
        if not can_retry(job):
            raise ValidationError(
                {"job": "Only a failed job with attempts remaining can be retried."}
            )
        job.status = ExtractionJobStatus.QUEUED
        job.error_code = ""
        job.error_row = None
        job.save(update_fields=["status", "error_code", "error_row", "updated_at"])
        return materialize(job)


def process_extraction(*, actor, organization_id, job_id):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        job = selectors.get_extraction_job_by_id(organization_id, job_id)
        now = timezone.now()
        if job.status not in (ExtractionJobStatus.QUEUED, ExtractionJobStatus.RUNNING):
            return job.status
        if job.status == ExtractionJobStatus.RUNNING and job.lease_expires_at > now:
            return "leased"
        if job.attempts >= 3:
            job.status = ExtractionJobStatus.FAILED
            job.error_code = "attempts_exhausted"
            job.claim_token = job.lease_expires_at = None
            job.save()
            return job.status
        job.status = ExtractionJobStatus.RUNNING
        job.attempts += 1
        job.claim_token = uuid4()
        job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        job.processed_by = actor
        job.save()
        token = job.claim_token
        document = job.document
        source = (document.file.name, document.size_bytes, job.source_sha256)
        order_id = document.order_id
        source_matches = document.source_sha256 == job.source_sha256
    result, pages, metrics, failure = [], [], {}, None
    try:
        if not source_matches:
            raise ExtractionFailure("source_changed")
        with open_document(*source) as stream:
            if job.parser_version == PARSER_VERSION:
                result = extract_csv(stream)
            elif (
                job.parser_version == "order-text-pdf-v1"
                and document.content_type == "application/pdf"
            ):
                parsed = extract_pdf(stream)
                result, pages, metrics = (
                    parsed["result"],
                    parsed["pages"],
                    parsed["metrics"],
                )
            else:
                raise ExtractionFailure("source_changed")
    except ExtractionFailure as error:
        failure = error
    except OSError:
        failure = ExtractionFailure("source_unavailable")
    # Unexpected exceptions deliberately leave the durable lease for recovery;
    # do not fabricate success or expose exception text/source contents.
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        current = selectors.get_extraction_job_by_id(organization_id, job_id)
        if (
            current.status != ExtractionJobStatus.RUNNING
            or current.claim_token != token
        ):
            return "superseded"
        if current.lease_expires_at <= timezone.now():
            return "lease_expired"
        document = current.document
        if (document.file.name, document.size_bytes, document.source_sha256) != source:
            failure = ExtractionFailure("source_changed")
        try:
            _require_editable_order(
                _locked_order(organization_id=organization_id, order_id=order_id)
            )
        except ValidationError:
            failure = ExtractionFailure("order_locked")
        current.result = [] if failure else result
        current.result_pages = [] if failure else pages
        current.parser_metrics = {} if failure else metrics
        current.status = (
            ExtractionJobStatus.FAILED if failure else ExtractionJobStatus.SUCCEEDED
        )
        current.error_code = failure.code if failure else ""
        current.error_row = failure.row if failure else None
        current.claim_token = current.lease_expires_at = None
        current.save()
        return current.status
