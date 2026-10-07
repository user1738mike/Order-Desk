"""Real PostgreSQL races for draft positions and protected writer demotion."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Event
from time import monotonic

from django.core.exceptions import PermissionDenied
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import TransactionTestCase

from apps.accounts.models import User
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.services import create_organization
from apps.organizations.transactions import tenant_scope


class DraftOrderConcurrencyTests(TransactionTestCase):
    def setUp(self) -> None:
        self.assertEqual(connection.vendor, "postgresql")
        self.user = User.objects.create_user(email="draft-race@example.test")
        self.organization = create_organization(
            actor=self.user, name="Draft race tenant"
        )
        self.membership = Membership.objects.get(
            organization=self.organization, user=self.user
        )
        self.order = DraftOrder.objects.create(
            organization=self.organization, initiating_user=self.user
        )

    @staticmethod
    def _pid() -> int:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.pg_backend_pid()")
            return cursor.fetchone()[0]

    def _assert_clean_context(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting("
                "'orderdesk.organization_id', true), ''), "
                "NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def _create_line(self, *, position: int) -> object:
        actor = User.objects.get(pk=self.user.pk)
        with tenant_scope(
            user=actor, workspace_id=self.organization.pk, write=True
        ) as scope:
            if scope.role not in {MembershipRole.ADMIN, MembershipRole.REVIEWER}:
                raise PermissionDenied("Draft writer access is required.")
            return DraftOrderLine.objects.create(
                organization_id=scope.organization_id,
                order_id=self.order.pk,
                position=position,
                requested_description="Synthetic draft request",
            ).pk

    def _wait_for_block(self, waiter: int, blocker: int) -> None:
        deadline = monotonic() + 5
        pause = Event()
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_catalog.pg_blocking_pids(%s)", [waiter])
                if blocker in cursor.fetchone()[0]:
                    return
            pause.wait(0.02)
        self.fail("Expected organization lock wait was not observed.")

    def test_concurrent_duplicate_position_commits_once(self) -> None:
        barrier = Barrier(2, timeout=10)

        def attempt() -> str:
            close_old_connections()
            try:
                barrier.wait()
                try:
                    self._create_line(position=1)
                except IntegrityError:
                    result = "duplicate"
                else:
                    result = "created"
                self._assert_clean_context()
                return result
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(outcomes, ["created", "duplicate"])
        self.assertEqual(
            DraftOrderLine.objects.filter(order=self.order, position=1).count(), 1
        )

    def test_committed_demotion_denies_waiting_writer(self) -> None:
        ready = Queue()
        blocker_pid = self._pid()

        def attempt() -> str:
            close_old_connections()
            observed = False

            def inspect(execute, statement, params, many, context):
                nonlocal observed
                if (
                    not observed
                    and "organizations_organization" in statement
                    and "FOR UPDATE" in statement
                ):
                    observed = True
                    ready.put(self._pid())
                return execute(statement, params, many, context)

            try:
                with connection.execute_wrapper(inspect):
                    try:
                        self._create_line(position=2)
                    except PermissionDenied:
                        result = "denied"
                    else:
                        result = "created"
                self._assert_clean_context()
                return result
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.organization.pk)
                Membership.objects.filter(pk=self.membership.pk).update(
                    role=MembershipRole.VIEWER
                )
                future = pool.submit(attempt)
                waiter_pid = ready.get(timeout=10)
                self._wait_for_block(waiter_pid, blocker_pid)
            self.assertEqual(future.result(timeout=15), "denied")
        self.assertFalse(DraftOrderLine.objects.filter(order=self.order).exists())
        self._assert_clean_context()

    def test_protected_writer_commits_before_waiting_demotion(self) -> None:
        inserted = Queue()
        demoter_ready = Queue()
        release = Event()

        def write() -> object:
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.user.pk)
                with tenant_scope(
                    user=actor, workspace_id=self.organization.pk, write=True
                ) as scope:
                    if scope.role not in {
                        MembershipRole.ADMIN,
                        MembershipRole.REVIEWER,
                    }:
                        raise PermissionDenied("Draft writer access is required.")
                    row = DraftOrderLine.objects.create(
                        organization_id=scope.organization_id,
                        order_id=self.order.pk,
                        position=3,
                        requested_sku="RACE-3",
                    )
                    inserted.put((self._pid(), row.pk))
                    if not release.wait(10):
                        raise RuntimeError("Writer release timed out")
                self._assert_clean_context()
                return row.pk
            finally:
                connections["default"].close()

        def demote() -> str:
            close_old_connections()
            try:
                demoter_ready.put(self._pid())
                with transaction.atomic():
                    Organization.objects.select_for_update().get(
                        pk=self.organization.pk
                    )
                    Membership.objects.filter(pk=self.membership.pk).update(
                        role=MembershipRole.VIEWER
                    )
                return "demoted"
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(write)
            try:
                writer_pid, row_id = inserted.get(timeout=10)
                demoting = pool.submit(demote)
                demoter_pid = demoter_ready.get(timeout=10)
                self._wait_for_block(demoter_pid, writer_pid)
            finally:
                release.set()
            self.assertEqual(writing.result(timeout=15), row_id)
            self.assertEqual(demoting.result(timeout=15), "demoted")
        self.assertTrue(DraftOrderLine.objects.filter(pk=row_id).exists())
        self._assert_clean_context()
