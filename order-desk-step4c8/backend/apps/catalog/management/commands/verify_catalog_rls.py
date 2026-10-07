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
