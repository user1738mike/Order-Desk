"""Independent PostgreSQL connections prove serialized edits and demotion order."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic

from django.db import close_old_connections, connection, connections, transaction

from apps.catalog.services import CATALOG_UPDATE_DENIED
from apps.catalog.tests.test_update_api import CatalogUpdateTestCase
from apps.organizations.models import Membership, MembershipRole, Organization


class CatalogUpdateConcurrencyTests(CatalogUpdateTestCase):
    def pid(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            return cursor.fetchone()[0]

    def assert_blocked(self, waiter, blocker):
        deadline = monotonic() + 5
        pause = Event()
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_blocking_pids(%s)", [waiter])
                if blocker in cursor.fetchone()[0]:
                    return
            pause.wait(0.02)
        self.fail("Expected protected lock wait was not observed.")

    def worker(self, client, csrf, data, *, ready=None, saved=None, release=None):
        close_old_connections()
        prepared = False
        pid = None
        item_locked = False

        def inspect(execute, sql, params, many, context):
            nonlocal prepared, pid, item_locked
            if (
                not prepared
                and "organizations_organization" in sql
                and "FOR UPDATE" in sql
            ):
                prepared = True
                self.assertTrue(connection.in_atomic_block)
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '8s'")
                    cursor.execute("SET LOCAL statement_timeout = '12s'")
                    cursor.execute(
                        "SELECT current_database(), current_user, session_user, "
                        "pg_backend_pid()"
                    )
                    database, user, session_user, pid = cursor.fetchone()
                self.assertEqual(database, "test_orderdesk")
                self.assertEqual(user, session_user)
                if ready is not None:
                    ready.put(pid)
            if "catalog_catalogitem" in sql and "FOR UPDATE" in sql:
                item_locked = True
            result = execute(sql, params, many, context)
            if (
                sql.startswith("UPDATE")
                and "catalog_catalogitem" in sql
                and saved is not None
            ):
                self.assertTrue(item_locked)
                saved.put(pid)
                if not release.wait(10):
                    raise RuntimeError("Update race release timed out.")
            return result

        try:
            with connection.execute_wrapper(inspect):
                response = self.update(data, client=client, csrf=csrf)
            self.assert_clean()
            return response.status_code, response.json(), pid
        finally:
            connections["default"].close()

    def ordered_edits(self, first_data, second_data):
        first, csrf1 = self.login_client(self.admin)
        second, csrf2 = self.login_client(self.peer_admin)
        saved, ready, release = Queue(), Queue(), Event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(
                self.worker, first, csrf1, first_data, saved=saved, release=release
            )
            try:
                first_pid = saved.get(timeout=10)
                second_future = pool.submit(
                    self.worker, second, csrf2, second_data, ready=ready
                )
                second_pid = ready.get(timeout=10)
                self.assertNotEqual(first_pid, second_pid)
                self.assert_blocked(second_pid, first_pid)
            finally:
                release.set()
            results = [
                first_future.result(timeout=15),
                second_future.result(timeout=15),
            ]
        self.assertEqual([result[0] for result in results], [200, 200])
        self.item.refresh_from_db()
        self.assert_clean()
        return results

    def test_independent_fields_preserve_both_committed_changes(self):
        self.ordered_edits({"description": "First editor"}, {"is_active": False})
        self.assertEqual(
            (self.item.description, self.item.is_active), ("First editor", False)
        )

    def test_same_field_uses_serialized_last_write_wins(self):
        results = self.ordered_edits(
            {"description": "First editor"}, {"description": "Second editor"}
        )
        self.assertEqual(results[0][1]["description"], "First editor")
        self.assertEqual(results[1][1]["description"], "Second editor")
        self.assertEqual(self.item.description, "Second editor")

    def test_demotion_first_prevents_waiting_update(self):
        client, csrf = self.login_client(self.admin)
        ready = Queue()
        before = self.state()
        blocker = self.pid()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.a.pk)
                Membership.objects.filter(pk=self.admin_membership.pk).update(
                    role=MembershipRole.VIEWER
                )
                future = pool.submit(
                    self.worker, client, csrf, {"description": "Forbidden"}, ready=ready
                )
                waiter = ready.get(timeout=10)
                self.assertNotEqual(waiter, blocker)
                self.assert_blocked(waiter, blocker)
            status, body, _ = future.result(timeout=15)
        self.assertEqual(status, 403)
        self.assertEqual(body, {"detail": CATALOG_UPDATE_DENIED})
        self.assertEqual(self.state(), before)

    def test_update_first_commits_before_demotion_then_next_update_denied(self):
        client, csrf = self.login_client(self.admin)
        saved, ready, release = Queue(), Queue(), Event()

        def demote():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '8s'")
                        cursor.execute("SET LOCAL statement_timeout = '12s'")
                    ready.put(self.pid())
                    Organization.objects.select_for_update().get(pk=self.a.pk)
                    Membership.objects.filter(pk=self.admin_membership.pk).update(
                        role=MembershipRole.VIEWER
                    )
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            update = pool.submit(
                self.worker,
                client,
                csrf,
                {"description": "Protected winner"},
                saved=saved,
                release=release,
            )
            try:
                updater = saved.get(timeout=10)
                demotion = pool.submit(demote)
                waiter = ready.get(timeout=10)
                self.assertNotEqual(updater, waiter)
                self.assert_blocked(waiter, updater)
            finally:
                release.set()
            self.assertEqual(update.result(timeout=15)[0], 200)
            demotion.result(timeout=15)
        self.item.refresh_from_db()
        self.assertEqual(self.item.description, "Protected winner")
        self.assertEqual(self.update({"description": "Later request"}).status_code, 403)
        self.assert_clean()
