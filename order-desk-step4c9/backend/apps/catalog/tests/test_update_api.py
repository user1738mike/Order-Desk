"""Real session/CSRF PATCH requests against the disposable PostgreSQL database."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.parsers import JSONParser
from rest_framework.test import APIClient

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.catalog.services import CATALOG_UPDATE_DENIED
from apps.catalog.tests.test_create_api import PUBLIC_FIELDS, CatalogCreateTestCase
from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.models import Membership, Organization


class CatalogUpdateTestCase(CatalogCreateTestCase):
    """Fixture helpers only; do not inherit discovered API tests."""

    def setUp(self):
        super().setUp()
        self.item = CatalogItem.objects.create(
            organization=self.a, sku="000Ab/P-1.x", description="Original"
        )
        self.other = CatalogItem.objects.create(
            organization=self.b, sku=self.item.sku, description="Other tenant"
        )
        CatalogItem.objects.filter(pk=self.item.pk).update(
            updated_at=timezone.now() - timedelta(days=1)
        )
        self.item.refresh_from_db()
        self.detail = self.item_url(self.a, self.item.pk)

    @staticmethod
    def item_url(workspace, item_id):
        return reverse(
            "workspaces:catalog:item",
            kwargs={"workspace_id": workspace.pk, "item_id": item_id},
        )

    def update(self, data, *, url=None, client=None, csrf=None):
        return (client or self.client).patch(
            url or self.detail, data, format="json", HTTP_X_CSRFTOKEN=csrf or self.csrf
        )

    def state(self):
        return CatalogItem.objects.filter(pk=self.item.pk).values().get()


class CatalogUpdateAPITests(CatalogUpdateTestCase):
    def test_description_change_preserves_omitted_fields_and_advances_timestamp(self):
        before = self.state()
        response = self.update({"description": "  Changed\n "})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()), PUBLIC_FIELDS)
        self.item.refresh_from_db()
        self.assertEqual(self.item.description, "  Changed\n ")
        for field in ("id", "organization_id", "sku", "created_at", "is_active"):
            self.assertEqual(getattr(self.item, field), before[field])
        self.assertGreater(self.item.updated_at, before["updated_at"])
        self.assert_private(response)
        self.assert_clean()

    def test_deactivation_reactivation_and_repeats_preserve_identity_and_history(self):
        for active in (False, True):
            response = self.update({"is_active": active})
            self.assertEqual(response.status_code, 200)
            self.item.refresh_from_db()
            stamp = self.item.updated_at
            self.assertEqual(self.item.is_active, active)
            self.assertEqual(self.item.description, "Original")
            rows = self.client.get(self.url).json()["results"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["is_active"], active)
            repeated = self.update({"is_active": active})
            self.assertEqual(repeated.status_code, 200)
            self.item.refresh_from_db()
            self.assertEqual(self.item.updated_at, stamp)
        self.assertEqual(CatalogItem.objects.count(), 2)
        self.assert_clean()

    def test_both_fields_and_blank_description(self):
        response = self.update({"description": "", "is_active": False})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual((self.item.description, self.item.is_active), ("", False))

    def test_noop_has_no_update_sql_and_preserves_timestamp(self):
        statements = []

        def observe(execute, sql, params, many, context):
            statements.append(sql)
            return execute(sql, params, many, context)

        before = self.item.updated_at
        with connection.execute_wrapper(observe):
            response = self.update({"description": "Original", "is_active": True})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            any(
                sql.startswith("UPDATE") and '"catalog_catalogitem"' in sql
                for sql in statements
            )
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.updated_at, before)

    def test_legacy_sku_whitespace_is_immutable_in_storage_and_response(self):
        raw = "  000Ab/P-1.x  "
        CatalogItem.objects.filter(pk=self.item.pk).update(sku=raw)
        response = self.update({"description": "Legacy item"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sku"], raw)
        self.item.refresh_from_db()
        self.assertEqual(self.item.sku, raw)

    def test_empty_unknown_and_protected_fields_leave_row_unchanged(self):
        before = self.state()
        payloads = [{}] + [
            {"description": "valid", key: "forged"}
            for key in (
                "sku",
                "id",
                "organization",
                "organization_id",
                "user_id",
                "created_at",
                "updated_at",
                "extra",
            )
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.update(payload).status_code, 400)
                self.assertEqual(self.state(), before)
                self.assert_clean()

    def test_invalid_types_and_nonobject_payloads(self):
        payloads = [[], None, False, "text"]
        payloads += [{"description": value} for value in (None, 1, False, [], {})]
        payloads += [
            {"is_active": value} for value in (None, 0, 1, "true", "false", [], {})
        ]
        before = self.state()
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.update(payload).status_code, 400)
                self.assertEqual(self.state(), before)

    def test_actual_unbounded_description_accepts_long_unicode(self):
        text = "é" * 6000
        self.assertEqual(self.update({"description": text}).status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.description, text)

    def test_malformed_json_and_unsupported_media(self):
        for content, media, expected in (
            ("{", "application/json", 400),
            ("x", "text/plain", 415),
            ("description=x", "application/x-www-form-urlencoded", 415),
        ):
            response = self.client.generic(
                "PATCH",
                self.detail,
                content,
                content_type=media,
                HTTP_X_CSRFTOKEN=self.csrf,
            )
            self.assertEqual(response.status_code, expected)
            self.assert_clean()

    def test_all_update_query_parameters_are_rejected(self):
        for query in (
            "page=1",
            "q=x",
            "is_active=true",
            "sku=x",
            "organization_id=x",
            "page=1&page=2",
        ):
            self.assertEqual(
                self.update(
                    {"description": "changed"}, url=self.detail + "?" + query
                ).status_code,
                400,
            )

    def test_nonadmins_are_denied_before_lookup_and_parser_for_any_item(self):
        for actor in (self.viewer, self.reviewer):
            client, csrf = self.login_client(actor)
            statements = []

            def observe(execute, sql, params, many, context, statements=statements):
                statements.append(sql)
                return execute(sql, params, many, context)

            with (
                connection.execute_wrapper(observe),
                patch.object(
                    JSONParser, "parse", side_effect=AssertionError("Early parse")
                ),
            ):
                for item_id in (self.item.pk, self.other.pk, uuid4()):
                    response = client.generic(
                        "PATCH",
                        self.item_url(self.a, item_id) + "?bad=x",
                        "{",
                        content_type="application/json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json(), {"detail": CATALOG_UPDATE_DENIED})
            self.assertFalse(any("catalog_catalogitem" in sql for sql in statements))
            self.assertEqual(client.get(self.url).status_code, 200)

    def test_missing_and_foreign_items_are_same_404_before_body_parse(self):
        with patch.object(
            JSONParser, "parse", side_effect=AssertionError("Early parse")
        ):
            for item_id in (uuid4(), self.other.pk):
                response = self.update({}, url=self.item_url(self.a, item_id))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Not found."})
                self.assert_clean()

    def test_missing_inaccessible_inactive_workspaces_and_operator_deny(self):
        outsider, csrf = self.login_client(self.outsider)
        response = self.update({}, client=outsider, csrf=csrf)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        response = self.update(
            {}, url=f"/api/v1/workspaces/{uuid4()}/catalog/items/{self.item.pk}/"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        for model, pk in (
            (Organization, self.a.pk),
            (Membership, self.admin_membership.pk),
        ):
            model.objects.filter(pk=pk).update(is_active=False)
            self.assertEqual(self.update({}).status_code, 403)
            model.objects.filter(pk=pk).update(is_active=True)
        self.assert_clean()

    def test_anonymous_expired_and_inactive_sessions_deny(self):
        anonymous = APIClient(enforce_csrf_checks=True)
        self.assertEqual(
            anonymous.patch(self.detail, {}, format="json").status_code, 403
        )
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        self.assertEqual(self.update({}).status_code, 403)
        self.admin.is_active = True
        self.admin.save(update_fields=["is_active"])
        Session.objects.filter(
            session_key=self.client.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.update({}).status_code, 403)

    def test_missing_invalid_csrf_and_untrusted_origin_deny(self):
        for headers in (
            {},
            {"HTTP_X_CSRFTOKEN": "invalid"},
            {
                "HTTP_X_CSRFTOKEN": self.csrf,
                "HTTP_ORIGIN": "https://untrusted.example.test",
            },
        ):
            self.assertEqual(
                self.client.patch(
                    self.detail, {"description": "changed"}, format="json", **headers
                ).status_code,
                403,
            )
        self.assertEqual(self.item.description, "Original")
        self.assert_clean()

    def test_url_scope_wins_over_selected_workspace_and_headers(self):
        session = self.client.session
        session["active_workspace_id"] = str(self.b.pk)
        session.save()
        response = self.client.patch(
            self.detail,
            {"description": "URL owns scope"},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_X_ORGANIZATION_ID=str(self.b.pk),
            HTTP_X_USER_ID=str(self.outsider.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["organization_id"], str(self.a.pk))
        self.other.refresh_from_db()
        self.assertEqual(self.other.description, "Other tenant")

    def test_parser_serializer_scope_and_materialized_render(
        self,
    ):
        original_parse = JSONParser.parse
        original_serialize = CatalogItemSerializer.to_representation

        def inspect_scope():
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

        def parse(parser, *args, **kwargs):
            inspect_scope()
            return original_parse(parser, *args, **kwargs)

        def serialize(serializer, item):
            inspect_scope()
            return original_serialize(serializer, item)

        with (
            patch.object(JSONParser, "parse", parse),
            patch.object(CatalogItemSerializer, "to_representation", serialize),
        ):
            response = self.update({"description": "Materialized"})
        self.assertEqual(response.status_code, 200)
        with patch.object(connection, "cursor", side_effect=AssertionError("Late SQL")):
            response.render()
        self.assert_clean()

    def test_unexpected_serialization_failure_rolls_back_and_next_scope_succeeds(self):
        before = self.state()
        with (
            patch.object(
                CatalogItemSerializer,
                "to_representation",
                side_effect=ValueError("Synthetic serialization failure"),
            ),
            self.assertRaises(ValueError),
        ):
            self.update({"description": "Must roll back", "is_active": False})
        self.assertEqual(self.state(), before)
        self.assert_clean()
        self.assertEqual(self.update({"description": "Recovered"}).status_code, 200)

    def test_detail_methods_uuid_routing_and_existing_collection_contract(self):
        for method in ("get", "head", "post", "put", "delete"):
            response = getattr(self.client, method)(
                self.detail, HTTP_X_CSRFTOKEN=self.csrf
            )
            self.assertEqual(response.status_code, 405)
        self.assertEqual(
            set(self.client.options(self.detail)["Allow"].split(", ")),
            {"PATCH", "OPTIONS"},
        )
        self.assertEqual(
            self.client.patch(
                self.detail.replace(str(self.item.pk), "not-a-uuid")
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.post({"sku": "NEW"}).status_code, 201)
        self.assertEqual(
            self.client.patch(
                self.url, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
            ).status_code,
            405,
        )
