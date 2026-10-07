import uuid
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.services import add_member, create_organization


class WorkspaceServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = User.objects.create_user(email="admin@example.test")
        cls.other_admin = User.objects.create_user(email="other-admin@example.test")
        cls.target = User.objects.create_user(email="new-member@example.test")
        cls.reviewer = User.objects.create_user(email="reviewer@example.test")
        cls.organization = create_organization(actor=cls.admin, name="Distributor A")
        cls.other_organization = create_organization(
            actor=cls.other_admin, name="Distributor B"
        )
        add_member(
            actor=cls.admin,
            organization_id=cls.organization.pk,
            user_id=cls.reviewer.pk,
            role=MembershipRole.REVIEWER,
        )

    def test_creation_makes_an_admin_without_operator_privileges(self) -> None:
        organization = create_organization(actor=self.target, name="  New Company  ")
        membership = Membership.objects.get(organization=organization, user=self.target)
        self.assertEqual(organization.name, "New Company")
        self.assertEqual(membership.role, MembershipRole.ADMIN)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)

    def test_creation_rolls_back_if_initial_membership_fails(self) -> None:
        initial_count = Organization.objects.count()
        with patch(
            "apps.organizations.services.Membership.save",
            side_effect=ValidationError("membership could not be saved"),
        ):
            with self.assertRaises(ValidationError):
                create_organization(actor=self.target, name="Must Roll Back")
        self.assertEqual(Organization.objects.count(), initial_count)

    def test_blank_and_overlong_names_are_rejected(self) -> None:
        initial_count = Organization.objects.count()
        for name in ("  ", "a" * 201):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                create_organization(actor=self.target, name=name)
        self.assertEqual(Organization.objects.count(), initial_count)

    def test_anonymous_and_disabled_actors_cannot_create_workspaces(self) -> None:
        with self.assertRaises(PermissionDenied):
            create_organization(actor=AnonymousUser(), name="Anonymous Workspace")
        User.objects.filter(pk=self.target.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            create_organization(actor=self.target, name="Disabled Workspace")

    def test_admin_adds_existing_user_to_the_authorized_workspace(self) -> None:
        membership = add_member(
            actor=self.admin,
            organization_id=self.organization.pk,
            user_id=self.target.pk,
        )
        self.assertEqual(membership.organization_id, self.organization.pk)
        self.assertEqual(membership.user_id, self.target.pk)
        self.assertEqual(membership.role, MembershipRole.VIEWER)

    def test_membership_admin_can_grant_another_workspace_admin(self) -> None:
        membership = add_member(
            actor=self.admin,
            organization_id=self.organization.pk,
            user_id=self.target.pk,
            role=MembershipRole.ADMIN,
        )
        self.assertEqual(membership.role, MembershipRole.ADMIN)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)

    def test_reviewer_cannot_add_a_member(self) -> None:
        with self.assertRaises(PermissionDenied):
            add_member(
                actor=self.reviewer,
                organization_id=self.organization.pk,
                user_id=self.target.pk,
            )
        self.assertFalse(Membership.objects.filter(user=self.target).exists())

    def test_admin_of_another_workspace_cannot_add_a_member(self) -> None:
        with self.assertRaises(PermissionDenied):
            add_member(
                actor=self.admin,
                organization_id=self.other_organization.pk,
                user_id=self.target.pk,
            )
        self.assertFalse(Membership.objects.filter(user=self.target).exists())

    def test_inactive_organization_cannot_receive_new_members(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            add_member(
                actor=self.admin,
                organization_id=self.organization.pk,
                user_id=self.target.pk,
            )

    def test_revoked_admin_cannot_add_a_member(self) -> None:
        Membership.objects.filter(user=self.admin).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            add_member(
                actor=self.admin,
                organization_id=self.organization.pk,
                user_id=self.target.pk,
            )

    def test_unknown_and_disabled_targets_have_the_same_validation_error(self) -> None:
        User.objects.filter(pk=self.target.pk).update(is_active=False)
        errors = []
        for user_id in (self.target.pk, uuid.uuid4()):
            with self.assertRaises(ValidationError) as error:
                add_member(
                    actor=self.admin,
                    organization_id=self.organization.pk,
                    user_id=user_id,
                )
            errors.append(error.exception.message_dict)
        self.assertEqual(errors[0], errors[1])

    def test_duplicate_membership_is_rejected_without_creating_another_row(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            add_member(
                actor=self.admin,
                organization_id=self.organization.pk,
                user_id=self.reviewer.pk,
            )
        self.assertEqual(
            Membership.objects.filter(
                organization=self.organization, user=self.reviewer
            ).count(),
            1,
        )

    def test_invalid_role_cannot_be_saved_by_service(self) -> None:
        with self.assertRaises(ValidationError):
            add_member(
                actor=self.admin,
                organization_id=self.organization.pk,
                user_id=self.target.pk,
                role="superuser",
            )
        self.assertFalse(Membership.objects.filter(user=self.target).exists())
