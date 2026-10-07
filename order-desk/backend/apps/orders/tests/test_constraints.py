"""Native PostgreSQL constraints, including writes that bypass model validation."""

from decimal import Decimal
from uuid import uuid4

from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.models import DraftOrder
from apps.organizations.services import create_organization


class DraftOrderConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(email="draft-constraints@example.test")
        cls.a = create_organization(actor=cls.user, name="Draft tenant A")
        cls.b = create_organization(actor=cls.user, name="Draft tenant B")
        cls.order_a = DraftOrder.objects.create(
            organization=cls.a, initiating_user=cls.user
        )
        cls.order_b = DraftOrder.objects.create(
            organization=cls.b, initiating_user=cls.user
        )
        cls.item_a = CatalogItem.objects.create(organization=cls.a, sku="A-1")
        cls.item_b = CatalogItem.objects.create(organization=cls.b, sku="B-1")

    def insert_line(
        self,
        *,
        organization_id=None,
        order_id=None,
        position=1,
        requested_sku="SKU",
        requested_description="",
        quantity=None,
        catalogue_item_id=None,
        catalogue_sku_snapshot="",
        catalogue_description_snapshot="",
    ) -> None:
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO public.orders_draftorderline "
                "(id, organization_id, order_id, position, requested_sku, "
                "requested_description, quantity, unit, catalogue_item_id, "
                "catalogue_sku_snapshot, catalogue_description_snapshot, "
                "created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, '', %s, %s, %s, %s, %s)",
                [
                    uuid4(),
                    organization_id or self.a.pk,
                    order_id or self.order_a.pk,
                    position,
                    requested_sku,
                    requested_description,
                    quantity,
                    catalogue_item_id,
                    catalogue_sku_snapshot,
                    catalogue_description_snapshot,
                    now,
                    now,
                ],
            )

    def test_direct_sql_requires_line_identity(self) -> None:
        for sku, description in (("", ""), ("   ", "\t")):
            with self.subTest(sku=sku), self.assertRaises(DatabaseError):
                with transaction.atomic():
                    self.insert_line(
                        requested_sku=sku, requested_description=description
                    )

    def test_direct_sql_quantity_bounds_exclude_nan(self) -> None:
        for quantity in (
            Decimal("0"),
            Decimal("-0.001"),
            Decimal("1000000000"),
            Decimal("NaN"),
        ):
            with self.subTest(quantity=quantity), self.assertRaises(DatabaseError):
                with transaction.atomic():
                    self.insert_line(quantity=quantity)
        self.insert_line(quantity=Decimal("0.001"))
        self.insert_line(position=2, quantity=Decimal("999999999.999"))

    def test_position_is_positive_and_unique_within_parent(self) -> None:
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.insert_line(position=0)
        self.insert_line(position=3)
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.insert_line(position=3)
        self.insert_line(position=5)

    def test_catalogue_link_needs_nonblank_snapshot(self) -> None:
        for snapshot in ("", "  "):
            with self.subTest(snapshot=snapshot), self.assertRaises(DatabaseError):
                with transaction.atomic():
                    self.insert_line(
                        catalogue_item_id=self.item_a.pk,
                        catalogue_sku_snapshot=snapshot,
                    )
        self.insert_line(
            catalogue_item_id=self.item_a.pk,
            catalogue_sku_snapshot=self.item_a.sku,
        )

    def test_composite_foreign_keys_reject_both_cross_tenant_references(self) -> None:
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.insert_line(order_id=self.order_b.pk)
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.insert_line(
                catalogue_item_id=self.item_b.pk,
                catalogue_sku_snapshot=self.item_b.sku,
            )

    def test_direct_write_rejects_unsupported_header_state(self) -> None:
        for values in ({"status": "approved"}, {"source_type": "webhook"}):
            with self.subTest(values=values), self.assertRaises(DatabaseError):
                with transaction.atomic():
                    DraftOrder.objects.create(
                        organization=self.a, initiating_user=self.user, **values
                    )

    def test_original_intake_text_is_bounded_in_database(self) -> None:
        with self.assertRaises(DatabaseError), transaction.atomic():
            DraftOrder.objects.create(
                organization=self.a,
                initiating_user=self.user,
                original_intake_text="x" * 10001,
            )
