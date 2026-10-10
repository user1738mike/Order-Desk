"""Capture/claim/publish in short tenant scopes; format and stream outside locks."""

import io
from datetime import UTC, timedelta
from uuid import uuid4

from django.db import DatabaseError, connection
from django.db.models.functions import Substr
from django.shortcuts import get_object_or_404
from django.utils import timezone
from psycopg.types.json import Jsonb

from apps.orders.csv_export import (
    PROFILE,
    ExportBlocked,
    ExportUnavailable,
    format_csv,
    validate_payload,
)
from apps.orders.models import PurchaseOrderExport, PurchaseOrderLine
from apps.orders.private_documents import open_document, staged_document
from apps.orders.selectors import get_export_order as get_purchase_order
from apps.orders.services import _require_writer
from apps.organizations.transactions import tenant_scope

LEASE_SECONDS = 120


def snapshot(order):
    lines = (
        PurchaseOrderLine.objects.filter(
            organization_id=order.organization_id, order_id=order.pk
        )
        .annotate(export_description=Substr("description", 1, 4097))
        .order_by("line_number", "id")[:501]
    )
    return {
        "order_id": str(order.pk),
        "source_draft_id": str(order.source_draft_id),
        "order_number": order.purchase_order_number,
        "order_date": order.created_at.astimezone(UTC).date().isoformat(),
        "customer_name": order.customer_name,
        "lines": [
            {
                "id": str(line.pk),
                "line_number": line.line_number,
                "sku": line.sku,
                "description": line.export_description,
                "quantity": str(line.quantity),
                "unit": line.unit,
            }
            for line in lines
        ],
    }


def revision(payload):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT encode(sha256(convert_to(%s::jsonb::text, 'UTF8')), 'hex')",
            [Jsonb(payload)],
        )
        return cursor.fetchone()[0]


def eligibility(order):
    errors = []
    for condition, code in (
        (not order.source_draft_id, "not_converted"),
        (order.status != "approved", "not_approved"),
        (not order.is_active, "inactive_order"),
    ):
        if condition:
            errors.append({"path": "order", "code": code})
    return errors


def export_metadata(record):
    if record is None:
        return None
    return {
        "id": str(record.pk),
        "organization_id": str(record.organization_id),
        "order_id": str(record.order_id),
        "profile": record.profile,
        "source_revision": record.source_revision,
        "status": record.status,
        "attempts": record.attempts,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "error_code": record.error_code,
        "created_at": record.created_at,
        "completed_at": record.completed_at,
        "lease_expired": record.status == "running"
        and record.lease_expires_at <= timezone.now(),
        "download_url": f"/api/v1/workspaces/{record.organization_id}/orders/"
        f"{record.order_id}/exports/{record.pk}/download/"
        if record.status == "succeeded"
        else None,
    }


def record_for(order, source_revision):
    return PurchaseOrderExport.objects.filter(
        organization_id=order.organization_id,
        order_id=order.pk,
        profile=PROFILE,
        source_revision=source_revision,
    ).first()


def preview(*, actor, organization_id, order_id):
    with tenant_scope(user=actor, workspace_id=organization_id) as context:
        _require_writer(context)
        order = get_purchase_order(organization_id, order_id)
        payload = snapshot(order)
        source_revision = revision(payload)
        errors = eligibility(order) + validate_payload(payload)
        record = export_metadata(record_for(order, source_revision))
        state = {
            "id": str(order.pk),
            "organization_id": str(organization_id),
            "source_draft_id": str(order.source_draft_id)
            if order.source_draft_id
            else None,
            "status": order.status,
            "is_active": order.is_active,
        }
    if not errors and (record is None or record["status"] != "succeeded"):
        try:
            format_csv(payload)
        except ExportBlocked as error:
            errors = error.blockers
    return payload, source_revision, errors, record, state


def _fail(actor, organization_id, order_id, record_id, token, code):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        record = PurchaseOrderExport.objects.get(
            pk=record_id, organization_id=organization_id, order_id=order_id
        )
        if record.status == "running" and record.claim_token == token:
            record.status, record.error_code = "failed", code
            record.claim_token = record.lease_expires_at = None
            record.save(
                update_fields=[
                    "status",
                    "error_code",
                    "claim_token",
                    "lease_expires_at",
                    "updated_at",
                ]
            )


