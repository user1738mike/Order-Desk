"""Reuse the audited two-role fixture boundary for direct-runtime HTTP checks."""

import unittest

from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections
from django.test import override_settings

from apps.catalog.management.commands.verify_catalog_rls import (
    Command as CatalogCommand,
)
from apps.catalog.tests.runtime_api import RuntimeCatalogAPIChecks
from apps.catalog.tests.runtime_rls import OWNER_ALIAS


class Command(CatalogCommand):
    help = (
        "Verify catalogue HTTP contracts as orderdesk_app, using only test_orderdesk."
    )

    def handle(self, *args, **options) -> None:
        self._validate_local_target()
        self._owner_registered = False
        try:
            self._audit_runtime_boundary()
            self._register_fixture_owner()
            loader = unittest.TestLoader()
            # Inherit fixture setup/cleanup without rerunning the separate RLS suite.
            loader.testMethodPrefix = "test_runtime_api_"
            suite = loader.loadTestsFromTestCase(RuntimeCatalogAPIChecks)
            expected_tests = suite.countTestCases()
            if expected_tests != 6:
                raise CommandError("The runtime catalogue API suite is incomplete.")
            with override_settings(
                ALLOWED_HOSTS=["testserver"],
                PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
            ):
                result = unittest.TextTestRunner(stream=self.stdout, verbosity=2).run(
                    suite
                )
            if (
                result.testsRun != expected_tests
                or result.skipped
                or not result.wasSuccessful()
            ):
                raise CommandError("Runtime catalogue API verification failed.")
            self.stdout.write(
                self.style.SUCCESS("Runtime catalogue API verification passed.")
            )
        except DatabaseError as error:
            raise CommandError(
                "API verification could not access the configured database."
            ) from error
        finally:
            connection.close()
            if self._owner_registered:
                connections[OWNER_ALIAS].close()
                del connections[OWNER_ALIAS]
                connections.databases.pop(OWNER_ALIAS)
