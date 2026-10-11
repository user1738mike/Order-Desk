"""Oversized legacy reads fail explicitly, with bounded native prefetches."""

from decimal import Decimal

from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.models import (
    OrderDocument,
    OrderDocumentReview,
    PurchaseOrder,
    PurchaseOrderLine,
)
from apps.orders.response_limits import (
    MAX_DOCUMENT_REVIEWS,
    MAX_ORDER_DOCUMENTS,
    MAX_ORDER_LINES,
)
from apps.organizations.services import create_organization


class PurchaseOrderResponseLimitTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="response-limits@example.test")
        self.organization = create_organization(actor=self.user, name="Limits")
        self.order = PurchaseOrder.objects.create(
            organization=self.organization,
            created_by=self.user,
            customer_name="Synthetic buyer",
            purchase_order_number="LIMIT-1",
        )
        self.client = APIClient()
        self.client.force_login(self.user)
        self.url = f"/api/v1/workspaces/{self.organization.pk}/orders/{self.order.pk}/"

    def populate(self, count):
        PurchaseOrderLine.objects.bulk_create(
            [
                PurchaseOrderLine(
                    organization=self.organization,
                    order=self.order,
                    line_number=i + 1,
                    sku=f"SKU-{i}",
                    quantity=Decimal("1.0000"),
                )
                for i in range(count)
            ]
        )

    def test_at_limit_returns_every_line_with_exact_values(self):
        self.populate(MAX_ORDER_LINES)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["lines"]), MAX_ORDER_LINES)
        self.assertEqual(response.json()["lines"][-1]["quantity"], "1.0000")

    def test_over_limit_detail_and_collection_fail_without_truncation(self):
        self.populate(MAX_ORDER_LINES + 1)
        for url in (self.url, f"/api/v1/workspaces/{self.organization.pk}/orders/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 413)
                self.assertEqual(set(response.json()), {"detail"})

    def test_foreign_parent_does_not_reveal_oversized_history(self):
        self.populate(MAX_ORDER_LINES + 1)
        other = create_organization(actor=self.user, name="Other limits")
        response = self.client.get(
            f"/api/v1/workspaces/{other.pk}/orders/{self.order.pk}/"
        )
        self.assertEqual(response.status_code, 404)

    def document(self):
        return OrderDocument(
            organization=self.organization,
            order=self.order,
            uploaded_by=self.user,
            file="legacy/synthetic.csv",
            original_name="synthetic.csv",
            content_type="text/csv",
            size_bytes=1,
        )

    def test_oversized_document_history_is_explicitly_rejected(self):
        OrderDocument.objects.bulk_create(
            [self.document() for _ in range(MAX_ORDER_DOCUMENTS + 1)]
        )
        self.assertEqual(self.client.get(self.url).status_code, 413)

    def test_oversized_review_history_is_explicitly_rejected(self):
        document = self.document()
        document.save()
        OrderDocumentReview.objects.bulk_create(
            [
                OrderDocumentReview(
                    organization=self.organization,
                    document=document,
                    created_by=self.user,
                    status="accepted",
                    resolved_by=self.user,
                    resolved_at=timezone.now(),
                )
                for _ in range(MAX_DOCUMENT_REVIEWS + 1)
            ]
        )
        self.assertEqual(self.client.get(self.url).status_code, 413)
