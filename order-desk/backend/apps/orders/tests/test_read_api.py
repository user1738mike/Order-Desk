"""Native PostgreSQL draft reads through CSRF-enforced browser sessions."""

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.serializers import (
    DraftOrderLineReadSerializer,
    DraftOrderSummarySerializer,
)
from apps.organizations.models import Membership, MembershipRole, Organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DraftReadAPITests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="draft-read@example.test")
        self.a = Organization.objects.create(name="Synthetic draft A")
        self.b = Organization.objects.create(name="Synthetic draft B")
        self.membership = Membership.objects.create(
            user=self.user, organization=self.a, role=MembershipRole.ADMIN
        )
        Membership.objects.create(
            user=self.user, organization=self.b, role=MembershipRole.ADMIN
        )
        self.order = DraftOrder.objects.create(
            organization=self.a,
            initiating_user=self.user,
            original_intake_text="Private intake",
        )
        self.foreign = DraftOrder.objects.create(
            organization=self.b, initiating_user=self.user
        )
        self.line = DraftOrderLine.objects.create(
            organization=self.a,
            order=self.order,
            position=1,
            requested_description="Unresolved",
        )
        DraftOrderLine.objects.create(
            organization=self.b,
            order=self.foreign,
            position=1,
            requested_description="Foreign",
        )
        self.url = f"/api/v1/workspaces/{self.a.pk}/draft-orders/"
        self.detail = f"{self.url}{self.order.pk}/"
        self.lines = f"{self.detail}lines/"
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def assert_clean(self):
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                "NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def test_all_member_roles_read_scalar_headers_detail_and_unresolved_lines(self):
        for role in MembershipRole.values:
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["count"], 1)
            summary = response.json()["results"][0]
            self.assertEqual(set(summary), set(DraftOrderSummarySerializer.Meta.fields))
            self.assertEqual(summary["line_count"], 1)
            detail = self.client.get(self.detail).json()
            self.assertEqual(detail["original_intake_text"], "Private intake")
            self.assertTrue(detail["lines_url"].endswith(self.lines))
            line = self.client.get(self.lines).json()["results"][0]
            self.assertEqual(set(line), set(DraftOrderLineReadSerializer.Meta.fields))
            self.assertIsNone(line["quantity"])
            self.assertIsNone(line["catalogue_item_id"])
            self.assert_clean()

    def test_foreign_or_missing_parent_is_404_in_both_routes(self):
        for order_id in (self.foreign.pk, uuid4()):
            for suffix in ("", "lines/"):
                self.assertEqual(
                    self.client.get(f"{self.url}{order_id}/{suffix}").status_code, 404
                )
                self.assert_clean()

    def test_anonymous_inactive_and_inaccessible_workspaces_are_denied(self):
        for path in (self.url, self.detail, self.lines):
            self.assertEqual(APIClient().get(path).status_code, 403)
        self.assertEqual(
            self.client.get(f"/api/v1/workspaces/{uuid4()}/draft-orders/").status_code,
            403,
        )
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url + "?unknown=1").status_code, 403)
        self.assert_clean()

    def test_query_allowlist_invalid_pages_and_read_only_methods(self):
        for path in (self.url, self.lines):
            for query in (
                "?page=1&page=1",
                "?page_size=1000",
                "?organization_id=" + str(self.b.pk),
            ):
                self.assertEqual(self.client.get(path + query).status_code, 400)
            for query in ("?page=0", "?page=last", "?page=2"):
                self.assertEqual(self.client.get(path + query).status_code, 404)
        self.assertEqual(self.client.get(self.detail + "?page=1").status_code, 400)
        for path in (self.url, self.detail, self.lines):
            self.assertEqual(self.client.head(path).status_code, 200)
            self.assertEqual(self.client.options(path).status_code, 200)
            # Use a valid CSRF token so a rejected method cannot hide a write handler.
            token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
            for method in ("post", "put", "patch", "delete"):
                data = (
                    {"position": 2, "requested_description": "New requested line"}
                    if path == self.lines and method == "post"
                    else {}
                )
                response = getattr(self.client, method)(
                    path, data, format="json", HTTP_X_CSRFTOKEN=token
                )
                if path == self.url and method == "post":
                    # Step 4D.3 adds creation only on the list route.
                    self.assertEqual(response.status_code, 201)
                    created = DraftOrder.objects.get(pk=response.json()["id"])
                    self.assertEqual(created.organization_id, self.a.pk)
                    self.assertEqual(created.initiating_user_id, self.user.pk)
                    self.assertEqual(created.draft_lines.count(), 0)
                elif path == self.lines and method == "post":
                    # Step 4D.4 adds requested line creation on this route.
                    self.assertEqual(response.status_code, 201)
                    created_line = DraftOrderLine.objects.get(pk=response.json()["id"])
                    self.assertEqual(created_line.organization_id, self.a.pk)
                    self.assertEqual(created_line.order_id, self.order.pk)
                    self.assertIsNone(created_line.catalogue_item_id)
                else:
                    self.assertEqual(response.status_code, 405)
        self.assertEqual(DraftOrder.objects.count(), 3)
        self.assertEqual(DraftOrderLine.objects.count(), 3)
        self.assert_clean()

    def test_fixed_pages_order_counts_and_empty_drafts(self):
        for position in range(2, 56):
            DraftOrderLine.objects.create(
                organization=self.a,
                order=self.order,
                position=position,
                requested_sku=f"P{position}",
            )
        first = self.client.get(self.lines).json()
        second = self.client.get(self.lines + "?page=2").json()
        self.assertEqual(first["count"], 55)
        self.assertEqual(
            [row["position"] for row in first["results"]], list(range(1, 51))
        )
        self.assertEqual(
            [row["position"] for row in second["results"]], list(range(51, 56))
        )
        for _ in range(51):
            DraftOrder.objects.create(organization=self.a, initiating_user=self.user)
        body = self.client.get(self.url).json()
        self.assertEqual(body["count"], 52)
        self.assertEqual(len(body["results"]), 50)
        expected = list(
            DraftOrder.objects.filter(organization=self.a)
            .order_by("-created_at", "-id")
            .values_list("pk", flat=True)
        )
        self.assertEqual(
            [row["id"] for row in body["results"]], [str(pk) for pk in expected[:50]]
        )
        self.assertEqual(
            len(self.client.get(self.url + "?page=2").json()["results"]), 2
        )
        empty = self.client.get(f"{self.url}{expected[0]}/lines/").json()
        self.assertEqual(
            empty, {"count": 0, "next": None, "previous": None, "results": []}
        )

    def test_decimal_and_snapshots_survive_catalogue_changes(self):
        item = CatalogItem.objects.create(
            organization=self.a, sku="CURRENT", description="Current"
        )
        self.line.quantity = Decimal("999999999.999")
        self.line.catalogue_item = item
        self.line.catalogue_sku_snapshot = "OLD"
        self.line.catalogue_description_snapshot = "Old description"
        self.line.save()
        item.is_active = False
        item.save()
        row = self.client.get(self.lines).json()["results"][0]
        self.assertEqual(row["quantity"], "999999999.999")
        self.assertEqual(row["catalogue_sku_snapshot"], "OLD")
        self.assertEqual(row["catalogue_description_snapshot"], "Old description")

    def test_serialization_queries_finish_inside_read_only_scope(self):
        original = DraftOrderLineReadSerializer.to_representation

        def checked(serializer, instance):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('transaction_read_only'), "
                    "current_setting('orderdesk.organization_id')"
                )
                self.assertEqual(cursor.fetchone(), ("on", str(self.a.pk)))
            with self.assertNumQueries(0):
                return original(serializer, instance)

        with patch.object(DraftOrderLineReadSerializer, "to_representation", checked):
            self.assertEqual(self.client.get(self.lines).status_code, 200)
        self.assert_clean()

    def test_serialization_failure_rolls_back_and_next_workspace_is_clean(self):
        with patch.object(
            DraftOrderSummarySerializer,
            "to_representation",
            side_effect=RuntimeError("Synthetic failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.get(self.url)
        self.assert_clean()
        response = self.client.get(f"/api/v1/workspaces/{self.b.pk}/draft-orders/")
        self.assertEqual(response.json()["results"][0]["id"], str(self.foreign.pk))
        self.assert_clean()
