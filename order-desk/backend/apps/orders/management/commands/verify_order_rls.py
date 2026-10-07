"""Verify order policies using the existing direct-runtime, two-role harness."""

import unittest

from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections

from apps.catalog.management.commands.verify_catalog_rls import (
    Command as CatalogVerifierCommand,
)
from apps.catalog.tests.runtime_rls import OWNER_ALIAS
from apps.orders.tests.runtime_rls import RuntimeOrderRLSChecks

TABLE_PREFIXES = {
    "orders_purchaseorder": "order",
    "orders_purchaseorderline": "orderline",
    "orders_orderdocument": "orderdocument",
    "orders_orderdocumentreview": "orderreview",
}


class Command(CatalogVerifierCommand):
    help = "Verify order RLS as orderdesk_app, using only test_orderdesk."

    def _audit_runtime_boundary(self) -> None:
        # Retain the existing target, actual session identity, restricted-role,
        # and catalogue-policy audits. Do not substitute an owner impersonation.
        super()._audit_runtime_boundary()
        with connection.cursor() as cursor:
            for table, prefix in TABLE_PREFIXES.items():
                cursor.execute(
                    "SELECT pg_catalog.pg_get_userbyid(c.relowner), "
                    "c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_catalog.pg_class AS c "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = %s "
                    "AND c.relkind = 'r'",
                    [table],
                )
                if cursor.fetchone() != ("orderdesk_migrator", True, True):
                    raise CommandError(f"Incorrect owner or forced RLS for {table}.")
                for privilege in ("SELECT", "INSERT", "UPDATE"):
                    cursor.execute(
                        "SELECT pg_catalog.has_table_privilege(current_user, %s, %s)",
                        [f"public.{table}", privilege],
                    )
                    if cursor.fetchone()[0] is not True:
                        raise CommandError(f"Missing runtime {privilege} for {table}.")
                for privilege in (
                    "DELETE",
                    "TRUNCATE",
                    "REFERENCES",
                    "TRIGGER",
                    "MAINTAIN",
                ):
                    cursor.execute(
                        "SELECT pg_catalog.has_table_privilege(current_user, %s, %s)",
                        [f"public.{table}", privilege],
                    )
                    if cursor.fetchone()[0]:
                        raise CommandError(
                            f"Unexpected runtime {privilege} for {table}."
                        )
                cursor.execute(
                    "SELECT policyname, permissive, roles, cmd, qual, with_check "
                    "FROM pg_catalog.pg_policies WHERE schemaname = 'public' "
                    "AND tablename = %s",
                    [table],
                )
                policies = {row[0]: row[1:] for row in cursor.fetchall()}
                self._validate_policies(table, prefix, policies)
            self._audit_parent_constraints(cursor)
            self._audit_draft_boundary(cursor)
        self.stdout.write(
            "Order metadata verified: 4 tables, forced RLS, 20 policies, "
            "restricted grants, 3 composite parent foreign keys."
        )
        self.stdout.write(
            "Draft metadata verified: 2 tables, forced RLS, 10 policies, "
            "2 composite tenant foreign keys."
        )

    @staticmethod
    def _validate_policies(table: str, prefix: str, policies: dict) -> None:
        expected = {
            f"{prefix}_tenant_boundary": ("RESTRICTIVE", ["orderdesk_app"], "ALL"),
            f"{prefix}_member_read": ("PERMISSIVE", ["orderdesk_app"], "SELECT"),
            f"{prefix}_reviewer_insert": ("PERMISSIVE", ["orderdesk_app"], "INSERT"),
            f"{prefix}_reviewer_update": ("PERMISSIVE", ["orderdesk_app"], "UPDATE"),
            f"{prefix}_owner_maintenance": (
                "PERMISSIVE",
                ["orderdesk_migrator"],
                "ALL",
            ),
        }
        if policies.keys() != expected.keys():
            raise CommandError(f"Unexpected policy names/count for {table}.")
        for name, header in expected.items():
            if policies[name][:3] != header:
                raise CommandError(f"Unexpected policy command/role for {table}.")
        boundary = policies[f"{prefix}_tenant_boundary"]
        update = policies[f"{prefix}_reviewer_update"]
        insert = policies[f"{prefix}_reviewer_insert"]
        if (
            not boundary[3]
            or boundary[3] != boundary[4]
            or not update[3]
            or update[3] != update[4]
            or insert[3] is not None
            or insert[4] != update[4]
            or policies[f"{prefix}_member_read"][3:] != ("true", None)
            or policies[f"{prefix}_owner_maintenance"][3:] != ("true", "true")
        ):
            raise CommandError(f"Unexpected policy expressions for {table}.")

    @staticmethod
    def _audit_parent_constraints(cursor) -> None:
        cursor.execute(
            """
            SELECT c.conname, source.relname, c.convalidated,
                   ARRAY(SELECT a.attname FROM unnest(c.conkey)
                         WITH ORDINALITY AS key_column(attnum, sequence_no)
                         JOIN pg_catalog.pg_attribute AS a
                         ON a.attrelid = c.conrelid AND a.attnum = key_column.attnum
                         ORDER BY key_column.sequence_no),
                   target.relname,
                   ARRAY(SELECT a.attname FROM unnest(c.confkey)
                         WITH ORDINALITY AS key_column(attnum, sequence_no)
                         JOIN pg_catalog.pg_attribute AS a
                         ON a.attrelid = c.confrelid AND a.attnum = key_column.attnum
                         ORDER BY key_column.sequence_no)
            FROM pg_catalog.pg_constraint AS c
            JOIN pg_catalog.pg_class AS source ON source.oid = c.conrelid
            JOIN pg_catalog.pg_namespace AS source_ns
              ON source_ns.oid = source.relnamespace
            JOIN pg_catalog.pg_class AS target ON target.oid = c.confrelid
            JOIN pg_catalog.pg_namespace AS target_ns
              ON target_ns.oid = target.relnamespace
            WHERE c.contype = 'f' AND source_ns.nspname = 'public'
              AND target_ns.nspname = 'public' AND c.conname = ANY(%s)
            """,
            [
                [
                    "orderline_order_org_fk",
                    "orderdocument_order_org_fk",
                    "orderreview_document_org_fk",
                ]
            ],
        )
        constraints = {row[0]: row[1:] for row in cursor.fetchall()}
        expected = {
            "orderline_order_org_fk": (
                "orders_purchaseorderline",
                True,
                ["order_id", "organization_id"],
                "orders_purchaseorder",
                ["id", "organization_id"],
            ),
            "orderdocument_order_org_fk": (
                "orders_orderdocument",
                True,
                ["order_id", "organization_id"],
                "orders_purchaseorder",
                ["id", "organization_id"],
            ),
            "orderreview_document_org_fk": (
                "orders_orderdocumentreview",
                True,
                ["document_id", "organization_id"],
                "orders_orderdocument",
                ["id", "organization_id"],
            ),
        }
        if constraints != expected:
            raise CommandError("Order parent ownership constraints are incorrect.")

    @staticmethod
    def _audit_draft_boundary(cursor) -> None:
        for table, prefix, required_fragment in (
            ("orders_draftorder", "draftorder", "initiating_user_id"),
            ("orders_draftorderline", "draftline", "orders_draftorder"),
        ):
            cursor.execute(
                "SELECT pg_catalog.pg_get_userbyid(c.relowner), "
                "c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = 'public' "
                "AND c.relname = %s AND c.relkind = 'r'",
                [table],
            )
            if cursor.fetchone() != ("orderdesk_migrator", True, True):
                raise CommandError(f"Incorrect draft owner or forced RLS: {table}.")
            cursor.execute(
                "SELECT policyname, permissive, roles, cmd, qual, with_check "
                "FROM pg_catalog.pg_policies WHERE schemaname = 'public' "
                "AND tablename = %s",
                [table],
            )
            policies = {row[0]: row[1:] for row in cursor.fetchall()}
            expected = {
                f"{prefix}_tenant_boundary": ("RESTRICTIVE", ["orderdesk_app"], "ALL"),
                f"{prefix}_member_read": ("PERMISSIVE", ["orderdesk_app"], "SELECT"),
                f"{prefix}_writer_insert": ("PERMISSIVE", ["orderdesk_app"], "INSERT"),
                f"{prefix}_writer_update": ("PERMISSIVE", ["orderdesk_app"], "UPDATE"),
                f"{prefix}_owner_maintenance": (
                    "PERMISSIVE",
                    ["orderdesk_migrator"],
                    "ALL",
                ),
            }
            if policies.keys() != expected.keys():
                raise CommandError(f"Unexpected draft policy set: {table}.")
            for name, header in expected.items():
                if policies[name][:3] != header:
                    raise CommandError(f"Unexpected draft policy header: {name}.")
            tenant = policies[f"{prefix}_tenant_boundary"]
            insert = policies[f"{prefix}_writer_insert"]
            update = policies[f"{prefix}_writer_update"]
            if (
                not tenant[3]
                or tenant[3] != tenant[4]
                or "orderdesk.organization_id" not in tenant[3]
                or "orderdesk.user_id" not in tenant[3]
                or "is_active" not in tenant[3]
                or insert[3] is not None
                or not insert[4]
                or required_fragment not in insert[4]
                or "admin" not in insert[4]
                or "reviewer" not in insert[4]
                or not update[3]
                or update[3] != update[4]
                or policies[f"{prefix}_member_read"][3:] != ("true", None)
                or policies[f"{prefix}_owner_maintenance"][3:] != ("true", "true")
            ):
                raise CommandError(f"Unexpected draft policy expressions: {table}.")

        for name, source, target, columns in (
            (
                "draftline_order_org_fk",
                "orders_draftorderline",
                "orders_draftorder",
                ["order_id", "organization_id"],
            ),
            (
                "draftline_catalogue_org_fk",
                "orders_draftorderline",
                "catalog_catalogitem",
                ["catalogue_item_id", "organization_id"],
            ),
        ):
            cursor.execute(
                "SELECT c.convalidated, c.condeferrable, source.relname, "
                "target.relname, ARRAY(SELECT a.attname FROM unnest(c.conkey) "
                "WITH ORDINALITY AS key_column(attnum, sequence_no) "
                "JOIN pg_catalog.pg_attribute a ON a.attrelid = c.conrelid "
                "AND a.attnum = key_column.attnum ORDER BY key_column.sequence_no), "
                "ARRAY(SELECT a.attname FROM unnest(c.confkey) "
                "WITH ORDINALITY AS key_column(attnum, sequence_no) "
                "JOIN pg_catalog.pg_attribute a ON a.attrelid = c.confrelid "
                "AND a.attnum = key_column.attnum ORDER BY key_column.sequence_no) "
                "FROM pg_catalog.pg_constraint c "
                "JOIN pg_catalog.pg_class source ON source.oid = c.conrelid "
                "JOIN pg_catalog.pg_class target ON target.oid = c.confrelid "
                "WHERE c.conname = %s AND c.contype = 'f'",
                [name],
            )
            if cursor.fetchone() != (
                True,
                True,
                source,
                target,
                columns,
                ["id", "organization_id"],
            ):
                raise CommandError(f"Draft tenant reference is incorrect: {name}.")

    def handle(self, *args, **options) -> None:
        self._validate_local_target()
        self._owner_registered = False
        try:
            self._audit_runtime_boundary()
            self._register_fixture_owner()
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(
                RuntimeOrderRLSChecks
            )
            expected_tests = suite.countTestCases()
            result = unittest.TextTestRunner(stream=self.stdout, verbosity=2).run(suite)
            if (
                expected_tests == 0
                or result.testsRun != expected_tests
                or result.skipped
                or not result.wasSuccessful()
            ):
                raise CommandError("Runtime order RLS verification failed.")
            self.stdout.write(
                self.style.SUCCESS("Runtime order RLS verification passed.")
            )
        except DatabaseError as error:
            raise CommandError(
                "Order RLS verification could not access the configured database."
            ) from error
        finally:
            connection.close()
            if self._owner_registered:
                connections[OWNER_ALIAS].close()
                del connections[OWNER_ALIAS]
                connections.databases.pop(OWNER_ALIAS)
