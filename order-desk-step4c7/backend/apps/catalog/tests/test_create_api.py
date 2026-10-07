"""Administrator catalogue creation through real PostgreSQL session requests."""

import json
import secrets
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.parsers import JSONParser
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.models import Membership, MembershipRole, Organization

NONADMIN_DENIAL = (
    "You do not have permission to create catalogue items in this workspace."
)
DUPLICATE = "A catalogue item with this stock code already exists."
PUBLIC_FIELDS = {
    "id",
    "organization_id",
    "sku",
    "description",
    "is_active",
    "created_at",
    "updated_at",
}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CatalogCreateTestCase(TransactionTestCase):
    """Shared synthetic fixtures; no inherited test methods or forced auth."""

    password = "catalog-create-synthetic-password-42"  # noqa: S105 -- test only

    def setUp(self) -> None:
        self.admin = User.objects.create_user(
            email="catalog-create-admin@example.test", password=self.password
        )
        self.peer_admin = User.objects.create_user(
            email="catalog-create-peer@example.test", password=self.password
        )
        self.reviewer = User.objects.create_user(
            email="catalog-create-reviewer@example.test", password=self.password
        )
        self.viewer = User.objects.create_user(
            email="catalog-create-viewer@example.test", password=self.password
        )
        self.outsider = User.objects.create_superuser(
            email="catalog-create-operator@example.test", password=self.password
        )
        self.a = Organization.objects.create(name="Synthetic create A")
        self.b = Organization.objects.create(name="Synthetic create B")
        self.admin_membership = Membership.objects.create(
            user=self.admin, organization=self.a, role=MembershipRole.ADMIN
        )
        Membership.objects.create(
            user=self.admin, organization=self.b, role=MembershipRole.ADMIN
        )
        Membership.objects.create(
            user=self.peer_admin, organization=self.a, role=MembershipRole.ADMIN
        )
        for actor, role in (
            (self.reviewer, MembershipRole.REVIEWER),
            (self.viewer, MembershipRole.VIEWER),
        ):
            Membership.objects.create(user=actor, organization=self.a, role=role)
        self.url = self.items_url(self.a)
        self.client, self.csrf = self.login_client(self.admin)

    @staticmethod
    def items_url(workspace: Organization) -> str:
        return reverse(
            "workspaces:catalog:items", kwargs={"workspace_id": workspace.pk}
        )

    def login_client(self, actor: User) -> tuple[APIClient, str]:
        client = APIClient(enforce_csrf_checks=True)
        bootstrap = client.get(reverse("session_auth:csrf"))
        self.assertEqual(bootstrap.status_code, 200)
        response = client.post(
            reverse("session_auth:login"),
            {"email": actor.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=bootstrap.json()["csrf_token"],
        )
        self.assertEqual(response.status_code, 200, response.content)
        return client, response.json()["csrf_token"]

    def post(self, data, *, url=None, client=None, csrf=None, **headers):
        return (client or self.client).post(
            url or self.url,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=csrf or self.csrf,
            **headers,
        )

    def assert_clean(self) -> None:
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                " NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def assert_private(self, response) -> None:
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])


