"""Direct runtime verification on the guarded synthetic database only."""

import unittest

from django.core.management.base import CommandError
from django.db import connection, connections

from apps.catalog.management.commands.verify_catalog_rls import (
    Command as CatalogCommand,
)
from apps.catalog.tests.runtime_rls import OWNER_ALIAS
from apps.product_units.tests.runtime_boundary import RuntimeUnitChecks, audit


class Command(CatalogCommand):
    help = (
        "Verify controlled product references using actual orderdesk_app credentials."
    )

    def handle(self, *args, **options):
        self._validate_local_target()
        self._owner_registered = False
        try:
            self._audit_runtime_boundary()
            with connection.cursor() as cursor:
                audit(cursor)
            self._register_fixture_owner()
            names = [
                name
                for name in unittest.defaultTestLoader.getTestCaseNames(
                    RuntimeUnitChecks
                )
                if name.startswith("test_unit_")
            ]
            suite = unittest.TestSuite(RuntimeUnitChecks(name) for name in names)
            result = unittest.TextTestRunner(stream=self.stdout, verbosity=2).run(suite)
            if (
                not names
                or result.testsRun != len(names)
                or result.skipped
                or not result.wasSuccessful()
            ):
                raise CommandError("Runtime product-unit verification failed.")
            self.stdout.write(
                self.style.SUCCESS("Runtime product-unit verification passed.")
            )
        finally:
            connection.close()
            if self._owner_registered:
                connections[OWNER_ALIAS].close()
                del connections[OWNER_ALIAS]
                connections.databases.pop(OWNER_ALIAS)
