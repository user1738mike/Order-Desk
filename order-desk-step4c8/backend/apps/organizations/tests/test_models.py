import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.accounts.models import User
from apps.organizations.models import Membership, MembershipRole, Organization


class OrganizationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.organization = Organization.objects.create(name="Distributor A")
        cls.user = User.objects.create_user(email="member@example.test")

    def test_organization_has_uuid_and_aware_creation_timestamp(self) -> None:
        self.assertIsInstance(self.organization.pk, uuid.UUID)
        self.assertIsNotNone(self.organization.created_at.tzinfo)

    def test_display_name_does_not_identify_a_tenant(self) -> None:
        other = Organization.objects.create(name=self.organization.name)
        self.assertNotEqual(other.pk, self.organization.pk)

    def test_blank_names_are_rejected_even_without_model_validation(self) -> None:
        for name in ("", "   ", "\t\n"):
            with self.subTest(name=name), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Organization.objects.create(name=name)

    def test_duplicate_membership_is_rejected_by_database(self) -> None:
        Membership.objects.create(organization=self.organization, user=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(organization=self.organization, user=self.user)

    def test_inactive_membership_still_occupies_the_unique_pair(self) -> None:
        Membership.objects.create(
            organization=self.organization, user=self.user, is_active=False
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(organization=self.organization, user=self.user)

    def test_invalid_role_is_rejected_by_database(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(
                organization=self.organization, user=self.user, role="superuser"
            )

    def test_membership_requires_an_organization(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.create(user=self.user, organization_id=None)

    def test_one_user_can_have_different_roles_in_different_workspaces(self) -> None:
        other = Organization.objects.create(name="Distributor B")
        first = Membership.objects.create(
            organization=self.organization, user=self.user, role=MembershipRole.ADMIN
        )
        second = Membership.objects.create(
            organization=other, user=self.user, role=MembershipRole.VIEWER
        )
        self.assertNotEqual(first.role, second.role)

    def test_member_defaults_to_least_privileged_role(self) -> None:
        membership = Membership.objects.create(
            organization=self.organization, user=self.user
        )
        self.assertEqual(membership.role, MembershipRole.VIEWER)

    def test_invalid_role_is_also_a_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            Membership(
                organization=self.organization, user=self.user, role="invalid"
            ).full_clean()

    def test_user_and_organization_deletion_are_protected(self) -> None:
        Membership.objects.create(organization=self.organization, user=self.user)
        with self.assertRaises(ProtectedError):
            self.user.delete()
        with self.assertRaises(ProtectedError):
            self.organization.delete()
