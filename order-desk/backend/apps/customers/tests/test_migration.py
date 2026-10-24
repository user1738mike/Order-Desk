"""Previous-schema customer upgrade preserves source bytes and business records."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.organizations.services import create_organization


class CustomerMigrationTests(TransactionTestCase):
    def test_customer_install_preserves_unconfirmed_legacy_and_incoming_records(self):
        executor = MigrationExecutor(connection)
        current = executor.loader.graph.leaf_nodes()
        executor.migrate([("customers", None)])
        try:
            state = (
                MigrationExecutor(connection)
                .loader.project_state([("orders", "0015_incoming_document_ownership")])
                .apps
            )
            user = User.objects.create_user(email="customer-upgrade@example.test")
            org = create_organization(actor=user, name="Synthetic customer upgrade")
            draft = state.get_model("orders", "DraftOrder").objects.create(
                organization_id=org.pk,
                initiating_user_id=user.pk,
                customer_name="Unconfirmed requested buyer",
                customer_reference="00042",
                original_intake_text="Preserve the exact requested text",
            )
            order = state.get_model("orders", "PurchaseOrder").objects.create(
                organization_id=org.pk,
                created_by_id=user.pk,
                customer_name="Historical buyer",
                purchase_order_number="CUSTOMER-UPGRADE-00001",
            )
            line = state.get_model("orders", "PurchaseOrderLine").objects.create(
                organization_id=org.pk,
                order_id=order.pk,
                line_number=1,
                sku="0001.Mixed-Case",
                quantity="1.2500",
                unit="case",
            )
            raw = b"sku,quantity,unit\n0001.Mixed-Case,1.250,case\n"
            digest = hashlib.sha256(raw).hexdigest()
            intake_key, link_key = uuid4(), uuid4()
            key = "intake/" + uuid4().hex
            with TemporaryDirectory() as directory:
                path = Path(directory) / key
                path.parent.mkdir()
                path.write_bytes(raw)
                source = state.get_model("orders", "OrderDocument").objects.create(
                    organization_id=org.pk,
                    uploaded_by_id=user.pk,
                    file=key,
                    source_sha256=digest,
                    size_bytes=len(raw),
                    original_name="original.csv",
                    content_type="text/csv",
                    intake_key=intake_key,
                )
                source.draft_id = draft.pk
                source.link_key = link_key
                source.link_hash = "a" * 64
                source.linked_by_id = user.pk
                source.linked_at = timezone.now()
                source.save()
                job = state.get_model("orders", "DocumentExtractionJob").objects.create(
                    organization_id=org.pk,
                    document_id=source.pk,
                    requested_by_id=user.pk,
                    source_sha256=digest,
                )
                MigrationExecutor(connection).migrate(current)
                from apps.customers.models import (
                    CustomerAccount,
                    DraftCustomerDecision,
                    OrderCustomerSnapshot,
                )
                from apps.orders.models import (
                    DocumentExtractionJob,
                    DraftOrder,
                    OrderDocument,
                    PurchaseOrder,
                    PurchaseOrderLine,
                )

                retained = OrderDocument.objects.get(pk=source.pk)
                self.assertEqual(
                    (retained.draft_id, retained.order_id, retained.intake_key),
                    (draft.pk, None, intake_key),
                )
                self.assertEqual(
                    (retained.file.name, retained.source_sha256, retained.link_key),
                    (key, digest, link_key),
                )
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(
                    DocumentExtractionJob.objects.get(pk=job.pk).status, "queued"
                )
                retained_draft = DraftOrder.objects.get(pk=draft.pk)
                self.assertEqual(
                    (
                        retained_draft.customer_name,
                        retained_draft.customer_reference,
                        retained_draft.original_intake_text,
                        retained_draft.status,
                    ),
                    (
                        "Unconfirmed requested buyer",
                        "00042",
                        "Preserve the exact requested text",
                        "draft",
                    ),
                )
                self.assertEqual(
                    PurchaseOrder.objects.get(pk=order.pk).customer_name,
                    "Historical buyer",
                )
                retained_line = PurchaseOrderLine.objects.get(pk=line.pk)
                self.assertEqual(
                    (
                        retained_line.sku,
                        str(retained_line.quantity),
                        retained_line.unit,
                    ),
                    ("0001.Mixed-Case", "1.2500", "case"),
                )
                for model in (
                    CustomerAccount,
                    DraftCustomerDecision,
                    OrderCustomerSnapshot,
                ):
                    self.assertFalse(model.objects.exists())
        finally:
            MigrationExecutor(connection).migrate(current)
