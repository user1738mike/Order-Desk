"""Scope guards and real PostgreSQL lifetimes; business-table RLS is a later step."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import SimpleTestCase, TransactionTestCase
from psycopg.pq import TransactionStatus

from apps.accounts.models import User
from apps.organizations.context import resolve_workspace_context
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.services import create_organization
from apps.organizations.transactions import (
    ORGANIZATION_SETTING,
    USER_SETTING,
    TenantScopeError,
    tenant_scope,
)


class TenantScopeGuardTests(SimpleTestCase):
    """Early failures must not query or close a caller-owned transaction."""

    def test_workspace_id_requires_an_already_parsed_uuid(self) -> None:
        for value in (str(uuid4()), None, 123):
            with self.subTest(value=value), self.assertRaises(TypeError):
                with tenant_scope(user=AnonymousUser(), workspace_id=value):
                    self.fail("Invalid workspace ID entered the scope.")

    def test_write_mode_requires_a_bool(self) -> None:
        for value in ("false", 1, None):
            with self.subTest(value=value), self.assertRaises(TypeError):
                with tenant_scope(
                    user=AnonymousUser(), workspace_id=uuid4(), write=value
                ):
                    self.fail("Invalid write mode entered the scope.")

    def test_non_postgresql_backend_is_rejected_before_sql(self) -> None:
        database = Mock(vendor="sqlite")
        with (
            patch("apps.organizations.transactions.connection", database),
            self.assertRaises(ImproperlyConfigured),
        ):
            with tenant_scope(user=AnonymousUser(), workspace_id=uuid4()):
                self.fail("SQLite entered a PostgreSQL scope.")
        database.cursor.assert_not_called()
        database.close.assert_not_called()

    def test_existing_atomic_block_is_rejected_without_touching_it(self) -> None:
        database = Mock(vendor="postgresql", in_atomic_block=True)
        with (
            patch("apps.organizations.transactions.connection", database),
            self.assertRaises(TenantScopeError),
        ):
            with tenant_scope(user=AnonymousUser(), workspace_id=uuid4()):
                self.fail("Existing transaction entered a scope.")
        database.get_autocommit.assert_not_called()
        database.cursor.assert_not_called()
        database.close.assert_not_called()

    def test_disabled_autocommit_is_rejected_without_touching_it(self) -> None:
        database = Mock(vendor="postgresql", in_atomic_block=False)
        database.get_autocommit.return_value = False
        with (
            patch("apps.organizations.transactions.connection", database),
            self.assertRaises(TenantScopeError),
        ):
            with tenant_scope(user=AnonymousUser(), workspace_id=uuid4()):
                self.fail("Manual transaction entered a scope.")
        database.cursor.assert_not_called()
        database.close.assert_not_called()

    def test_nonidle_driver_states_are_rejected_without_touching_them(self) -> None:
        for status in (
            TransactionStatus.INTRANS,
            TransactionStatus.INERROR,
            TransactionStatus.ACTIVE,
            TransactionStatus.UNKNOWN,
        ):
            database = Mock(vendor="postgresql", in_atomic_block=False)
            database.get_autocommit.return_value = True
            database.connection.autocommit = True
            database.connection.info.transaction_status = status
            with (
                self.subTest(status=status),
                patch("apps.organizations.transactions.connection", database),
                self.assertRaises(TenantScopeError),
            ):
                with tenant_scope(user=AnonymousUser(), workspace_id=uuid4()):
                    self.fail("An unsafe driver state entered the scope.")
            for handle in (database, database.connection):
                for method in ("cursor", "close", "commit", "rollback"):
                    getattr(handle, method).assert_not_called()

    def test_disabled_driver_autocommit_is_rejected_before_sql(self) -> None:
        database = Mock(vendor="postgresql", in_atomic_block=False)
        database.get_autocommit.return_value = True
        database.connection.autocommit = False
        database.connection.info.transaction_status = TransactionStatus.IDLE
        with (
            patch("apps.organizations.transactions.connection", database),
            self.assertRaises(TenantScopeError),
        ):
            with tenant_scope(user=AnonymousUser(), workspace_id=uuid4()):
                self.fail("Disabled native autocommit entered the scope.")
        for handle in (database, database.connection):
            for method in ("cursor", "close", "commit", "rollback"):
                getattr(handle, method).assert_not_called()


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL transactions.")
class TenantTransactionTests(TransactionTestCase):
    """Use committed fixtures: TestCase's outer atomic block violates this contract."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(email="scope-member@example.test")
        self.other_user = User.objects.create_user(email="other-member@example.test")
        self.organization = create_organization(actor=self.user, name="Distributor A")
        self.other_organization = create_organization(
            actor=self.user, name="Distributor B"
        )
        self.membership = Membership.objects.get(
            organization=self.organization, user=self.user
        )
        Membership.objects.create(
            organization=self.other_organization,
            user=self.other_user,
            role=MembershipRole.VIEWER,
        )

    def tearDown(self) -> None:
        # A test deliberately changes session defaults/settings. Do not leave them
        # on the connection Django uses to flush fixtures after tearDown.
        connection.close()
        super().tearDown()

    @staticmethod
    def _context_ids() -> tuple[str | None, str | None]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(pg_catalog.current_setting(%s, true), ''), "
                "NULLIF(pg_catalog.current_setting(%s, true), '')",
                [ORGANIZATION_SETTING, USER_SETTING],
            )
            return cursor.fetchone()

    @staticmethod
    def _transaction_mode() -> tuple[str, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.current_setting('transaction_read_only'), "
                "pg_catalog.current_setting('transaction_isolation')"
            )
            return cursor.fetchone()

    @staticmethod
    def _backend_pid() -> int:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.pg_backend_pid()")
            return cursor.fetchone()[0]

    def _assert_clean(self) -> None:
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        self.assertEqual(self._context_ids(), (None, None))

    def test_read_scope_binds_both_ids_and_returns_current_context(self) -> None:
        with tenant_scope(user=self.user, workspace_id=self.organization.pk) as context:
            self.assertTrue(connection.in_atomic_block)
            self.assertEqual(self._transaction_mode(), ("on", "read committed"))
            self.assertEqual(
                self._context_ids(), (str(self.organization.pk), str(self.user.pk))
            )
            self.assertEqual(context.organization_id, self.organization.pk)
            self.assertEqual(context.organization_name, "Distributor A")
            self.assertEqual(context.user_id, self.user.pk)
            self.assertEqual(context.membership_id, self.membership.pk)
            self.assertEqual(context.role, MembershipRole.ADMIN)
        self._assert_clean()

    def test_write_scope_commits_and_clears_context(self) -> None:
        with tenant_scope(
            user=self.user, workspace_id=self.organization.pk, write=True
        ):
            self.assertEqual(self._transaction_mode(), ("off", "read committed"))
            Organization.objects.filter(pk=self.organization.pk).update(name="Updated")
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Updated")
        self._assert_clean()

    def test_application_exception_rolls_back_changes_and_context(self) -> None:
        with self.assertRaisesRegex(ValueError, "abort scope"):
            with tenant_scope(
                user=self.user, workspace_id=self.organization.pk, write=True
            ):
                Organization.objects.filter(pk=self.organization.pk).update(
                    name="Must roll back"
                )
                raise ValueError("abort scope")
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Distributor A")
        self._assert_clean()

    def test_database_exception_rolls_back_changes_and_connection_remains_usable(
        self,
    ) -> None:
        with self.assertRaises(DatabaseError) as error:
            with tenant_scope(
                user=self.user, workspace_id=self.organization.pk, write=True
            ):
                Organization.objects.filter(pk=self.organization.pk).update(
                    name="Must roll back"
                )
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 / 0")
        self.assertEqual(error.exception.__cause__.sqlstate, "22012")
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Distributor A")
        self._assert_clean()

    def test_read_scope_rejects_database_writes(self) -> None:
        with self.assertRaises(DatabaseError) as error:
            with tenant_scope(user=self.user, workspace_id=self.organization.pk):
                Organization.objects.filter(pk=self.organization.pk).update(
                    name="Forbidden write"
                )
        self.assertEqual(error.exception.__cause__.sqlstate, "25006")
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Distributor A")
        self._assert_clean()

    def test_commit_then_different_tenant_and_actor_reuses_clean_connection(
        self,
    ) -> None:
        backend_pid = self._backend_pid()
        for actor, workspace in (
            (self.user, self.organization),
            (self.other_user, self.other_organization),
            (self.user, self.organization),
        ):
            with self.subTest(workspace=workspace.pk):
                with tenant_scope(user=actor, workspace_id=workspace.pk):
                    self.assertEqual(
                        self._context_ids(), (str(workspace.pk), str(actor.pk))
                    )
                    self.assertEqual(self._backend_pid(), backend_pid)
                self._assert_clean()
                self.assertEqual(self._backend_pid(), backend_pid)

    def test_rollback_then_new_scope_reuses_clean_connection(self) -> None:
        backend_pid = self._backend_pid()
        with self.assertRaises(ValueError):
            with tenant_scope(user=self.user, workspace_id=self.organization.pk):
                raise ValueError("abort scope")
        self._assert_clean()
        with tenant_scope(
            user=self.other_user, workspace_id=self.other_organization.pk
        ):
            self.assertEqual(self._backend_pid(), backend_pid)
            self.assertEqual(
                self._context_ids(),
                (str(self.other_organization.pk), str(self.other_user.pk)),
            )
        self._assert_clean()

    def test_earlier_context_does_not_override_new_role_or_name(self) -> None:
        earlier = resolve_workspace_context(
            user=self.user, workspace_id=self.organization.pk
        )
        Membership.objects.filter(pk=self.membership.pk).update(
            role=MembershipRole.VIEWER
        )
        Organization.objects.filter(pk=self.organization.pk).update(name="Renamed")
        with tenant_scope(user=self.user, workspace_id=self.organization.pk) as context:
            self.assertEqual(earlier.role, MembershipRole.ADMIN)
            self.assertEqual(context.role, MembershipRole.VIEWER)
            self.assertEqual(context.organization_name, "Renamed")
        self._assert_clean()

    def test_generic_write_scope_does_not_grant_or_require_a_business_role(
        self,
    ) -> None:
        Membership.objects.filter(pk=self.membership.pk).update(
            role=MembershipRole.VIEWER
        )
        with tenant_scope(
            user=self.user, workspace_id=self.organization.pk, write=True
        ) as context:
            self.assertEqual(context.role, MembershipRole.VIEWER)
        self._assert_clean()

    def test_disabled_account_is_denied_even_with_a_stale_active_instance(self) -> None:
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertTrue(self.user.is_active)
        self._assert_denied(self.user, self.organization.pk)

    def test_revoked_membership_is_denied(self) -> None:
        Membership.objects.filter(pk=self.membership.pk).update(is_active=False)
        self._assert_denied(self.user, self.organization.pk)

    def test_inactive_organization_is_denied(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=False)
        self._assert_denied(self.user, self.organization.pk)

    def test_anonymous_unsaved_nonmember_and_unknown_workspace_are_denied(self) -> None:
        for actor, workspace_id in (
            (AnonymousUser(), self.organization.pk),
            (User(email="unsaved@example.test"), self.organization.pk),
            (self.other_user, self.organization.pk),
            (self.user, uuid4()),
        ):
            with self.subTest(actor=type(actor).__name__, workspace=workspace_id):
                self._assert_denied(actor, workspace_id)

    def _assert_denied(self, actor: User | AnonymousUser, workspace_id: UUID) -> None:
        for write in (False, True):
            with self.subTest(write=write), self.assertRaises(PermissionDenied):
                with tenant_scope(user=actor, workspace_id=workspace_id, write=write):
                    self.fail("Unauthorized caller entered the scope.")
            self._assert_clean()

    def test_nested_scope_is_rejected_without_changing_the_outer_context(self) -> None:
        with tenant_scope(user=self.user, workspace_id=self.organization.pk):
            backend_pid = self._backend_pid()
            for workspace_id in (self.organization.pk, self.other_organization.pk):
                with self.subTest(workspace=workspace_id):
                    with self.assertRaises(TenantScopeError):
                        with tenant_scope(user=self.user, workspace_id=workspace_id):
                            self.fail("Nested scope entered.")
                    self.assertEqual(self._backend_pid(), backend_pid)
                    self.assertEqual(
                        self._context_ids(),
                        (str(self.organization.pk), str(self.user.pk)),
                    )
        self._assert_clean()

    def test_existing_atomic_transaction_is_preserved_on_rejection(self) -> None:
        with transaction.atomic():
            Organization.objects.filter(pk=self.organization.pk).update(name="Outer")
            backend_pid = self._backend_pid()
            with self.assertRaises(TenantScopeError):
                with tenant_scope(user=self.user, workspace_id=self.organization.pk):
                    self.fail("Scope entered an existing atomic block.")
            self.assertEqual(self._backend_pid(), backend_pid)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Outer")
        self._assert_clean()

    def test_manual_transaction_is_preserved_on_rejection(self) -> None:
        connection.set_autocommit(False)
        try:
            Organization.objects.filter(pk=self.organization.pk).update(name="Manual")
            backend_pid = self._backend_pid()
            with self.assertRaises(TenantScopeError):
                with tenant_scope(user=self.user, workspace_id=self.organization.pk):
                    self.fail("Scope entered a manual transaction.")
            self.assertEqual(self._backend_pid(), backend_pid)
            self.assertEqual(
                Organization.objects.get(pk=self.organization.pk).name, "Manual"
            )
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Distributor A")
        self._assert_clean()

    def test_raw_transaction_preserves_pending_work_and_local_context_on_rejection(
        self,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN")
        native_connection = connection.connection
        try:
            Organization.objects.filter(pk=self.organization.pk).update(
                name="Raw outer"
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_catalog.set_config(%s, %s, true), "
                    "pg_catalog.set_config(%s, %s, true)",
                    [
                        ORGANIZATION_SETTING,
                        str(self.organization.pk),
                        USER_SETTING,
                        str(self.user.pk),
                    ],
                )
            self.assertTrue(connection.get_autocommit())
            self.assertFalse(connection.in_atomic_block)
            for write in (False, True):
                with (
                    self.subTest(write=write),
                    self.assertNumQueries(0),
                    self.assertRaises(TenantScopeError),
                ):
                    with tenant_scope(
                        user=self.user,
                        workspace_id=self.other_organization.pk,
                        write=write,
                    ):
                        self.fail("Scope entered a raw PostgreSQL transaction.")
                self.assertIs(connection.connection, native_connection)
                self.assertEqual(
                    native_connection.info.transaction_status, TransactionStatus.INTRANS
                )
                self.assertEqual(
                    self._context_ids(), (str(self.organization.pk), str(self.user.pk))
                )
                self.assertEqual(
                    Organization.objects.get(pk=self.organization.pk).name, "Raw outer"
                )
        finally:
            connection.rollback()
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Distributor A")
        self._assert_clean()

    def test_aborted_raw_transaction_is_rejected_without_sql_or_cleanup(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN")
        native_connection = connection.connection
        try:
            with self.assertRaises(DatabaseError), connection.cursor() as cursor:
                cursor.execute("SELECT 1 / 0")
            self.assertTrue(connection.get_autocommit())
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(
                native_connection.info.transaction_status, TransactionStatus.INERROR
            )
            with self.assertNumQueries(0), self.assertRaises(TenantScopeError):
                with tenant_scope(user=self.user, workspace_id=self.organization.pk):
                    self.fail("Scope entered an aborted raw transaction.")
            self.assertIs(connection.connection, native_connection)
            self.assertEqual(
                native_connection.info.transaction_status, TransactionStatus.INERROR
            )
        finally:
            connection.rollback()
        self._assert_clean()

    def test_disabled_native_autocommit_is_rejected_while_driver_remains_idle(
        self,
    ) -> None:
        native_connection = connection.connection
        native_connection.autocommit = False
        try:
            self.assertTrue(connection.get_autocommit())
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(
                native_connection.info.transaction_status, TransactionStatus.IDLE
            )
            with self.assertNumQueries(0), self.assertRaises(TenantScopeError):
                with tenant_scope(user=self.user, workspace_id=self.organization.pk):
                    self.fail("Scope entered with disabled native autocommit.")
            self.assertIs(connection.connection, native_connection)
            self.assertFalse(native_connection.autocommit)
            self.assertTrue(connection.get_autocommit())
            self.assertEqual(
                native_connection.info.transaction_status, TransactionStatus.IDLE
            )
        finally:
            if not native_connection.closed:
                native_connection.rollback()
                native_connection.autocommit = True
        self._assert_clean()

    def test_inner_savepoint_rollback_keeps_outer_context_and_other_writes(
        self,
    ) -> None:
        with tenant_scope(
            user=self.user, workspace_id=self.organization.pk, write=True
        ):
            with self.assertRaises(ValueError):
                with transaction.atomic():
                    Organization.objects.filter(pk=self.organization.pk).update(
                        name="Savepoint must roll back"
                    )
                    raise ValueError("abort savepoint")
            self.assertEqual(
                self._context_ids(), (str(self.organization.pk), str(self.user.pk))
            )
            self.assertEqual(
                Organization.objects.get(pk=self.organization.pk).name, "Distributor A"
            )
            Organization.objects.filter(pk=self.organization.pk).update(
                name="Committed"
            )
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Committed")
        self._assert_clean()

    def test_ambient_valid_or_malformed_setting_discards_the_idle_connection(
        self,
    ) -> None:
        for setting in (ORGANIZATION_SETTING, USER_SETTING):
            for value in (str(uuid4()), "not-a-uuid"):
                with self.subTest(setting=setting, value=value):
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_catalog.set_config(%s, %s, false)",
                            [setting, value],
                        )
                    with self.assertRaises(TenantScopeError):
                        with tenant_scope(
                            user=self.user, workspace_id=self.organization.pk
                        ):
                            self.fail("Ambient context entered a scope.")
                    self.assertIsNone(connection.connection)
                    self._assert_clean()

    def test_blank_session_baseline_is_allowed(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.set_config(%s, '', false), "
                "pg_catalog.set_config(%s, '', false)",
                [ORGANIZATION_SETTING, USER_SETTING],
            )
        with tenant_scope(user=self.user, workspace_id=self.organization.pk):
            self.assertEqual(
                self._context_ids(), (str(self.organization.pk), str(self.user.pk))
            )
        self._assert_clean()

    def test_modes_override_but_do_not_change_the_session_defaults(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.set_config('default_transaction_isolation', "
                "'repeatable read', false), "
                "pg_catalog.set_config('default_transaction_read_only', 'on', false)"
            )
        for write in (True, False):
            with self.subTest(write=write):
                with tenant_scope(
                    user=self.user, workspace_id=self.organization.pk, write=write
                ):
                    self.assertEqual(
                        self._transaction_mode(),
                        ("off" if write else "on", "read committed"),
                    )
                self.assertEqual(self._transaction_mode(), ("on", "repeatable read"))
                self._assert_clean()

    def test_on_commit_callback_observes_a_clean_connection(self) -> None:
        observed = []
        with tenant_scope(
            user=self.user, workspace_id=self.organization.pk, write=True
        ):
            transaction.on_commit(lambda: observed.append(self._context_ids()))
        self.assertEqual(observed, [(None, None)])
        self._assert_clean()

    def test_write_scope_waits_for_lock_and_observes_committed_demotion(self) -> None:
        role = self._write_scope_after_locked_change(role=MembershipRole.VIEWER)
        self.assertEqual(role, MembershipRole.VIEWER)
        self._assert_clean()

    def test_write_scope_rechecks_membership_after_waiting_for_revocation(self) -> None:
        with self.assertRaises(PermissionDenied):
            self._write_scope_after_locked_change(is_active=False)
        self._assert_clean()

    def _write_scope_after_locked_change(self, **changes: object) -> MembershipRole:
        ready: Queue[int] = Queue()
        actor_id, workspace_id = self.user.pk, self.organization.pk
        blocking_pid = self._backend_pid()

        def attempt_write() -> MembershipRole:
            close_old_connections()
            try:
                actor = User.objects.get(pk=actor_id)
                # Bound a faulty test's wait without modifying session defaults.
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                ready.put(self._backend_pid())
                with tenant_scope(
                    user=actor, workspace_id=workspace_id, write=True
                ) as context:
                    return context.role
            finally:
                connections["default"].close()

        # The executor outlives the lock transaction: failures release the lock
        # before joining a blocked worker. Assert real blocking, not a timed guess.
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=workspace_id)
                Membership.objects.filter(pk=self.membership.pk).update(**changes)
                future = executor.submit(attempt_write)
                worker_pid = ready.get(timeout=10)
                deadline = monotonic() + 4
                pause = Event()
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_catalog.pg_blocking_pids(%s)", [worker_pid]
                        )
                        if blocking_pid in cursor.fetchone()[0]:
                            break
                    pause.wait(0.02)
                else:
                    self.fail("Write scope did not wait for the organization lock.")
            return future.result(timeout=10)
