"""Native service ownership, scoped locks, partial saves, and rollback."""

from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.catalog.services import CATALOG_UPDATE_DENIED, update_catalog_item
from apps.catalog.tests.test_update_api import CatalogUpdateTestCase
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.transactions import TenantScopeError


class CatalogUpdateServiceTests(CatalogUpdateTestCase):
    def mutate(self, data, **kwargs):
        return update_catalog_item(
            actor=self.admin,
            organization_id=self.a.pk,
            item_id=kwargs.pop("item_id", self.item.pk),
            data=data,
            **kwargs,
        )

    def test_callbacks_and_locked_lookup_run_in_owned_write_scope(self):
        queries = []

        def observe(execute, sql, params, many, context):
            queries.append(sql)
            return execute(sql, params, many, context)

        def data():
            self.assertTrue(connection.in_atomic_block)
            locked = [sql for sql in queries if "FOR UPDATE" in sql]
            self.assertIn("organizations_organization", locked[0])
            self.assertIn("catalog_catalogitem", locked[1])
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('transaction_read_only'), "
                    "current_setting('orderdesk.organization_id')"
                )
                self.assertEqual(cursor.fetchone(), ("off", str(self.a.pk)))
            return {"description": "Changed"}

        def materialize(item):
            self.assertTrue(connection.in_atomic_block)
            with self.assertNumQueries(0):
                return dict(CatalogItemSerializer(item).data)

        with connection.execute_wrapper(observe):
            result = self.mutate(data, materialize=materialize)
        self.assertEqual(result["description"], "Changed")
        self.assert_clean()

    def test_noop_never_saves_and_real_change_saves_only_mutable_fields(self):
        with patch.object(
            CatalogItem, "save", side_effect=AssertionError("No-op save")
        ):
            result = self.mutate({"description": "Original"})
        self.assertEqual(result.updated_at, self.item.updated_at)
        queries = []

        def observe(execute, sql, params, many, context):
            if sql.startswith("UPDATE") and "catalog_catalogitem" in sql:
                queries.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(observe):
            result = self.mutate({"is_active": False})
        self.assertEqual(len(queries), 1)
        self.assertIn('"is_active" =', queries[0])
        self.assertIn('"updated_at" =', queries[0])
        for field in ("sku", "organization_id", "created_at", "description"):
            self.assertNotIn(f'"{field}" =', queries[0])
        self.assertFalse(result.is_active)
        self.assert_clean()

    def test_fresh_demotion_denies_before_catalogue_lookup_and_data(self):
        Membership.objects.filter(pk=self.admin_membership.pk).update(
            role=MembershipRole.VIEWER
        )
        data = Mock(return_value={"description": "changed"})
        queries = []

        def observe(execute, sql, params, many, context):
            queries.append(sql)
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(observe),
            self.assertRaisesMessage(PermissionDenied, CATALOG_UPDATE_DENIED),
        ):
            self.mutate(data)
        data.assert_not_called()
        self.assertFalse(any("catalog_catalogitem" in sql for sql in queries))
        self.assert_clean()

    def test_missing_foreign_item_never_parses_input(self):
        for item_id in (uuid4(), self.other.pk):
            data = Mock()
            with self.assertRaises(Http404):
                self.mutate(data, item_id=item_id)
            data.assert_not_called()
            self.assert_clean()

    def test_invalid_input_and_callback_failures_leave_item_unchanged(self):
        before = self.state()
        with self.assertRaises(ValidationError):
            self.mutate({"description": "valid", "sku": "forged"})
        with self.assertRaisesMessage(ValueError, "Synthetic data error"):
            self.mutate(Mock(side_effect=ValueError("Synthetic data error")))
        with self.assertRaisesMessage(ValueError, "Synthetic output error"):
            self.mutate(
                {"description": "Must roll back", "is_active": False},
                materialize=Mock(side_effect=ValueError("Synthetic output error")),
            )
        self.assertEqual(self.state(), before)
        self.assert_clean()
        self.assertEqual(
            self.mutate({"description": "Recovered"}).description, "Recovered"
        )

    def test_unexpected_database_failure_propagates_after_rollback(self):
        before = self.state()

        def materialize(item):
            User.objects.create(email=self.admin.email)

        with self.assertRaises(IntegrityError) as error:
            self.mutate({"description": "Must roll back"}, materialize=materialize)
        self.assertEqual(error.exception.__cause__.sqlstate, "23505")
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_service_refuses_existing_transaction_without_data_evaluation(self):
        data = Mock()
        with transaction.atomic(), self.assertRaises(TenantScopeError):
            self.mutate(data)
        data.assert_not_called()
        self.assert_clean()
