"""Upgrade from the actual previous schema preserves unrelated legacy orders."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from apps.accounts.models import User
from apps.orders.models import PurchaseOrder, PurchaseOrderLine
from apps.organizations.services import create_organization


class DraftConversionMigrationTests(TransactionTestCase):
    def test_previous_schema_upgrade_preserves_legacy_data(self):
        previous = [("orders", "0007_draft_order_boundary")]
        target = [("orders", "0008_draft_conversion")]
        executor = MigrationExecutor(connection)
        # Restore the current schema after exercising the historical upgrade;
        # otherwise later tests run against a schema missing newer columns.
        current = executor.loader.graph.leaf_nodes()
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            user = User.objects.create_user(email="legacy-conversion@example.test")
            org = create_organization(actor=user, name="Legacy synthetic upgrade")
            order = apps.get_model("orders", "PurchaseOrder").objects.create(
                organization_id=org.pk,
                created_by_id=user.pk,
                customer_name="Legacy buyer",
                purchase_order_number="LEGACY-1",
            )
            line = apps.get_model("orders", "PurchaseOrderLine").objects.create(
                order_id=order.pk,
                organization_id=org.pk,
                line_number=1,
                sku="0001",
                quantity="1.125",
                unit="ea",
            )
            MigrationExecutor(connection).migrate(target)
            upgraded = PurchaseOrder.objects.get(pk=order.pk)
            self.assertIsNone(upgraded.source_draft_id)
            self.assertEqual(upgraded.customer_name, "Legacy buyer")
            self.assertEqual(upgraded.purchase_order_number, "LEGACY-1")
            copied = PurchaseOrderLine.objects.get(pk=line.pk)
            self.assertEqual(
                (copied.sku, str(copied.quantity), copied.unit),
                ("0001", "1.1250", "ea"),
            )
        finally:
            MigrationExecutor(connection).migrate(current)
