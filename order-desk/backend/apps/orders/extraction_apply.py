"""Explicit human decisions in one freshly authorized tenant write transaction."""

import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID, uuid4, uuid5

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from apps.orders import selectors
from apps.orders.models import (
    DocumentExtractionJob,
    DraftOrder,
    DraftOrderLine,
    ExtractionApplication,
    ExtractionCreatedRow,
    ExtractionJobStatus,
)
from apps.orders.revisions import check_revision, draft_revision
from apps.orders.services import _require_draft_editable, _require_preparer
from apps.organizations.transactions import tenant_scope

FIELD_NAMES = {
    "sku": "requested_sku",
    "quantity": "quantity",
    "description": "requested_description",
    "unit": "unit",
}


class ExtractionApplicationConflict(Exception):
    """A source, operation key or source-row insertion conflicts with current data."""

    def __init__(self, code="extraction_application_conflict"):
        self.code = code
        super().__init__(code)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def result_revision(job):
    return hashlib.sha256(
        _json(
            {
                "job_id": str(job.pk),
                "source_sha256": job.source_sha256,
                "parser_version": job.parser_version,
                "result": job.result,
                "pages": job.result_pages,
            }
        ).encode()
    ).hexdigest()


def candidates(job):
    return [
        {
            "candidate_id": str(
                uuid5(
                    job.pk,
                    f"row:{fields['sku']['row']}"
                    if job.parser_version == "order-csv-v1"
                    else f"page:{fields['sku']['page']}:line:{fields['sku']['line']}",
                )
            ),
            "fields": fields,
        }
        for fields in job.result
    ]


def reviewed_fields(job, draft):
    reviewed = {}
    for decisions in ExtractionApplication.objects.filter(
        organization_id=job.organization_id, job=job, draft=draft
    ).values_list("decisions", flat=True):
        for decision in decisions:
            reviewed.setdefault(decision["candidate_id"], set()).update(
                decision["fields"]
            )
    return [
        {"candidate_id": key, "fields": sorted(value)}
        for key, value in sorted(reviewed.items())
    ]


def _invalid(field, message):
    raise ValidationError({field: [message]})


def _uuid(value, field):
    if not isinstance(value, (str, UUID)):
        _invalid(field, "Provide a UUID.")
    try:
        return str(UUID(str(value)))
    except ValueError:
        _invalid(field, "Provide a UUID.")


def normalize_request(data):
    required = {
        "job_id",
        "draft_id",
        "result_revision",
        "expected_draft_revision",
        "operation_key",
        "mappings",
    }
    if not isinstance(data, Mapping):
        _invalid("non_field_errors", "Provide an object.")
    if set(data) - required:
        raise ValidationError(
            {key: ["Unsupported field."] for key in sorted(set(data) - required)}
        )
    if required - set(data):
        raise ValidationError(
            {key: ["This field is required."] for key in sorted(required - set(data))}
        )
    result = {
        key: _uuid(data[key], key) for key in ("job_id", "draft_id", "operation_key")
    }
    for key in ("result_revision", "expected_draft_revision"):
        value = data[key]
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            _invalid(key, "Provide a result/draft revision.")
        result[key] = value
    mappings = data["mappings"]
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= 50:
        _invalid("mappings", "Select between 1 and 50 rows.")
    output, source_ids, target_ids = [], set(), set()
    for item in mappings:
        if not isinstance(item, Mapping) or set(item) - {
            "candidate_id",
            "action",
            "fields",
            "corrections",
            "position",
            "line_id",
        }:
            _invalid("mappings", "Unsupported mapping fields.")
        candidate = _uuid(item.get("candidate_id"), "mappings")
        if candidate in source_ids:
            _invalid("mappings", "Select each source row once.")
        source_ids.add(candidate)
        action, fields = item.get("action"), item.get("fields")
        if action not in ("create", "update", "reject"):
            _invalid("mappings", "Choose create, update or reject.")
        if (
            not isinstance(fields, list)
            or not 1 <= len(fields) <= 4
            or any(
                not isinstance(field, str) or field not in FIELD_NAMES
                for field in fields
            )
            or len(set(fields)) != len(fields)
        ):
            _invalid("mappings", "Select distinct supported fields.")
        corrections = item.get("corrections", {})
        if (
            not isinstance(corrections, Mapping)
            or set(corrections) - set(fields)
            or any(
                not isinstance(value, str) or len(value) > 4096
                for value in corrections.values()
            )
        ):
            _invalid(
                "mappings", "Corrections must be bounded strings for selected fields."
            )
        mapping = {
            "candidate_id": candidate,
            "action": action,
            "fields": sorted(fields),
            "corrections": dict(corrections),
        }
        if action == "create":
            position = item.get("position")
            if (
                type(position) is not int
                or not 1 <= position <= 2147483647
                or "line_id" in item
            ):
                _invalid(
                    "mappings", "Choose a valid new line position, without a line ID."
                )
            mapping["position"] = position
        elif action == "update":
            line_id = _uuid(item.get("line_id"), "mappings")
            if line_id in target_ids or "position" in item:
                _invalid(
                    "mappings", "Select each target line once, without a position."
                )
            target_ids.add(line_id)
            mapping["line_id"] = line_id
        elif corrections or "position" in item or "line_id" in item:
            _invalid("mappings", "Rejection has no target or corrections.")
        output.append(mapping)
    result["mappings"] = sorted(output, key=lambda item: item["candidate_id"])
    return result


