"""Offline confinement and failure-cleanup checks for the live catalogue verifier.

Run on the host:
    python -m unittest discover -s scripts/tests -v
"""

import contextlib
import io
import unittest
from unittest.mock import patch
from uuid import UUID

from scripts import verify_catalog_api as verifier

BASE = verifier.DEFAULT_BASE_URL
WORKSPACE = UUID("11111111-1111-4111-8111-111111111111")
ENDPOINT = f"/api/v1/workspaces/{WORKSPACE}/catalog/items/"
PRIVATE = "max-age=0, no-cache, no-store, must-revalidate, private"


class LocalTargetGuardTests(unittest.TestCase):
    def test_only_numeric_loopback_http_origins_are_allowed(self) -> None:
        for url in (
            "http://127.0.0.1:8000",
            "http://127.0.0.2:8000/",
            "https://[::1]:8443/",
        ):
            with self.subTest(url=url):
                self.assertEqual(verifier.validate_base_url(url), url.rstrip("/"))
        for url in (
            "https://example.test",
            "http://localhost:8000",
            "http://192.168.1.2:8000",
            "http://0.0.0.0:8000",
            "file:///tmp/local",
            "http://user:password@127.0.0.1:8000",
            BASE + "/api/v1",
            BASE + "?secret=value",
            BASE + "#fragment",
            "http://127.0.0.1:0",
            "http://127.0.0.1:65536",
            "http://127.0.0.1:invalid",
            BASE + "\n",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                verifier.validate_base_url(url)

    def test_relative_requests_cannot_replace_the_origin(self) -> None:
        self.assertEqual(verifier.request_url(BASE, ENDPOINT), BASE + ENDPOINT)
        for path in (
            "//example.test/credentials",
            "https://example.test/credentials",
            "catalog/items/",
            ENDPOINT + "#fragment",
            ENDPOINT + "\n",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                verifier.request_url(BASE, path)

    def test_pagination_cannot_escape_origin_endpoint_or_query_allowlist(self) -> None:
        expected = (BASE + ENDPOINT + "?page=2", 2)
        self.assertEqual(
            verifier.page_path(BASE, expected[0], endpoint=ENDPOINT), expected
        )
        self.assertEqual(
            verifier.page_path(BASE, ENDPOINT + "?page=2", endpoint=ENDPOINT),
            expected,
        )
        for link in (
            "https://example.test" + ENDPOINT + "?page=2",
            "http://127.0.0.1:9000" + ENDPOINT + "?page=2",
            "http://user@127.0.0.1:8000" + ENDPOINT + "?page=2",
            BASE + verifier.WORKSPACES + "?page=2",
            BASE + ENDPOINT + "?page=2&page=3",
            BASE + ENDPOINT + "?page=2&organization_id=forged",
            BASE + ENDPOINT + "?page=0",
            BASE + ENDPOINT + "?page=2#secret",
            "//example.test" + ENDPOINT + "?page=2",
        ):
            with self.subTest(link=link), self.assertRaises(RuntimeError):
                verifier.page_path(BASE, link, endpoint=ENDPOINT)

    def test_redirects_are_refused_even_when_target_is_loopback(self) -> None:
        request = verifier.urllib.request.Request(BASE)
        redirect = verifier.NoRedirect()
        self.assertIsNone(
            redirect.redirect_request(
                request, None, 302, "Moved", {}, BASE + "/unexpected"
            )
        )
        self.assertIsNone(
            redirect.redirect_request(
                request, None, 307, "Moved", {}, "https://example.test"
            )
        )


class CatalogueResponseTests(unittest.TestCase):
    @staticmethod
    def response(page: dict, cache_control: str = PRIVATE) -> verifier.Response:
        return verifier.Response(page, cache_control)

    def test_empty_first_page_requires_no_fixture_creation(self) -> None:
        page = {"count": 0, "next": None, "previous": None, "results": []}
        self.assertEqual(
            verifier.validate_catalogue_page(
                self.response(page),
                base_url=BASE,
                endpoint=ENDPOINT,
                number=1,
            ),
            page,
        )

    def test_unexpected_fields_and_private_cache_fail_closed(self) -> None:
        item = {
            "id": str(WORKSPACE),
            "organization_id": str(WORKSPACE),
            "sku": "000-part",
            "description": "",
            "is_active": False,
            "created_at": "2026-10-05T12:00:00Z",
            "updated_at": "2026-10-05T12:00:00Z",
        }
        page = {"count": 1, "next": None, "previous": None, "results": [item]}
        verifier.validate_catalogue_page(
            self.response(page), base_url=BASE, endpoint=ENDPOINT, number=1
        )
        item["user_id"] = str(WORKSPACE)
        with self.assertRaisesRegex(RuntimeError, "unexpected fields"):
            verifier.validate_catalogue_page(
                self.response(page), base_url=BASE, endpoint=ENDPOINT, number=1
            )
        with self.assertRaisesRegex(RuntimeError, "private"):
            verifier.validate_catalogue_page(
                self.response(page, "public, max-age=3600"),
                base_url=BASE,
                endpoint=ENDPOINT,
                number=1,
            )

    def test_foreign_organization_field_is_rejected(self) -> None:
        item = {
            "id": str(WORKSPACE),
            "organization_id": "22222222-2222-4222-8222-222222222222",
            "sku": "000-part",
            "description": "",
            "is_active": True,
            "created_at": "2026-10-05T12:00:00Z",
            "updated_at": "2026-10-05T12:00:00Z",
        }
        page = {"count": 1, "next": None, "previous": None, "results": [item]}
        with self.assertRaisesRegex(RuntimeError, "another workspace"):
            verifier.validate_catalogue_page(
                self.response(page), base_url=BASE, endpoint=ENDPOINT, number=1
            )

    def test_count_and_page_size_must_agree(self) -> None:
        for count in (True, -1, 1, 51):
            page = {"count": count, "next": None, "previous": None, "results": []}
            with self.subTest(count=count), self.assertRaises(RuntimeError):
                verifier.validate_catalogue_page(
                    self.response(page), base_url=BASE, endpoint=ENDPOINT, number=1
                )

    def test_second_page_accepts_drf_previous_link_without_page_query(self) -> None:
        item = {
            "id": str(WORKSPACE),
            "organization_id": str(WORKSPACE),
            "sku": "000-part",
            "description": "",
            "is_active": True,
            "created_at": "2026-10-05T12:00:00Z",
            "updated_at": "2026-10-05T12:00:00Z",
        }
        page = {
            "count": 51,
            "next": None,
            "previous": BASE + ENDPOINT,
            "results": [item],
        }
        self.assertEqual(
            verifier.validate_catalogue_page(
                self.response(page), base_url=BASE, endpoint=ENDPOINT, number=2
            ),
            page,
        )


class SessionCleanupTests(unittest.TestCase):
    def run_main(
        self, *, verification_error=None, malformed_login=False, cleanup_error=False
    ):
        requests = []

        def fake_request(opener, base_url, path, **kwargs):
            requests.append((path, kwargs))
            if path == "/api/v1/auth/csrf/":
                if cleanup_error and len(requests) > 4:
                    raise RuntimeError("Synthetic cleanup failure.")
                return verifier.Response({"csrf_token": "offline-csrf"}, PRIVATE)
            if path == "/api/v1/auth/login/":
                body = {} if malformed_login else {"csrf_token": "offline-rotated"}
                return verifier.Response(body, PRIVATE)
            if path == "/api/v1/auth/logout/":
                return verifier.Response(None, PRIVATE)
            return verifier.Response(verifier.DENIAL, PRIVATE)

        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch.object(verifier, "request", side_effect=fake_request),
            patch.object(verifier, "choose_workspace", return_value=str(WORKSPACE)),
            patch.object(verifier, "verify_catalogue", side_effect=verification_error),
            patch("builtins.input", return_value="existing@example.test"),
            patch.object(
                verifier.getpass, "getpass", return_value="offline-secret-value"
            ),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            caught = None
            try:
                verifier.main([])
            except RuntimeError as error:
                caught = error
        self.assertNotIn("offline-secret-value", output.getvalue() + errors.getvalue())
        return requests, caught, output.getvalue(), errors.getvalue()

    def test_failed_verification_logs_out_with_a_fresh_csrf_token(self) -> None:
        requests, error, _, _ = self.run_main(
            verification_error=RuntimeError("Synthetic assertion failure.")
        )
        self.assertEqual(str(error), "Synthetic assertion failure.")
        self.assertEqual(requests[-2][0], "/api/v1/auth/csrf/")
        self.assertEqual(requests[-1][0], "/api/v1/auth/logout/")
        self.assertEqual(requests[-1][1]["csrf"], "offline-csrf")

    def test_malformed_login_response_still_attempts_session_cleanup(self) -> None:
        requests, error, _, _ = self.run_main(malformed_login=True)
        self.assertIn("rotated CSRF", str(error))
        self.assertEqual(requests[-1][0], "/api/v1/auth/logout/")

    def test_cleanup_failure_preserves_original_verification_error(self) -> None:
        _, error, _, stderr = self.run_main(
            verification_error=RuntimeError("Original verification failure."),
            cleanup_error=True,
        )
        self.assertEqual(str(error), "Original verification failure.")
        self.assertIn("Session cleanup failed", stderr)

    def test_success_requires_logout_before_reporting_pass(self) -> None:
        requests, error, stdout, _ = self.run_main()
        self.assertIsNone(error)
        self.assertEqual(requests[-2][0], "/api/v1/auth/logout/")
        self.assertEqual(requests[-1][1]["expected"], 403)
        self.assertIn("Read-only catalogue HTTP verification passed.", stdout)


if __name__ == "__main__":
    unittest.main()
