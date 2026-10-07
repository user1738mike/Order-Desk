"""Global identities. Organization membership will be added in a later step."""

import uuid
from typing import Any

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from apps.accounts.managers import UserManager, canonical_email


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []
    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"), name="accounts_user_email_ci_unique"
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.email = canonical_email(self.email)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = canonical_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email


class LoginAttemptBucket(models.Model):
    """Shared login budgets; keys are HMAC digests, never raw emails or IPs."""

    key = models.CharField(max_length=64, primary_key=True)
    window_started_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"Login attempt counter {self.key[:12]}"