def _field_value(name, value):
    if name == "quantity":
        if (
            not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,3})?", value)
            or Decimal(value) <= 0
        ):
            _invalid(
                "quantity",
                "Use a positive decimal with up to 9 integer digits "
                "and 3 decimal places.",
            )
        return Decimal(value)
    if name == "unit" and len(value) > 32:
        _invalid("unit", "Ensure this field has no more than 32 characters.")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in value):
        _invalid(name, "Unsupported control character.")
    return value


def apply_extraction(*, actor, organization_id, order_id, document_id, data):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_preparer(context)
        payload = normalize_request(data() if callable(data) else data)
        if len(_json(payload).encode()) > 950000:
            _invalid("mappings", "The selected request is too large.")
        draft = get_object_or_404(
            DraftOrder.objects.select_for_update().filter(
                organization_id=organization_id
            ),
            pk=payload["draft_id"],
        )
        document = selectors.get_private_document(
            organization_id, order_id, document_id
        )
        if document.order_id is None and document.draft_id != draft.pk:
            _invalid("draft_id", "Use the draft linked to this incoming source.")
        job = get_object_or_404(
            DocumentExtractionJob.objects.filter(
                organization_id=organization_id, document=document
            ),
            pk=payload["job_id"],
        )
        key = payload.pop("operation_key")
        payload_hash = hashlib.sha256(_json(payload).encode()).hexdigest()
        previous = ExtractionApplication.objects.filter(
            organization_id=organization_id, operation_key=key
        ).first()
        if previous is not None:
            if previous.payload_hash != payload_hash:
                raise ExtractionApplicationConflict("operation_key_reused")
            return previous.response, False
        _require_draft_editable(draft)
        check_revision(draft, payload["expected_draft_revision"])
        current = selectors.current_extraction_job(
            organization_id, order_id, document_id
        )
        if (
            job.status != ExtractionJobStatus.SUCCEEDED
            or current is None
            or current.pk != job.pk
            or result_revision(job) != payload["result_revision"]
        ):
            raise ExtractionApplicationConflict("extraction_result_changed")
        available = {row["candidate_id"]: row["fields"] for row in candidates(job)}
        existing = list(
            DraftOrderLine.objects.filter(organization_id=organization_id, order=draft)
            .select_for_update()
            .order_by("position", "id")
        )
        lines = {str(line.pk): line for line in existing}
        positions = {line.position for line in existing}
        changes, decisions, created_rows = [], [], []
        for mapping in payload["mappings"]:
            fields = available.get(mapping["candidate_id"])
            if fields is None or set(mapping["fields"]) - set(fields):
                _invalid("mappings", "Unknown source candidate or field.")
            action = mapping["action"]
            line = None
            if action == "create":
                if ExtractionCreatedRow.objects.filter(
                    organization_id=organization_id,
                    job=job,
                    draft=draft,
                    candidate_id=mapping["candidate_id"],
                ).exists():
                    raise ExtractionApplicationConflict("source_row_already_created")
                if mapping["position"] in positions:
                    _invalid(
                        "position", "This draft already has a line at this position."
                    )
                positions.add(mapping["position"])
                line = DraftOrderLine(
                    organization_id=organization_id,
                    order=draft,
                    position=mapping["position"],
                )
            elif action == "update":
                line = lines.get(mapping["line_id"])
                if line is None:
                    _invalid(
                        "mappings", "The target line is unavailable in this draft."
                    )
            values = {}
            changed = []
            for name in mapping["fields"]:
                value = mapping["corrections"].get(name, fields[name]["value"])
                values[name] = {
                    "source": fields[name],
                    "value": value,
                    "corrected": name in mapping["corrections"],
                }
                if line is not None:
                    target = FIELD_NAMES[name]
                    parsed = _field_value(name, value)
                    if getattr(line, target) != parsed:
                        changed.append(target)
                        setattr(line, target, parsed)
            if line is not None:
                # All models/positions are validated before the first business write.
                line.full_clean()
                changes.append((line, changed, action == "create"))
                if action == "create":
                    created_rows.append((line, mapping["candidate_id"]))
            decisions.append(
                {
                    "candidate_id": mapping["candidate_id"],
                    "action": action,
                    "line_id": str(line.pk) if line else None,
                    "fields": values,
                }
            )
        if len(_json(decisions).encode()) > 1900000:
            _invalid("mappings", "The selected provenance is too large.")
        mutated = False
        for line, changed, new in changes:
            if new:
                line.save()
            elif changed:
                line.save(update_fields=[*changed, "updated_at"])
            mutated |= new or bool(changed)
        if mutated:
            draft.save(update_fields=["updated_at"])
        complete = {
            row["candidate_id"]: set(row["fields"])
            for row in reviewed_fields(job, draft)
        }
        for decision in decisions:
            complete.setdefault(decision["candidate_id"], set()).update(
                decision["fields"]
            )
        response = {
            "application_id": str(uuid4()),
            "job_id": str(job.pk),
            "draft_id": str(draft.pk),
            "revision": draft_revision(draft),
            "decisions": decisions,
            "review_complete": all(
                set(fields) <= complete.get(key, set())
                for key, fields in available.items()
            ),
        }
        application = ExtractionApplication.objects.create(
            id=response["application_id"],
            organization_id=organization_id,
            job=job,
            draft=draft,
            actor_id=context.user_id,
            operation_key=key,
            payload_hash=payload_hash,
            request=payload,
            decisions=decisions,
            response=response,
        )
        for line, candidate in created_rows:
            ExtractionCreatedRow.objects.create(
                organization_id=organization_id,
                application=application,
                job=job,
                draft=draft,
                line=line,
                candidate_id=candidate,
            )
        return response, True
