from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth import aauthenticate, authenticate
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.accounts.backends import request_peer
from apps.accounts.login_limits import (
    LOGIN_WINDOW,
    login_bucket_key,
    reserve_login_attempt,
)
from apps.accounts.models import LoginAttemptBucket, User


class LoginLimitTests(TestCase):
    def test_first_attempt_creates_two_pseudonymous_budgets(self) -> None:
        self.assertIsNone(
            reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1")
        )
        self.assertEqual(LoginAttemptBucket.objects.count(), 2)
        for bucket in LoginAttemptBucket.objects.all():
            self.assertEqual(len(bucket.key), 64)
            self.assertEqual(bucket.attempts, 1)
            self.assertNotIn("buyer", bucket.key)
            self.assertNotIn("192.0.2.1", bucket.key)

    def test_email_case_and_whitespace_share_the_same_budget(self) -> None:
        self.assertEqual(
            login_bucket_key("email", " Buyer@Example.Test "),
            login_bucket_key("email", "buyer@example.test"),
        )
        self.assertNotEqual(
            login_bucket_key("email", "same"), login_bucket_key("peer", "same")
        )

    def test_hmac_keys_depend_on_the_server_secret(self) -> None:
        before = login_bucket_key("email", "buyer@example.test")
        with override_settings(SECRET_KEY="a-different-test-only-secret"):
            after = login_bucket_key("email", "buyer@example.test")
        self.assertNotEqual(before, after)

    def test_email_budget_applies_across_different_peers(self) -> None:
        with patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 2):
            self.assertIsNone(
                reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1")
            )
            self.assertIsNone(
                reserve_login_attempt(email="BUYER@example.test", peer="192.0.2.2")
            )
            wait = reserve_login_attempt(email="buyer@example.test", peer="192.0.2.3")
        self.assertGreater(wait, 0)
        self.assertLessEqual(wait, 600)
        self.assertEqual(
            LoginAttemptBucket.objects.get(
                pk=login_bucket_key("email", "buyer@example.test")
            ).attempts,
            2,
        )

    def test_peer_budget_applies_across_emails(self) -> None:
        with patch("apps.accounts.login_limits.PEER_ATTEMPT_LIMIT", 2):
            for email in ("first@example.test", "second@example.test"):
                self.assertIsNone(reserve_login_attempt(email=email, peer="192.0.2.1"))
            wait = reserve_login_attempt(email="third@example.test", peer="192.0.2.1")
        self.assertGreater(wait, 0)
        self.assertFalse(
            LoginAttemptBucket.objects.filter(
                pk=login_bucket_key("email", "third@example.test")
            ).exists()
        )

    def test_blocked_attempt_does_not_increment_other_budget(self) -> None:
        with patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 1):
            reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1")
            self.assertIsNotNone(
                reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1")
            )
        self.assertEqual(
            LoginAttemptBucket.objects.get(
                pk=login_bucket_key("peer", "192.0.2.1")
            ).attempts,
            1,
        )

    def test_window_resets_at_exact_expiry(self) -> None:
        now = timezone.now()
        with (
            patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 1),
            patch("apps.accounts.login_limits.timezone.now", return_value=now),
        ):
            self.assertIsNone(
                reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1")
            )
            self.assertEqual(
                reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1"),
                600,
            )
        with patch(
            "apps.accounts.login_limits.timezone.now", return_value=now + LOGIN_WINDOW
        ):
            self.assertIsNone(
                reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1")
            )
        for bucket in LoginAttemptBucket.objects.all():
            self.assertEqual(bucket.attempts, 1)
            self.assertEqual(bucket.window_started_at, now + LOGIN_WINDOW)

    def test_retry_after_rounds_up_and_is_positive(self) -> None:
        now = timezone.now()
        with (
            patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 1),
            patch("apps.accounts.login_limits.timezone.now", return_value=now),
        ):
            reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1")
        with (
            patch(
                "apps.accounts.login_limits.timezone.now",
                return_value=now + LOGIN_WINDOW - timedelta(milliseconds=1),
            ),
            patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 1),
        ):
            self.assertEqual(
                reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1"),
                1,
            )

    def test_database_rejects_duplicate_key_and_negative_count(self) -> None:
        LoginAttemptBucket.objects.create(
            key="a" * 64, window_started_at=timezone.now()
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            LoginAttemptBucket.objects.create(
                key="a" * 64, window_started_at=timezone.now()
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            LoginAttemptBucket.objects.create(
                key="b" * 64, window_started_at=timezone.now(), attempts=-1
            )

    def test_prune_keeps_active_and_recent_expired_windows(self) -> None:
        now = timezone.now()
        old = LoginAttemptBucket.objects.create(
            key="a" * 64, window_started_at=now - timedelta(days=2)
        )
        recent = LoginAttemptBucket.objects.create(
            key="b" * 64, window_started_at=now - timedelta(hours=1)
        )
        active = LoginAttemptBucket.objects.create(key="c" * 64, window_started_at=now)
        output = StringIO()
        call_command("prune_login_attempts", stdout=output)
        self.assertFalse(LoginAttemptBucket.objects.filter(pk=old.pk).exists())
        self.assertTrue(LoginAttemptBucket.objects.filter(pk=recent.pk).exists())
        self.assertTrue(LoginAttemptBucket.objects.filter(pk=active.pk).exists())
        self.assertIn("Deleted 1", output.getvalue())

    def test_missing_peer_and_spoofed_forwarded_headers_do_not_bypass_budget(
        self,
    ) -> None:
        factory = RequestFactory()
        request = factory.post("/", HTTP_X_FORWARDED_FOR="203.0.113.99")
        self.assertEqual(request_peer(request), "127.0.0.1")
        request.META["REMOTE_ADDR"] = "invalid"
        self.assertEqual(request_peer(request), "unknown")
        request.META.pop("REMOTE_ADDR")
        self.assertEqual(request_peer(request), "unknown")
        request.META["REMOTE_ADDR"] = "2001:0db8:0000:0000:0000:0000:0000:0001"
        self.assertEqual(request_peer(request), "2001:db8::1")

    @override_settings(
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
    )
    def test_successful_authentication_still_consumes_an_attempt(self) -> None:
        user = User.objects.create_user(
            email="buyer@example.test", password="test-password-42"
        )
        request = RequestFactory().post("/")
        with patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 1):
            self.assertEqual(
                authenticate(request, email=user.email, password="test-password-42"),
                user,
            )
            self.assertIsNone(
                authenticate(
                    RequestFactory().post("/"),
                    email=user.email,
                    password="test-password-42",
                )
            )

    @override_settings(
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
    )
    def test_async_authentication_uses_the_same_shared_budget(self) -> None:
        user = User.objects.create_user(
            email="buyer@example.test", password="test-password-42"
        )
        with patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 1):
            self.assertEqual(
                authenticate(
                    RequestFactory().post("/"),
                    email=user.email,
                    password="test-password-42",
                ),
                user,
            )
            request = RequestFactory().post("/")
            self.assertIsNone(
                async_to_sync(aauthenticate)(
                    request, email=user.email, password="test-password-42"
                )
            )
            self.assertGreater(request.login_retry_after, 0)

    def test_counter_update_failure_rolls_back_the_reservation(self) -> None:
        reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1")
        real_save = LoginAttemptBucket.save
        save_calls = 0

        def fail_second_save(bucket, *args, **kwargs):
            nonlocal save_calls
            save_calls += 1
            if save_calls == 2:
                raise RuntimeError("Second counter update failed.")
            return real_save(bucket, *args, **kwargs)

        with (
            patch.object(LoginAttemptBucket, "save", new=fail_second_save),
            self.assertRaises(RuntimeError),
        ):
            reserve_login_attempt(email="buyer@example.test", peer="192.0.2.1")
        self.assertEqual(LoginAttemptBucket.objects.count(), 2)
        self.assertEqual(
            list(LoginAttemptBucket.objects.values_list("attempts", flat=True)), [1, 1]
        )