def generate_export(*, actor, organization_id, order_id, validate_input):
    # Resolve permission/parent before parsing untrusted mutation inputs.
    payload, source_revision, errors, _, _ = preview(
        actor=actor, organization_id=organization_id, order_id=order_id
    )
    validate_input()
    if errors:
        raise ExportBlocked(errors)
    # Formatting is bounded and outside transactions; no staged partial on failure.
    data = None
    with tenant_scope(user=actor, workspace_id=organization_id) as context:
        _require_writer(context)
        existing = record_for(
            get_purchase_order(organization_id, order_id), source_revision
        )
        already_complete = existing is not None and existing.status == "succeeded"
    if not already_complete:
        data = format_csv(payload)
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = get_purchase_order(organization_id, order_id)
        if errors := eligibility(order):
            raise ExportBlocked(errors)
        if revision(snapshot(order)) != source_revision:
            raise ExportUnavailable()
        record = record_for(order, source_revision)
        if record is not None and record.status == "succeeded":
            result, code = export_metadata(record), 200
            storage = (record.storage_key, record.size_bytes, record.sha256)
        elif (
            record is not None
            and record.status == "running"
            and (record.lease_expires_at > timezone.now())
        ):
            return export_metadata(record), 202
        else:
            if record is not None and record.attempts >= 3:
                raise ExportBlocked(
                    [{"path": "artifact", "code": "attempts_exhausted"}]
                )
            token = uuid4()
            if record is None:
                record = PurchaseOrderExport(
                    organization_id=organization_id,
                    order=order,
                    profile=PROFILE,
                    source_revision=source_revision,
                    payload=payload,
                    created_by=actor,
                    generated_by=actor,
                )
            else:
                record.attempts += 1
            record.status, record.error_code = "running", ""
            record.generated_by, record.claim_token = actor, token
            record.lease_expires_at = timezone.now() + timedelta(seconds=LEASE_SECONDS)
            if record._state.adding:
                record.save()
            else:
                record.save(
                    update_fields=[
                        "attempts",
                        "status",
                        "error_code",
                        "generated_by",
                        "claim_token",
                        "lease_expires_at",
                        "updated_at",
                    ]
                )
            result, code, storage = None, 201, None
            record_id = record.pk
    if result is not None:
        try:
            with open_document(*storage):
                pass
        except OSError as error:
            raise ExportUnavailable() from error
        return result, code
    # A concurrent first completion can precede our claim; format only fresh work.
    if data is None:
        data = format_csv(payload)
    upload = io.BytesIO(data)
    upload.name = "generic-po.csv"
    try:
        with staged_document(upload, namespace="exports") as stage:
            with open_document(stage["key"], stage["size"], stage["sha256"]):
                pass
            with tenant_scope(
                user=actor, workspace_id=organization_id, write=True
            ) as context:
                _require_writer(context)
                order = get_purchase_order(organization_id, order_id)
                if errors := eligibility(order):
                    raise ExportBlocked(errors)
                current = PurchaseOrderExport.objects.get(
                    pk=record_id, organization_id=organization_id, order_id=order_id
                )
                if (
                    current.status != "running"
                    or current.claim_token != token
                    or (current.lease_expires_at <= timezone.now())
                ):
                    return export_metadata(current), 202
                if revision(snapshot(order)) != source_revision:
                    raise ExportUnavailable()
                # Stage digest and sealed bytes have been verified by shared storage.
                current.status, current.storage_key = "succeeded", stage["key"]
                current.size_bytes, current.sha256 = stage["size"], stage["sha256"]
                current.completed_at = timezone.now()
                current.claim_token = current.lease_expires_at = None
                current.save(
                    update_fields=[
                        "status",
                        "storage_key",
                        "size_bytes",
                        "sha256",
                        "completed_at",
                        "claim_token",
                        "lease_expires_at",
                        "updated_at",
                    ]
                )
                result = export_metadata(current)
                stage["commit_attempt"] = True
            stage["committed"] = True
        return result, 201
    except (OSError, DatabaseError, ExportUnavailable) as error:
        # Never overwrite a possibly committed success after acknowledgment loss.
        try:
            _fail(
                actor,
                organization_id,
                order_id,
                record_id,
                token,
                "generation_unavailable",
            )
        except Exception:
            pass  # Fresh denial/disconnect leaves durable lease for explicit recovery.
        raise ExportUnavailable() from error


def download_metadata(*, actor, organization_id, order_id, artifact_id):
    with tenant_scope(user=actor, workspace_id=organization_id) as context:
        _require_writer(context)
        order = get_purchase_order(organization_id, order_id)
        record = get_object_or_404(
            PurchaseOrderExport,
            pk=artifact_id,
            organization_id=organization_id,
            order_id=order_id,
        )
        if errors := eligibility(order):
            raise ExportBlocked(errors)
        if record.status != "succeeded":
            return None
        return (
            record.storage_key,
            record.size_bytes,
            record.sha256,
            f"generic-po-csv-v1-{record.order_id}.csv",
        )
