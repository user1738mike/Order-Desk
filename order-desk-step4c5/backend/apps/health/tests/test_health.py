from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient


class LivenessTests(SimpleTestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def test_liveness_is_public_and_does_not_access_database(self) -> None:
        # SimpleTestCase forbids database access, so this also verifies independence.
        response = self.client.get(reverse("health:live"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(response["Content-Type"].startswith("application/json"))

    def test_post_is_not_allowed(self) -> None:
        response = self.client.post(reverse("health:live"), {}, format="json")
        self.assertEqual(response.status_code, 405)


class ReadinessTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def test_readiness_checks_migrated_database_without_requiring_a_user(self) -> None:
        response = self.client.get(reverse("health:ready"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_database_failure_returns_503_without_exception_details(self) -> None:
        with patch(
            "apps.health.views.User.objects.exists",
            side_effect=OperationalError("private database connection details"),
        ):
            response = self.client.get(reverse("health:ready"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotContains(
            response, "private database connection details", status_code=503
        )
