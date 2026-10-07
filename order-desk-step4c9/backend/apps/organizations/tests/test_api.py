"""Exercise real Django sessions, not a bypass of DRF authentication."""

import uuid

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.organizations.models import Membership, MembershipRole, Organization


class WorkspaceDiscoveryTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.alpha = Organization.objects.create(name="Alpha Distribution")
        cls.beta = Organization.objects.create(name="Beta Industrial")
        cls.other = Organization.objects.create(name="Other Distributor")
        cls.inactive = Organization.objects.create(name="Inactive", is_active=False)
        cls.user = User.objects.create_user(email="member@example.test")
        cls.outsider = User.objects.create_user(email="outsider@example.test")
        cls.operator = User.objects.create_superuser(
            email="operator@example.test", password="operator-test-password-42"
        )
        Membership.objects.create(
            organization=cls.alpha, user=cls.user, role=MembershipRole.VIEWER
        )
        Membership.objects.create(
            organization=cls.beta, user=cls.user, role=MembershipRole.REVIEWER
        )
        Membership.objects.create(
            organization=cls.other,
            user=cls.user,
            role=MembershipRole.ADMIN,
            is_active=False,
        )
        Membership.objects.create(
            organization=cls.inactive, user=cls.user, role=MembershipRole.ADMIN
        )
        Membership.objects.create(
            organization=cls.other, user=cls.outsider, role=MembershipRole.ADMIN
        )

    def setUp(self) -> None:
        self.client = APIClient(enforce_csrf_checks=True)
        self.url = reverse("workspaces:list")

    def expected_workspaces(self) -> list[dict[str, str]]:
        return [
            {"id": str(self.alpha.pk), "name": self.alpha.name},
            {"id": str(self.beta.pk), "name": self.beta.name},
        ]

    def test_anonymous_request_is_denied_as_json(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(), {"detail": "Authentication credentials were not provided."}
        )
        self.assertTrue(response["Content-Type"].startswith("application/json"))

    def test_real_session_lists_only_accessible_workspaces(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "count": 2,
                "next": None,
                "previous": None,
                "results": self.expected_workspaces(),
            },
        )

    def test_only_public_workspace_fields_are_serialized(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for workspace in response.json()["results"]:
            self.assertEqual(set(workspace), {"id", "name"})
        self.assertNotContains(response, self.other.name)
        self.assertNotContains(response, self.user.email)
        self.assertNotContains(response, self.outsider.email)

    def test_viewers_reviewers_and_admins_can_discover_their_workspaces(self) -> None:
        self.client.force_login(self.user)
        for role in MembershipRole.values:
            with self.subTest(role=role):
                Membership.objects.filter(
                    user=self.user, organization=self.alpha
                ).update(role=role)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["results"], self.expected_workspaces())

    def test_user_without_memberships_gets_empty_page(self) -> None:
        user = User.objects.create_user(email="no-workspaces@example.test")
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"count": 0, "next": None, "previous": None, "results": []},
        )

    def test_operator_flags_do_not_grant_workspace_access(self) -> None:
        self.client.force_login(self.operator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)
        self.assertEqual(response.json()["results"], [])

    def test_membership_revocation_is_respected_by_the_next_request(self) -> None:
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).json()["count"], 2)
        Membership.objects.filter(user=self.user, organization=self.alpha).update(
            is_active=False
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            response.json()["results"],
            [{"id": str(self.beta.pk), "name": self.beta.name}],
        )

    def test_workspace_deactivation_is_respected_by_the_next_request(self) -> None:
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).json()["count"], 2)
        Organization.objects.filter(pk=self.beta.pk).update(is_active=False)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            response.json()["results"],
            [{"id": str(self.alpha.pk), "name": self.alpha.name}],
        )

    def test_account_deactivation_invalidates_session_access(self) -> None:
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_query_parameters_cannot_choose_another_user_or_workspace(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(
            self.url,
            {
                "user_id": str(self.outsider.pk),
                "organization_id": str(self.other.pk),
                "workspace_id": str(uuid.uuid4()),
                "is_superuser": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], self.expected_workspaces())

    def test_fabricated_identity_headers_do_not_authenticate(self) -> None:
        response = self.client.get(
            self.url,
            HTTP_X_USER_ID=str(self.user.pk),
            HTTP_AUTHORIZATION=f"Bearer {self.user.pk}",
        )
        self.assertEqual(response.status_code, 403)

    def test_logged_out_session_is_denied(self) -> None:
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_authenticated_get_does_not_require_a_csrf_token(self) -> None:
        self.client.force_login(self.user)
        self.assertNotIn("csrftoken", self.client.cookies)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_unsafe_methods_do_not_create_update_or_delete_workspaces(self) -> None:
        # This client isolates method restrictions from the separate CSRF check.
        client = APIClient()
        client.force_login(self.user)
        before = Organization.objects.count()
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(client, method)(
                    self.url, {"name": "Unwanted workspace"}, format="json"
                )
                self.assertEqual(response.status_code, 405)
        self.assertEqual(Organization.objects.count(), before)

    def test_authentication_and_success_responses_are_not_cacheable(self) -> None:
        response = self.client.get(self.url)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])

    def test_pagination_is_bounded_and_deterministic(self) -> None:
        # Existing fixtures + 51 workspaces exercise a full first page and a second.
        organizations = [Organization(name=f"Extra {i:02d}") for i in range(51)]
        Organization.objects.bulk_create(organizations)
        Membership.objects.bulk_create(
            [Membership(organization=org, user=self.user) for org in organizations]
        )
        self.client.force_login(self.user)
        first = self.client.get(self.url, {"page_size": 10000})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["count"], 53)
        self.assertEqual(len(first.json()["results"]), 50)
        self.assertIsNotNone(first.json()["next"])
        second = self.client.get(self.url, {"page": 2})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(second.json()["results"]), 3)
        self.assertIsNone(second.json()["next"])
        rows = first.json()["results"] + second.json()["results"]
        expected = [self.alpha, self.beta, *organizations]
        self.assertEqual([row["id"] for row in rows], [str(org.pk) for org in expected])

    def test_duplicate_names_are_ordered_by_stable_uuid_tiebreaker(self) -> None:
        Organization.objects.filter(pk=self.beta.pk).update(name=self.alpha.name)
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]],
            [str(pk) for pk in sorted([self.alpha.pk, self.beta.pk])],
        )

    def test_invalid_page_returns_json_without_workspace_details(self) -> None:
        self.client.force_login(self.user)
        for page in (0, "invalid", 999):
            with self.subTest(page=page):
                response = self.client.get(self.url, {"page": page})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Invalid page."})
                self.assertIn("no-store", response["Cache-Control"])
