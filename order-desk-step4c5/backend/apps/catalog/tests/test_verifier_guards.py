from io import StringIO
from unittest.mock import MagicMock, Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class CatalogVerifierGuardTests(SimpleTestCase):
    """Wrong environment/database/transaction must fail before any SQL or fixtures."""

    def _assert_rejected(self, database: Mock, *, debug: bool) -> None:
        with (
            override_settings(DEBUG=debug),
            patch(
                "apps.catalog.management.commands.verify_catalog_rls.connection",
                database,
            ),
            self.assertRaises(CommandError),
        ):
            call_command("verify_catalog_rls", stdout=StringIO())
        database.cursor.assert_not_called()
        database.close.assert_not_called()

    def test_non_development_settings_reject_before_connecting(self) -> None:
        self._assert_rejected(Mock(), debug=False)

    def test_non_postgresql_backend_rejects_before_connecting(self) -> None:
        self._assert_rejected(Mock(vendor="sqlite"), debug=True)

    def test_main_database_cannot_be_populated(self) -> None:
        database = Mock(vendor="postgresql", settings_dict={"NAME": "orderdesk"})
        self._assert_rejected(database, debug=True)

    def test_outer_transaction_cannot_be_used(self) -> None:
        database = Mock(
            vendor="postgresql",
            settings_dict={"NAME": "test_orderdesk"},
            in_atomic_block=True,
        )
        self._assert_rejected(database, debug=True)

    def test_manual_transaction_cannot_be_used(self) -> None:
        database = Mock(
            vendor="postgresql",
            settings_dict={"NAME": "test_orderdesk"},
            in_atomic_block=False,
        )
        database.get_autocommit.return_value = False
        self._assert_rejected(database, debug=True)

    def test_actual_database_and_session_role_are_checked_before_fixtures(self) -> None:
        for identity in (
            ("orderdesk", "orderdesk_app", "orderdesk_app"),
            ("test_orderdesk", "orderdesk_migrator", "orderdesk_migrator"),
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
                patch(
                    "apps.catalog.management.commands.verify_catalog_rls.connection",
                    database,
                ),
                patch(
                    "apps.catalog.management.commands.verify_catalog_rls."
                    "Command._register_fixture_owner"
                ) as register_owner,
                self.assertRaises(CommandError),
            ):
                call_command("verify_catalog_rls", stdout=StringIO())
            register_owner.assert_not_called()
            cursor.execute.assert_called_once_with(
                "SELECT current_database(), current_user, session_user"
            )
