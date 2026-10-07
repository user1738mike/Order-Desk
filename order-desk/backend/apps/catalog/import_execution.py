"""Atomic create-only CSV imports with protected tenant-scoped durable replay."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.catalog import selectors
from apps.catalog.import_services import CONFLICT_BATCH_SIZE
from apps.catalog.imports import (
    MAX_FILE_BYTES,
    MAX_PREVIEW,
    ImportUploadTooLarge,
    parse_catalogue_csv,
)
from apps.catalog.models import CONTRACT_IDENTIFIER, CatalogImportReceipt, CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.catalog.services import CATALOG_SKU_CONFLICT
from apps.organizations.models import MembershipRole
from apps.organizations.transactions import tenant_scope

if TYPE_CHECKING:
    from apps.accounts.models import User

CATALOG_IMPORT_DENIED = (
    "You do not have permission to import catalogue items in this workspace."
)
CATALOG_IMPORT_KEY_REUSED = (
    "This idempotency key has already been used for a different catalogue import."
)
CATALOG_IMPORT_ROWS_INVALID = "The CSV file contains invalid catalogue rows."


@dataclass(frozen=True, slots=True)
class ImportExecutionResult:
    payload: dict
    replayed: bool


class ImportKeyConflict(APIException):
    status_code = 409
    default_detail = CATALOG_IMPORT_KEY_REUSED
    default_code = "idempotency_key_reused"


class ImportRowsInvalid(APIException):
    status_code = 400
    default_code = "invalid_import_rows"

    def __init__(self, report: dict) -> None:
        # Preserve bool/int report values rather than APIException's recursive
        # conversion of arbitrary primitives into ErrorDetail strings.
        super().__init__(CATALOG_IMPORT_ROWS_INVALID)
        self.detail = {"detail": CATALOG_IMPORT_ROWS_INVALID, "report": report}


class ImportSKUConflict(APIException):
    status_code = 409
    default_code = "catalogue_sku_conflict"

    def __init__(self, report: dict) -> None:
        super().__init__(CATALOG_SKU_CONFLICT)
        self.detail = {"detail": CATALOG_SKU_CONFLICT, "report": report}


def parse_import_key(value: str | UUID | None) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValidationError(
        {"idempotency_key": ["Provide a valid Idempotency-Key UUID header."]}
    )


def import_fingerprint(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        raise TypeError("Import data must be bytes.")
    if len(raw) > MAX_FILE_BYTES:
        raise ImportUploadTooLarge()
    # Fixed, separated operation/version bytes exclude workspace, actor, file
    # name, multipart framing, and session metadata from the stable file digest.
    digest = hashlib.sha256()
    digest.update(b"catalogue-import\x00create_only\x00")
    digest.update(CONTRACT_IDENTIFIER.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(raw)
    return digest.hexdigest()


def _canonical_payload(payload: dict) -> dict:
    # PostgreSQL JSONB does not retain insertion order. Sorting recursively on
    # both paths gives identical renderer bytes for first execution and replay.
    return json.loads(json.dumps(payload, sort_keys=True, allow_nan=False))


def _receipt_result(
    receipt: CatalogImportReceipt, fingerprint: str
) -> ImportExecutionResult:
    if (
        receipt.request_fingerprint != fingerprint
        or receipt.mode != "create_only"
        or receipt.contract_identifier != CONTRACT_IDENTIFIER
    ):
        raise ImportKeyConflict()
    if (
        receipt.state != CatalogImportReceipt.State.COMPLETED
        or receipt.completed_at is None
        or not isinstance(receipt.response_payload, dict)
    ):
        # The deferred database trigger forbids a durable processing receipt.
        # Do not reinterpret an abnormal observed reservation as resumable work.
        raise RuntimeError("An incomplete catalogue import receipt was observed.")
    return ImportExecutionResult(_canonical_payload(receipt.response_payload), True)


def _is_unique(error: DatabaseError, *, constraint: str, table: str) -> bool:
    diagnostics = getattr(error.__cause__, "diag", None)
    return (
        isinstance(error, IntegrityError)
        and getattr(error.__cause__, "sqlstate", None) == "23505"
        and getattr(diagnostics, "constraint_name", None) == constraint
        and getattr(diagnostics, "table_name", None) == table
    )


def execute_catalogue_import(
    *,
    actor: User | AnonymousUser,
    organization_id: UUID,
    data: bytes | Callable[[], bytes],
    idempotency_key: str | UUID | None,
) -> ImportExecutionResult:
    """Own organization lock, receipt reservation, and sorted atomic item writes.

    Every exception must leave this outer scope before HTTP translation. A
    reservation is never separately committed. No caller transaction is accepted.
    """
    parsed = None
    current_item = None
    try:
        with tenant_scope(
            user=actor, workspace_id=organization_id, write=True
        ) as scope:
            if scope.role != MembershipRole.ADMIN:
                raise PermissionDenied(CATALOG_IMPORT_DENIED)
            key = parse_import_key(idempotency_key)
            raw = data() if callable(data) else data
            fingerprint = import_fingerprint(raw)
            receipts = CatalogImportReceipt.objects.filter(
                organization_id=scope.organization_id, idempotency_key=key
            )
            # The organization lock serializes supported workspace writers.
            # Completed receipts are immutable under the UPDATE RLS policy, so
            # SELECT FOR UPDATE would correctly hide them; ordinary SELECT is
            # the required replay lookup, not a weakening of their boundary.
            receipt = receipts.first()
            if receipt is not None:
                return _receipt_result(receipt, fingerprint)
            try:
                # Only this insert owns the savepoint. A native key collision
                # rolls it back before reading its committed winner exactly once.
                with transaction.atomic():
                    receipt = CatalogImportReceipt.objects.create(
                        organization_id=scope.organization_id,
                        initiating_user_id=scope.user_id,
                        idempotency_key=key,
                        request_fingerprint=fingerprint,
                        mode="create_only",
                        contract_identifier=CONTRACT_IDENTIFIER,
                    )
            except IntegrityError as error:
                if not _is_unique(
                    error,
                    constraint="catalog_import_org_key_unique",
                    table="catalog_catalogimportreceipt",
                ):
                    raise
                receipt = receipts.first()
                if receipt is None:
                    raise
                return _receipt_result(receipt, fingerprint)

            parsed = parse_catalogue_csv(raw)
            report = _canonical_payload(parsed.report(set()))
            if not report["can_import"]:
                raise ImportRowsInvalid(report)
            skus = sorted(parsed.skus)
            existing = set()
            for start in range(0, len(skus), CONFLICT_BATCH_SIZE):
                existing.update(
                    selectors.existing_catalog_skus(
                        organization_id=scope.organization_id,
                        skus=skus[start : start + CONFLICT_BATCH_SIZE],
                    )
                )
            if existing:
                raise ImportSKUConflict(_canonical_payload(parsed.report(existing)))

            created = {}
            for row in sorted(parsed.rows, key=lambda row: row.data["sku"]):
                current_item = CatalogItem(
                    organization_id=scope.organization_id, **row.data
                )
                # Pure parser validation already checks all mutable model fields.
                # Preserve normal save hooks/timestamps without FK/unique queries
                # or caller-controlled tenant assignment on every record.
                current_item.save()
                created[row.row_number] = current_item
            payload = _canonical_payload(
                {
                    "import_id": str(receipt.pk),
                    "organization_id": str(scope.organization_id),
                    "mode": "create_only",
                    "created_count": len(parsed.rows),
                    "items": [
                        CatalogItemSerializer(created[row.row_number]).data
                        for row in parsed.rows[:MAX_PREVIEW]
                    ],
                    "items_truncated": len(parsed.rows) > MAX_PREVIEW,
                }
            )
            changed = CatalogImportReceipt.objects.filter(
                pk=receipt.pk,
                organization_id=scope.organization_id,
                state=CatalogImportReceipt.State.PROCESSING,
            ).update(
                state=CatalogImportReceipt.State.COMPLETED,
                response_payload=payload,
                completed_at=timezone.now(),
            )
            if changed != 1:
                raise RuntimeError(
                    "The catalogue import receipt could not be completed."
                )
            return ImportExecutionResult(payload, False)
    except DatabaseError as error:
        # Translate only actual known catalogue errors after the entire scope
        # rolls back its receipt and every preceding item insertion.
        if _is_unique(
            error, constraint="catalog_org_sku_unique", table="catalog_catalogitem"
        ):
            if parsed is None or current_item is None:
                raise
            raise ImportSKUConflict(
                _canonical_payload(parsed.report({current_item.sku}))
            ) from error
        diagnostics = getattr(error.__cause__, "diag", None)
        if (
            getattr(error.__cause__, "sqlstate", None) == "54000"
            and getattr(diagnostics, "constraint_name", None)
            == "catalog_org_sku_unique"
            and getattr(diagnostics, "table_name", None) == "catalog_catalogitem"
        ):
            raise ValidationError(
                {"sku": ["This stock code is too large for the catalogue index."]}
            ) from error
        raise
