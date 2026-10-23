"""Real PostgreSQL/session regression for scalar operational queues."""

from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.models import DraftOrder, PurchaseOrder
from apps.orders.queue import OrderQueueSerializer
from apps.organizations.models import Membership, MembershipRole, Organization


class OrderQueueTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="queue@example.test")
        self.a = Organization.objects.create(name="Synthetic queue A")
        self.b = Organization.objects.create(name="Synthetic queue B")
        self.membership = Membership.objects.create(
            organization=self.a, user=self.user, role=MembershipRole.VIEWER
        )
        Membership.objects.create(organization=self.b, user=self.user)
        self.order = PurchaseOrder.objects.create(
            organization=self.a,
            created_by=self.user,
            customer_name="Buyer 100%_",
            purchase_order_number="INTERNAL-001",
        )
        PurchaseOrder.objects.create(
            organization=self.b,
            created_by=self.user,
            customer_name="PRIVATE FOREIGN",
            purchase_order_number="FOREIGN-001",
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.url = f"/api/v1/workspaces/{self.a.pk}/orders/queue/"

    def test_roles_scalar_payload_no_nested_reads_and_no_private_cache(self):
        for role in MembershipRole.values:
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertEqual(response.json()["count"], 1)
            row = response.json()["results"][0]
            self.assertEqual(set(row), set(OrderQueueSerializer.Meta.fields))
            self.assertEqual(row["organization_id"], str(self.a.pk))
            self.assertIsNone(row["customer_reference"])
            for query in queries:
                self.assertNotIn('FROM "orders_orderdocument"', query["sql"])
                self.assertNotIn('FROM "orders_purchaseorderline"', query["sql"])
                self.assertNotIn('"comments"', query["sql"])
                self.assertNotIn('"original_intake_text"', query["sql"])

    def test_literal_customer_number_search_and_exact_status(self):
        for query in ("buyer", "100%_", "internal-001"):
            self.assertEqual(self.client.get(self.url, {"q": query}).json()["count"], 1)
        for query in ("PRIVATE", "100%_X", "foreign"):
            self.assertEqual(self.client.get(self.url, {"q": query}).json()["count"], 0)
        self.assertEqual(
            self.client.get(self.url, {"status": "draft"}).json()["count"], 1
        )
        self.assertEqual(
            self.client.get(self.url, {"status": "approved"}).json()["count"], 0
        )

    def test_source_reference_is_searchable_without_loading_intake_text(self):
        # Conversion service supplies the only supported source link.
        from apps.catalog.models import CatalogItem
        from apps.orders.models import DraftOrderLine
        from apps.orders.services import convert_draft_to_purchase_order

        self.membership.role = MembershipRole.ADMIN
        self.membership.save(update_fields=["role"])
        draft = DraftOrder.objects.create(
            organization=self.a,
            initiating_user=self.user,
            customer_name="Converted buyer",
            customer_reference="External-0042",
            original_intake_text="PRIVATE INTAKE",
        )
        item = CatalogItem.objects.create(organization=self.a, sku="SKU")
        DraftOrderLine.objects.create(
            organization=self.a,
            order=draft,
            position=1,
            quantity=1,
            catalogue_item=item,
            catalogue_sku_snapshot="SKU",
        )
        convert_draft_to_purchase_order(
            actor=self.user, organization_id=self.a.pk, order_id=draft.pk, data={}
        )
        response = self.client.get(self.url, {"q": "external-0042"})
        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["source_draft_id"], str(draft.pk))
        self.assertEqual(row["customer_reference"], "External-0042")
        self.assertNotIn("PRIVATE INTAKE", response.content.decode())

    def test_strict_queries_and_read_only_endpoint(self):
        for suffix in (
            "?q=a&q=b",
            "?status=draft&status=approved",
            "?page=1&page=2",
            "?status=unknown",
            "?page_size=500",
            "?q=" + "a" * 201,
            "?q=a%00b",
        ):
            self.assertEqual(self.client.get(self.url + suffix).status_code, 400)
        for value in ("0", "-1", "last", "1.1", "999"):
            self.assertEqual(
                self.client.get(self.url, {"page": value}).status_code, 404
            )
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)  # CSRF
        self.assertEqual(self.client.get(self.url).json()["count"], 1)

    def test_stable_pagination_and_revocation(self):
        PurchaseOrder.objects.bulk_create(
            [
                PurchaseOrder(
                    organization=self.a,
                    created_by=self.user,
                    customer_name="Pagination",
                    purchase_order_number=f"PAGE-{i}",
                )
                for i in range(51)
            ]
        )
        first = self.client.get(self.url).json()
        second = self.client.get(self.url, {"page": "2"}).json()
        self.assertEqual(first["count"], 52)
        self.assertEqual(len(first["results"]), 50)
        self.assertEqual(len(second["results"]), 2)
        self.assertTrue(
            {r["id"] for r in first["results"]}.isdisjoint(
                {r["id"] for r in second["results"]}
            )
        )
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)
