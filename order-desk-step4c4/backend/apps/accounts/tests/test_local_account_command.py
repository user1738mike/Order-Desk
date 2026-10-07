from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.accounts.models import User


@override_settings(DEBUG=True)
class LocalAccountCommandTests(TestCase):
    def create_account(
        self, passwords: list[str], email: str = "local@example.test"
    ) -> None:
        with (
            patch("builtins.input", return_value=email),
            patch(
                "apps.accounts.management.commands.create_local_account.getpass",
                side_effect=passwords,
            ),
        ):
            call_command("create_local_account", verbosity=0)

    def test_creation_validates_password_and_keeps_operator_flags_off(self) -> None:
        password = "a-long-local-test-password-42"  # noqa: S105 -- test fixture only
        self.create_account([password, password], " Local@Example.Test ")
        user = User.objects.get(email="local@example.test")
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_weak_password_is_rejected(self) -> None:
        with self.assertRaises(CommandError):
            self.create_account(["123", "123"])
        self.assertEqual(User.objects.count(), 0)

    def test_password_confirmation_is_required(self) -> None:
        with self.assertRaisesMessage(CommandError, "Passwords did not match"):
            self.create_account(["first-password", "different-password"])
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_email_and_duplicate_account_are_rejected(self) -> None:
        with self.assertRaises(CommandError):
            self.create_account([], "invalid")
        User.objects.create_user(email="local@example.test")
        password = "a-long-local-test-password-42"  # noqa: S105 -- test fixture only
        with self.assertRaises(CommandError):
            self.create_account([password, password])
        self.assertEqual(User.objects.count(), 1)

    @override_settings(DEBUG=False)
    def test_non_development_settings_reject_the_command_before_prompting(self) -> None:
        with patch("builtins.input") as prompt, self.assertRaises(CommandError):
            call_command("create_local_account")
        prompt.assert_not_called()

    def test_cancelled_input_does_not_create_a_user(self) -> None:
        with (
            patch("builtins.input", side_effect=EOFError),
            self.assertRaisesMessage(CommandError, "cancelled"),
        ):
            call_command("create_local_account")
        self.assertEqual(User.objects.count(), 0)