class CatalogCreateAPITests(CatalogCreateTestCase):
    def test_admin_creation_returns_one_allowlisted_object_with_model_defaults(self):
        response = self.post({"sku": "PART-001"})
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(set(body), PUBLIC_FIELDS)
        self.assertEqual(body["organization_id"], str(self.a.pk))
        self.assertEqual(body["description"], "")
        self.assertTrue(body["is_active"])
        item = CatalogItem.objects.get(pk=UUID(body["id"]))
        self.assertEqual(item.organization_id, self.a.pk)
        self.assertEqual(item.sku, "PART-001")
        self.assert_private(response)
        self.assert_clean()

    def test_case_punctuation_leading_zeroes_and_surrounding_whitespace_are_preserved(
        self,
    ):
        response = self.post(
            {
                "sku": "  000Ab/c.D-1  ",
                "description": "  Synthetic pump part  ",
                "is_active": False,
            }
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["sku"], "000Ab/c.D-1")
        self.assertEqual(response.json()["description"], "  Synthetic pump part  ")
        self.assertFalse(response.json()["is_active"])
        self.assert_clean()

    def test_saved_item_is_read_back_only_in_its_url_workspace(self):
        created = self.post({"sku": "ONLY-A"})
        self.assertEqual(created.status_code, 201)
        identity = created.json()["id"]
        a = self.client.get(self.url)
        b = self.client.get(self.items_url(self.b))
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(a.json()["count"], 1)
        self.assertEqual(b.json()["count"], 0)
        self.assertEqual(a.json()["results"][0]["id"], identity)
        self.assertNotContains(b, identity)
        self.assert_clean()

    def test_url_scope_wins_over_selected_workspace_and_forged_headers_cookies(self):
        selected = self.client.put(
            reverse("workspaces:current"),
            {"workspace_id": str(self.b.pk)},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(selected.status_code, 200)
        self.client.cookies["organization_id"] = str(self.b.pk)
        self.client.cookies["user_id"] = str(self.outsider.pk)
        response = self.post(
            {"sku": "URL-A"},
            HTTP_X_WORKSPACE_ID=str(self.b.pk),
            HTTP_X_ORGANIZATION_ID=str(self.b.pk),
            HTTP_X_USER_ID=str(self.outsider.pk),
            HTTP_AUTHORIZATION=f"Bearer {self.outsider.pk}",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["organization_id"], str(self.a.pk))
        self.assertEqual(CatalogItem.objects.filter(organization=self.b).count(), 0)
        self.assert_clean()

    def test_viewer_and_reviewer_creation_denial_preserves_read_access(self):
        for actor in (self.viewer, self.reviewer):
            client, csrf = self.login_client(actor)
            with self.subTest(role=actor.email):
                response = self.post({"sku": "FORBIDDEN"}, client=client, csrf=csrf)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": NONADMIN_DENIAL})
                self.assertEqual(client.get(self.url).status_code, 200)
                self.assert_private(response)
                self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_nonadmin_authorization_precedes_conflicts_payload_parsing_and_validation(
        self,
    ):
        CatalogItem.objects.create(organization=self.a, sku="EXISTING")
        for actor in (self.viewer, self.reviewer):
            client, csrf = self.login_client(actor)
            for data, content_type in (
                ('{"sku":"EXISTING"}', "application/json"),
                ('{"sku":123,"organization_id":"forged"}', "application/json"),
                ("{", "application/json"),
                ("sku=EXISTING", "application/x-www-form-urlencoded"),
            ):
                with self.subTest(
                    actor=actor.email, content_type=content_type, data=data
                ):
                    catalogue_queries = []

                    def inspect(
                        execute, sql, params, many, context, queries=catalogue_queries
                    ):
                        if '"catalog_catalogitem"' in sql:
                            queries.append(sql)
                        return execute(sql, params, many, context)

                    with connection.execute_wrapper(inspect):
                        response = client.post(
                            self.url + "?page=1",
                            data,
                            content_type=content_type,
                            HTTP_X_CSRFTOKEN=csrf,
                        )
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json(), {"detail": NONADMIN_DENIAL})
                    self.assertEqual(catalogue_queries, [])
                    self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 1)

    def test_operator_flags_cannot_replace_workspace_membership(self):
        client, csrf = self.login_client(self.outsider)
        response = self.post({"sku": "OPERATOR"}, client=client, csrf=csrf)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assert_clean()

    def test_anonymous_and_fabricated_identity_headers_do_not_authenticate_creation(
        self,
    ):
        response = APIClient(enforce_csrf_checks=True).post(
            self.url,
            {"sku": "ANON"},
            format="json",
            HTTP_X_USER_ID=str(self.admin.pk),
            HTTP_X_WORKSPACE_ID=str(self.a.pk),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(), {"detail": "Authentication credentials were not provided."}
        )
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assert_clean()

    def test_expired_logged_out_and_replayed_sessions_cannot_create(self):
        expired, csrf = self.login_client(self.admin)
        session = expired.session
        session.set_expiry(timezone.now() - timedelta(seconds=1))
        session.save()
        expired_response = self.post({"sku": "EXPIRED"}, client=expired, csrf=csrf)
        self.assertEqual(expired_response.status_code, 403)
        key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        logged_out = self.client.post(
            reverse("session_auth:logout"),
            {},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(logged_out.status_code, 204)
        replay = APIClient(enforce_csrf_checks=True)
        replay.cookies[settings.SESSION_COOKIE_NAME] = key
        for client in (self.client, replay):
            self.assertEqual(
                client.post(self.url, {"sku": "REPLAY"}, format="json").status_code,
                403,
            )
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assert_clean()

    def test_missing_invalid_and_prelogin_csrf_tokens_create_no_rows(self):
        prelogin = self.client.get(reverse("session_auth:csrf")).json()["csrf_token"]
        relogin = self.client.post(
            reverse("session_auth:login"),
            {"email": self.admin.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=prelogin,
        )
        self.assertEqual(relogin.status_code, 200)
        for headers in (
            {},
            {"HTTP_X_CSRFTOKEN": "invalid"},
            {"HTTP_X_CSRFTOKEN": prelogin},
        ):
            with self.subTest(headers=headers):
                response = self.client.post(
                    self.url,
                    {"sku": "NO-CSRF"},
                    format="json",
                    **headers,
                )
                self.assertEqual(response.status_code, 403)
                self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_untrusted_origin_denies_creation_with_valid_csrf(self):
        response = self.post(
            {"sku": "BAD-ORIGIN"}, HTTP_ORIGIN="https://untrusted.example.test"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assert_clean()

    def test_inactive_account_denies_existing_authenticated_session(self):
        User.objects.filter(pk=self.admin.pk).update(is_active=False)
        self.assertEqual(self.post({"sku": "INACTIVE"}).status_code, 403)
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assert_clean()

    def test_revoked_membership_denies_creation(self):
        Membership.objects.filter(pk=self.admin_membership.pk).update(is_active=False)
        response = self.post({"sku": "REVOKED"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assert_clean()

    def test_demoted_administrator_loses_creation_but_keeps_read_access(self):
        Membership.objects.filter(pk=self.admin_membership.pk).update(
            role=MembershipRole.VIEWER
        )
        response = self.post({"sku": "DEMOTED"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": NONADMIN_DENIAL})
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assert_clean()

    def test_missing_foreign_and_inactive_workspaces_share_generic_denial(self):
        foreign = Organization.objects.create(name="Synthetic inaccessible workspace")
        inactive = Organization.objects.create(
            name="Synthetic inactive workspace", is_active=False
        )
        Membership.objects.create(
            user=self.admin, organization=inactive, role=MembershipRole.ADMIN
        )
        for workspace_id in (uuid4(), foreign.pk, inactive.pk):
            with self.subTest(workspace_id=workspace_id):
                url = reverse(
                    "workspaces:catalog:items", kwargs={"workspace_id": workspace_id}
                )
                response = self.post({"sku": "NOT-ALLOWED"}, url=url)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
                self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_admin_bad_values_and_nonobject_payloads_return_400_without_insertion(self):
        for data in (
            {},
            [],
            ["PART"],
            "PART",
            7,
            True,
            None,
            {"sku": ""},
            {"sku": " \t\n "},
            {"sku": None},
            {"sku": 123},
            {"sku": True},
            {"sku": []},
            {"sku": "NEW", "description": None},
            {"sku": "NEW", "description": 123},
            {"sku": "NEW", "is_active": "false"},
            {"sku": "NEW", "is_active": 0},
        ):
            with self.subTest(data=data):
                # generic preserves JSON null, unlike APIClient.post(data=None).
                response = self.client.generic(
                    "POST",
                    self.url,
                    data=json.dumps(data),
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=self.csrf,
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_unknown_and_protected_fields_are_rejected_not_silently_discarded(self):
        for field in (
            "id",
            "organization",
            "organization_id",
            "user_id",
            "created_at",
            "updated_at",
            "role",
            "unknown",
        ):
            with self.subTest(field=field):
                response = self.post({"sku": "PROTECTED", field: str(self.b.pk)})
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
                self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_textfield_lengths_follow_actual_model_and_boolean_types_are_strict(self):
        self.assertIsNone(CatalogItem._meta.get_field("sku").max_length)
        self.assertIsNone(CatalogItem._meta.get_field("description").max_length)
        response = self.post({"sku": "S" * 5000, "description": "D" * 6000})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(len(response.json()["sku"]), 5000)
        self.assertEqual(len(response.json()["description"]), 6000)
        self.assert_clean()

    def test_unindexable_sku_returns_safe_field_error_and_next_creation_succeeds(self):
        # Real high-entropy text exercises PostgreSQL's index-row storage limit;
        # repeated/compressible long text remains valid in the separate test.
        sku = secrets.token_urlsafe(3750)
        self.assertEqual(len(sku), 5000)
        response = self.post({"sku": sku})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            response.json(),
            {"sku": ["This stock code is too large for the catalogue index."]},
        )
        for detail in (
            "54000",
            "catalog_org_sku_unique",
            "catalog_catalogitem",
            "INSERT INTO",
        ):
            self.assertNotContains(response, detail, status_code=400)
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assert_clean()
        recovered = self.post({"sku": "AFTER-INDEX-LIMIT"})
        self.assertEqual(recovered.status_code, 201)
        self.assertEqual(CatalogItem.objects.count(), 1)
        self.assert_clean()

    def test_malformed_json_and_unsupported_media_types_leave_no_rows(self):
        for data, content_type, status in (
            ("{", "application/json", 400),
            ("sku=NEW", "application/x-www-form-urlencoded", 415),
            ("NEW", "text/plain", 415),
        ):
            with self.subTest(content_type=content_type):
                response = self.client.post(
                    self.url,
                    data,
                    content_type=content_type,
                    HTTP_X_CSRFTOKEN=self.csrf,
                )
                self.assertEqual(response.status_code, status)
                self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_creation_query_parameters_are_all_rejected(self):
        for query in (
            "page=1",
            "page_size=100",
            "ordering=sku",
            "organization_id=" + str(self.b.pk),
            "user_id=" + str(self.outsider.pk),
            "page=1&page=1",
        ):
            with self.subTest(query=query):
                response = self.post({"sku": "QUERY"}, url=self.url + "?" + query)
                self.assertEqual(response.status_code, 400)
                self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_same_workspace_active_inactive_and_trimmed_duplicates_return_exact_409(
        self,
    ):
        CatalogItem.objects.create(organization=self.a, sku="EXISTING")
        CatalogItem.objects.create(organization=self.a, sku="ARCHIVED", is_active=False)
        for sku in ("EXISTING", "ARCHIVED", "  EXISTING  "):
            with self.subTest(sku=sku):
                response = self.post({"sku": sku})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json(), {"detail": DUPLICATE})
                for forbidden in ("catalog_org_sku_unique", "23505", "INSERT INTO"):
                    self.assertNotContains(response, forbidden, status_code=409)
                self.assert_private(response)
                self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 2)

    def test_cross_workspace_same_sku_and_same_workspace_different_case_are_valid(self):
        a = self.post({"sku": "SAME"})
        b = self.post({"sku": "SAME"}, url=self.items_url(self.b))
        lower = self.post({"sku": "same"})
        for response in (a, b, lower):
            self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(a.json()["organization_id"], str(self.a.pk))
        self.assertEqual(b.json()["organization_id"], str(self.b.pk))
        self.assertEqual(CatalogItem.objects.count(), 3)
        self.assert_clean()

    def test_insert_and_response_serialization_use_one_owned_write_scope(self):
        writes = []
        original = CatalogItemSerializer.to_representation

        def inspect_query(execute, sql, params, many, context):
            if sql.startswith("INSERT INTO") and '"catalog_catalogitem"' in sql:
                self.assertTrue(connection.in_atomic_block)
                writes.append(sql)
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
                    cursor.fetchone(), ("off", str(self.a.pk), str(self.admin.pk))
                )
            return original(serializer, item)

        with (
            connection.execute_wrapper(inspect_query),
            patch.object(CatalogItemSerializer, "to_representation", serialize),
        ):
            response = self.post({"sku": "WRITE-SCOPE"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(writes), 1)
        with self.assertNumQueries(0):
            self.assertEqual(response.json()["sku"], "WRITE-SCOPE")
        self.assert_clean()

    def test_json_body_parsing_begins_inside_the_fresh_write_scope(self):
        original = JSONParser.parse
        parsed = []

        def inspect(parser, stream, media_type=None, parser_context=None):
            self.assertTrue(connection.in_atomic_block)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('transaction_read_only'), "
                    "current_setting('orderdesk.organization_id'), "
                    "current_setting('orderdesk.user_id')"
                )
                self.assertEqual(
                    cursor.fetchone(), ("off", str(self.a.pk), str(self.admin.pk))
                )
            parsed.append(True)
            return original(
                parser, stream, media_type=media_type, parser_context=parser_context
            )

        with patch.object(JSONParser, "parse", inspect):
            response = self.post({"sku": "PARSER-SCOPE"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(parsed, [True])
        self.assert_clean()

    def test_unexpected_response_failure_rolls_back_item_and_context(
        self,
    ):
        with (
            patch.object(
                CatalogItemSerializer,
                "to_representation",
                side_effect=ValueError("Synthetic creation serialization failure."),
            ),
            self.assertRaisesRegex(ValueError, "Synthetic creation"),
        ):
            self.post({"sku": "ROLLBACK"})
        self.assertFalse(CatalogItem.objects.filter(sku="ROLLBACK").exists())
        self.assert_clean()
        response = self.post({"sku": "AFTER-ROLLBACK"})
        self.assertEqual(response.status_code, 201)
        self.assert_clean()

    def test_get_head_and_remaining_write_method_contracts_stay_intact(self):
        before = CatalogItem.objects.count()
        for method in ("put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url,
                    {"sku": "FORBIDDEN"},
                    format="json",
                    HTTP_X_CSRFTOKEN=self.csrf,
                )
                self.assertEqual(response.status_code, 405)
                self.assert_private(response)
        self.assertEqual(CatalogItem.objects.count(), before)
        self.assertEqual(self.client.head(self.url).status_code, 200)
        self.assertEqual(self.client.get(self.url + "?page_size=500").status_code, 400)
        self.assertEqual(self.client.get(self.url + "?page=0").status_code, 404)
        self.assert_clean()
