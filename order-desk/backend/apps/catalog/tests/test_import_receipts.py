"""Native receipt constraints and real commit boundaries under the test owner."""

from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import (
    CONTRACT_IDENTIFIER,
    MAX_RECEIPT_PAYLOAD_BYTES,
    CatalogImportReceipt,
    CatalogItem,
)
from apps.organizations.services import create_organization


class CatalogImportReceiptTests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.actor = User.objects.create_user(email="receipt-owner@example.test")
        self.a = create_organization(actor=self.actor, name="Receipt distributor A")
        self.b = create_organization(actor=self.actor, name="Receipt distributor B")
        self.key = uuid4()

    def values(self, **overrides):
        return {
            "organization": self.a,
            "initiating_user": self.actor,
            "idempotency_key": self.key,
            "request_fingerprint": "a" * 64,
            **overrides,
        }

    def completed(self, **overrides):
        with transaction.atomic():
            receipt = CatalogImportReceipt.objects.create(**self.values(**overrides))
            receipt.state = CatalogImportReceipt.State.COMPLETED
            receipt.response_payload = {
                "import_id": str(receipt.pk),
                "organization_id": str(receipt.organization_id),
                "mode": "create_only",
                "created_count": 1,
                "items": [],
                "items_truncated": True,
            }
            receipt.completed_at = timezone.now()
            receipt.save(update_fields=["state", "response_payload", "completed_at"])
        return receipt

    def assert_constraint(self, name, action):
        with self.assertRaises(IntegrityError) as error:
            with transaction.atomic():
                action()
        self.assertEqual(error.exception.__cause__.sqlstate, "23514")
        self.assertEqual(error.exception.__cause__.diag.constraint_name, name)
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)

    def test_defaults_identity_timestamp_and_completion_survive_commit(self):
        with transaction.atomic():
            receipt = CatalogImportReceipt.objects.create(**self.values())
            self.assertIsInstance(receipt.pk, UUID)
            self.assertEqual(receipt.mode, "create_only")
            self.assertEqual(receipt.contract_identifier, CONTRACT_IDENTIFIER)
            self.assertEqual(receipt.state, CatalogImportReceipt.State.PROCESSING)
            self.assertIsNone(receipt.response_payload)
            self.assertIsNone(receipt.completed_at)
            self.assertIsNotNone(receipt.created_at.utcoffset())
            payload = {"import_id": str(receipt.pk), "items": []}
            CatalogImportReceipt.objects.filter(pk=receipt.pk).update(
                state=CatalogImportReceipt.State.COMPLETED,
                response_payload=payload,
                completed_at=timezone.now(),
            )
        receipt.refresh_from_db()
        self.assertEqual(receipt.response_payload, payload)
        self.assertEqual(receipt.initiating_user_id, self.actor.pk)
        self.assertGreaterEqual(receipt.completed_at, receipt.created_at)

    def test_organization_scoped_key_uniqueness_and_cross_workspace_reuse(self):
        first = self.completed()
        other = self.completed(organization=self.b)
        self.assertNotEqual(first.pk, other.pk)
        with self.assertRaises(IntegrityError) as error:
            self.completed()
        self.assertEqual(error.exception.__cause__.sqlstate, "23505")
        self.assertEqual(
            error.exception.__cause__.diag.constraint_name,
            "catalog_import_org_key_unique",
        )
        self.assertEqual(CatalogImportReceipt.objects.count(), 2)

    def test_unfinished_receipt_cannot_commit_and_key_can_be_reused(self):
        self.assert_constraint(
            "catalog_import_completed_at_commit",
            lambda: CatalogImportReceipt.objects.create(**self.values()),
        )
        self.assertEqual(CatalogImportReceipt.objects.count(), 0)
        receipt = self.completed()
        self.assertEqual(receipt.idempotency_key, self.key)

    def test_deferred_failure_rolls_back_catalogue_items_with_the_receipt(self):
        def incomplete_import():
            CatalogItem.objects.create(organization=self.a, sku="ROLLED-BACK-ITEM")
            CatalogImportReceipt.objects.create(**self.values())

        self.assert_constraint("catalog_import_completed_at_commit", incomplete_import)
        self.assertEqual(CatalogImportReceipt.objects.count(), 0)
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_completed_insert_and_update_events_check_final_state(self):
        receipt = self.completed()
        self.assertEqual(receipt.state, CatalogImportReceipt.State.COMPLETED)
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)

    def test_explicit_rollback_does_not_consume_key(self):
        with self.assertRaisesMessage(ValueError, "Abort synthetic import"):
            with transaction.atomic():
                CatalogImportReceipt.objects.create(**self.values())
                raise ValueError("Abort synthetic import")
        self.assertEqual(CatalogImportReceipt.objects.count(), 0)
        self.completed()
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)

    def test_fixed_mode_contract_and_sha256_format_have_database_checks(self):
        for field, value, constraint in (
            ("mode", "upsert", "catalog_import_create_only_mode"),
            ("contract_identifier", "other-v1", "catalog_import_contract_identifier"),
            ("request_fingerprint", "A" * 64, "catalog_import_fingerprint_sha256"),
            ("request_fingerprint", "a" * 63, "catalog_import_fingerprint_sha256"),
        ):
            with self.subTest(field=field, value=value):
                self.assert_constraint(
                    constraint,
                    lambda field=field, value=value: (
                        CatalogImportReceipt.objects.create(
                            **self.values(**{field: value})
                        )
                    ),
                )
        self.assertEqual(CatalogImportReceipt.objects.count(), 0)

    def test_state_requires_the_matching_timestamp_and_response_shape(self):
        for values in (
            {"state": "unknown"},
            {"state": "completed"},
            {"state": "processing", "response_payload": {}},
            {"state": "processing", "completed_at": timezone.now()},
            {"state": "completed", "response_payload": {}},
        ):
            with self.subTest(values=values):
                self.assert_constraint(
                    "catalog_import_completion_shape",
                    lambda values=values: CatalogImportReceipt.objects.create(
                        **self.values(**values)
                    ),
                )

    def test_response_must_be_json_object(self):
        receipt = self.completed()
        for payload in ([], "text", False, 1):
            with self.subTest(payload=payload):
                self.assert_constraint(
                    "catalog_import_response_object",
                    lambda payload=payload: CatalogImportReceipt.objects.filter(
                        pk=receipt.pk
                    ).update(response_payload=payload),
                )
        receipt.refresh_from_db()
        self.assertIsInstance(receipt.response_payload, dict)

    def test_successful_response_has_database_byte_limit(self):
        receipt = self.completed()
        self.assert_constraint(
            "catalog_import_response_size",
            lambda: CatalogImportReceipt.objects.filter(pk=receipt.pk).update(
                response_payload={"preview": "x" * MAX_RECEIPT_PAYLOAD_BYTES}
            ),
        )
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)

    def test_completion_timestamp_cannot_precede_creation(self):
        receipt = self.completed()
        self.assert_constraint(
            "catalog_import_completion_time",
            lambda: CatalogImportReceipt.objects.filter(pk=receipt.pk).update(
                completed_at=receipt.created_at - timedelta(seconds=1)
            ),
        )

    def test_fingerprint_model_validation_rejects_invalid_values(self):
        for value in ("", "not-a-hash", "A" * 64, "a" * 63):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CatalogImportReceipt._meta.get_field("request_fingerprint").clean(
                    value, None
                )

    def test_receipt_protects_workspace_and_original_user_identity(self):
        self.completed()
        self.a.memberships.all().delete()
        with self.assertRaises(ProtectedError) as organization_error:
            self.a.delete()
        self.assertTrue(
            any(
                isinstance(row, CatalogImportReceipt)
                for row in organization_error.exception.protected_objects
            )
        )
        with self.assertRaises(ProtectedError) as user_error:
            self.actor.delete()
        self.assertTrue(
            any(
                isinstance(row, CatalogImportReceipt)
                for row in user_error.exception.protected_objects
            )
        )


class ReceiptRuntimeStartupGuardTests(SimpleTestCase):
    def test_unsafe_receipt_grants_prevent_runtime_startup(self):
        cursor = MagicMock()
        cursor.__enter__.return_value.fetchone.return_value = (False,) * 7 + (True,)
        with (
            patch(
                "apps.health.management.commands.check_runtime_role.connection"
            ) as database,
            self.assertRaises(CommandError),
        ):
            database.vendor = "postgresql"
            database.cursor.return_value = cursor
            call_command("check_runtime_role", verbosity=0)
