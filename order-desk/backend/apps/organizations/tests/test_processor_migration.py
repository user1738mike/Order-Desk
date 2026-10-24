"""Existing memberships keep their roles; processor rollback cannot relabel data."""

from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from apps.accounts.models import User
from apps.orders.models import DraftOrder
from apps.organizations.models import Membership
from apps.organizations.services import create_organization


class ProcessorMigrationTests(TransactionTestCase):
    def test_previous_roles_and_draft_survive_upgrade_and_rollback_refuses_processor(
        self,
    ):
        executor = MigrationExecutor(connection)
        current = executor.loader.graph.leaf_nodes()
        previous = [
            ("orders", "0015_incoming_document_ownership"),
            ("customers", "0003_reference_write_receipts"),
            ("organizations", "0001_initial"),
        ]
        executor.migrate(previous)
        processor = None
        try:
            actor = User.objects.create_user(email="processor-upgrade@example.test")
            org = create_organization(actor=actor, name="Synthetic role upgrade")
            for role in ("reviewer", "viewer"):
                user = User.objects.create_user(email=role + "-upgrade@example.test")
                Membership.objects.create(user=user, organization=org, role=role)
            before = list(
                Membership.objects.order_by("id").values_list("id", "role", "is_active")
            )
            draft = DraftOrder.objects.create(
                organization=org,
                initiating_user=actor,
                customer_name="Keep requested buyer",
                customer_reference="00042",
                original_intake_text="Unchanged synthetic source text",
            )
            MigrationExecutor(connection).migrate(current)
            self.assertEqual(
                list(
                    Membership.objects.order_by("id").values_list(
                        "id", "role", "is_active"
                    )
                ),
                before,
            )
            draft.refresh_from_db()
            self.assertEqual(
                (
                    draft.customer_name,
                    draft.customer_reference,
                    draft.original_intake_text,
                ),
                ("Keep requested buyer", "00042", "Unchanged synthetic source text"),
            )
            user = User.objects.create_user(email="new-processor-upgrade@example.test")
            processor = Membership.objects.create(
                user=user, organization=org, role="processor"
            )
            with self.assertRaises(IntegrityError):
                MigrationExecutor(connection).migrate(previous)
            processor.refresh_from_db()
            self.assertEqual(processor.role, "processor")
        finally:
            if processor is not None:
                processor.delete()
            MigrationExecutor(connection).migrate(current)
