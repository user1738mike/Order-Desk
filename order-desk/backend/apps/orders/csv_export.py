"""One deterministic machine CSV; no database, storage or HTTP operations."""

import csv
import io
import re
import unicodedata
from decimal import Decimal

PROFILE = "generic-po-csv-v1"
MAX_LINES = 500
MAX_BYTES = 2 * 1024 * 1024
HEADERS = (
    "profile",
    "order_id",
    "source_draft_id",
    "order_number",
    "order_date",
    "customer_name",
    "line_number",
    "sku",
    "description",
    "quantity",
    "unit",
)


class ExportBlocked(Exception):
    def __init__(self, blockers):
        self.blockers = blockers[:100]
        self.count = len(blockers)


class ExportUnavailable(Exception):
    """Unconfirmed or unavailable private generation; refresh actual status."""


def text_error(value, maximum, *, required=False, multiline=False):
    if not isinstance(value, str) or (required and not value.strip()):
        return "required"
    if len(value) > maximum:
        return "text_limit"
    if any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs"}
        and not (multiline and char in "\r\n")
        for char in value
    ):
        return "unsupported_control"
    for part in value.splitlines() or [value]:
        while part and (part[0].isspace() or part[0] in "\"'"):
            part = part[1:]
        if part.startswith(("=", "+", "-", "@")):
            return "unsafe_formula"
    return None


def validate_payload(payload):
    errors = []

    def add(path, code, line=None):
        item = {"path": path, "code": code}
        if line is not None:
            item["line_id"] = line["id"]
        errors.append(item)

    for field, limit in (("order_number", 64), ("customer_name", 255)):
        if code := text_error(payload[field], limit, required=True):
            add(field, code)
    rows = payload["lines"]
    if not rows:
        add("lines", "no_lines")
    if len(rows) > MAX_LINES:
        add("lines", "line_limit")
    for line in rows:
        for field, limit, required in (
            ("sku", 128, True),
            ("description", 4096, False),
            ("unit", 32, False),
        ):
            if code := text_error(
                line[field], limit, required=required, multiline=field == "description"
            ):
                add(f"lines.{field}", code, line)
        value = line["quantity"]
        if not re.fullmatch(r"[0-9]{1,14}\.[0-9]{4}", value) or Decimal(value) <= 0:
            add("lines.quantity", "invalid_quantity", line)
    return errors


def format_csv(payload):
    errors = validate_payload(payload)
    if errors:
        raise ExportBlocked(errors)
    output = io.BytesIO()

    def write(row):
        text = io.StringIO(newline="")
        csv.writer(text, lineterminator="\r\n").writerow(row)
        data = text.getvalue().encode("utf-8")
        if output.tell() + len(data) > MAX_BYTES:
            raise ExportBlocked([{"path": "lines", "code": "output_limit"}])
        output.write(data)

    write(HEADERS)
    for line in payload["lines"]:
        write(
            [
                PROFILE,
                payload["order_id"],
                payload["source_draft_id"],
                payload["order_number"],
                payload["order_date"],
                payload["customer_name"],
                line["line_number"],
                line["sku"],
                line["description"],
                line["quantity"],
                line["unit"],
            ]
        )
    return output.getvalue()
