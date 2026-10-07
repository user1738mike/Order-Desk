"""Native PostgreSQL catalogue reads through real browser sessions and CSRF."""

import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.models import Membership, MembershipRole, Organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CatalogReadAPITests(TransactionTestCase):
    password = "catalog-read-synthetic-password-42"  # noqa: S105 -- test only

    def setUp(self) -> None:
        self.admin = User.objects.create_user(
            email="catalog-admin@example.test", password=self.password
        )
        self.viewer = User.objects.create_user(
            email="catalog-viewer@example.test", password=self.password
        )
        self.reviewer = User.objects.create_user(
            email="catalog-reviewer@example.test", password=self.password
        )
        self.outsider = User.objects.create_superuser(
            email="catalog-operator@example.test", password=self.password
        )
        self.a = Organization.objects.create(name="Synthetic catalogue A")
        self.b = Organization.objects.create(name="Synthetic catalogue B")
        self.admin_membership = Membership.objects.create(
            user=self.admin, organization=self.a, role=MembershipRole.ADMIN
        )
        Membership.objects.create(
            user=self.admin, organization=self.b, role=MembershipRole.ADMIN
        )
        for user, role in (
            (self.viewer, MembershipRole.VIEWER),
            (self.reviewer, MembershipRole.REVIEWER),
        ):
            Membership.objects.create(user=user, organization=self.a, role=role)
        self.item_a = CatalogItem.objects.create(
            organization=self.a, sku="PART-001", description="Fixture A"
        )
        self.archived_a = CatalogItem.objects.create(
            organization=self.a, sku="ARCH-001", is_active=False
        )
        self.item_b = CatalogItem.objects.create(
            organization=self.b, sku="PART-001", description="Private fixture B"
        )
        self.url = self.items_url(self.a)
        self.client, self.csrf = self.login_client(self.admin)

    @staticmethod
    def items_url(workspace: Organization) -> str:
        return reverse(
            "workspaces:catalog:items", kwargs={"workspace_id": workspace.pk}
        )

    def login_client(self, user: User) -> tuple[APIClient, str]:
        client = APIClient(enforce_csrf_checks=True)
        csrf = client.get(reverse("session_auth:csrf")).json()["csrf_token"]
        response = client.post(
            reverse("session_auth:login"),
            {"email": user.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return client, response.json()["csrf_token"]

    def assert_clean(self) -> None:
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                " NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def test_anonymous_get_and_head_preserve_session_authentication_denial(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.get(
            self.url,
            HTTP_X_USER_ID=str(self.admin.pk),
            HTTP_X_WORKSPACE_ID=str(self.a.pk),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(), {"detail": "Authentication credentials were not provided."}
        )
        self.assertEqual(client.head(self.url).status_code, 403)

    def test_active_admin_reviewer_and_viewer_members_can_read(self):
        for user in (self.admin, self.reviewer, self.viewer):
            client, _ = self.login_client(user)
            with self.subTest(user=user.pk):
                response = client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["count"], 2)
                self.assertEqual(
                    {row["organization_id"] for row in response.json()["results"]},
                    {str(self.a.pk)},
                )
                self.assert_clean()

    def test_authenticated_safe_get_requires_no_csrf_cookie_or_token(self):
        self.client.cookies.pop(settings.CSRF_COOKIE_NAME, None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)

    def test_expired_session_is_denied_with_existing_session_error_contract(self):
        session = self.client.session
        session.set_expiry(timezone.now() - timedelta(seconds=1))
        session.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(), {"detail": "Authentication credentials were not provided."}
        )

    def test_logout_invalidates_catalogue_access_and_replayed_session(self):
        old_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        response = self.client.post(
            reverse("session_auth:logout"),
            {},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 204)
        replay = APIClient(enforce_csrf_checks=True)
        replay.cookies[settings.SESSION_COOKIE_NAME] = old_key
        for client in (self.client, replay):
            response = client.get(self.url)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.json(),
                {"detail": "Authentication credentials were not provided."},
            )

    def test_account_deactivation_denies_an_existing_authenticated_session(self):
        User.objects.filter(pk=self.admin.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assert_clean()

    def test_membership_revocation_returns_generic_workspace_denial(self):
        Membership.objects.filter(pk=self.admin_membership.pk).update(is_active=False)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        self.assert_clean()

    def test_workspace_deactivation_returns_generic_workspace_denial(self):
        Organization.objects.filter(pk=self.a.pk).update(is_active=False)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        self.assert_clean()

    def test_missing_and_unauthorized_workspaces_have_identical_responses(self):
        client, _ = self.login_client(self.viewer)
        missing = reverse("workspaces:catalog:items", kwargs={"workspace_id": uuid4()})
        for url in (missing, self.items_url(self.b)):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
                self.assertNotContains(
                    response, self.item_b.description, status_code=403
                )
        malformed = "/api/v1/workspaces/not-a-uuid/catalog/items/"
        self.assertEqual(client.get(malformed).status_code, 404)

    def test_operator_flags_do_not_bypass_workspace_membership(self):
        client, _ = self.login_client(self.outsider)
        response = client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})

    def test_member_of_two_workspaces_sees_only_each_requested_catalogue(self):
        for workspace, expected_ids in (
            (self.a, {self.item_a.pk, self.archived_a.pk}),
            (self.b, {self.item_b.pk}),
            (self.a, {self.item_a.pk, self.archived_a.pk}),
        ):
            with self.subTest(workspace=workspace.pk):
                response = self.client.get(self.items_url(workspace))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["count"], len(expected_ids))
                self.assertEqual(
                    {row["id"] for row in response.json()["results"]},
                    {str(pk) for pk in expected_ids},
                )
                self.assertEqual(
                    {row["organization_id"] for row in response.json()["results"]},
                    {str(workspace.pk)},
                )
                self.assert_clean()

    def test_url_scope_overrides_a_different_selected_session_workspace(self):
        response = self.client.put(
            reverse("workspaces:current"),
            {"workspace_id": str(self.b.pk)},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertNotContains(response, self.item_b.description)

    def test_forged_identity_headers_and_get_body_cannot_override_url_or_actor(self):
        self.client.cookies["organization_id"] = str(self.b.pk)
        self.client.cookies["user_id"] = str(self.outsider.pk)
        response = self.client.generic(
            "GET",
            self.url,
            data=json.dumps(
                {"organization_id": str(self.b.pk), "user_id": str(self.outsider.pk)}
            ),
            content_type="application/json",
            HTTP_X_WORKSPACE_ID=str(self.b.pk),
            HTTP_X_ORGANIZATION_ID=str(self.b.pk),
            HTTP_X_USER_ID=str(self.outsider.pk),
            HTTP_AUTHORIZATION=f"Bearer {self.outsider.pk}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertNotContains(response, self.item_b.description)

    def test_empty_catalogue_has_one_empty_first_page(self):
        workspace = Organization.objects.create(name="Empty catalogue")
        Membership.objects.create(
            user=self.admin, organization=workspace, role=MembershipRole.ADMIN
        )
        response = self.client.get(self.items_url(workspace))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )
        response = self.client.get(self.items_url(workspace), {"page": 2})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Invalid page."})

    def test_inactive_items_are_visible_and_stock_code_case_and_punctuation_survive(
        self,
    ):
        item = CatalogItem.objects.create(organization=self.a, sku="000Ab/P-1.x")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        rows = {row["id"]: row for row in response.json()["results"]}
        self.assertFalse(rows[str(self.archived_a.pk)]["is_active"])
        self.assertEqual(rows[str(item.pk)]["sku"], "000Ab/P-1.x")
        self.assertEqual(
            set(rows[str(item.pk)]),
            {
                "id",
                "organization_id",
                "sku",
                "description",
                "is_active",
                "created_at",
                "updated_at",
            },
        )
        self.assertNotContains(response, self.admin.email)

    def test_fixed_fifty_item_page_boundary_uses_database_sku_then_id_order(self):
        CatalogItem.objects.bulk_create(
            [CatalogItem(organization=self.a, sku=f"EXTRA-{i:03d}") for i in range(49)]
        )
        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["count"], 51)
        self.assertEqual(len(first.json()["results"]), 50)
        self.assertEqual(len(second.json()["results"]), 1)
        rows = first.json()["results"] + second.json()["results"]
        expected = list(
            CatalogItem.objects.filter(organization=self.a)
            .order_by("sku", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual([row["id"] for row in rows], [str(pk) for pk in expected])

    def test_pagination_links_preserve_workspace_route_and_only_page_parameter(self):
        CatalogItem.objects.bulk_create(
            [CatalogItem(organization=self.a, sku=f"EXTRA-{i:03d}") for i in range(49)]
        )
        first = self.client.get(self.url).json()
        self.assertIsNone(first["previous"])
        next_link = urlsplit(first["next"])
        self.assertEqual(next_link.path, self.url)
        self.assertEqual(parse_qs(next_link.query), {"page": ["2"]})
        second = self.client.get(self.url, {"page": 2}).json()
        self.assertIsNone(second["next"])
        previous_link = urlsplit(second["previous"])
        self.assertEqual(previous_link.path, self.url)
        self.assertEqual(parse_qs(previous_link.query), {})

    def test_unsupported_and_repeated_query_parameters_return_400(self):
        for query in (
            "page_size=5000",
            "organization_id=" + str(self.b.pk),
            "user_id=" + str(self.outsider.pk),
            "is_active=true",
            "ordering=-sku",
            "search=part",
            "page=1&page=2",
            "page=1&page=1",
            "search=a&search=b",
        ):
            with self.subTest(query=query):
                response = self.client.get(self.url + "?" + query)
                self.assertEqual(response.status_code, 400)
                self.assert_clean()

    def test_invalid_nonpositive_blank_last_and_unavailable_pages_return_exact_404(
        self,
    ):
        for page in ("", "0", "00", "-1", "invalid", "last", "1.5", "2", "9" * 5000):
            with self.subTest(page=page[:20]):
                response = self.client.get(self.url, {"page": page})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Invalid page."})
                self.assert_clean()

    def test_head_preserves_authentication_workspace_and_pagination_contracts(self):
        response = self.client.head(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        for query, status in (
            ("page=1", 200),
            ("page=0", 404),
            ("page=2", 404),
            ("page_size=1000", 400),
            ("page=1&page=2", 400),
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    self.client.head(self.url + "?" + query).status_code, status
                )
        viewer, _ = self.login_client(self.viewer)
        self.assertEqual(viewer.head(self.items_url(self.b)).status_code, 403)
        self.assert_clean()

    def test_read_only_method_contract_with_valid_session_csrf_and_private_responses(
        self,
    ):
        before = list(CatalogItem.objects.order_by("id").values())
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url,
                    {"sku": "FORBIDDEN"},
                    format="json",
                    HTTP_X_CSRFTOKEN=self.csrf,
                )
                self.assertEqual(response.status_code, 405)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertIn("private", response["Cache-Control"])
        options = self.client.options(self.url)
        self.assertEqual(options.status_code, 200)
        self.assertEqual(set(options["Allow"].split(", ")), {"GET", "HEAD", "OPTIONS"})
        self.assertEqual(list(CatalogItem.objects.order_by("id").values()), before)
        for response in (
            self.client.get(self.url),
            self.client.get(self.url, {"page": 2}),
            self.client.get(self.url, {"page_size": 1000}),
            APIClient().get(self.url),
        ):
            self.assertIn("no-store", response["Cache-Control"])
            self.assertIn("private", response["Cache-Control"])

    def test_count_rows_and_serializer_materialize_inside_scope_and_clear_after_errors(
        self,
    ):
        queries = []
        original = CatalogItemSerializer.to_representation

        def inspect_query(execute, sql, params, many, context):
            if '"catalog_catalogitem"' in sql:
                self.assertTrue(connection.in_atomic_block)
                queries.append(sql)
            return execute(sql, params, many, context)

        def serialize(serializer, item):
            self.assertTrue(connection.in_atomic_block)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('transaction_read_only'), "
                    "current_setting('orderdesk.organization_id'), "
                    "current_setting('orderdesk.user_id')"
                )
                self.assertEqual(
                    cursor.fetchone(), ("on", str(self.a.pk), str(self.admin.pk))
                )
            return original(serializer, item)

        with (
            connection.execute_wrapper(inspect_query),
            patch.object(CatalogItemSerializer, "to_representation", serialize),
        ):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(queries), 2)
        self.assertTrue(any("COUNT(" in query for query in queries))
        with self.assertNumQueries(0):
            self.assertEqual(response.json()["count"], 2)
        self.assert_clean()
        with (
            patch.object(
                CatalogItemSerializer,
                "to_representation",
                side_effect=ValueError("Synthetic serialization failure."),
            ),
            self.assertRaisesRegex(ValueError, "Synthetic serialization failure"),
        ):
            self.client.get(self.url)
        self.assert_clean()
        response = self.client.get(self.items_url(self.b))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assert_clean()
