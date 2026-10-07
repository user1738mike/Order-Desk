"""Local-only verification with runtime reads/writes and separate owner fixtures."""

import os
import unittest
from copy import deepcopy

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, connections

from apps.catalog.tests.runtime_rls import OWNER_ALIAS, RuntimeCatalogRLSChecks


class Command(BaseCommand):
    help = "Verify catalogue RLS as orderdesk_app, using only test_orderdesk."
    # Validate the target before any check that could access application tables.
    requires_system_checks = []

    def _validate_local_target(self) -> None:
        if not settings.DEBUG:
            raise CommandError("Catalogue RLS verification is local-development only.")
        if connection.vendor != "postgresql":
            raise CommandError("Catalogue RLS verification requires PostgreSQL.")
        if connection.settings_dict["NAME"] != "test_orderdesk":
            raise CommandError("Refusing to populate anything except test_orderdesk.")
        if connection.in_atomic_block or not connection.get_autocommit():
            raise CommandError("Run the verifier outside an existing transaction.")

    def _audit_runtime_boundary(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, session_user")
            identity = cursor.fetchone()
        if identity != ("test_orderdesk", "orderdesk_app", "orderdesk_app"):
            raise CommandError("Connect directly as orderdesk_app to test_orderdesk.")
        call_command("check_runtime_role", stdout=self.stdout)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolinherit, rolreplication FROM pg_catalog.pg_roles "
                "WHERE rolname = current_user"
            )
            if any(cursor.fetchone()):
                raise CommandError("Unexpected runtime role inheritance/replication.")
            cursor.execute(
                """
                SELECT pg_catalog.pg_get_userbyid(c.relowner),
                       c.relrowsecurity, c.relforcerowsecurity
                FROM pg_catalog.pg_class AS c
                JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'catalog_catalogitem'
                      AND c.relkind = 'r'
                """
            )
            if cursor.fetchone() != ("orderdesk_migrator", True, True):
                raise CommandError("Catalogue owner or ENABLE/FORCE RLS is incorrect.")
            for privilege in ("SELECT", "INSERT", "UPDATE"):
                cursor.execute(
                    "SELECT pg_catalog.has_table_privilege("
                    "current_user, 'public.catalog_catalogitem', %s)",
                    [privilege],
                )
                if cursor.fetchone()[0] is not True:
                    raise CommandError("A required runtime catalogue grant is missing.")
            for privilege in (
                "DELETE",
                "TRUNCATE",
                "REFERENCES",
                "TRIGGER",
                "MAINTAIN",
            ):
                cursor.execute(
                    "SELECT pg_catalog.has_table_privilege("
                    "current_user, 'public.catalog_catalogitem', %s)",
                    [privilege],
                )
                if cursor.fetchone()[0]:
                    raise CommandError("An unexpected runtime catalogue grant exists.")
            cursor.execute(
                "SELECT policyname, permissive, roles, cmd, qual, with_check "
                "FROM pg_catalog.pg_policies WHERE schemaname = 'public' "
                "AND tablename = 'catalog_catalogitem'"
            )
            policies = {row[0]: row[1:] for row in cursor.fetchall()}

        expected = {
            "catalog_tenant_boundary": ("RESTRICTIVE", ["orderdesk_app"], "ALL"),
            "catalog_member_read": ("PERMISSIVE", ["orderdesk_app"], "SELECT"),
            "catalog_admin_insert": ("PERMISSIVE", ["orderdesk_app"], "INSERT"),
            "catalog_admin_update": ("PERMISSIVE", ["orderdesk_app"], "UPDATE"),
            "catalog_owner_maintenance": ("PERMISSIVE", ["orderdesk_migrator"], "ALL"),
        }
        if policies.keys() != expected.keys():
            raise CommandError(
                "Catalogue policy names/count do not match the contract."
            )
        for name, header in expected.items():
            if policies[name][:3] != header:
                raise CommandError("Unexpected policy command, role, or composition.")
        boundary = policies["catalog_tenant_boundary"]
        update = policies["catalog_admin_update"]
        insert = policies["catalog_admin_insert"]
        if (
            not boundary[3]
            or boundary[3] != boundary[4]
            or not update[3]
            or update[3] != update[4]
            or insert[3] is not None
            or insert[4] != update[4]
            or policies["catalog_member_read"][3:] != ("true", None)
            or policies["catalog_owner_maintenance"][3:] != ("true", "true")
        ):
            raise CommandError("Unexpected policy USING/WITH CHECK expressions.")
        self.stdout.write(
            "Catalogue metadata verified: owner, forced RLS, 5 policies, grants."
        )
        self._audit_receipt_boundary()

    def _audit_receipt_boundary(self) -> None:
        """Audit optional new schema before registering privileged fixtures."""
        table = "public.catalog_catalogimportreceipt"
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.to_regclass(%s)", [table])
            if cursor.fetchone()[0] is None:
                return
            cursor.execute(
                "SELECT pg_catalog.pg_get_userbyid(relowner), "
                "relrowsecurity, relforcerowsecurity FROM pg_catalog.pg_class "
                "WHERE oid = %s::regclass",
                [table],
            )
            if cursor.fetchone() != ("orderdesk_migrator", True, True):
                raise CommandError("Receipt owner or ENABLE/FORCE RLS is incorrect.")
            for privilege in ("SELECT", "INSERT"):
                cursor.execute(
                    "SELECT pg_catalog.has_table_privilege(current_user, %s, %s)",
                    [table, privilege],
                )
                if cursor.fetchone()[0] is not True:
                    raise CommandError("A required runtime receipt grant is missing.")
            for privilege in (
                "UPDATE",
                "DELETE",
                "TRUNCATE",
                "REFERENCES",
                "TRIGGER",
                "MAINTAIN",
            ):
                cursor.execute(
                    "SELECT pg_catalog.has_table_privilege(current_user, %s, %s)",
                    [table, privilege],
                )
                if cursor.fetchone()[0]:
                    raise CommandError("An unexpected runtime receipt grant exists.")
            completion_columns = {"state", "response_payload", "completed_at"}
            columns = {
                "id",
                "organization_id",
                "initiating_user_id",
                "idempotency_key",
                "request_fingerprint",
                "mode",
                "contract_identifier",
                "state",
                "response_payload",
                "created_at",
                "completed_at",
            }
            for column in sorted(columns):
                cursor.execute(
                    "SELECT pg_catalog.has_column_privilege("
                    "current_user, %s, %s, 'UPDATE')",
                    [table, column],
                )
                if cursor.fetchone()[0] is not (column in completion_columns):
                    raise CommandError("Receipt UPDATE column grants are incorrect.")
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c, "
                "LATERAL pg_catalog.aclexplode(c.relacl) acl "
                "WHERE c.oid = %s::regclass AND acl.grantee = 0) OR EXISTS ("
                "SELECT 1 FROM pg_catalog.pg_attribute a, "
                "LATERAL pg_catalog.aclexplode(a.attacl) acl "
                "WHERE a.attrelid = %s::regclass AND acl.grantee = 0)",
                [table, table],
            )
            if cursor.fetchone()[0]:
                raise CommandError("PUBLIC must have no receipt table/column grants.")
            cursor.execute(
                "SELECT policyname, permissive, roles, cmd, qual, with_check "
                "FROM pg_catalog.pg_policies WHERE schemaname = 'public' "
                "AND tablename = 'catalog_catalogimportreceipt'"
            )
            policies = {row[0]: row[1:] for row in cursor.fetchall()}
            cursor.execute(
                "SELECT conname, contype, condeferrable, "
                "pg_catalog.pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
                "WHERE conrelid = %s::regclass",
                [table],
            )
            constraints = {row[0]: row[1:] for row in cursor.fetchall()}
            cursor.execute(
                "SELECT t.tgdeferrable, t.tginitdeferred, t.tgenabled, t.tgtype, "
                "p.prosecdef, pg_catalog.pg_get_userbyid(p.proowner), p.proconfig, "
                "pg_catalog.has_function_privilege(current_user, p.oid, 'EXECUTE'), "
                "pg_catalog.pg_get_functiondef(p.oid), EXISTS ("
                "SELECT 1 FROM pg_catalog.aclexplode(p.proacl) acl "
                "WHERE acl.grantee = 0) "
                "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_proc p "
                "ON p.oid = t.tgfoid WHERE t.tgrelid = %s::regclass "
                "AND t.tgname = 'catalog_import_completed_at_commit' "
                "AND NOT t.tgisinternal",
                [table],
            )
            trigger = cursor.fetchone()

        expected = {
            "catalog_import_tenant_boundary": ("RESTRICTIVE", ["orderdesk_app"], "ALL"),
            "catalog_import_admin_read": ("PERMISSIVE", ["orderdesk_app"], "SELECT"),
            "catalog_import_admin_insert": ("PERMISSIVE", ["orderdesk_app"], "INSERT"),
            "catalog_import_admin_complete": (
                "PERMISSIVE",
                ["orderdesk_app"],
                "UPDATE",
            ),
            "catalog_import_owner_maintenance": (
                "PERMISSIVE",
                ["orderdesk_migrator"],
                "ALL",
            ),
        }
        if policies.keys() != expected.keys() or any(
            policies[name][:3] != header for name, header in expected.items()
        ):
            raise CommandError("Receipt policy names/roles/commands are incorrect.")
        boundary = policies["catalog_import_tenant_boundary"]
        insert = policies["catalog_import_admin_insert"]
        update = policies["catalog_import_admin_complete"]
        if (
            not boundary[3]
            or boundary[3] != boundary[4]
            or not all(
                fragment in boundary[3]
                for fragment in (
                    "orderdesk.organization_id",
                    "orderdesk.user_id",
                    "organizations_membership",
                    "accounts_user",
                    "is_active",
                    "admin",
                )
            )
            or policies["catalog_import_admin_read"][3:] != ("true", None)
            or policies["catalog_import_owner_maintenance"][3:] != ("true", "true")
            or insert[3] is not None
            or not insert[4]
            or not all(
                fragment in insert[4]
                for fragment in (
                    "initiating_user_id",
                    "orderdesk.user_id",
                    "processing",
                    "response_payload IS NULL",
                    "completed_at IS NULL",
                )
            )
            or not update[3]
            or not update[4]
            or not all(
                fragment in update[3]
                for fragment in (
                    "initiating_user_id",
                    "orderdesk.user_id",
                    "processing",
                )
            )
            or not all(
                fragment in update[4]
                for fragment in ("initiating_user_id", "orderdesk.user_id", "completed")
            )
        ):
            raise CommandError("Receipt policy expressions are incorrect.")
        checks = {
            "catalog_import_create_only_mode",
            "catalog_import_contract_identifier",
            "catalog_import_fingerprint_sha256",
            "catalog_import_completion_shape",
            "catalog_import_completion_time",
            "catalog_import_response_object",
            "catalog_import_response_size",
        }
        if any(
            name not in constraints or constraints[name][:2] != ("c", False)
            for name in checks
        ) or constraints.get("catalog_import_org_key_unique") != (
            "u",
            False,
            "UNIQUE (organization_id, idempotency_key)",
        ):
            raise CommandError("Receipt checks or organization/key uniqueness differ.")
        if (
            trigger is None
            or trigger[:8]
            != (
                True,
                True,
                "O",
                21,
                True,
                "orderdesk_migrator",
                ["search_path=pg_catalog"],
                False,
            )
            or trigger[9]
            or "public.catalog_catalogimportreceipt" not in trigger[8]
            or "receipt.id = NEW.id" not in trigger[8]
            or "receipt.state <> 'completed'" not in trigger[8]
            or "catalog_import_completed_at_commit" not in trigger[8]
        ):
            raise CommandError("Receipt deferred completion trigger is unsafe.")
        self.stdout.write(
            "Receipt metadata verified: forced RLS, 5 policies, completion-only "
            "column grants, constraints, deferred completion trigger."
        )

    def _register_fixture_owner(self) -> None:
        if OWNER_ALIAS in connections.databases:
            raise CommandError("The verifier owner connection alias already exists.")
        owner_user = os.environ.get("RLS_VERIFIER_OWNER_USER", "")
        owner_password = os.environ.get("RLS_VERIFIER_OWNER_PASSWORD", "")
        if owner_user != "orderdesk_migrator" or not owner_password:
            raise CommandError(
                "The local verifier needs separate migration credentials."
            )
        database = deepcopy(connection.settings_dict)
        database.update(USER=owner_user, PASSWORD=owner_password, CONN_MAX_AGE=0)
        connections.databases[OWNER_ALIAS] = database
        self._owner_registered = True
        with connections[OWNER_ALIAS].cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_user, session_user, "
                "rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, "
                "rolinherit, rolreplication, EXISTS ("
                "SELECT 1 FROM pg_catalog.pg_auth_members m "
                "WHERE m.member = pg_roles.oid) FROM pg_catalog.pg_roles "
                "WHERE rolname = current_user"
            )
            identity = cursor.fetchone()
        if identity != (
            "test_orderdesk",
            "orderdesk_migrator",
            "orderdesk_migrator",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        ):
            raise CommandError(
                "Fixture connection must be the non-bypass maintenance owner."
            )

    def handle(self, *args, **options) -> None:
        self._validate_local_target()
        self._owner_registered = False
        try:
            self._audit_runtime_boundary()
            self._register_fixture_owner()
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(
                RuntimeCatalogRLSChecks
            )
            expected_tests = suite.countTestCases()
            result = unittest.TextTestRunner(stream=self.stdout, verbosity=2).run(suite)
            if (
                expected_tests == 0
                or result.testsRun != expected_tests
                or result.skipped
                or not result.wasSuccessful()
            ):
                raise CommandError("Runtime catalogue RLS verification failed.")
            self.stdout.write(
                self.style.SUCCESS("Runtime catalogue RLS verification passed.")
            )
        except DatabaseError as error:
            raise CommandError(
                "RLS verification could not access the configured database."
            ) from error
        finally:
            connection.close()
            if self._owner_registered:
                connections[OWNER_ALIAS].close()
                del connections[OWNER_ALIAS]
                connections.databases.pop(OWNER_ALIAS)
