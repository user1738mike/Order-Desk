import uuid

from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.forms import AccountCreationForm
from apps.accounts.models import User


class UserTests(TestCase):
    def test_create_user_normalizes_email_and_hashes_password(self) -> None:
        user = User.objects.create_user(
            email="  Buyer@Example.COM  ", password="a-long-test-password-42"
        )
        self.assertIsInstance(user.pk, uuid.UUID)
        self.assertEqual(user.email, "buyer@example.com")
        self.assertTrue(user.check_password("a-long-test-password-42"))
        self.assertNotEqual(user.password, "a-long-test-password-42")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_authentication_accepts_case_variants(self) -> None:
        user = User.objects.create_user(
            email="buyer@example.com", password="a-long-test-password-42"
        )
        self.assertEqual(
            authenticate(email="BUYER@example.com", password="a-long-test-password-42"),
            user,
        )

    def test_inactive_user_cannot_authenticate(self) -> None:
        User.objects.create_user(
            email="buyer@example.com",
            password="a-long-test-password-42",
            is_active=False,
        )
        self.assertIsNone(
            authenticate(email="buyer@example.com", password="a-long-test-password-42")
        )

    def test_invalid_emails_are_rejected(self) -> None:
        for email in ("", "  ", "missing-at-sign"):
            with self.subTest(email=email), self.assertRaises(ValueError):
                User.objects.create_user(email=email)

    def test_user_without_password_has_an_unusable_password(self) -> None:
        user = User.objects.create_user(email="buyer@example.com")
        self.assertFalse(user.has_usable_password())

    def test_superuser_requires_explicit_operator_permissions(self) -> None:
        for flags in ({"is_staff": False}, {"is_superuser": False}):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                User.objects.create_superuser(
                    email="operator@example.com",
                    password="operator-test-password-42",
                    **flags,
                )

    def test_superuser_requires_password(self) -> None:
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email="operator@example.com")

    def test_create_superuser_sets_operator_permissions(self) -> None:
        user = User.objects.create_superuser(
            email="operator@example.com", password="operator-test-password-42"
        )
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_database_rejects_case_variant_even_if_save_is_bypassed(self) -> None:
        User.objects.create_user(email="buyer@example.com")
        # bulk_create bypasses model.save(): the database must still enforce identity.
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email="BUYER@EXAMPLE.COM")])

    def test_admin_creation_form_works_without_username(self) -> None:
        form = AccountCreationForm(
            data={
                "email": "Buyer@example.com",
                "password1": "a-long-test-password-42",
                "password2": "a-long-test-password-42",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().email, "buyer@example.com")

    def test_invalid_admin_email_is_a_validation_error(self) -> None:
        form = AccountCreationForm(data={"email": "invalid"})
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_model_validation_rejects_invalid_email(self) -> None:
        with self.assertRaises(ValidationError):
            User(email="invalid").full_clean()
