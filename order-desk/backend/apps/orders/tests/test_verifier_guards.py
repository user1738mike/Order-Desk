from io import StringIO
from unittest.mock import MagicMock, Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from apps.orders.management.commands.verify_order_rls import Command

CATALOG_COMMAND = "apps.catalog.management.commands.verify_catalog_rls"
ORDER_COMMAND = "apps.orders.management.commands.verify_order_rls"


class OrderVerifierGuardTests(SimpleTestCase):
    """Unsafe targets fail before SQL or fixture registration."""

    def _assert_rejected(self, database: Mock, *, debug: bool) -> None:
        with (
            override_settings(DEBUG=debug),
            patch(f"{CATALOG_COMMAND}.connection", database),
            patch(f"{ORDER_COMMAND}.connection", database),
            self.assertRaises(CommandError),
        ):
            call_command("verify_order_rls", stdout=StringIO())
        database.cursor.assert_not_called()
        database.close.assert_not_called()

    def test_non_development_settings_reject_before_connecting(self) -> None:
        self._assert_rejected(Mock(), debug=False)

    def test_non_postgresql_backend_rejects_before_connecting(self) -> None:
        self._assert_rejected(Mock(vendor="sqlite"), debug=True)

    def test_main_database_cannot_be_populated(self) -> None:
        self._assert_rejected(
            Mock(vendor="postgresql", settings_dict={"NAME": "orderdesk"}),
            debug=True,
        )

    def test_outer_transaction_cannot_be_used(self) -> None:
        self._assert_rejected(
            Mock(
                vendor="postgresql",
                settings_dict={"NAME": "test_orderdesk"},
                in_atomic_block=True,
            ),
            debug=True,
        )

    def test_manual_transaction_cannot_be_used(self) -> None:
        database = Mock(
            vendor="postgresql",
            settings_dict={"NAME": "test_orderdesk"},
            in_atomic_block=False,
        )
        database.get_autocommit.return_value = False
        self._assert_rejected(database, debug=True)

    def test_actual_database_and_both_session_identities_are_checked(self) -> None:
        for identity in (
            ("orderdesk", "orderdesk_app", "orderdesk_app"),
            ("test_orderdesk", "orderdesk_migrator", "orderdesk_migrator"),
            ("test_orderdesk", "orderdesk_app", "orderdesk_migrator"),
        ):
            database = MagicMock(
                vendor="postgresql",
                settings_dict={"NAME": "test_orderdesk"},
                in_atomic_block=False,
            )
            database.get_autocommit.return_value = True
            cursor = database.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = identity
            with (
                self.subTest(identity=identity),
                override_settings(DEBUG=True),
                patch(f"{CATALOG_COMMAND}.connection", database),
                patch(f"{ORDER_COMMAND}.connection", database),
                patch(f"{ORDER_COMMAND}.Command._register_fixture_owner") as owner,
                self.assertRaises(CommandError),
            ):
                call_command("verify_order_rls", stdout=StringIO())
            owner.assert_not_called()
            cursor.execute.assert_called_once_with(
                "SELECT current_database(), current_user, session_user"
            )

    def test_missing_forced_rls_is_rejected_before_fixtures(self) -> None:
        database = MagicMock()
        cursor = database.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("orderdesk_migrator", True, False)
        command = Command(stdout=StringIO())
        with (
            patch(f"{CATALOG_COMMAND}.Command._audit_runtime_boundary"),
            patch(f"{ORDER_COMMAND}.connection", database),
            self.assertRaises(CommandError),
        ):
            command._audit_runtime_boundary()
        cursor.execute.assert_called_once()

    def test_policy_composition_and_public_access_are_rejected(self) -> None:
        policies = {
            "order_tenant_boundary": (
                "RESTRICTIVE",
                ["orderdesk_app"],
                "ALL",
                "boundary",
                "boundary",
            ),
            "order_member_read": (
                "PERMISSIVE",
                ["orderdesk_app"],
                "SELECT",
                "true",
                None,
            ),
            "order_reviewer_insert": (
                "PERMISSIVE",
                ["orderdesk_app"],
                "INSERT",
                None,
                "reviewer",
            ),
            "order_reviewer_update": (
                "PERMISSIVE",
                ["orderdesk_app"],
                "UPDATE",
                "reviewer",
                "reviewer",
            ),
            "order_owner_maintenance": (
                "PERMISSIVE",
                ["orderdesk_migrator"],
                "ALL",
                "true",
                "true",
            ),
        }
        Command._validate_policies("orders_purchaseorder", "order", policies)
        for invalid in (
            ("PERMISSIVE", ["orderdesk_app"], "ALL", "boundary", "boundary"),
            ("RESTRICTIVE", ["public"], "ALL", "boundary", "boundary"),
            ("RESTRICTIVE", ["orderdesk_app"], "ALL", "boundary", "true"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(CommandError):
                Command._validate_policies(
                    "orders_purchaseorder",
                    "order",
                    {**policies, "order_tenant_boundary": invalid},
                )

    def test_skipped_failed_and_incomplete_runtime_suites_are_rejected(self) -> None:
        for tests_run, skipped, successful in (
            (1, [("test", "skipped")], True),
            (1, [], False),
            (0, [], True),
        ):
            database = MagicMock()
            suite = Mock()
            suite.countTestCases.return_value = 1
            result = Mock(testsRun=tests_run, skipped=skipped)
            result.wasSuccessful.return_value = successful
            command = Command(stdout=StringIO())
            with (
                self.subTest(tests_run=tests_run, skipped=skipped, success=successful),
                patch.object(command, "_validate_local_target"),
                patch.object(command, "_audit_runtime_boundary"),
                patch.object(command, "_register_fixture_owner"),
                patch(f"{ORDER_COMMAND}.connection", database),
                patch(
                    f"{ORDER_COMMAND}.unittest.defaultTestLoader.loadTestsFromTestCase",
                    return_value=suite,
                ),
                patch(f"{ORDER_COMMAND}.unittest.TextTestRunner") as runner,
                self.assertRaises(CommandError),
            ):
                runner.return_value.run.return_value = result
                command.handle()
            database.close.assert_called_once()
