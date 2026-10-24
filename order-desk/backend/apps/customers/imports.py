"""Bounded create-only customer CSV; validation never approves alias learning."""

import csv
import hashlib
from collections import Counter
from io import StringIO
from uuid import uuid4

from rest_framework.exceptions import ValidationError

from apps.catalog.imports import MAX_FILE_BYTES, ImportUploadTooLarge
from apps.customers.models import CustomerAccount, CustomerAlias, ReferenceWriteReceipt
from apps.customers.serializers import AccountInput
from apps.customers.services import ReferenceConflict, require_admin
from apps.organizations.transactions import tenant_scope

HEADERS = {"code", "display_name", "destination_id", "requires_location", "is_active"}


def parse(raw):
    if len(raw) > MAX_FILE_BYTES:
        raise ImportUploadTooLarge()
    try:
        reader = csv.reader(StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        header = next(reader)
        if len(header) != len(HEADERS) or set(header) != HEADERS:
            raise ValidationError(
                {
                    "file": (
                        "Headers must be exactly code, display_name, destination_id, "
                        "requires_location, is_active."
                    )
                }
            )
        rows, errors = [], []
        for number, cells in enumerate(reader, 2):
            if not cells:
                continue
            if len(rows) >= 1000:
                raise ValidationError({"file": "Use at most 1,000 customer records."})
            if len(cells) != len(header):
                raise ValidationError(
                    {"file": f"Record {number} must have exactly five cells."}
                )
            data = dict(zip(header, cells, strict=True))
            for field in ("requires_location", "is_active"):
                if data[field] not in {"true", "false"}:
                    errors.append(
                        {"row": number, "field": field, "message": "Use true or false."}
                    )
            form = AccountInput(data=data)
            if form.is_valid():
                rows.append((number, dict(form.validated_data)))
            else:
                rows.append((number, {"code": data["code"]}))
                for field, messages in form.errors.items():
                    errors.extend(
                        {"row": number, "field": field, "message": str(message)}
                        for message in messages
                    )
    except (UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise ValidationError(
            {"file": "Use a nonempty well-formed UTF-8 CSV with a header and data."}
        ) from error
    if not rows:
        raise ValidationError({"file": "Include at least one customer record."})
    return rows, errors


def import_customers(
    *, actor, organization_id, upload, execute=False, operation_key=None
):
    with tenant_scope(user=actor, workspace_id=organization_id) as context:
        require_admin(context)
    raw = upload()
    rows, errors = parse(raw)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    with tenant_scope(
        user=actor, workspace_id=organization_id, write=execute
    ) as context:
        require_admin(context)
        operation_key = operation_key or uuid4()
        if execute:
            previous = ReferenceWriteReceipt.objects.filter(
                organization_id=organization_id, operation_key=operation_key
            ).first()
            if previous:
                if (
                    previous.kind != "account.import"
                    or previous.request_hash != source_sha256
                ):
                    raise ReferenceConflict(
                        "This import key already identifies a different "
                        "source or operation."
                    )
                return {
                    **previous.response,
                    "created": 0,
                    "original_created": previous.response["created"],
                    "replayed": True,
                }
        codes = [values["code"] for _, values in rows]
        duplicates = {code for code, count in Counter(codes).items() if count > 1}
        existing = set(
            CustomerAccount.objects.filter(
                organization_id=organization_id, code__in=codes
            ).values_list("code", flat=True)
        )
        aliases = set(
            CustomerAlias.objects.filter(
                organization_id=organization_id, is_active=True, value__in=codes
            ).values_list("value", flat=True)
        )
        for number, values in rows:
            for condition, message in (
                (values["code"] in duplicates, "Duplicate code in this file."),
                (
                    values["code"] in existing,
                    "Customer code already exists; this import never updates "
                    "existing accounts.",
                ),
                (
                    values["code"] in aliases,
                    "Code collides with an approved customer alias.",
                ),
            ):
                if condition:
                    errors.append({"row": number, "field": "code", "message": message})
        report = {
            "organization_id": str(organization_id),
            "valid": not errors,
            "rows": len(rows),
            "error_count": len(errors),
            "errors": errors[:100],
            "created": 0,
            "mode": "create" if execute else "validate",
        }
        if errors or not execute:
            return report
        CustomerAccount.objects.bulk_create(
            [
                CustomerAccount(
                    organization_id=organization_id,
                    created_by_id=actor.pk,
                    updated_by_id=actor.pk,
                    **values,
                )
                for _, values in rows
            ]
        )
        report["created"] = len(rows)
        report.update(operation_key=str(operation_key), replayed=False)
        ReferenceWriteReceipt.objects.create(
            organization_id=organization_id,
            actor_id=actor.pk,
            kind="account.import",
            operation_key=operation_key,
            request_hash=source_sha256,
            source_sha256=source_sha256,
            response=report,
        )
        return report
