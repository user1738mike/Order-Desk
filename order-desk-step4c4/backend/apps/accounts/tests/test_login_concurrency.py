from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.accounts.login_limits import login_bucket_key, reserve_login_attempt
from apps.accounts.models import LoginAttemptBucket


@skipUnlessDBFeature("has_select_for_update")
class LoginLimitConcurrencyTests(TransactionTestCase):
    def test_concurrent_first_attempts_cannot_exceed_account_budget(self) -> None:
        barrier = Barrier(2)

        def attempt(peer: str) -> str:
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                wait = reserve_login_attempt(email="buyer@example.test", peer=peer)
                return "accepted" if wait is None else "limited"
            finally:
                connections["default"].close()

        with (
            patch("apps.accounts.login_limits.EMAIL_ATTEMPT_LIMIT", 1),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            futures = [
                executor.submit(attempt, peer) for peer in ("192.0.2.1", "192.0.2.2")
            ]
            results = [future.result(timeout=20) for future in futures]

        self.assertCountEqual(results, ["accepted", "limited"])
        self.assertEqual(
            LoginAttemptBucket.objects.get(
                pk=login_bucket_key("email", "buyer@example.test")
            ).attempts,
            1,
        )
