"""Email-only user creation. UUIDs identify users; email is the login identifier."""

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

if TYPE_CHECKING:
    from apps.accounts.models import User


def canonical_email(value: str) -> str:
    """Product policy: an email address represents one account, regardless of case."""
    email = value.strip().lower()
    validate_email(email)
    return email


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, email: str) -> User:
        return self.get(email__iexact=email.strip())

    def _create_user(
        self, email: str, password: str | None, **extra_fields: Any
    ) -> User:
        try:
            email = canonical_email(email)
        except ValidationError as error:
            raise ValueError("A valid email address is required.") from error
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if (
            extra_fields["is_staff"] is not True
            or extra_fields["is_superuser"] is not True
        ):
            raise ValueError(
                "A superuser requires is_staff=True and is_superuser=True."
            )
        if not password:
            raise ValueError("A superuser requires a password.")
        return self._create_user(email, password, **extra_fields)
