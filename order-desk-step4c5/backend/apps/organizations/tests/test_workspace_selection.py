"""Exercise tenant boundaries with real sessions and CSRF enforcement."""

import uuid

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.selection import SELECTED_WORKSPACE_KEY


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class WorkspaceSelectionTests(TestCase):
    password = "workspace-selection-test-password-42"  # noqa: S105 -- test only

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(
            email="member@example.test", password=cls.password
        )
        cls.outsider = User.objects.create_user(
            email="outsider@example.test", password=cls.password
        )
        cls.operator = User.objects.create_superuser(
            email="operator@example.test", password=cls.password
        )
        cls.alpha = Organization.objects.create(name="Alpha Distribution")
        cls.beta = Organization.objects.create(name="Beta Industrial")
        cls.other = Organization.objects.create(name="Private Distributor")
        cls.inactive = Organization.objects.create(name="Inactive", is_active=False)
        cls.alpha_membership = Membership.objects.create(
            user=cls.user, organization=cls.alpha, role=MembershipRole.VIEWER
        )
        Membership.objects.create(
            user=cls.user, organization=cls.beta, role=MembershipRole.REVIEWER
        )
        Membership.objects.create(
            user=cls.outsider, organization=cls.other, role=MembershipRole.ADMIN
        )
        Membership.objects.create(user=cls.user, organization=cls.inactive)

    def setUp(self) -> None:
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.current_url = reverse("workspaces:current")
        self.csrf = self.client.get(reverse("session_auth:csrf")).json()["csrf_token"]

    def context_url(self, organization_id) -> str:
        return reverse("workspaces:context", kwargs={"workspace_id": organization_id})

    def select(self, organization_id=None):
        return self.client.put(
            self.current_url,
            {"workspace_id": str(organization_id or self.alpha.pk)},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )

    def expected(self, organization, role=MembershipRole.VIEWER) -> dict:
        return {
            "workspace": {
                "id": str(organization.pk),
                "name": organization.name,
                "role": str(role),
            }
        }

    def test_anonymous_access_and_fabricated_identity_headers_are_denied(self) -> None:
        anonymous = APIClient(enforce_csrf_checks=True)
        for url in (self.current_url, self.context_url(self.alpha.pk)):
            with self.subTest(url=url):
                response = anonymous.get(
                    url,
                    HTTP_X_USER_ID=str(self.user.pk),
                    HTTP_X_WORKSPACE_ID=str(self.alpha.pk),
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.json(),
                    {"detail": "Authentication credentials were not provided."},
                )
        for method in ("put", "delete"):
            with self.subTest(method=method):
                response = getattr(anonymous, method)(
                    self.current_url,
                    {"workspace_id": str(self.alpha.pk)},
                    format="json",
                )
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(SELECTED_WORKSPACE_KEY, anonymous.session)

    def test_unselected_account_has_no_current_workspace(self) -> None:
        response = self.client.get(self.current_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"workspace": None})

    def test_selection_persists_only_the_workspace_uuid(self) -> None:
        response = self.select()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.expected(self.alpha))
        session = self.client.session
        self.assertEqual(session[SELECTED_WORKSPACE_KEY], str(self.alpha.pk))
        self.assertEqual(
            {key for key in session.keys() if not key.startswith("_")},
            {SELECTED_WORKSPACE_KEY},
        )
        self.assertEqual(
            self.client.get(self.current_url).json(), self.expected(self.alpha)
        )

    def test_same_choice_is_idempotent_and_all_membership_roles_can_select(
        self,
    ) -> None:
        for role in MembershipRole.values:
            Membership.objects.filter(pk=self.alpha_membership.pk).update(role=role)
            for _ in range(2):
                with self.subTest(role=role):
                    response = self.select()
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), self.expected(self.alpha, role))
        self.assertEqual(Membership.objects.count(), 4)

    def test_unknown_unavailable_and_foreign_workspaces_share_the_same_denial(
        self,
    ) -> None:
        inactive_membership = Organization.objects.create(name="Revoked member")
        Membership.objects.create(
            user=self.user, organization=inactive_membership, is_active=False
        )
        for organization_id in (
            uuid.uuid4(),
            self.other.pk,
            self.inactive.pk,
            inactive_membership.pk,
        ):
            with self.subTest(organization_id=organization_id):
                for response in (
                    self.select(organization_id),
                    self.client.get(self.context_url(organization_id)),
                ):
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(
                        response.json(), {"detail": WORKSPACE_ACCESS_DENIED}
                    )
                    self.assertNotContains(response, self.other.name, status_code=403)

    def test_denied_selection_preserves_the_previous_choice(self) -> None:
        self.select()
        self.assertEqual(self.select(self.other.pk).status_code, 403)
        self.assertEqual(
            self.client.get(self.current_url).json(), self.expected(self.alpha)
        )

    def test_operator_flags_do_not_bypass_membership(self) -> None:
        self.client.force_login(self.operator)
        for response in (
            self.select(),
            self.client.get(self.context_url(self.alpha.pk)),
        ):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})

    def test_selection_validation_rejects_invalid_types_and_fabricated_roles(
        self,
    ) -> None:
        self.select()
        invalid_payloads = [
            {},
            [],
            {"workspace_id": None},
            {"workspace_id": 1},
            {"workspace_id": True},
            {"workspace_id": "invalid"},
            {"workspace_id": str(self.alpha.pk), "role": "admin"},
            {"workspace_id": str(self.alpha.pk), "user_id": str(self.outsider.pk)},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.put(
                    self.current_url,
                    payload,
                    format="json",
                    HTTP_X_CSRFTOKEN=self.csrf,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    self.client.session[SELECTED_WORKSPACE_KEY], str(self.alpha.pk)
                )
        self.alpha_membership.refresh_from_db()
        self.assertEqual(self.alpha_membership.role, MembershipRole.VIEWER)

    def test_malformed_json_and_non_json_selection_do_not_change_preference(
        self,
    ) -> None:
        self.select()
        for body, content_type, status in (
            ("{", "application/json", 400),
            (f"workspace_id={self.beta.pk}", "application/x-www-form-urlencoded", 415),
        ):
            with self.subTest(content_type=content_type):
                response = self.client.put(
                    self.current_url,
                    body,
                    content_type=content_type,
                    HTTP_X_CSRFTOKEN=self.csrf,
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(
                    self.client.session[SELECTED_WORKSPACE_KEY], str(self.alpha.pk)
                )

    def test_missing_csrf_blocks_selection_and_clearing(self) -> None:
        self.select()
        for method in ("put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.current_url, {"workspace_id": str(self.beta.pk)}, format="json"
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    self.client.get(self.current_url).json(), self.expected(self.alpha)
                )

    def test_untrusted_origin_blocks_selection_and_clearing(self) -> None:
        self.select()
        for method in ("put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.current_url,
                    {"workspace_id": str(self.beta.pk)},
                    format="json",
                    HTTP_X_CSRFTOKEN=self.csrf,
                    HTTP_ORIGIN="https://untrusted.example.test",
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    self.client.session[SELECTED_WORKSPACE_KEY], str(self.alpha.pk)
                )

    def test_role_and_name_changes_are_seen_on_the_next_request(self) -> None:
        self.select()
        Membership.objects.filter(pk=self.alpha_membership.pk).update(
            role=MembershipRole.ADMIN
        )
        Organization.objects.filter(pk=self.alpha.pk).update(name="Renamed Distributor")
        self.alpha.refresh_from_db()
        expected = self.expected(self.alpha, MembershipRole.ADMIN)
        self.assertEqual(self.client.get(self.current_url).json(), expected)
        self.assertEqual(
            self.client.get(self.context_url(self.alpha.pk)).json(), expected
        )

    def test_membership_revocation_removes_current_context_and_denies_explicit_access(
        self,
    ) -> None:
        self.select()
        Membership.objects.filter(pk=self.alpha_membership.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.current_url).json(), {"workspace": None})
        self.assertEqual(
            self.client.get(self.context_url(self.alpha.pk)).status_code, 403
        )
        self.assertEqual(self.select().status_code, 403)
        self.assertEqual(self.select(self.beta.pk).status_code, 200)

    def test_membership_deletion_is_respected_by_the_next_request(self) -> None:
        self.select()
        Membership.objects.filter(pk=self.alpha_membership.pk).delete()
        self.assertEqual(self.client.get(self.current_url).json(), {"workspace": None})
        self.assertEqual(
            self.client.get(self.context_url(self.alpha.pk)).status_code, 403
        )

    def test_workspace_deactivation_is_respected_by_the_next_request(self) -> None:
        self.select()
        Organization.objects.filter(pk=self.alpha.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.current_url).json(), {"workspace": None})
        self.assertEqual(
            self.client.get(self.context_url(self.alpha.pk)).status_code, 403
        )

    def test_account_deactivation_denies_selection_current_and_context(self) -> None:
        self.select()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        for response in (
            self.client.get(self.current_url),
            self.client.get(self.context_url(self.alpha.pk)),
            self.select(),
        ):
            self.assertEqual(response.status_code, 403)

    def test_malformed_or_stale_session_preferences_are_unselected_and_get_is_read_only(
        self,
    ) -> None:
        for value in (
            None,
            True,
            1,
            {},
            [],
            "invalid",
            str(uuid.uuid4()),
            str(self.other.pk),
        ):
            with self.subTest(value=value):
                session = self.client.session
                session[SELECTED_WORKSPACE_KEY] = value
                session.save()
                response = self.client.get(self.current_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"workspace": None})
                self.assertEqual(self.client.session[SELECTED_WORKSPACE_KEY], value)

    def test_explicit_context_works_without_any_selection(self) -> None:
        response = self.client.get(self.context_url(self.alpha.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.expected(self.alpha))
        self.assertEqual(self.client.get(self.current_url).json(), {"workspace": None})

    def test_shared_session_change_in_another_tab_does_not_redirect_explicit_context(
        self,
    ) -> None:
        self.select()
        second_tab = APIClient(enforce_csrf_checks=True)
        second_tab.cookies = self.client.cookies.copy()
        response = second_tab.put(
            self.current_url,
            {"workspace_id": str(self.beta.pk)},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.get(self.current_url).json(),
            self.expected(self.beta, MembershipRole.REVIEWER),
        )
        self.assertEqual(
            self.client.get(self.context_url(self.alpha.pk)).json(),
            self.expected(self.alpha),
        )
        self.assertEqual(
            self.client.get(self.context_url(self.beta.pk)).json(),
            self.expected(self.beta, MembershipRole.REVIEWER),
        )

    def test_headers_and_query_parameters_cannot_override_url_scope(self) -> None:
        response = self.client.get(
            self.context_url(self.alpha.pk),
            {"workspace_id": str(self.other.pk), "user_id": str(self.outsider.pk)},
            HTTP_X_WORKSPACE_ID=str(self.other.pk),
            HTTP_X_ORGANIZATION_ID=str(self.other.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.expected(self.alpha))

    def test_clearing_is_idempotent_keeps_login_and_does_not_affect_explicit_context(
        self,
    ) -> None:
        self.select()
        for _ in range(2):
            response = self.client.delete(self.current_url, HTTP_X_CSRFTOKEN=self.csrf)
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get(self.current_url).json(), {"workspace": None})
        self.assertEqual(
            self.client.get(self.context_url(self.alpha.pk)).json(),
            self.expected(self.alpha),
        )

    def test_selection_does_not_extend_the_absolute_session_expiry(self) -> None:
        # Use real sign-in so the eight-hour absolute expiry is set by the API.
        response = self.client.post(
            reverse("session_auth:login"),
            {"email": self.user.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json()["csrf_token"]
        expiry = self.client.session.get_expiry_date()
        self.assertEqual(self.select().status_code, 200)
        self.assertEqual(self.client.session.get_expiry_date(), expiry)

    def test_real_relogin_as_another_user_clears_workspace_selection(self) -> None:
        self.select()
        response = self.client.post(
            reverse("session_auth:login"),
            {"email": self.outsider.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SELECTED_WORKSPACE_KEY, self.client.session)
        self.assertEqual(self.client.get(self.current_url).json(), {"workspace": None})
        self.assertEqual(
            self.client.get(self.context_url(self.alpha.pk)).status_code, 403
        )

    def test_real_logout_invalidates_context_and_replayed_session(self) -> None:
        self.select()
        old_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        response = self.client.post(
            reverse("session_auth:logout"),
            {},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 204)
        self.assertNotIn(SELECTED_WORKSPACE_KEY, self.client.session)
        replay = APIClient(enforce_csrf_checks=True)
        replay.cookies[settings.SESSION_COOKIE_NAME] = old_key
        for client in (self.client, replay):
            self.assertEqual(client.get(self.current_url).status_code, 403)
            self.assertEqual(
                client.get(self.context_url(self.alpha.pk)).status_code, 403
            )

    def test_context_is_read_only_and_current_rejects_unsupported_methods(self) -> None:
        for method in ("post", "patch"):
            response = getattr(self.client, method)(
                self.current_url, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
            )
            self.assertEqual(response.status_code, 405)
        for method in ("post", "put", "patch", "delete"):
            response = getattr(self.client, method)(
                self.context_url(self.alpha.pk),
                {},
                format="json",
                HTTP_X_CSRFTOKEN=self.csrf,
            )
            self.assertEqual(response.status_code, 405)
        self.assertNotIn(SELECTED_WORKSPACE_KEY, self.client.session)

    def test_success_and_denial_responses_are_private_and_not_cacheable(self) -> None:
        responses = [
            self.client.get(self.current_url),
            self.select(),
            self.select(self.other.pk),
            self.client.get(self.context_url(self.alpha.pk)),
            self.client.get(self.context_url(self.other.pk)),
            self.client.delete(self.current_url, HTTP_X_CSRFTOKEN=self.csrf),
            APIClient().get(self.current_url),
        ]
        for response in responses:
            with self.subTest(status=response.status_code):
                self.assertIn("no-store", response["Cache-Control"])
                self.assertIn("private", response["Cache-Control"])
