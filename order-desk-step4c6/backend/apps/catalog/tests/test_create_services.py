"""Creation authorization, database conflicts, and owned-scope rollback checks."""

from secrets import token_urlsafe
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.catalog.services import (
    CATALOG_CREATE_DENIED,
    CATALOG_SKU_CONFLICT,
    CatalogSKUConflict,
    create_catalog_item,
)
from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.transactions import TenantScopeError, tenant_scope


class CatalogCreateServiceTests(TransactionTestCase):
    def setUp(self) -> None:
        self.admin = User.objects.create_user(email="create-admin@example.test")
        self.operator = User.objects.create_user(
            email="create-operator@example.test", is_staff=True, is_superuser=True
        )
        self.a = Organization.objects.create(name="Synthetic creation A")
        self.b = Organization.objects.create(name="Synthetic creation B")
        self.membership = Membership.objects.create(
            user=self.admin, organization=self.a, role=MembershipRole.ADMIN
        )
        Membership.objects.create(
            user=self.admin, organization=self.b, role=MembershipRole.ADMIN
        )

    def create(self, data: object, **kwargs: object):
        return create_catalog_item(
            actor=self.admin, organization_id=self.a.pk, data=data, **kwargs
        )

    def context_and_mode(self) -> tuple:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                " NULLIF(current_setting('orderdesk.user_id', true), ''),"
                " current_setting('transaction_read_only'),"
                " current_setting('transaction_isolation')"
            )
            return cursor.fetchone()

    def assert_clean(self) -> None:
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        self.assertEqual(self.context_and_mode()[:2], (None, None))

    def assert_owned_write_scope(self) -> None:
        self.assertFalse(connection.get_autocommit())
        self.assertTrue(connection.in_atomic_block)
        self.assertEqual(
            self.context_and_mode(),
            (str(self.a.pk), str(self.admin.pk), "off", "read committed"),
        )

    def test_create_commits_model_defaults_and_returns_fully_loaded_scalars(self):
        item = self.create({"sku": " 000Ab/P-1.x "})
        self.assertIsInstance(item, CatalogItem)
        self.assertEqual(item.get_deferred_fields(), set())
        self.assertEqual(CatalogItem.objects.filter(pk=item.pk).count(), 1)
        self.assert_clean()
        with self.assertNumQueries(0):
            self.assertEqual(item.organization_id, self.a.pk)
            self.assertEqual(item.sku, "000Ab/P-1.x")
            self.assertEqual(item.description, "")
            self.assertTrue(item.is_active)
            self.assertIsNotNone(item.created_at)
            self.assertIsNotNone(item.updated_at)

    def test_data_and_materialization_callbacks_run_inside_owned_write_scope(self):
        events = []

        def data():
            self.assert_owned_write_scope()
            events.append("data")
            return {"sku": "CALLBACK", "description": " preserved ", "is_active": False}

        def materialize(item):
            self.assert_owned_write_scope()
            self.assertTrue(CatalogItem.objects.filter(pk=item.pk).exists())
            with self.assertNumQueries(0):
                result = CatalogItemSerializer(item).data
            events.append("materialize")
            return dict(result)

        result = self.create(data, materialize=materialize)
        self.assertEqual(events, ["data", "materialize"])
        self.assertEqual(result["organization_id"], str(self.a.pk))
        self.assertEqual(result["description"], " preserved ")
        self.assertFalse(result["is_active"])
        self.assertEqual(
            set(result),
            {
                "id",
                "organization_id",
                "sku",
                "description",
                "is_active",
                "created_at",
                "updated_at",
            },
        )
        self.assert_clean()

    def test_nonadmin_denial_precedes_payload_callbacks_and_catalogue_queries(self):
        statements = []

        def capture(execute, sql, params, many, context):
            statements.append(sql)
            return execute(sql, params, many, context)

        for role in (MembershipRole.VIEWER, MembershipRole.REVIEWER):
            Membership.objects.filter(pk=self.membership.pk).update(role=role)
            data = Mock(
                side_effect=AssertionError("Denied input must not be evaluated.")
            )
            statements.clear()

            with (
                self.subTest(role=role),
                connection.execute_wrapper(capture),
                self.assertRaises(PermissionDenied) as error,
            ):
                self.create(data)
            self.assertEqual(str(error.exception), CATALOG_CREATE_DENIED)
            data.assert_not_called()
            self.assertFalse(any("catalog_catalogitem" in sql for sql in statements))
            self.assert_clean()
        self.assertEqual(CatalogItem.objects.count(), 0)

    def test_fresh_committed_demotion_rejects_an_earlier_admin_context(self):
        with tenant_scope(user=self.admin, workspace_id=self.a.pk) as earlier:
            self.assertEqual(earlier.role, MembershipRole.ADMIN)
        Membership.objects.filter(pk=self.membership.pk).update(
            role=MembershipRole.VIEWER
        )
        data = Mock(return_value={"sku": "DEMOTED"})
        with self.assertRaises(PermissionDenied) as error:
            self.create(data)
        self.assertEqual(str(error.exception), CATALOG_CREATE_DENIED)
        data.assert_not_called()
        self.assertFalse(CatalogItem.objects.exists())
        self.assert_clean()

    def test_anonymous_operator_nonmember_and_unknown_workspace_never_parse_input(self):
        for actor, workspace_id, expected in (
            (AnonymousUser(), self.a.pk, "An active account is required."),
            (self.operator, self.a.pk, WORKSPACE_ACCESS_DENIED),
            (self.admin, uuid4(), WORKSPACE_ACCESS_DENIED),
        ):
            data = Mock(return_value={"sku": "DENIED"})
            with (
                self.subTest(actor=type(actor).__name__),
                self.assertRaises(PermissionDenied) as error,
            ):
                create_catalog_item(
                    actor=actor, organization_id=workspace_id, data=data
                )
            self.assertEqual(str(error.exception), expected)
            data.assert_not_called()
            self.assert_clean()
        self.assertFalse(CatalogItem.objects.exists())

    def test_stale_active_actor_revoked_membership_and_inactive_workspace_are_denied(
        self,
    ):
        for model, pk in (
            (User, self.admin.pk),
            (Membership, self.membership.pk),
            (Organization, self.a.pk),
        ):
            model.objects.filter(pk=pk).update(is_active=False)
            try:
                data = Mock(return_value={"sku": "INACTIVE"})
                with (
                    self.subTest(model=model.__name__),
                    self.assertRaises(PermissionDenied),
                ):
                    self.create(data)
                data.assert_not_called()
                self.assert_clean()
            finally:
                model.objects.filter(pk=pk).update(is_active=True)
        self.assertTrue(self.admin.is_active)
        self.assertFalse(CatalogItem.objects.exists())

    def test_invalid_payload_rolls_back_without_inserting_and_next_scope_succeeds(self):
        for data in (
            {},
            {"sku": " "},
            {"sku": 1},
            {"sku": "BAD", "description": False},
            {"sku": "BAD", "is_active": "true"},
            {"sku": "BAD", "organization_id": str(self.b.pk)},
            ["BAD"],
        ):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                self.create(data)
            self.assertFalse(CatalogItem.objects.exists())
            self.assert_clean()
        self.assertEqual(self.create({"sku": "RECOVERED"}).sku, "RECOVERED")
        self.assert_clean()

    def test_data_callback_failure_rolls_back_its_work_and_clears_context(self):
        def data():
            self.assert_owned_write_scope()
            Organization.objects.filter(pk=self.a.pk).update(name="Must roll back")
            raise ValueError("Synthetic parser failure")

        with self.assertRaisesMessage(ValueError, "Synthetic parser failure"):
            self.create(data)
        self.a.refresh_from_db()
        self.assertEqual(self.a.name, "Synthetic creation A")
        self.assertFalse(CatalogItem.objects.exists())
        self.assert_clean()

    def test_model_field_validation_failure_rolls_back_before_insert(self):
        with (
            patch.object(
                CatalogItem,
                "full_clean",
                side_effect=DjangoValidationError(
                    {"sku": "Synthetic field validation"}
                ),
            ) as full_clean,
            self.assertRaises(DjangoValidationError),
        ):
            self.create({"sku": "VALIDATION"})
        full_clean.assert_called_once_with(
            validate_unique=False, validate_constraints=False
        )
        self.assertFalse(CatalogItem.objects.exists())
        self.assert_clean()

    def test_duplicate_is_database_conflict_after_rollback_with_no_preflight_lookup(
        self,
    ):
        original = self.create({"sku": "DUPLICATE", "description": "Original"})
        statements = []

        def capture(execute, sql, params, many, context):
            statements.append(sql)
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(capture),
            self.assertRaises(CatalogSKUConflict) as error,
        ):
            self.create({"sku": " DUPLICATE ", "description": "Must roll back"})
        self.assertEqual(str(error.exception), CATALOG_SKU_CONFLICT)
        cause = error.exception.__cause__.__cause__
        self.assertEqual(cause.sqlstate, "23505")
        self.assertEqual(cause.diag.constraint_name, "catalog_org_sku_unique")
        self.assertFalse(
            any(
                "catalog_catalogitem" in sql
                and sql.lstrip().upper().startswith("SELECT")
                for sql in statements
            )
        )
        self.assertEqual(CatalogItem.objects.count(), 1)
        original.refresh_from_db()
        self.assertEqual(original.description, "Original")
        self.assert_clean()
        self.assertEqual(self.create({"sku": "AFTER-CONFLICT"}).sku, "AFTER-CONFLICT")
        self.assert_clean()

    def test_identical_stock_code_in_other_workspace_and_different_case_are_allowed(
        self,
    ):
        first = self.create({"sku": "Shared-001"})
        second = create_catalog_item(
            actor=self.admin, organization_id=self.b.pk, data={"sku": "Shared-001"}
        )
        different_case = self.create({"sku": "shared-001"})
        self.assertEqual(first.organization_id, self.a.pk)
        self.assertEqual(second.organization_id, self.b.pk)
        self.assertNotEqual(first.pk, second.pk)
        self.assertNotEqual(first.pk, different_case.pk)
        self.assertEqual(CatalogItem.objects.count(), 3)
        self.assert_clean()

    def test_serialization_failure_rolls_back_insert_and_keeps_connection_reusable(
        self,
    ):
        def materialize(item):
            self.assert_owned_write_scope()
            self.assertTrue(CatalogItem.objects.filter(pk=item.pk).exists())
            raise ValueError("Synthetic serialization failure")

        with self.assertRaisesMessage(ValueError, "Synthetic serialization failure"):
            self.create({"sku": "ROLLBACK"}, materialize=materialize)
        self.assertFalse(CatalogItem.objects.exists())
        self.assert_clean()
        self.assertEqual(self.create({"sku": "ROLLBACK"}).sku, "ROLLBACK")
        self.assert_clean()

    def test_other_unique_constraint_integrity_error_is_not_mapped_to_sku_conflict(
        self,
    ):
        def materialize(item):
            User.objects.create(email=self.admin.email)

        with self.assertRaises(IntegrityError) as error:
            self.create({"sku": "OTHER-UNIQUE"}, materialize=materialize)
        self.assertEqual(error.exception.__cause__.sqlstate, "23505")
        self.assertNotEqual(
            error.exception.__cause__.diag.constraint_name, "catalog_org_sku_unique"
        )
        self.assertFalse(CatalogItem.objects.exists())
        self.assert_clean()

    def test_check_constraint_integrity_error_is_not_mapped_to_sku_conflict(self):
        def materialize(item):
            CatalogItem.objects.filter(pk=item.pk).update(sku=" ")

        with self.assertRaises(IntegrityError) as error:
            self.create({"sku": "CHECK-FAILURE"}, materialize=materialize)
        self.assertEqual(error.exception.__cause__.sqlstate, "23514")
        self.assertEqual(
            error.exception.__cause__.diag.constraint_name, "catalog_sku_not_blank"
        )
        self.assertFalse(CatalogItem.objects.exists())
        self.assert_clean()

    def test_service_rejects_caller_owned_transactions_without_evaluating_input(self):
        data = Mock(return_value={"sku": "OUTER"})
        with transaction.atomic():
            Organization.objects.filter(pk=self.a.pk).update(name="Caller transaction")
            with self.assertRaises(TenantScopeError):
                self.create(data)
            self.assertEqual(
                Organization.objects.get(pk=self.a.pk).name, "Caller transaction"
            )
        data.assert_not_called()
        self.assertFalse(CatalogItem.objects.exists())
        self.assert_clean()

    def test_unbounded_model_text_accepts_long_values_through_database_creation(self):
        item = self.create({"sku": "A" * 1024, "description": "D" * 2048})
        item.refresh_from_db()
        self.assertEqual(len(item.sku), 1024)
        self.assertEqual(len(item.description), 2048)
        self.assert_clean()

    def test_unindexable_stock_code_is_safe_validation_after_rollback_and_reuse(self):
        sku = token_urlsafe(3750)
        self.assertEqual(len(sku), 5000)
        with self.assertRaises(DjangoValidationError) as error:
            self.create({"sku": sku})
        self.assertEqual(
            error.exception.message_dict,
            {"sku": ["This stock code is too large for the catalogue index."]},
        )
        cause = error.exception.__cause__.__cause__
        self.assertEqual(cause.sqlstate, "54000")
        self.assertEqual(cause.diag.constraint_name, "catalog_org_sku_unique")
        self.assertEqual(cause.diag.table_name, "catalog_catalogitem")
        self.assertFalse(CatalogItem.objects.exists())
        self.assert_clean()
        self.assertEqual(
            self.create({"sku": "AFTER-INDEX-FAILURE"}).sku, "AFTER-INDEX-FAILURE"
        )
        self.assert_clean()
