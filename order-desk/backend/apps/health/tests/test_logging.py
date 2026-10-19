"""Production diagnostic retention and rejection of untrusted log payloads."""

import json
import logging
from types import SimpleNamespace

from django.test import SimpleTestCase

from config.logging import RedactedHttpFormatter


class RedactedHttpLoggingTests(SimpleTestCase):
    def test_untrusted_metadata_is_not_echoed(self):
        record = logging.makeLogRecord(
            {
                "msg": "PRIVATE-MESSAGE",
                "args": ("PRIVATE-ARGUMENT",),
                "levelno": logging.WARNING,
                "levelname": "WARNING",
                "request": SimpleNamespace(
                    method="PRIVATE-METHOD",
                    META={"HTTP_X_REQUEST_ID": "PRIVATE-HEADER"},
                    resolver_match=SimpleNamespace(view_name="PRIVATE/ROUTE"),
                ),
                "status_code": "PRIVATE-STATUS",
                "stack_info": "PRIVATE-STACK",
                "exc_text": "PRIVATE-EXCEPTION",
            }
        )
        text = RedactedHttpFormatter().format(record)
        self.assertNotIn("PRIVATE", text)
        result = json.loads(text)
        self.assertEqual(result["level"], "WARNING")
        self.assertEqual(result["event"], "http_event")
        self.assertEqual(result["method"], "OTHER")
        for key in ("status", "route", "request_id", "error_type"):
            self.assertIsNone(result[key])

    def test_message_objects_are_never_formatted(self):
        class PrivatePayload:
            def __str__(self):
                raise AssertionError("Private payload must not be rendered.")

        record = logging.makeLogRecord(
            {
                "msg": PrivatePayload(),
                "args": (),
                "levelno": logging.INFO,
                "levelname": "INFO",
            }
        )
        self.assertEqual(
            json.loads(RedactedHttpFormatter().format(record))["method"], "OTHER"
        )
