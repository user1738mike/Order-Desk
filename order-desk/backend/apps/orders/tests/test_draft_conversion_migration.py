"""Upgrade from the actual previous schema preserves unrelated legacy orders."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from apps.accounts.models import User
from apps.orders.models import PurchaseOrder, PurchaseOrderLine
from apps.organizations.services import create_organization


class DraftConversionMigrationTests(TransactionTestCase):
    def test_private_order_owned_source_and_queued_job_survive_incoming_upgrade(self):
        previous = [("orders", "0014_export_boundary")]
        executor = MigrationExecutor(connection)
        current = executor.loader.graph.leaf_nodes()
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            user = User.objects.create_user(email="private-upgrade@example.test")
            org = create_organization(actor=user, name="Synthetic private upgrade")
            order = apps.get_model("orders", "PurchaseOrder").objects.create(
                organization_id=org.pk,
                created_by_id=user.pk,
                customer_name="Historical buyer",
                purchase_order_number="PRIVATE-UPGRADE",
            )
            raw = b"sku,quantity\n00042,1.250\n"
            digest = hashlib.sha256(raw).hexdigest()
            key = "intake/" + "a" * 32
            with TemporaryDirectory() as directory:
                source = Path(directory) / key
                source.parent.mkdir()
                source.write_bytes(raw)
                document = apps.get_model("orders", "OrderDocument").objects.create(
                    organization_id=org.pk,
                    order_id=order.pk,
                    uploaded_by_id=user.pk,
                    file=key,
                    source_sha256=digest,
                    size_bytes=len(raw),
                    original_name="original.csv",
                    content_type="text/csv",
                )
                job = apps.get_model("orders", "DocumentExtractionJob").objects.create(
                    organization_id=org.pk,
                    document_id=document.pk,
                    requested_by_id=user.pk,
                    source_sha256=digest,
                )
                MigrationExecutor(connection).migrate(current)
                from apps.orders.models import DocumentExtractionJob, OrderDocument

                upgraded = OrderDocument.objects.get(pk=document.pk)
                self.assertEqual(
                    (upgraded.organization_id, upgraded.order_id), (org.pk, order.pk)
                )
                self.assertIsNone(upgraded.draft_id)
                self.assertIsNone(upgraded.intake_key)
                self.assertEqual(
                    (upgraded.file.name, upgraded.source_sha256), (key, digest)
                )
                self.assertEqual(source.read_bytes(), raw)
                retained = DocumentExtractionJob.objects.get(pk=job.pk)
                self.assertEqual(
                    (retained.document_id, retained.source_sha256, retained.status),
                    (document.pk, digest, "queued"),
                )
        finally:
            MigrationExecutor(connection).migrate(current)

    def test_legacy_document_upgrade_preserves_ownership_bytes_and_review(self):
        previous = [("orders", "0008_draft_conversion")]
        executor = MigrationExecutor(connection)
        current = executor.loader.graph.leaf_nodes()
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            user = User.objects.create_user(email="legacy-document@example.test")
            org = create_organization(actor=user, name="Synthetic document upgrade")
            order = apps.get_model("orders", "PurchaseOrder").objects.create(
                organization_id=org.pk,
                created_by_id=user.pk,
                customer_name="Legacy buyer",
                purchase_order_number="LEGACY-DOC-001",
            )
            with TemporaryDirectory() as directory:
                key = "orders/source_documents/legacy-original.pdf"
                original = b"%PDF-1.7\nSynthetic historical source\n%%EOF\n"
                source = Path(directory) / key
                source.parent.mkdir(parents=True)
                source.write_bytes(original)
                document = apps.get_model("orders", "OrderDocument").objects.create(
                    organization_id=org.pk,
                    order_id=order.pk,
                    uploaded_by_id=user.pk,
                    file=key,
                    original_name="legacy-original.pdf",
                    content_type="application/pdf",
                    size_bytes=len(original),
                )
                review = apps.get_model("orders", "OrderDocumentReview").objects.create(
                    organization_id=org.pk,
                    document_id=document.pk,
                    created_by_id=user.pk,
                )
                MigrationExecutor(connection).migrate(current)
                from apps.orders.models import OrderDocument, OrderDocumentReview

                upgraded = OrderDocument.objects.get(pk=document.pk)
                self.assertEqual(
                    (upgraded.organization_id, upgraded.order_id), (org.pk, order.pk)
                )
                self.assertEqual(upgraded.file.name, key)
                self.assertEqual(upgraded.source_sha256, "")
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(
                    OrderDocumentReview.objects.get(pk=review.pk).document_id,
                    document.pk,
                )
        finally:
            MigrationExecutor(connection).migrate(current)

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
