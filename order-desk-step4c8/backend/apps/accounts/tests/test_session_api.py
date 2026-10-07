"""Login/logout tests enforce CSRF and enter real credentials over HTTP."""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import LoginAttemptBucket, User
from apps.organizations.models import Membership, Organization


# Fast hashing is confined to these behavior tests. The application retains
# Django's secure default hashers; the existing user tests exercise them.
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SessionApiTests(TestCase):
    password = "  local-session-test-password-42  "  # noqa: S105 -- test fixture only

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(
            email="member@example.test", password=cls.password
        )
        cls.other = User.objects.create_user(
            email="other@example.test", password="other-session-password-42"
        )
        cls.organization = Organization.objects.create(name="Member Distributor")
        cls.other_organization = Organization.objects.create(name="Other Distributor")
        Membership.objects.create(user=cls.user, organization=cls.organization)
        Membership.objects.create(user=cls.other, organization=cls.other_organization)

    def setUp(self) -> None:
        self.client = APIClient(enforce_csrf_checks=True)
        self.csrf_url = reverse("session_auth:csrf")
        self.login_url = reverse("session_auth:login")
        self.logout_url = reverse("session_auth:logout")
        self.workspaces_url = reverse("workspaces:list")

    def csrf(self) -> str:
        response = self.client.get(self.csrf_url)
        self.assertEqual(response.status_code, 200)
        return response.json()["csrf_token"]

    def login(self, **credentials):
        token = self.csrf()
        data = {"email": self.user.email, "password": self.password}
        data.update(credentials)
        return self.client.post(
            self.login_url, data, format="json", HTTP_X_CSRFTOKEN=token
        )

    def assert_csrf_failure(self, response) -> None:
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "CSRF verification failed."})
        self.assertIn("no-store", response["Cache-Control"])

    def test_bootstrap_is_public_sets_cookie_and_does_not_create_a_session(
        self,
    ) -> None:
        response = self.client.get(self.csrf_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"csrf_token"})
        self.assertEqual(len(response.json()["csrf_token"]), 64)
        self.assertIn(settings.CSRF_COOKIE_NAME, response.cookies)
        self.assertEqual(Session.objects.count(), 0)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])

    def test_anonymous_login_without_csrf_cookie_or_token_is_denied(self) -> None:
        with patch("apps.accounts.views.authenticate") as authenticate:
            response = self.client.post(
                self.login_url,
                {"email": self.user.email, "password": self.password},
                format="json",
            )
        self.assert_csrf_failure(response)
        authenticate.assert_not_called()
        self.assertEqual(LoginAttemptBucket.objects.count(), 0)

    def test_csrf_header_without_matching_cookie_is_denied(self) -> None:
        token = self.csrf()
        self.client.cookies.clear()
        response = self.client.post(
            self.login_url, {}, format="json", HTTP_X_CSRFTOKEN=token
        )
        self.assert_csrf_failure(response)

    def test_csrf_cookie_without_header_is_denied(self) -> None:
        self.csrf()
        response = self.client.post(self.login_url, {}, format="json")
        self.assert_csrf_failure(response)

    def test_wrong_csrf_token_is_denied(self) -> None:
        self.csrf()
        response = self.client.post(
            self.login_url, {}, format="json", HTTP_X_CSRFTOKEN="x" * 64
        )
        self.assert_csrf_failure(response)

    def test_untrusted_origin_is_denied_with_valid_csrf(self) -> None:
        token = self.csrf()
        response = self.client.post(
            self.login_url,
            {},
            format="json",
            HTTP_X_CSRFTOKEN=token,
            HTTP_ORIGIN="https://untrusted.example.test",
        )
        self.assert_csrf_failure(response)
        self.assertEqual(LoginAttemptBucket.objects.count(), 0)

    def test_https_login_without_referer_or_origin_is_denied(self) -> None:
        token = self.csrf()
        response = self.client.post(
            self.login_url, {}, format="json", HTTP_X_CSRFTOKEN=token, secure=True
        )
        self.assert_csrf_failure(response)

    def test_correct_origin_with_valid_csrf_is_accepted(self) -> None:
        token = self.csrf()
        response = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=token,
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, 200)

    def test_login_creates_ordinary_user_session_with_explicit_response_fields(
        self,
    ) -> None:
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"user", "csrf_token"})
        self.assertEqual(
            response.json()["user"],
            {"id": str(self.user.pk), "email": self.user.email},
        )
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertNotContains(response, self.password)
        self.assertIn("no-store", response["Cache-Control"])

    def test_email_is_canonicalized_and_password_whitespace_is_preserved(self) -> None:
        self.assertEqual(self.login(email="  MEMBER@EXAMPLE.TEST  ").status_code, 200)
        self.assertEqual(self.login(password=self.password.strip()).status_code, 400)

    def test_wrong_unknown_inactive_and_unusable_credentials_have_same_error(
        self,
    ) -> None:
        inactive = User.objects.create_user(
            email="inactive@example.test", password=self.password, is_active=False
        )
        unusable = User.objects.create_user(email="unusable@example.test")
        errors = []
        for credentials in (
            {"password": "incorrect-password"},
            {"email": "unknown@example.test"},
            {"email": inactive.email},
            {"email": unusable.email},
        ):
            with self.subTest(credentials=credentials):
                response = self.login(**credentials)
                self.assertEqual(response.status_code, 400)
                errors.append(response.json())
                self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(errors, [{"detail": "Invalid email or password."}] * 4)

    def test_missing_invalid_and_nonstring_inputs_fail_before_authentication(
        self,
    ) -> None:
        token = self.csrf()
        for data in (
            {},
            {"email": "invalid", "password": self.password},
            {"email": self.user.email, "password": ""},
            {"email": self.user.email, "password": 123},
            {"email": self.user.email, "password": ["invalid"]},
            ["invalid"],
        ):
            with (
                self.subTest(data=data),
                patch("apps.accounts.views.authenticate") as auth,
            ):
                response = self.client.post(
                    self.login_url, data, format="json", HTTP_X_CSRFTOKEN=token
                )
                self.assertEqual(response.status_code, 400)
                auth.assert_not_called()
        self.assertEqual(LoginAttemptBucket.objects.count(), 0)

    def test_password_and_email_length_limits_fail_before_authentication(self) -> None:
        token = self.csrf()
        for data in (
            {"email": self.user.email, "password": "x" * 1025},
            {"email": "x" * 250 + "@example.test", "password": self.password},
        ):
            with self.subTest(field_lengths=[len(value) for value in data.values()]):
                response = self.client.post(
                    self.login_url, data, format="json", HTTP_X_CSRFTOKEN=token
                )
                self.assertEqual(response.status_code, 400)
        self.assertEqual(LoginAttemptBucket.objects.count(), 0)

    def test_oversized_body_is_rejected_before_credentials_are_processed(self) -> None:
        token = self.csrf()
        with patch("apps.accounts.views.authenticate") as authenticate:
            response = self.client.post(
                self.login_url,
                " " * (16 * 1024 + 1),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=token,
            )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {"detail": "Login request is too large."})
        authenticate.assert_not_called()

    def test_non_json_and_malformed_json_are_rejected(self) -> None:
        token = self.csrf()
        response = self.client.post(
            self.login_url,
            "email=test&password=test",
            content_type="application/x-www-form-urlencoded",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 415)
        response = self.client.post(
            self.login_url,
            "{",
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 400)

    def test_login_replaces_existing_session_and_discards_old_workspace_context(
        self,
    ) -> None:
        session = self.client.session
        session["selected_workspace_id"] = str(self.other_organization.pk)
        session.save()
        old_key = session.session_key
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assertNotIn("selected_workspace_id", self.client.session)

    def test_same_user_relogin_also_replaces_session(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        old_key = self.client.session.session_key
        self.assertEqual(self.login().status_code, 200)
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())

    def test_login_rotates_csrf_secret_and_old_token_cannot_logout(self) -> None:
        old_token = self.csrf()
        old_secret = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        response = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=old_token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(
            self.client.cookies[settings.CSRF_COOKIE_NAME].value, old_secret
        )
        denied = self.client.post(
            self.logout_url, {}, format="json", HTTP_X_CSRFTOKEN=old_token
        )
        self.assert_csrf_failure(denied)
        self.assertEqual(self.client.get(self.workspaces_url).status_code, 200)
        allowed = self.client.post(
            self.logout_url,
            {},
            format="json",
            HTTP_X_CSRFTOKEN=response.json()["csrf_token"],
        )
        self.assertEqual(allowed.status_code, 204)

    def test_login_session_has_an_absolute_eight_hour_expiry(self) -> None:
        before = timezone.now()
        self.assertEqual(self.login().status_code, 200)
        expires = self.client.session.get_expiry_date()
        self.assertGreaterEqual(expires, before + timedelta(hours=8))
        self.assertLessEqual(expires, timezone.now() + timedelta(hours=8))
        self.client.get(self.workspaces_url)
        self.assertEqual(self.client.session.get_expiry_date(), expires)

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_session_cookie_uses_secure_httponly_and_samesite_flags(self) -> None:
        response = self.login()
        self.assertEqual(response.status_code, 200)
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertTrue(response.cookies[settings.CSRF_COOKIE_NAME]["secure"])

    def test_session_authenticates_existing_scoped_workspace_endpoint(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        response = self.client.get(self.workspaces_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"],
            [{"id": str(self.organization.pk), "name": self.organization.name}],
        )

    def test_client_fields_cannot_elevate_role_or_select_another_identity(self) -> None:
        response = self.login(
            user_id=str(self.other.pk),
            is_staff=True,
            is_superuser=True,
            workspace_id=str(self.other_organization.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], str(self.user.pk))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertNotIn("workspace_id", self.client.session)

    def test_invalid_relogin_preserves_current_session(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        key = self.client.session.session_key
        self.assertEqual(self.login(password="incorrect-password").status_code, 400)
        self.assertEqual(self.client.session.session_key, key)
        self.assertEqual(self.client.get(self.workspaces_url).status_code, 200)

    def test_identity_switch_drops_previous_session_context(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        old_key = self.client.session.session_key
        session = self.client.session
        session["selected_workspace_id"] = str(self.organization.pk)
        session.save()
        response = self.login(
            email=self.other.email, password="other-session-password-42"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("selected_workspace_id", self.client.session)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assertEqual(self.client.session[SESSION_KEY], str(self.other.pk))
        self.assertEqual(
            self.client.get(self.workspaces_url).json()["results"],
            [
                {
                    "id": str(self.other_organization.pk),
                    "name": self.other_organization.name,
                }
            ],
        )

    def test_logout_without_csrf_is_denied_and_preserves_access(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        self.assert_csrf_failure(self.client.post(self.logout_url, {}, format="json"))
        self.assertEqual(self.client.get(self.workspaces_url).status_code, 200)

    def test_logout_flushes_session_and_replayed_old_cookie_is_denied(self) -> None:
        response = self.login()
        key = self.client.session.session_key
        token = response.json()["csrf_token"]
        logged_out = self.client.post(
            self.logout_url, {}, format="json", HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(logged_out.status_code, 204)
        self.assertEqual(logged_out.content, b"")
        self.assertIn("no-store", logged_out["Cache-Control"])
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        replay = APIClient(enforce_csrf_checks=True)
        replay.cookies[settings.SESSION_COOKIE_NAME] = key
        self.assertEqual(replay.get(self.workspaces_url).status_code, 403)

    def test_logout_is_idempotent_with_valid_csrf(self) -> None:
        token = self.csrf()
        for _ in range(2):
            response = self.client.post(
                self.logout_url, {}, format="json", HTTP_X_CSRFTOKEN=token
            )
            self.assertEqual(response.status_code, 204)

    def test_expired_authenticated_session_is_denied(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        Session.objects.filter(session_key=self.client.session.session_key).update(
            expire_date=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.client.get(self.workspaces_url).status_code, 403)

    def test_password_change_invalidates_existing_session(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        self.user.set_password("changed-session-password-42")
        self.user.save(update_fields=["password"])
        self.assertEqual(self.client.get(self.workspaces_url).status_code, 403)

    def test_login_and_logout_reject_get_without_changing_session(self) -> None:
        self.assertEqual(self.client.get(self.login_url).status_code, 405)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get(self.logout_url).status_code, 405)
        self.assertEqual(self.client.get(self.workspaces_url).status_code, 200)

    def test_rate_limit_returns_retry_after_and_never_checks_blocked_password(
        self,
    ) -> None:
        with patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 1):
            self.assertEqual(self.login(password="incorrect-password").status_code, 400)
            with patch(
                "django.contrib.auth.backends.ModelBackend.authenticate"
            ) as auth:
                response = self.login()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(), {"detail": "Too many login attempts. Try again later."}
            )
            self.assertGreater(int(response["Retry-After"]), 0)
            self.assertLessEqual(int(response["Retry-After"]), 600)
            self.assertIn("no-store", response["Cache-Control"])
            auth.assert_not_called()
            self.assertNotIn(SESSION_KEY, self.client.session)

    def test_limiter_database_failure_fails_closed_before_password_check(self) -> None:
        token = self.csrf()
        with (
            patch(
                "apps.accounts.backends.reserve_login_attempt",
                side_effect=DatabaseError,
            ),
            patch("django.contrib.auth.backends.ModelBackend.authenticate") as auth,
        ):
            response = self.client.post(
                self.login_url,
                {"email": self.user.email, "password": self.password},
                format="json",
                HTTP_X_CSRFTOKEN=token,
            )
        auth.assert_not_called()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"detail": "Sign-in is temporarily unavailable."}
        )
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_admin_login_cannot_bypass_the_same_account_budget(self) -> None:
        operator = User.objects.create_superuser(
            email="operator@example.test", password="operator-session-password-42"
        )
        with patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 1):
            self.assertEqual(
                self.login(email=operator.email, password="wrong").status_code, 400
            )
            self.client.get(reverse("admin:login"))
            token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
            response = self.client.post(
                reverse("admin:login"),
                {
                    "username": operator.email,
                    "password": "operator-session-password-42",
                    "csrfmiddlewaretoken": token,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(SESSION_KEY, self.client.session)

    def test_api_csrf_errors_are_generic_but_admin_retains_html(self) -> None:
        response = self.client.post(reverse("admin:login"), {})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response["Content-Type"].startswith("text/html"))
        self.assert_csrf_failure(self.client.post(self.login_url, {}, format="json"))
