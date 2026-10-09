"""Deterministic order CSV proposals with physical-line and column provenance."""

import csv
import io
import json
import re
from decimal import Decimal

PARSER_VERSION = "order-csv-v1"
MAX_ROWS = 500
MAX_RESULT_BYTES = 2 * 1024 * 1024


class ExtractionFailure(Exception):
    def __init__(self, code, row=None):
        self.code = code
        self.row = row
        super().__init__(code)


def extract_csv(source):
    text = io.TextIOWrapper(source, encoding="utf-8-sig", newline="")
    result = []
    try:
        reader = csv.reader(text, strict=True)
        headers = next(reader, [])
        if (
            len(headers) != len(set(headers))
            or not {"sku", "quantity"}.issubset(headers)
            or set(headers) - {"sku", "quantity", "description", "unit"}
        ):
            raise ExtractionFailure("unsupported_headers", 1)
        while True:
            start = reader.line_num + 1
            cells = next(reader, None)
            if cells is None:
                break
            if len(result) >= MAX_ROWS:
                raise ExtractionFailure("row_limit", start)
            if len(cells) != len(headers) or any(len(cell) > 4096 for cell in cells):
                raise ExtractionFailure("invalid_row", start)
            fields = {}
            for index, (header, raw) in enumerate(zip(headers, cells, strict=True), 1):
                value = raw if header == "description" else raw.strip()
                if header == "sku" and (not value or len(value) > 128):
                    raise ExtractionFailure("invalid_sku", start)
                if header == "unit" and len(value) > 32:
                    raise ExtractionFailure("invalid_unit", start)
                if header == "quantity" and (
                    not re.fullmatch(r"[0-9]{1,14}(?:\.[0-9]{1,4})?", value)
                    or Decimal(value) <= 0
                ):
                    raise ExtractionFailure("invalid_quantity", start)
                if any(ord(char) < 32 and char not in "\t\r\n" for char in raw):
                    raise ExtractionFailure("invalid_row", start)
                fields[header] = {
                    "value": value,
                    "raw": raw,
                    "row": start,
                    "end_row": reader.line_num,
                    "column": header,
                    "column_index": index,
                }
            result.append(fields)
        if not result:
            raise ExtractionFailure("empty_result")
        if len(json.dumps(result, ensure_ascii=True).encode()) > MAX_RESULT_BYTES:
            raise ExtractionFailure("result_limit")
        return result
    except (UnicodeError, csv.Error) as error:
        raise ExtractionFailure("invalid_csv") from error
    finally:
        text.detach()
