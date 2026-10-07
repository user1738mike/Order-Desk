import uuid

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.accounts.models import User
from apps.organizations.access import require_membership, require_workspace_admin
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.selectors import (
    memberships_for_organization,
    organizations_for_user,
)


class WorkspaceAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.organization_a = Organization.objects.create(name="Distributor A")
        cls.organization_b = Organization.objects.create(name="Distributor B")
        cls.admin = User.objects.create_user(email="admin@example.test")
        cls.reviewer = User.objects.create_user(email="reviewer@example.test")
        cls.viewer = User.objects.create_user(email="viewer@example.test")
        cls.outsider = User.objects.create_user(email="outsider@example.test")
        cls.operator = User.objects.create_superuser(
            email="operator@example.test", password="operator-test-password-42"
        )
        Membership.objects.create(
            organization=cls.organization_a, user=cls.admin, role=MembershipRole.ADMIN
        )
        Membership.objects.create(
            organization=cls.organization_a,
            user=cls.reviewer,
            role=MembershipRole.REVIEWER,
        )
        Membership.objects.create(
            organization=cls.organization_a, user=cls.viewer, role=MembershipRole.VIEWER
        )
        Membership.objects.create(
            organization=cls.organization_b, user=cls.admin, role=MembershipRole.VIEWER
        )

    def test_workspace_discovery_only_lists_active_memberships(self) -> None:
        self.assertQuerySetEqual(
            organizations_for_user(user=self.viewer), [self.organization_a]
        )
        self.assertQuerySetEqual(organizations_for_user(user=self.outsider), [])

    def test_anonymous_user_is_denied(self) -> None:
        with self.assertRaises(PermissionDenied):
            organizations_for_user(user=AnonymousUser())

    def test_unsaved_user_cannot_use_a_fabricated_existing_identity(self) -> None:
        unsaved = User(id=self.admin.pk, email=self.admin.email)
        with self.assertRaises(PermissionDenied):
            organizations_for_user(user=unsaved)

    def test_guessed_workspace_id_does_not_grant_access(self) -> None:
        with self.assertRaises(PermissionDenied):
            require_membership(user=self.viewer, organization_id=self.organization_b.pk)

    def test_missing_and_unauthorized_workspaces_have_the_same_error(self) -> None:
        errors = []
        for organization_id in (self.organization_b.pk, uuid.uuid4()):
            with self.assertRaises(PermissionDenied) as error:
                require_membership(user=self.viewer, organization_id=organization_id)
            errors.append(str(error.exception))
        self.assertEqual(errors[0], errors[1])

    def test_membership_role_is_scoped_to_its_workspace(self) -> None:
        require_workspace_admin(user=self.admin, organization_id=self.organization_a.pk)
        with self.assertRaises(PermissionDenied):
            require_workspace_admin(
                user=self.admin, organization_id=self.organization_b.pk
            )

    def test_operator_privileges_do_not_bypass_membership(self) -> None:
        with self.assertRaises(PermissionDenied):
            require_membership(
                user=self.operator, organization_id=self.organization_a.pk
            )
        self.assertQuerySetEqual(organizations_for_user(user=self.operator), [])

    def test_inactive_membership_is_denied(self) -> None:
        Membership.objects.filter(user=self.viewer).update(is_active=False)
        self.assertQuerySetEqual(organizations_for_user(user=self.viewer), [])
        with self.assertRaises(PermissionDenied):
            require_membership(user=self.viewer, organization_id=self.organization_a.pk)

    def test_inactive_organization_is_denied(self) -> None:
        Organization.objects.filter(pk=self.organization_a.pk).update(is_active=False)
        self.assertQuerySetEqual(organizations_for_user(user=self.viewer), [])
        with self.assertRaises(PermissionDenied):
            require_membership(user=self.viewer, organization_id=self.organization_a.pk)

    def test_stale_user_instance_does_not_bypass_account_deactivation(self) -> None:
        User.objects.filter(pk=self.viewer.pk).update(is_active=False)
        self.assertTrue(self.viewer.is_active)
        with self.assertRaises(PermissionDenied):
            organizations_for_user(user=self.viewer)

    def test_team_listing_is_scoped_and_requires_workspace_admin(self) -> None:
        memberships = memberships_for_organization(
            user=self.admin, organization_id=self.organization_a.pk
        )
        self.assertEqual(memberships.count(), 3)
        self.assertEqual(
            set(memberships.values_list("organization_id", flat=True)),
            {self.organization_a.pk},
        )
        for user in (self.reviewer, self.viewer):
            with self.subTest(user=user.pk), self.assertRaises(PermissionDenied):
                memberships_for_organization(
                    user=user, organization_id=self.organization_a.pk
                )

    def test_lazy_workspace_query_respects_later_membership_revocation(self) -> None:
        organizations = organizations_for_user(user=self.viewer)
        Membership.objects.filter(user=self.viewer).update(is_active=False)
        self.assertEqual(list(organizations), [])

    def test_lazy_team_query_respects_later_admin_demotion(self) -> None:
        memberships = memberships_for_organization(
            user=self.admin, organization_id=self.organization_a.pk
        )
        Membership.objects.filter(
            user=self.admin, organization=self.organization_a
        ).update(role=MembershipRole.VIEWER)
        self.assertEqual(list(memberships), [])
