"""Atomic, fixed-window login budgets shared by every application process."""

import math
from datetime import datetime, timedelta
from typing import Literal

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.accounts.models import LoginAttemptBucket

LOGIN_WINDOW = timedelta(minutes=10)
EMAIL_ATTEMPT_LIMIT = 10
PEER_ATTEMPT_LIMIT = 60
BUCKET_RETENTION = timedelta(days=1)


def login_bucket_key(kind: Literal["email", "peer"], identity: str) -> str:
    if kind == "email":
        identity = identity.strip().lower()
    return salted_hmac(
        f"orderdesk.login.{kind}", identity, algorithm="sha256"
    ).hexdigest()


def retry_after(bucket: LoginAttemptBucket, limit: int, now: datetime) -> int | None:
    remaining = (bucket.window_started_at + LOGIN_WINDOW - now).total_seconds()
    if remaining > 0 and bucket.attempts >= limit:
        return max(1, math.ceil(remaining))
    return None


@transaction.atomic
def reserve_login_attempt(*, email: str, peer: str) -> int | None:
    """Reserve one attempt before hashing; return seconds to wait if blocked.

    Accepted attempts count whether credentials succeed or fail. No network
    calls or password hashing happen while the database rows are locked.
    """
    now = timezone.now()
    email_key = login_bucket_key("email", email)
    peer_key = login_bucket_key("peer", peer)

    # Avoid creating a fresh email row for every request from a blocked peer.
    peer_bucket = LoginAttemptBucket.objects.filter(pk=peer_key).first()
    if peer_bucket is not None:
        wait = retry_after(peer_bucket, PEER_ATTEMPT_LIMIT, now)
        if wait is not None:
            return wait

    buckets = []
    # A consistent key order avoids deadlocks when requests share one bucket.
    for key, limit in sorted(
        [(email_key, EMAIL_ATTEMPT_LIMIT), (peer_key, PEER_ATTEMPT_LIMIT)]
    ):
        # Existing rows are locked. A new row is protected by its unique PK and
        # this transaction; get_or_create handles a concurrent first insertion.
        bucket, _ = LoginAttemptBucket.objects.select_for_update().get_or_create(
            key=key, defaults={"window_started_at": now, "attempts": 0}
        )
        buckets.append((bucket, limit))

    # Re-read the clock after locking; queued requests may cross a window edge.
    now = timezone.now()
    waits = [
        wait
        for bucket, limit in buckets
        if (wait := retry_after(bucket, limit, now)) is not None
    ]
    if waits:
        return max(waits)

    for bucket, _ in buckets:
        if bucket.window_started_at + LOGIN_WINDOW <= now:
            bucket.window_started_at = now
            bucket.attempts = 0
        bucket.attempts += 1
        bucket.save(update_fields=["window_started_at", "attempts"])
    return None
