"""Native PostgreSQL HTTP creation races using independent connections."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Event
from time import monotonic

from django.db import close_old_connections, connection, connections, transaction

from apps.catalog.models import CatalogItem
from apps.catalog.tests.test_create_api import (
    DUPLICATE,
    NONADMIN_DENIAL,
    CatalogCreateTestCase,
)
from apps.organizations.models import Membership, MembershipRole, Organization


class CatalogCreateConcurrencyTests(CatalogCreateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(connection.vendor, "postgresql")

    @staticmethod
    def _pid() -> int:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.pg_backend_pid()")
            return cursor.fetchone()[0]

    def _prepare_request_transaction(self) -> int:
        # Request lifecycle signals can close a connection opened before POST.
        # Prepare the actual request connection inside its owned transaction.
        self.assertTrue(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '8s'")
            cursor.execute("SET LOCAL statement_timeout = '12s'")
            cursor.execute(
                "SELECT current_database(), current_user, session_user, "
                "pg_catalog.pg_backend_pid()"
            )
            database, current_user, session_user, pid = cursor.fetchone()
        self.assertEqual(database, connection.settings_dict["NAME"])
        self.assertEqual(current_user, connection.settings_dict["USER"])
        self.assertEqual(current_user, session_user)
        return pid

    def _assert_blocked(self, worker_pid: int, blocker_pid: int) -> None:
        deadline = monotonic() + 5
        pause = Event()
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_catalog.pg_blocking_pids(%s)", [worker_pid])
                if blocker_pid in cursor.fetchone()[0]:
                    return
            pause.wait(0.02)
        self.fail("The request did not wait for the protected organization lock.")

    def _post_worker(self, client, csrf, url, *, barrier=None, ready=None):
        close_old_connections()
        observed = False
        request_pid = None

        def inspect(execute, sql, params, many, context):
            nonlocal observed, request_pid
            if (
                not observed
                and '"organizations_organization"' in sql
                and "FOR UPDATE" in sql
            ):
                observed = True
                request_pid = self._prepare_request_transaction()
                if ready is not None:
                    ready.put(request_pid)
            return execute(sql, params, many, context)

        try:
            if barrier is not None:
                barrier.wait(timeout=10)
            with connection.execute_wrapper(inspect):
                response = client.post(
                    url,
                    {"sku": "CONCURRENT-PART"},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
            self.assertTrue(observed, "Creation did not use the organization lock.")
            self.assert_clean()
            return response.status_code, response.json(), request_pid
        finally:
            connections["default"].close()

    def test_simultaneous_same_workspace_posts_create_one_item_and_one_409(self):
        first, first_csrf = self.login_client(self.admin)
        second, second_csrf = self.login_client(self.admin)
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    self._post_worker, client, csrf, self.url, barrier=barrier
                )
                for client, csrf in ((first, first_csrf), (second, second_csrf))
            ]
            results = [future.result(timeout=25) for future in futures]
        self.assertCountEqual([status for status, _, _ in results], [201, 409])
        self.assertEqual(len({pid for _, _, pid in results}), 2)
        conflict = next(body for status, body, _ in results if status == 409)
        self.assertEqual(conflict, {"detail": DUPLICATE})
        self.assertEqual(
            CatalogItem.objects.filter(
                organization=self.a, sku="CONCURRENT-PART"
            ).count(),
            1,
        )
        self.assert_clean()

    def test_simultaneous_different_workspace_posts_can_reuse_the_same_sku(self):
        first, first_csrf = self.login_client(self.admin)
        second, second_csrf = self.login_client(self.admin)
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._post_worker, client, csrf, url, barrier=barrier)
                for client, csrf, url in (
                    (first, first_csrf, self.url),
                    (second, second_csrf, self.items_url(self.b)),
                )
            ]
            results = [future.result(timeout=25) for future in futures]
        self.assertEqual([status for status, _, _ in results], [201, 201])
        self.assertEqual(len({pid for _, _, pid in results}), 2)
        self.assertEqual(
            {body["organization_id"] for _, body, _ in results},
            {str(self.a.pk), str(self.b.pk)},
        )
        self.assertEqual(CatalogItem.objects.filter(sku="CONCURRENT-PART").count(), 2)
        self.assert_clean()

    def test_demotion_committed_before_protected_authorization_denies_waiting_creation(
        self,
    ):
        client, csrf = self.login_client(self.admin)
        ready = Queue()
        blocker = self._pid()
        # This matches the repository's established membership-change lock order.
        # There is currently no public demotion service to call.
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.a.pk)
                Membership.objects.filter(pk=self.admin_membership.pk).update(
                    role=MembershipRole.VIEWER
                )
                future = executor.submit(
                    self._post_worker, client, csrf, self.url, ready=ready
                )
                worker_pid = ready.get(timeout=10)
                self.assertNotEqual(worker_pid, blocker)
                self._assert_blocked(worker_pid, blocker)
            status, body, _ = future.result(timeout=15)
        self.assertEqual(status, 403)
        self.assertEqual(body, {"detail": NONADMIN_DENIAL})
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assert_clean()

    def test_creation_winning_org_lock_commits_before_later_demotion(self):
        client, csrf = self.login_client(self.admin)
        inserted = Queue()
        demoter_ready = Queue()
        release_creation = Event()

        def create():
            close_old_connections()
            prepared = False
            request_pid = None

            def hold_after_insert(execute, sql, params, many, context):
                nonlocal prepared, request_pid
                if (
                    not prepared
                    and '"organizations_organization"' in sql
                    and "FOR UPDATE" in sql
                ):
                    prepared = True
                    request_pid = self._prepare_request_transaction()
                result = execute(sql, params, many, context)
                if sql.startswith("INSERT INTO") and '"catalog_catalogitem"' in sql:
                    # The real INSERT has executed while the organization lock
                    # remains held. Instrument timing without replacing SQL/auth.
                    self.assertTrue(prepared)
                    inserted.put(request_pid)
                    if not release_creation.wait(timeout=10):
                        raise RuntimeError("The creation race release timed out.")
                return result

            try:
                with connection.execute_wrapper(hold_after_insert):
                    response = client.post(
                        self.url,
                        {"sku": "CREATION-FIRST"},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                self.assert_clean()
                return response.status_code, response.json()
            finally:
                connections["default"].close()

        def demote():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                    cursor.execute("SET statement_timeout = '12s'")
                demoter_ready.put(self._pid())
                with transaction.atomic():
                    Organization.objects.select_for_update().get(pk=self.a.pk)
                    Membership.objects.filter(pk=self.admin_membership.pk).update(
                        role=MembershipRole.VIEWER
                    )
                return "demoted"
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            creation = executor.submit(create)
            try:
                creator_pid = inserted.get(timeout=10)
                demotion = executor.submit(demote)
                demoter_pid = demoter_ready.get(timeout=10)
                self.assertNotEqual(creator_pid, demoter_pid)
                self._assert_blocked(demoter_pid, creator_pid)
            finally:
                release_creation.set()
            status, body = creation.result(timeout=15)
            self.assertEqual(demotion.result(timeout=15), "demoted")
        self.assertEqual(status, 201)
        self.assertEqual(body["organization_id"], str(self.a.pk))
        self.assertEqual(
            CatalogItem.objects.filter(
                organization=self.a, sku="CREATION-FIRST"
            ).count(),
            1,
        )
        self.admin_membership.refresh_from_db()
        self.assertEqual(self.admin_membership.role, MembershipRole.VIEWER)
        denied = self.post({"sku": "AFTER-DEMOTION"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json(), {"detail": NONADMIN_DENIAL})
        self.assertEqual(CatalogItem.objects.count(), 1)
        self.assert_clean()
