from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class RuntimeRoleTests(SimpleTestCase):
    def check_flags(
        self,
        flags: tuple[bool, ...],
        *,
        draft_table_state: tuple[bool, ...] = (
            True,
            True,
            True,
            True,
            True,
            False,
            False,
        ),
    ) -> None:
        cursor = MagicMock()
        cursor.__enter__.return_value.fetchone.side_effect = [
            flags,
            draft_table_state,
            *([(True,)] * 4),
            *([(False,)] * 6),
            draft_table_state,
            *([(True,)] * 9),
            *([(False,)] * 4),
        ]
        with patch(
            "apps.health.management.commands.check_runtime_role.connection"
        ) as connection:
            connection.vendor = "postgresql"
            connection.cursor.return_value = cursor
            call_command("check_runtime_role", verbosity=0)

    def test_each_privileged_capability_prevents_startup(self) -> None:
        # Superuser, RLS bypass, DB/role creation, schema creation, table ownership,
        # and role membership are independently disallowed for the API account.
        for position in range(7):
            flags = tuple(index == position for index in range(7))
            with self.subTest(position=position), self.assertRaises(CommandError):
                self.check_flags(flags)

    def test_restricted_role_is_accepted(self) -> None:
        self.check_flags((False,) * 7)

    def test_missing_draft_table_grant_prevents_startup(self) -> None:
        with self.assertRaises(CommandError):
            self.check_flags(
                (False,) * 7,
                draft_table_state=(True, True, True, True, False, False, False),
            )
