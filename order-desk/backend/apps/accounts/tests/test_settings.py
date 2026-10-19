import json
import os
import subprocess
import sys
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.env import boolean, integer, required


class EnvironmentTests(SimpleTestCase):
    def test_missing_secret_fails_without_echoing_values(self) -> None:
        with patch.dict(os.environ, {"STEP3_TEST_SECRET": ""}):
            with self.assertRaisesMessage(ImproperlyConfigured, "STEP3_TEST_SECRET"):
                required("STEP3_TEST_SECRET")

    def test_invalid_boolean_is_rejected(self) -> None:
        with patch.dict(os.environ, {"STEP3_TEST_BOOLEAN": "sometimes"}):
            with self.assertRaisesMessage(ImproperlyConfigured, "STEP3_TEST_BOOLEAN"):
                boolean("STEP3_TEST_BOOLEAN")

    def test_port_outside_allowed_range_is_rejected(self) -> None:
        with patch.dict(os.environ, {"STEP3_TEST_PORT": "70000"}):
            with self.assertRaisesMessage(ImproperlyConfigured, "STEP3_TEST_PORT"):
                integer("STEP3_TEST_PORT", 5432)


class ProductionSettingsTests(SimpleTestCase):
    def production_check(
        self, overrides: dict[str, str], code: str
    ) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment.update(
            DJANGO_SETTINGS_MODULE="config.settings.production",
            DJANGO_ALLOWED_HOSTS="orders.example.com",
            DJANGO_CSRF_TRUSTED_ORIGINS="https://orders.example.com",
            DJANGO_SECRET_KEY="step3-settings-test-key-abcdefghijklmnopqrstuvwxyz-0123456789",
            DATABASE_SSLROOTCERT="/verification-only/not-a-real-ca.pem",
            DJANGO_TRUST_PROXY_HTTPS="false",
        )
        environment.update(overrides)
        # Fixed interpreter and code only. No shell, user input, or live DB connection.
        return subprocess.run(  # noqa: S603
            [sys.executable, "-c", code],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_production_security_defaults(self) -> None:
        result = self.production_check(
            {},
            "from django.conf import settings as s; "
            "print(s.DEBUG, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, "
            "s.SECURE_SSL_REDIRECT, s.DATABASES['default']['OPTIONS']['sslmode'])",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False True True True verify-full")

    def test_http_errors_keep_diagnostics_without_private_exception_text(self):
        result = self.production_check(
            {},
            "import django, logging; from types import SimpleNamespace; "
            "django.setup(); "
            "request = SimpleNamespace(method='POST', "
            "resolver_match=SimpleNamespace(view_name='workspaces:orders:detail'), "
            "META={'HTTP_X_REQUEST_ID': 'a'*32, 'HTTP_COOKIE': 'PRIVATE-COOKIE'}, "
            "body=b'PRIVATE-DOCUMENT'); "
            "[(logging.getLogger(name).error('PRIVATE-DOCUMENT: %s', 'PRIVATE-COOKIE', "
            "exc_info=(ValueError,ValueError('PRIVATE-DOCUMENT'),None), "
            "extra={'request':request,'status_code':500})) "
            "for name in ('django.request','django.security.csrf','django.server')]",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("PRIVATE-DOCUMENT", result.stderr)
        self.assertNotIn("PRIVATE-COOKIE", result.stderr)
        records = [json.loads(line) for line in result.stderr.splitlines()]
        self.assertEqual(len(records), 3)
        for record in records:
            self.assertEqual(record["status"], 500)
            self.assertEqual(record["method"], "POST")
            self.assertEqual(record["route"], "workspaces:orders:detail")
            self.assertEqual(record["error_type"], "ValueError")
            self.assertEqual(record["request_id"], "a" * 32)
            self.assertEqual(record["level"], "ERROR")

    def test_wildcard_host_is_rejected(self) -> None:
        result = self.production_check(
            {"DJANGO_ALLOWED_HOSTS": "*"}, "from config.settings import production"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_ALLOWED_HOSTS", result.stderr)

    def test_weak_secret_is_rejected(self) -> None:
        result = self.production_check(
            {"DJANGO_SECRET_KEY": "weak"}, "from config.settings import production"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("strong DJANGO_SECRET_KEY", result.stderr)

    def test_missing_database_ca_is_rejected(self) -> None:
        result = self.production_check(
            {"DATABASE_SSLROOTCERT": ""}, "from config.settings import production"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_SSLROOTCERT", result.stderr)
