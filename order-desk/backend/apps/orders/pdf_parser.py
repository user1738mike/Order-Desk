"""Fixed memory-only parser child. No Django or database configuration imports."""

import codecs
import ctypes
import io
import json
import logging
import platform
import re
import resource
import sys
import time
from decimal import Decimal

MAX_INPUT = 10 * 1024 * 1024
MAX_TEXT_PAGE = 65536
MAX_TEXT_TOTAL = 262144
MAX_ROWS = 500


class ProfileFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def isolate():
    """Deny all syscalls outside the minimal memory/text processing set."""
    architecture = platform.machine()
    if sys.platform != "linux" or architecture not in ("x86_64", "aarch64"):
        raise ProfileFailure("parser_unavailable")
    native_arch, allowed = (
        (
            0xC000003E,
            [
                0,
                1,
                3,
                5,
                8,
                9,
                10,
                11,
                12,
                13,
                14,
                15,
                16,
                24,
                25,
                28,
                39,
                60,
                72,
                96,
                98,
                99,
                102,
                104,
                107,
                108,
                131,
                158,
                186,
                202,
                204,
                228,
                230,
                231,
                273,
                318,
                324,
                334,
            ],
        )
        if architecture == "x86_64"
        else (
            0xC00000B7,
            [
                25,
                29,
                57,
                62,
                63,
                64,
                80,
                93,
                94,
                98,
                99,
                113,
                115,
                123,
                124,
                132,
                134,
                135,
                139,
                165,
                169,
                172,
                174,
                175,
                176,
                177,
                178,
                214,
                215,
                216,
                222,
                226,
                233,
                278,
                283,
                293,
            ],
        )
    )

    class Filter(ctypes.Structure):
        _fields_ = [
            ("code", ctypes.c_ushort),
            ("jt", ctypes.c_ubyte),
            ("jf", ctypes.c_ubyte),
            ("k", ctypes.c_uint),
        ]

    class Program(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("filters", ctypes.POINTER(Filter))]

    # Validate architecture before reading syscall number, including x32 rejection.
    rules = [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, native_arch),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
    ]
    for number in allowed:
        rules.extend([(0x15, 0, 1, number), (0x06, 0, 0, 0x7FFF0000)])
    rules.append(
        (0x06, 0, 0, 0x00050001)
    )  # EPERM for filesystem/network/process syscalls.
    filters = (Filter * len(rules))(*(Filter(*rule) for rule in rules))
    program = Program(len(rules), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    if (
        libc.prctl(38, 1, 0, 0, 0) != 0
        or libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0
    ):
        raise ProfileFailure("parser_unavailable")


def extract(reader):
    if reader.is_encrypted:
        raise ProfileFailure("encrypted_pdf")
    if not 1 <= len(reader.pages) <= 10:
        raise ProfileFailure("page_limit")
    root = reader.trailer["/Root"]
    if any(key in root for key in ("/AcroForm", "/OpenAction", "/AA", "/Names")):
        raise ProfileFailure("unsupported_layout")
    pages, result = [], []
    total_text = 0
    for page_number, page in enumerate(reader.pages, 1):
        if page.get("/Rotate", 0) != 0 or tuple(
            float(value) for value in page.mediabox
        ) != (0.0, 0.0, 612.0, 792.0):
            raise ProfileFailure("unsupported_layout")
        if page.get("/Annots") or page.get("/Resources", {}).get("/XObject"):
            raise ProfileFailure("unsupported_layout")
        fragments, previous_y = [], [None]

        def visit(text, cm, tm, font, size, fragments=fragments, previous_y=previous_y):
            if not text:
                return
            if (
                len(text) > MAX_TEXT_PAGE
                or sum(len(item) for item in fragments) + len(text) > MAX_TEXT_PAGE
            ):
                raise ProfileFailure("text_limit")
            if (
                not font
                or font.get("/BaseFont") != "/Courier"
                or size != 10
                or tuple(cm[:4]) != (1, 0, 0, 1)
                or tuple(tm[:4]) != (1, 0, 0, 1)
                or abs(tm[4] - 50) > 0.1
                or not 30 <= tm[5] <= 760
            ):
                raise ProfileFailure("ambiguous_layout")
            if previous_y[0] is not None and tm[5] >= previous_y[0]:
                raise ProfileFailure("ambiguous_layout")
            previous_y[0] = tm[5]
            fragments.append(text)

        page.extract_text(visitor_text=visit)
        text = "".join(fragments)
        if not text.strip():
            raise ProfileFailure("no_text")
        total_text += len(text)
        if len(text) > MAX_TEXT_PAGE or total_text > MAX_TEXT_TOTAL:
            raise ProfileFailure("text_limit")
        pages.append(text)
        lines = text.splitlines(keepends=True)
        nonempty = [line.rstrip("\r\n") for line in lines if line.strip()]
        if (
            not nonempty
            or nonempty[0] != "ORDER DESK TEXT PO v1"
            or len(nonempty) < 3
            or nonempty[1] != "SKU | QUANTITY | UNIT | DESCRIPTION"
            or nonempty[-1] != f"END PAGE {page_number}/{len(reader.pages)}"
        ):
            raise ProfileFailure("unsupported_layout")
        offset, previous = 0, None
        for line_number, original in enumerate(lines, 1):
            raw_line = original.rstrip("\r\n")
            start = offset
            offset += len(original)
            if not raw_line.strip() or raw_line in (
                "ORDER DESK TEXT PO v1",
                "SKU | QUANTITY | UNIT | DESCRIPTION",
                f"END PAGE {page_number}/{len(reader.pages)}",
            ):
                continue
            if raw_line.startswith("> "):
                if previous is None or "|" in raw_line:
                    raise ProfileFailure("ambiguous_layout")
                field = previous["description"]
                field["value"] += "\n" + raw_line[2:]
                field["span_end"] = start + len(raw_line)
                field["raw"] = text[field["span_start"] : field["span_end"]]
                if len(field["value"]) > 4096 or len(field["raw"]) > 4096:
                    raise ProfileFailure("text_limit")
                continue
            cells = raw_line.split("|")
            if len(cells) != 4 or len(result) >= MAX_ROWS:
                raise ProfileFailure(
                    "row_limit" if len(result) >= MAX_ROWS else "ambiguous_layout"
                )
            fields, cell_start = {}, start
            for name, raw in zip(
                ("sku", "quantity", "unit", "description"), cells, strict=True
            ):
                value = raw.strip()
                if len(raw) > 4096 or any(ord(char) < 32 for char in raw):
                    raise ProfileFailure("text_limit")
                if name == "sku" and (not value or len(value) > 128):
                    raise ProfileFailure("invalid_sku")
                if name == "quantity" and (
                    not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,3})?", value)
                    or Decimal(value) <= 0
                ):
                    raise ProfileFailure("invalid_quantity")
                if name == "unit" and len(value) > 32:
                    raise ProfileFailure("invalid_unit")
                fields[name] = {
                    "value": value,
                    "raw": raw,
                    "page": page_number,
                    "line": line_number,
                    "column": name,
                    "span_start": cell_start,
                    "span_end": cell_start + len(raw),
                }
                cell_start += len(raw) + 1
            result.append(fields)
            previous = fields
    if not result:
        raise ProfileFailure("empty_result")
    return result, pages


