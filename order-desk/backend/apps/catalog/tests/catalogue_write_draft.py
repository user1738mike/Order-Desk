"""Unwired future creation draft, preserved outside normal test discovery."""

from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.catalog.services import create_catalog_item
from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.models import Membership, MembershipRole, Organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CatalogAPITests(TransactionTestCase):
    password = "catalog-api-synthetic-password-42"  # noqa: S105 -- test only

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

    def create_item(self, payload, *, url=None):
        return self.client.post(
            url or self.url, payload, format="json", HTTP_X_CSRFTOKEN=self.csrf
        )

    def assert_clean(self) -> None:
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                " "
                "NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def test_anonymous_and_fabricated_identity_headers_cannot_access_catalogue(self):
        client = APIClient(enforce_csrf_checks=True)
        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(client, method)(
                    self.url,
                    HTTP_X_USER_ID=str(self.admin.pk),
                    HTTP_X_WORKSPACE_ID=str(self.a.pk),
                )
                self.assertEqual(response.status_code, 403)

    def test_all_members_can_read_inactive_items_and_only_public_fields(self):
        for user in (self.admin, self.reviewer, self.viewer):
            client, _ = self.login_client(user)
            with self.subTest(user=user.pk):
                response = client.get(self.url)
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["count"], 2)
                self.assertEqual(
                    [item["id"] for item in body["results"]],
                    [str(self.archived_a.pk), str(self.item_a.pk)],
                )
                self.assertFalse(body["results"][0]["is_active"])
                self.assertEqual(
                    set(body["results"][0]),
                    {
                        "id",
                        "sku",
                        "description",
                        "is_active",
                        "created_at",
                        "updated_at",
                    },
                )
                self.assertNotContains(response, self.item_b.description)
                self.assertNotContains(response, self.admin.email)
                self.assert_clean()

    def test_url_scope_ignores_shared_session_workspace_preference(self):
        selected = self.client.put(
            reverse("workspaces:current"),
            {"workspace_id": str(self.b.pk)},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(selected.status_code, 200)
        response = self.client.get(self.url, HTTP_X_WORKSPACE_ID=str(self.b.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertNotContains(response, self.item_b.description)

    def test_foreign_unknown_and_operator_workspaces_share_generic_denial(self):
        viewer, _ = self.login_client(self.viewer)
        operator, csrf = self.login_client(self.outsider)
        unknown = reverse("workspaces:catalog:items", kwargs={"workspace_id": uuid4()})
        for client, url in ((viewer, self.items_url(self.b)), (viewer, unknown)):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        for response in (
            operator.get(self.url),
            operator.post(
                self.url, {"sku": "FORBIDDEN"}, format="json", HTTP_X_CSRFTOKEN=csrf
            ),
        ):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})

    def test_revocation_deactivation_and_demotion_affect_subsequent_requests(self):
        self.admin_membership.is_active = False
        self.admin_membership.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.admin_membership.is_active = True
        self.admin_membership.role = MembershipRole.VIEWER
        self.admin_membership.save(update_fields=["is_active", "role"])
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.create_item({"sku": "DEMOTED"}).status_code, 403)
        Organization.objects.filter(pk=self.a.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        Organization.objects.filter(pk=self.a.pk).update(is_active=True)
        User.objects.filter(pk=self.admin.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assert_clean()

    def test_catalogue_count_rows_and_serialization_run_inside_read_only_scope(self):
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
                cursor.execute("SHOW transaction_read_only")
                self.assertEqual(cursor.fetchone(), ("on",))
            return original(serializer, item)

        with (
            connection.execute_wrapper(inspect_query),
            patch.object(CatalogItemSerializer, "to_representation", serialize),
        ):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(queries), 2)
        self.assertTrue(any("COUNT(" in query for query in queries))
        self.assert_clean()

    def test_admin_creation_preserves_stock_code_and_uses_url_ownership(self):
        response = self.create_item(
            {
                "sku": "  000Ab/c.D-1  ",
                "description": "  Pump part  ",
                "is_active": False,
            }
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["sku"], "000Ab/c.D-1")
        self.assertEqual(body["description"], "  Pump part  ")
        self.assertFalse(body["is_active"])
        item = CatalogItem.objects.get(pk=body["id"])
        self.assertEqual(item.organization_id, self.a.pk)
        self.assert_clean()

    def test_viewers_and_reviewers_cannot_create_catalogue_items(self):
        before = CatalogItem.objects.count()
        for user in (self.viewer, self.reviewer):
            client, csrf = self.login_client(user)
            with self.subTest(user=user.pk):
                response = client.post(
                    self.url, {"sku": "FORBIDDEN"}, format="json", HTTP_X_CSRFTOKEN=csrf
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        self.assertEqual(CatalogItem.objects.count(), before)

    def test_invalid_input_and_server_owned_fields_do_not_create_items(self):
        before = CatalogItem.objects.count()
        payloads = [
            {},
            [],
            {"sku": None},
            {"sku": 123},
            {"sku": True},
            {"sku": " \t\n "},
            {"sku": "NEW", "description": 123},
            {"sku": "NEW", "is_active": "false"},
            {"sku": "NEW", "is_active": 0},
        ]
        for field in ("organization", "organization_id", "user_id", "role", "id"):
            payloads.append({"sku": "NEW", field: str(self.b.pk)})
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.create_item(payload).status_code, 400)
        self.assertEqual(CatalogItem.objects.count(), before)

    def test_duplicate_active_and_inactive_stock_codes_return_400(self):
        for sku in ("PART-001", "ARCH-001", "  PART-001  "):
            with self.subTest(sku=sku):
                response = self.create_item({"sku": sku})
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, "23505", status_code=400)
                self.assert_clean()
        self.assertEqual(CatalogItem.objects.filter(organization=self.a).count(), 2)

    def test_same_code_in_different_workspaces_and_different_case_are_valid(self):
        self.assertEqual(self.create_item({"sku": "part-001"}).status_code, 201)
        self.assertEqual(self.create_item({"sku": "UNIQUE-A"}).status_code, 201)
        response = self.create_item({"sku": "UNIQUE-A"}, url=self.items_url(self.b))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["sku"], "UNIQUE-A")

    def test_missing_csrf_and_untrusted_origin_block_creation(self):
        before = CatalogItem.objects.count()
        for headers in (
            {},
            {"HTTP_X_CSRFTOKEN": self.csrf, "HTTP_ORIGIN": "https://bad.test"},
        ):
            with self.subTest(headers=headers):
                response = self.client.post(
                    self.url, {"sku": "NEW"}, format="json", **headers
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(CatalogItem.objects.count(), before)

    def test_malformed_json_and_non_json_creation_are_rejected(self):
        for body, content_type, status in (
            ("{", "application/json", 400),
            ("sku=NEW", "application/x-www-form-urlencoded", 415),
        ):
            with self.subTest(content_type=content_type):
                response = self.client.post(
                    self.url,
                    body,
                    content_type=content_type,
                    HTTP_X_CSRFTOKEN=self.csrf,
                )
                self.assertEqual(response.status_code, status)

    def test_fixed_pagination_orders_by_sku_and_excludes_other_workspaces(self):
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
        self.assertIsNotNone(first.json()["next"])
        self.assertIsNone(first.json()["previous"])
        self.assertIsNone(second.json()["next"])
        self.assertIsNotNone(second.json()["previous"])
        rows = first.json()["results"] + second.json()["results"]
        expected = list(
            CatalogItem.objects.filter(organization=self.a)
            .order_by("sku", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual([row["id"] for row in rows], [str(pk) for pk in expected])

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
        self.assertEqual(
            self.client.get(self.items_url(workspace), {"page": 2}).status_code, 404
        )

    def test_unknown_and_repeated_query_parameters_return_400(self):
        for query in (
            "page_size=5000",
            "organization_id=" + str(self.b.pk),
            "user_id=" + str(self.outsider.pk),
            "is_active=true",
            "ordering=-sku",
            "page=1&page=2",
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    self.client.get(self.url + "?" + query).status_code, 400
                )
        self.assertEqual(
            self.create_item({"sku": "NEW"}, url=self.url + "?page=1").status_code, 400
        )

    def test_invalid_and_out_of_range_pages_return_404(self):
        for page in ("", "0", "-1", "invalid", "last", "1.5", "2", "9" * 5000):
            with self.subTest(page=page[:20]):
                self.assertEqual(
                    self.client.get(self.url, {"page": page}).status_code, 404
                )

    def test_unsupported_methods_do_not_modify_catalogue(self):
        before = CatalogItem.objects.count()
        for method in ("put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url, {"sku": "NEW"}, format="json", HTTP_X_CSRFTOKEN=self.csrf
                )
                self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.head(self.url).status_code, 200)
        self.assertEqual(CatalogItem.objects.count(), before)

    def test_success_and_error_responses_are_private_and_not_cacheable(self):
        responses = (
            self.client.get(self.url),
            self.create_item({"sku": "NEW"}),
            self.create_item({"sku": "PART-001"}),
            self.client.get(self.url, {"page": 2}),
            APIClient().get(self.url),
        )
        for response in responses:
            with self.subTest(status=response.status_code):
                self.assertIn("no-store", response["Cache-Control"])
                self.assertIn("private", response["Cache-Control"])

    def test_materialization_failure_rolls_back_creation_and_tenant_settings(self):
        def abort(item):
            self.assertTrue(connection.in_atomic_block)
            self.assertEqual(item.organization_id, self.a.pk)
            raise ValueError("Cannot build the response.")

        with self.assertRaisesRegex(ValueError, "Cannot build"):
            create_catalog_item(
                actor=self.admin,
                organization_id=self.a.pk,
                sku="ROLLBACK",
                materialize=abort,
            )
        self.assertFalse(CatalogItem.objects.filter(sku="ROLLBACK").exists())
        self.assert_clean()

    @override_settings(DEBUG=False)
    def test_runtime_api_verifier_refuses_non_development_before_fixtures(self):
        with self.assertRaises(CommandError):
            call_command("verify_catalog_api")
