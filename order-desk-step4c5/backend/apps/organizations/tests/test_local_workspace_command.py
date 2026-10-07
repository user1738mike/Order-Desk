"""The fixture helper uses the existing transaction and refuses production."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.organizations.models import Membership, MembershipRole, Organization


@override_settings(DEBUG=True)
class LocalWorkspaceCommandTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(email="local@example.test")

    def create_workspace(self, *, email="local@example.test", name="Local Distributor"):
        with patch("builtins.input", side_effect=[email, name]):
            call_command("create_local_workspace", stdout=StringIO())

    def test_creates_workspace_and_admin_membership_without_operator_flags(
        self,
    ) -> None:
        self.create_workspace(email=" Local@Example.Test ", name="  Test Distributor  ")
        organization = Organization.objects.get()
        self.assertEqual(organization.name, "Test Distributor")
        membership = Membership.objects.get(organization=organization, user=self.user)
        self.assertEqual(membership.role, MembershipRole.ADMIN)
        self.assertTrue(membership.is_active)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    def test_missing_inactive_and_invalid_accounts_do_not_create_workspaces(
        self,
    ) -> None:
        User.objects.create_user(email="inactive@example.test", is_active=False)
        for email in ("missing@example.test", "inactive@example.test", "invalid"):
            with self.subTest(email=email), self.assertRaises(CommandError):
                self.create_workspace(email=email)
        self.assertEqual(Organization.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)

    def test_invalid_names_do_not_leave_partial_workspaces(self) -> None:
        for name in (" ", "x" * 201):
            with self.subTest(name=name), self.assertRaises(CommandError):
                self.create_workspace(name=name)
        self.assertEqual(Organization.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)

    @override_settings(DEBUG=False)
    def test_non_development_settings_reject_before_prompting(self) -> None:
        with patch("builtins.input") as prompt, self.assertRaises(CommandError):
            call_command("create_local_workspace")
        prompt.assert_not_called()

    def test_cancelled_input_does_not_create_a_workspace(self) -> None:
        with (
            patch("builtins.input", side_effect=EOFError),
            self.assertRaises(CommandError),
        ):
            call_command("create_local_workspace")
        self.assertEqual(Organization.objects.count(), 0)
