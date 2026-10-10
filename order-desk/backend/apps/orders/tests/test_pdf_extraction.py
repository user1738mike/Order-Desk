"""Independent profile expectations and actual bounded Linux parser children."""

import io
import json
import os
import sys
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from pypdf import PdfReader, PdfWriter

from apps.orders.csv_extraction import ExtractionFailure
from apps.orders.extraction_services import process_extraction
from apps.orders.models import DocumentExtractionJob
from apps.orders.pdf_extraction import extract_pdf, supervise
from apps.orders.tests import test_private_document_intake as fixtures
from apps.orders.tests.pdf_fixtures import pdf_bytes, supported_pdf

HEAD = ["ORDER DESK TEXT PO v1", "SKU | QUANTITY | UNIT | DESCRIPTION"]


class TextPDFProfileTests(SimpleTestCase):
    def parse(self, data):
        return extract_pdf(io.BytesIO(data))

    def failure(self, data, code):
        with self.assertRaises(ExtractionFailure) as caught:
            self.parse(data)
        self.assertEqual(caught.exception.code, code)

    def test_single_page_exact_fields_and_truthful_saved_text_spans(self):
        result = self.parse(supported_pdf())
        fields = result["result"][0]
        self.assertEqual(
            {key: field["value"] for key, field in fields.items()},
            {
                "sku": "0001.Mixed-Case",
                "quantity": "1.234",
                "unit": "each",
                "description": "Synthetic widget",
            },
        )
        for key, field in fields.items():
            self.assertEqual(
                (field["page"], field["line"], field["column"]), (1, 3, key)
            )
            self.assertEqual(
                result["pages"][0][field["span_start"] : field["span_end"]],
                field["raw"],
            )
        self.assertGreater(result["metrics"]["peak_rss_kib"], 0)
        self.assertLess(result["metrics"]["peak_rss_kib"], 256 * 1024)

    def test_multipage_wrapping_repeated_heading_and_empty_optional_values(
        self,
    ):
        raw = pdf_bytes(
            [
                HEAD
                + [
                    "0001-A | 0.001 | ea | First",
                    "> wrapped",
                    HEAD[1],
                    "Zero.Optional | 999999999.999 | |",
                    "END PAGE 1/2",
                ],
                HEAD + ["00.Mixed.Case | 2.500 | each | Last", "END PAGE 2/2"],
            ]
        )
        result = self.parse(raw)
        self.assertEqual(
            [row["sku"]["value"] for row in result["result"]],
            ["0001-A", "Zero.Optional", "00.Mixed.Case"],
        )
        self.assertEqual(
            [row["quantity"]["value"] for row in result["result"]],
            ["0.001", "999999999.999", "2.500"],
        )
        self.assertEqual(result["result"][0]["description"]["value"], "First\nwrapped")
        self.assertEqual(result["result"][1]["unit"]["value"], "")
        self.assertEqual(result["result"][1]["description"]["value"], "")
        self.assertEqual(result["result"][2]["sku"]["page"], 2)
        description = result["result"][0]["description"]
        self.assertEqual(
            result["pages"][0][description["span_start"] : description["span_end"]],
            description["raw"],
        )

    def test_missing_invalid_values_and_ambiguous_rows_fail_whole_document(self):
        for line, code in [
            ("A | | each | Missing", "invalid_quantity"),
            ("A | 0 | each | Zero", "invalid_quantity"),
            ("A | 1.2345 | each | Precision", "invalid_quantity"),
            (" | 1 | ea | Missing SKU", "invalid_sku"),
            ("A | 1 | ea", "ambiguous_layout"),
            ("Unknown prose", "ambiguous_layout"),
        ]:
            with self.subTest(line=line):
                self.failure(
                    pdf_bytes(
                        [HEAD + ["VALID | 1 | ea | Valid", line, "END PAGE 1/1"]]
                    ),
                    code,
                )
        self.failure(
            pdf_bytes([HEAD + ["A | 1 | ea | Fine", "END PAGE 1/2"]]),
            "unsupported_layout",
        )
        self.failure(
            pdf_bytes([HEAD + ["> no previous row", "END PAGE 1/1"]]),
            "ambiguous_layout",
        )

    def test_unsupported_scanned_mixed_encrypted_and_truncated_sources_are_visible(
        self,
    ):
        self.failure(pdf_bytes([["Unsupported purchase order"]]), "unsupported_layout")
        self.failure(pdf_bytes([[]]), "no_text")
        self.failure(
            pdf_bytes([HEAD + ["A | 1 | ea | Good", "END PAGE 1/2"], []]), "no_text"
        )
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(io.BytesIO(supported_pdf())))
        writer.encrypt("Synthetic-fixture", algorithm="RC4-40")
        encrypted = io.BytesIO()
        writer.write(encrypted)
        self.failure(encrypted.getvalue(), "encrypted_pdf")
        for malformed in (b"%PDF-1.4\n%%EOF", supported_pdf()[:-30]):
            with self.subTest(size=len(malformed)):
                self.failure(malformed, "malformed_pdf")

    def test_page_origin_and_decompression_text_limits_are_enforced(self):
        self.failure(
            pdf_bytes([HEAD + ["A | 1 | ea | Fine", "END PAGE 1/11"]] * 11),
            "page_limit",
        )
        self.failure(
            pdf_bytes([HEAD + ["A | 1 | ea | " + "X" * 66000, "END PAGE 1/1"]]),
            "text_limit",
        )
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(io.BytesIO(supported_pdf())))
        writer.pages[0].compress_content_streams()
        compressed = io.BytesIO()
        writer.write(compressed)
        self.assertEqual(
            self.parse(compressed.getvalue())["result"][0]["quantity"]["value"], "1.234"
        )
        shifted = supported_pdf().replace(b"50 742 Td", b"60 742 Td")
        self.failure(shifted, "ambiguous_layout")
        self.failure(b"X" * (10 * 1024 * 1024 + 1), "input_limit")

    def test_external_deadline_and_bounded_stdout_and_stderr(self):
        cases = [
            ("import time; time.sleep(10)", "parser_timeout", 0.3),
            ("import os; os.write(1, b'x' * 2097153)", "parser_output_limit", 3),
            ("import os; os.write(2, b'x' * 4097)", "parser_output_limit", 3),
        ]
        for script, code, deadline in cases:
            with self.subTest(code=code), self.assertRaises(ExtractionFailure) as error:
                supervise([sys.executable, "-I", "-c", script], b"", deadline=deadline)
            self.assertEqual(error.exception.code, code)

    def test_child_environment_and_real_syscall_denials(
        self,
    ):
        script = """import runpy, socket, os, resource, json, errno, ctypes
module = runpy.run_path('/app/apps/orders/pdf_parser.py')
module['set_limits']()
observed_limits = {
 'memory': resource.getrlimit(resource.RLIMIT_AS)[0],
 'cpu': resource.getrlimit(resource.RLIMIT_CPU)[0],
 'file_size': resource.getrlimit(resource.RLIMIT_FSIZE)[0],
 'files': resource.getrlimit(resource.RLIMIT_NOFILE)[0],
 'processes': resource.getrlimit(resource.RLIMIT_NPROC)[0],
}
libc = ctypes.CDLL(None, use_errno=True)
class Limit(ctypes.Structure):
    _fields_ = [('soft', ctypes.c_ulong), ('hard', ctypes.c_ulong)]
limit = Limit(300000000, 300000000)
def extend_limits():
    if libc.setrlimit(resource.RLIMIT_AS, ctypes.byref(limit)) != 0:
        raise OSError(ctypes.get_errno(), 'denied')
module['isolate']()
outcomes = {}
operations = [
    ('network', lambda: socket.socket()),
    ('read_file', lambda: open('/etc/passwd')),
    ('write_file', lambda: open('/tmp/pdf-parser-probe', 'w')),
    ('fork', os.fork),
    ('exec', lambda: os.execv('/bin/true', ['/bin/true'])),
    ('limits', extend_limits),
]
for name, operation in operations:
    try:
        operation()
        outcomes[name] = False
    except OSError as error:
        outcomes[name] = error.errno == errno.EPERM
    except Exception as error:
        outcomes[name] = type(error).__name__
outcomes['environment'] = sorted(os.environ)
outcomes['observed_limits'] = observed_limits
try:
    allocation = bytearray(300 * 1024 * 1024)
    outcomes['memory_bound'] = False
except MemoryError:
    outcomes['memory_bound'] = True
print(json.dumps(outcomes))
"""
        with patch.dict(
            os.environ,
            {
                "DATABASE_PASSWORD": "Synthetic-never-inherited",
                "DJANGO_SECRET_KEY": "Synthetic-never-inherited",
            },
        ):
            outcome = json.loads(supervise([sys.executable, "-I", "-c", script], b""))
        self.assertTrue(
            all(
                outcome[key] is True
                for key in (
                    "network",
                    "read_file",
                    "write_file",
                    "fork",
                    "exec",
                    "limits",
                )
            )
        )
        self.assertEqual(
            outcome["environment"],
            ["LANG", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE"],
        )
        self.assertIs(outcome["memory_bound"], True)
        self.assertEqual(
            outcome["observed_limits"],
            {
                "memory": 256 * 1024 * 1024,
                "cpu": 10,
                "file_size": 0,
                "files": 32,
                "processes": 1,
            },
        )


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class TextPDFJobTests(TransactionTestCase):
    setUp = fixtures.PrivateDocumentIntakeTests.setUp
    upload = fixtures.PrivateDocumentIntakeTests.upload

    def job(self, data):
        source = self.upload(data, "synthetic.pdf")
        self.assertEqual(source.status_code, 201, source.content)
        self.path = source.json()["extraction_url"]
        first = self.client.post(
            self.path, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
        )
        self.assertEqual(first.status_code, 202, first.content)
        duplicate = self.client.post(
            self.path, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(first.json()["id"], duplicate.json()["id"])
        return DocumentExtractionJob.objects.get(pk=first.json()["id"])

    def process(self, job):
        return process_extraction(
            actor=self.user, organization_id=self.organization.pk, job_id=job.pk
        )

    def test_job_publishes_immutable_pages_without_holding_parse_transaction(self):
        job = self.job(supported_pdf())

        def actual_parse(stream):
            self.assertFalse(connection.in_atomic_block)
            return extract_pdf(stream)

        with patch(
            "apps.orders.extraction_services.extract_pdf", side_effect=actual_parse
        ):
            self.assertEqual(self.process(job), "succeeded")
        result = self.client.get(self.path).json()
        self.assertEqual(result["job"]["parser_version"], "order-text-pdf-v1")
        self.assertEqual(result["results"][0]["sku"]["page"], 1)
        self.assertEqual(len(result["job"]["result_pages"]), 1)
        self.assertEqual(self.process(job), "succeeded")
        self.assertEqual(self.client.get(self.path).json(), result)

    def test_permanent_failure_cannot_retry_or_publish_partial_rows(self):
        job = self.job(pdf_bytes([HEAD + ["A | 1 | ea | Good", "END PAGE 1/2"], []]))
        self.assertEqual(self.process(job), "failed")
        result = self.client.get(self.path).json()
        self.assertEqual(result["results"], [])
        self.assertEqual(result["job"]["result_pages"], [])
        self.assertEqual(result["job"]["error_code"], "no_text")
        self.assertFalse(result["job"]["can_retry"])
        self.assertEqual(
            self.client.post(
                self.path + "retry/", {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
            ).status_code,
            400,
        )

    def test_transient_timeout_retry_uses_same_durable_job_then_real_child(self):
        job = self.job(supported_pdf())
        with patch(
            "apps.orders.extraction_services.extract_pdf",
            side_effect=ExtractionFailure("parser_timeout"),
        ):
            self.assertEqual(self.process(job), "failed")
        self.assertTrue(self.client.get(self.path).json()["job"]["can_retry"])
        self.assertEqual(
            self.client.post(
                self.path + "retry/", {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
            ).status_code,
            202,
        )
        self.assertEqual(self.process(job), "succeeded")
        job.refresh_from_db()
        self.assertEqual(job.attempts, 2)
