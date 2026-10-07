from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.models import (
    DraftOrder,
    DraftOrderLine,
    OrderStatus,
    PurchaseOrder,
    PurchaseOrderLine,
)
from apps.organizations.services import create_organization


class PurchaseOrderModelTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(email="orders@example.test")
        self.organization = create_organization(actor=self.user, name="Distributor 1")

    def test_order_requires_nonblank_customer_and_number(self) -> None:
        order = PurchaseOrder(
            organization=self.organization,
            created_by=self.user,
            customer_name="   ",
            purchase_order_number="PO-100",
        )
        with self.assertRaises(ValidationError):
            order.full_clean()

        order = PurchaseOrder(
            organization=self.organization,
            created_by=self.user,
            customer_name="Customer",
            purchase_order_number="   ",
        )
        with self.assertRaises(ValidationError):
            order.full_clean()

    def test_duplicate_order_number_in_same_workspace_is_rejected(self) -> None:
        PurchaseOrder.objects.create(
            organization=self.organization,
            created_by=self.user,
            customer_name="Acme",
            purchase_order_number="PO-100",
        )

        duplicate = PurchaseOrder(
            organization=self.organization,
            created_by=self.user,
            customer_name="Acme",
            purchase_order_number="PO-100",
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_approved_order_requires_reviewer(self) -> None:
        order = PurchaseOrder(
            organization=self.organization,
            created_by=self.user,
            customer_name="Acme",
            purchase_order_number="PO-100",
            status=OrderStatus.APPROVED,
        )
        with self.assertRaises(ValidationError):
            order.full_clean()

    def test_line_requires_positive_quantity_and_nonblank_sku(self) -> None:
        order = PurchaseOrder.objects.create(
            organization=self.organization,
            created_by=self.user,
            customer_name="Acme",
            purchase_order_number="PO-100",
        )
        for sku, quantity in (("   ", Decimal("2.5")), ("ABC-123", Decimal("0"))):
            with self.subTest(sku=sku, quantity=quantity):
                line = PurchaseOrderLine(
                    order=order,
                    organization=self.organization,
                    line_number=1,
                    sku=sku,
                    quantity=quantity,
                )
                with self.assertRaises(ValidationError):
                    line.full_clean()

    def test_order_line_numbers_are_unique_per_order(self) -> None:
        order = PurchaseOrder.objects.create(
            organization=self.organization,
            created_by=self.user,
            customer_name="Acme",
            purchase_order_number="PO-100",
        )
        PurchaseOrderLine.objects.create(
            order=order,
            organization=self.organization,
            line_number=1,
            sku="ABC-123",
            quantity=Decimal("2"),
        )
        duplicate = PurchaseOrderLine(
            order=order,
            organization=self.organization,
            line_number=1,
            sku="XYZ-999",
            quantity=Decimal("1"),
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()


class DraftOrderModelTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(email="draft-owner@example.test")
        cls.organization = create_organization(actor=cls.user, name="Draft distributor")

    def test_empty_draft_defaults_and_user_history(self) -> None:
        order = DraftOrder.objects.create(
            organization=self.organization, initiating_user=self.user
        )
        self.assertIsInstance(order.pk, UUID)
        self.assertEqual(order.status, DraftOrder.Status.DRAFT)
        self.assertEqual(order.source_type, DraftOrder.SourceType.MANUAL)
        self.assertEqual(order.customer_name, "")
        self.assertEqual(order.customer_reference, "")
        self.assertEqual(order.original_intake_text, "")
        self.assertFalse(order.draft_lines.exists())
        self.assertIsNotNone(order.created_at.utcoffset())
        self.assertIsNotNone(order.updated_at.utcoffset())

        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(
            DraftOrder.objects.get(pk=order.pk).initiating_user_id, self.user.pk
        )

    def test_unmatched_line_keeps_unknown_quantity_and_original_request(self) -> None:
        order = DraftOrder.objects.create(
            organization=self.organization,
            initiating_user=self.user,
            original_intake_text="Please send the blue parts; quantity to follow.",
        )
        line = DraftOrderLine.objects.create(
            organization=self.organization,
            order=order,
            position=3,
            requested_description="blue parts",
        )
        self.assertIsNone(line.quantity)
        self.assertIsNone(line.catalogue_item_id)
        self.assertEqual(line.catalogue_sku_snapshot, "")
        self.assertEqual(line.requested_description, "blue parts")
        self.assertIn("quantity to follow", order.original_intake_text)

    def test_decimal_quantity_boundaries_and_catalogue_snapshot(self) -> None:
        order = DraftOrder.objects.create(
            organization=self.organization, initiating_user=self.user
        )
        item = CatalogItem.objects.create(
            organization=self.organization,
            sku="PART-7",
            description="First description",
        )
        line = DraftOrderLine(
            organization=self.organization,
            order=order,
            position=1,
            quantity=Decimal("999999999.999"),
            catalogue_item=item,
            catalogue_sku_snapshot=item.sku,
            catalogue_description_snapshot=item.description,
        )
        line.full_clean()
        line.save()
        item.description = "New description"
        item.is_active = False
        item.save(update_fields=["description", "is_active", "updated_at"])
        line.refresh_from_db()
        self.assertEqual(line.quantity, Decimal("999999999.999"))
        self.assertEqual(line.catalogue_description_snapshot, "First description")
        self.assertEqual(line.catalogue_item_id, item.pk)

    def test_validation_rejects_unresolved_identity_and_bad_optional_labels(
        self,
    ) -> None:
        order = DraftOrder(
            organization=self.organization,
            initiating_user=self.user,
            customer_name="   ",
        )
        with self.assertRaises(ValidationError):
            order.full_clean()
        saved = DraftOrder.objects.create(
            organization=self.organization, initiating_user=self.user
        )
        for values in (
            {},
            {"requested_sku": "  "},
            {"requested_description": "\t"},
            {"requested_sku": "SKU", "quantity": Decimal("0")},
            {"requested_sku": "SKU", "quantity": Decimal("1000000000")},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                DraftOrderLine(
                    organization=self.organization, order=saved, position=1, **values
                ).full_clean()
