"""Bounded pure CSV validation for advisory, create-only catalogue imports."""

import csv
from collections import Counter
from dataclasses import dataclass
from io import StringIO

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import APIException, ValidationError

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemCreateSerializer

MAX_FILE_BYTES = 1_048_576
MAX_RECORDS = 1000
MAX_ERRORS = 100
MAX_PREVIEW = 25
MAX_ERROR_MESSAGE = 200
HEADERS = {"sku", "description", "is_active"}


class ImportStructureError(APIException):
    status_code = 400
    default_code = "invalid_csv"

    def __init__(self, detail: str, *, row_number: int | None = None) -> None:
        payload = {"detail": detail[:MAX_ERROR_MESSAGE]}
        if row_number is not None:
            payload["row_number"] = row_number
        super().__init__(payload)
        if row_number is not None:
            # DRF normally converts APIException primitives to ErrorDetail text;
            # retain the documented logical record location as an integer.
            self.detail["row_number"] = row_number


class ImportUploadTooLarge(APIException):
    status_code = 413
    default_code = "upload_too_large"
    default_detail = {"detail": "The CSV file exceeds the 1 MiB upload limit."}


def _row_error(row_number: int, field: str, code: str, message: object) -> dict:
    return {
        "row_number": row_number,
        "field": field,
        "code": code,
        "message": str(message)[:MAX_ERROR_MESSAGE],
    }


@dataclass(frozen=True, slots=True)
class ParsedImportRow:
    row_number: int
    data: dict | None
    errors: list[dict]
    sku: str | None


@dataclass(frozen=True, slots=True)
class ParsedImport:
    rows: list[ParsedImportRow]

    @property
    def skus(self) -> set[str]:
        """Normalized valid SKU fields, including rows with other field errors."""
        return {row.sku for row in self.rows if row.sku is not None}

    def report(self, existing_skus: set[str]) -> dict:
        """Bound output only; inspect every permitted row without mutating it."""
        errors = []
        preview = []
        error_count = 0
        rows_ready = 0
        rows_invalid = 0
        for row in self.rows:
            row_errors = list(row.errors)
            if row.sku is not None and row.sku in existing_skus:
                row_errors.append(
                    _row_error(
                        row.row_number,
                        "sku",
                        "existing_workspace_sku",
                        "This stock code already exists in this workspace.",
                    )
                )
            error_count += len(row_errors)
            if row_errors:
                rows_invalid += 1
                errors.extend(row_errors[: max(0, MAX_ERRORS - len(errors))])
            else:
                rows_ready += 1
                if len(preview) < MAX_PREVIEW:
                    preview.append({"row_number": row.row_number, **row.data})
        return {
            "dry_run": True,
            "mode": "create_only",
            "can_import": rows_invalid == 0,
            "summary": {
                "rows_total": len(self.rows),
                "rows_ready": rows_ready,
                "rows_invalid": rows_invalid,
            },
            "errors": errors,
            "errors_truncated": error_count > len(errors),
            "preview": preview,
            "preview_truncated": rows_ready > len(preview),
        }


def _validate_row(row_number: int, values: dict[str, str]) -> ParsedImportRow:
    data = {"sku": values["sku"], "description": values["description"]}
    active = values["is_active"]
    if active:
        data["is_active"] = {"true": True, "false": False}.get(active, active)
    serializer = CatalogItemCreateSerializer(data=data)
    errors = []
    if not serializer.is_valid():
        for field, messages in serializer.errors.items():
            for message in messages:
                if field == "is_active":
                    message = "Use true, false, or an empty cell."
                errors.append(_row_error(row_number, field, "invalid_value", message))

    # Validate the SKU separately so every normalized duplicate can be marked,
    # even when another field prevents the serializer from returning row data.
    sku = None
    try:
        normalized = serializer.fields["sku"].run_validation(values["sku"])
        sku = CatalogItem._meta.get_field("sku").clean(normalized, None)
    except ValidationError:
        pass  # Its field error is already present in serializer.errors.
    except DjangoValidationError as error:
        errors.extend(
            _row_error(row_number, "sku", "invalid_value", message)
            for message in error.messages
        )

    validated = None
    if serializer.is_valid():
        validated = dict(serializer.validated_data)
        candidate = CatalogItem(**validated)
        for field, value in validated.items():
            if field == "sku":
                continue  # The actual model field was checked above.
            try:
                validated[field] = candidate._meta.get_field(field).clean(
                    value, candidate
                )
            except DjangoValidationError as error:
                errors.extend(
                    _row_error(row_number, field, "invalid_value", message)
                    for message in error.messages
                )
    return ParsedImportRow(row_number, None if errors else validated, errors, sku)


def parse_catalogue_csv(raw: bytes) -> ParsedImport:
    """Strict UTF-8/BOM CSV; numbers count logical records, including blank ones.

    The first record is header 1. Only subsequent completely empty records are
    skipped. Python's existing CSV field-size limit is respected and never
    changed process-globally; exceeding it is a structural HTTP 400 failure.
    """
    if len(raw) > MAX_FILE_BYTES:
        raise ImportUploadTooLarge()
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ImportStructureError("Upload a valid UTF-8 CSV file.") from error
    reader = csv.reader(StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as error:
        raise ImportStructureError(
            "The CSV must contain a header and at least one data record."
        ) from error
    except csv.Error as error:
        raise ImportStructureError("Malformed CSV header.", row_number=1) from error
    if len(header) != len(HEADERS) or set(header) != HEADERS:
        raise ImportStructureError(
            "CSV headers must contain exactly sku, description, and is_active.",
            row_number=1,
        )
    rows = []
    row_number = 1
    while True:
        row_number += 1
        try:
            cells = next(reader)
        except StopIteration:
            break
        except csv.Error as error:
            raise ImportStructureError(
                "Malformed CSV record or field exceeds the CSV parser limit.",
                row_number=row_number,
            ) from error
        if not cells:
            continue
        if len(rows) >= MAX_RECORDS:
            raise ImportStructureError(
                "The CSV exceeds the 1,000 data-record limit.", row_number=row_number
            )
        if len(cells) != len(header):
            raise ImportStructureError(
                "The CSV record must contain exactly three columns.",
                row_number=row_number,
            )
        rows.append(_validate_row(row_number, dict(zip(header, cells, strict=True))))
    if not rows:
        raise ImportStructureError("The CSV must contain at least one data record.")
    duplicates = {
        sku
        for sku, count in Counter(
            row.sku for row in rows if row.sku is not None
        ).items()
        if count > 1
    }
    return ParsedImport(
        [
            ParsedImportRow(
                row.row_number,
                None if row.sku in duplicates else row.data,
                row.errors
                + (
                    [
                        _row_error(
                            row.row_number,
                            "sku",
                            "duplicate_file_sku",
                            "This stock code appears more than once in the file.",
                        )
                    ]
                    if row.sku in duplicates
                    else []
                ),
                row.sku,
            )
            for row in rows
        ]
    )