def set_limits():
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))


def main():
    started = time.monotonic()
    try:
        set_limits()
        # Imports/codecs must complete before the syscall boundary closes files.
        from pypdf import PdfReader, apply_configuration

        for encoding in ("utf-16-be", "utf-16-le", "utf-8", "latin1", "cp1252"):
            codecs.lookup(encoding)
        logging.disable(logging.CRITICAL)
        source = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(source) > MAX_INPUT:
            raise ProfileFailure("input_limit")
        with apply_configuration(
            maximum_declared_stream_length=8 * 1024 * 1024,
            array_based_stream_maximum_output_length=8 * 1024 * 1024,
            zlib_maximum_output_length=8 * 1024 * 1024,
            zlib_maximum_recovery_input_length=2 * 1024 * 1024,
            lzw_maximum_output_length=8 * 1024 * 1024,
            run_length_maximum_output_length=8 * 1024 * 1024,
            stream_filters_maximum_length=4,
            stream_decoding_work_maximum_length=16 * 1024 * 1024,
            page_tree_maximum_entries=64,
            page_tree_maximum_depth=16,
            xform_maximum_invocations_per_extraction=0,
            jbig2dec_binary=None,
        ):
            isolate()
            reader = PdfReader(io.BytesIO(source), strict=True)
            result, pages = extract(reader)
        response = {
            "result": result,
            "pages": pages,
            "metrics": {
                "elapsed_seconds": round(time.monotonic() - started, 6),
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            },
        }
    except ProfileFailure as error:
        response = {"error": error.code}
    except MemoryError:
        response = {"error": "parser_resource_limit"}
    except Exception:
        # Never print parser tracebacks, paths or source fragments.
        response = {"error": "malformed_pdf"}
    sys.stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
