"""Atomic imports and durable replay on independent PostgreSQL connections."""

import csv
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from queue import Queue
from threading import Barrier, Event
from time import monotonic
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, connections, transaction

from apps.catalog.models import CatalogImportReceipt, CatalogItem
from apps.catalog.tests.test_create_api import CatalogCreateTestCase
from apps.organizations.models import Membership, MembershipRole, Organization

IMPORT_DENIAL = (
    "You do not have permission to import catalogue items in this workspace."
)


class CatalogImportConcurrencyTests(CatalogCreateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(connection.vendor, "postgresql")

    @staticmethod
    def csv_bytes(*skus: str) -> bytes:
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("sku", "description", "is_active"))
        writer.writerows((sku, "Synthetic concurrency item", "") for sku in skus)
        return output.getvalue().encode("utf-8")

    @staticmethod
    def import_url(workspace: Organization) -> str:
        return f"/api/v1/workspaces/{workspace.pk}/catalog/imports/"

    @staticmethod
    def pid() -> int:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            return cursor.fetchone()[0]

    def prepare_request(self) -> int:
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
        self.assertEqual(user, connection.settings_dict["USER"])
        self.assertEqual(user, session_user)
        return pid

    def assert_blocked(self, waiter: int, blocker: int) -> None:
        deadline = monotonic() + 5
        pause = Event()
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_blocking_pids(%s)", [waiter])
                if blocker in cursor.fetchone()[0]:
                    return
            pause.wait(0.02)
        self.fail("A protected import lock wait was not observed.")

    def worker(
        self,
        client,
        csrf,
        raw,
        key,
        *,
        workspace=None,
        barrier=None,
        ready=None,
        inserted=None,
        release=None,
        fail_after_first=False,
        single=False,
    ):
        close_old_connections()
        prepared = False
        held = False
        request_pid = None

        def inspect(execute, sql, params, many, context):
            nonlocal prepared, held, request_pid
            if (
                not prepared
                and "organizations_organization" in sql
                and "FOR UPDATE" in sql
            ):
                prepared = True
                request_pid = self.prepare_request()
                if ready is not None:
                    ready.put(request_pid)
            result = execute(sql, params, many, context)
            if not held and sql.startswith("INSERT") and '"catalog_catalogitem"' in sql:
                held = True
                if inserted is not None:
                    inserted.put(request_pid)
                if release is not None and not release.wait(10):
                    raise RuntimeError("The import race release timed out.")
                if fail_after_first:
                    raise ValueError(
                        "Synthetic first import rolls back after insertion."
                    )
            return result

        try:
            if barrier is not None:
                barrier.wait(timeout=10)
            with connection.execute_wrapper(inspect):
                if single:
                    response = client.post(
                        self.items_url(workspace or self.a),
                        {"sku": raw},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                else:
                    response = client.post(
                        self.import_url(workspace or self.a),
                        {"file": SimpleUploadedFile("synthetic.csv", raw)},
                        format="multipart",
                        HTTP_X_CSRFTOKEN=csrf,
                        HTTP_IDEMPOTENCY_KEY=str(key),
                    )
            self.assertTrue(
                prepared, "Import did not use the protected organization lock."
            )
            self.assert_clean()
            if fail_after_first:
                self.assertTrue(
                    held, "The intentional failure preceded the real INSERT."
                )
                self.assertEqual(response.status_code, 500)
                return "rolled_back", None, request_pid, None
            self.assertLess(response.status_code, 500)
            return (
                response.status_code,
                response.json(),
                request_pid,
                response.get("Idempotency-Replayed"),
            )
        finally:
            connections["default"].close()

    def race(self, requests):
        first, token1 = self.login_client(self.admin)
        second, token2 = self.login_client(self.peer_admin)
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    self.worker, client, token, raw, key, barrier=barrier, **options
                )
                for (client, token), (raw, key, options) in zip(
                    ((first, token1), (second, token2)), requests, strict=True
                )
            ]
            results = [future.result(timeout=25) for future in futures]
        self.assertEqual(len({result[2] for result in results}), 2)
        self.assertFalse(
            CatalogImportReceipt.objects.filter(state="processing").exists()
        )
        self.assert_clean()
        return results

    def test_same_key_same_file_commits_once_and_waiter_replays(self):
        key = uuid4()
        raw = self.csv_bytes("SAME-KEY-A", "SAME-KEY-B")
        results = self.race(((raw, key, {}), (raw, key, {})))
        self.assertCountEqual([result[0] for result in results], [201, 200])
        self.assertEqual(results[0][1], results[1][1])
        self.assertCountEqual([result[3] for result in results], ["false", "true"])
        self.assertEqual(CatalogItem.objects.count(), 2)
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)

    def test_same_key_different_files_has_one_success_and_one_key_conflict(self):
        key = uuid4()
        results = self.race(
            (
                (self.csv_bytes("FIRST-A", "FIRST-B"), key, {}),
                (self.csv_bytes("SECOND-A", "SECOND-B"), key, {}),
            )
        )
        self.assertCountEqual([result[0] for result in results], [201, 409])
        winner = next(result[1] for result in results if result[0] == 201)
        conflict = next(result[1] for result in results if result[0] == 409)
        self.assertEqual(
            conflict,
            {
                "detail": (
                    "This idempotency key has already been used for a different "
                    "catalogue import."
                )
            },
        )
        self.assertEqual(CatalogItem.objects.count(), 2)
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)
        self.assertEqual(
            set(CatalogItem.objects.values_list("sku", flat=True)),
            {item["sku"] for item in winner["items"]},
        )

    def test_different_keys_overlapping_skus_leave_one_complete_import(self):
        results = self.race(
            (
                (self.csv_bytes("OVERLAP", "UNIQUE-A"), uuid4(), {}),
                (self.csv_bytes("OVERLAP", "UNIQUE-B"), uuid4(), {}),
            )
        )
        self.assertCountEqual([result[0] for result in results], [201, 409])
        winner = next(result[1] for result in results if result[0] == 201)
        self.assertEqual(CatalogItem.objects.count(), 2)
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)
        self.assertEqual(
            set(CatalogItem.objects.values_list("sku", flat=True)),
            {item["sku"] for item in winner["items"]},
        )

    def test_same_key_and_skus_in_different_workspaces_remain_independent(self):
        # Both sessions belong to the administrator who can access A and B.
        first, csrf1 = self.login_client(self.admin)
        second, csrf2 = self.login_client(self.admin)
        key, raw, barrier = uuid4(), self.csv_bytes("CROSS-WORKSPACE"), Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    self.worker,
                    client,
                    token,
                    raw,
                    key,
                    workspace=workspace,
                    barrier=barrier,
                )
                for client, token, workspace in (
                    (first, csrf1, self.a),
                    (second, csrf2, self.b),
                )
            ]
            results = [future.result(timeout=25) for future in futures]
        self.assertEqual([result[0] for result in results], [201, 201])
        self.assertEqual(len({result[2] for result in results}), 2)
        self.assertEqual(CatalogItem.objects.count(), 2)
        self.assertEqual(CatalogImportReceipt.objects.count(), 2)
        self.assertEqual(
            {result[1]["organization_id"] for result in results},
            {str(self.a.pk), str(self.b.pk)},
        )
        self.assert_clean()

    def test_import_racing_single_creation_preserves_uniqueness_and_atomicity(self):
        results = self.race(
            (
                (self.csv_bytes("SINGLE-OVERLAP", "UNIQUE-IMPORT"), uuid4(), {}),
                ("SINGLE-OVERLAP", None, {"single": True}),
            )
        )
        self.assertCountEqual([result[0] for result in results], [201, 409])
        import_won = results[0][0] == 201
        self.assertEqual(CatalogItem.objects.count(), 2 if import_won else 1)
        self.assertEqual(CatalogImportReceipt.objects.count(), int(import_won))
        self.assertEqual(CatalogItem.objects.filter(sku="SINGLE-OVERLAP").count(), 1)
        self.assertIs(
            CatalogItem.objects.filter(sku="UNIQUE-IMPORT").exists(), import_won
        )

    def test_demotion_winning_org_lock_denies_waiting_import_without_receipt(self):
        client, csrf = self.login_client(self.admin)
        ready = Queue()
        blocker = self.pid()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.a.pk)
                Membership.objects.filter(pk=self.admin_membership.pk).update(
                    role=MembershipRole.VIEWER
                )
                pending = pool.submit(
                    self.worker,
                    client,
                    csrf,
                    self.csv_bytes("DENIED-A", "DENIED-B"),
                    uuid4(),
                    ready=ready,
                )
                waiter = ready.get(timeout=10)
                self.assertNotEqual(waiter, blocker)
                self.assert_blocked(waiter, blocker)
            status, body, _, _ = pending.result(timeout=15)
        self.assertEqual(status, 403)
        self.assertEqual(body, {"detail": IMPORT_DENIAL})
        self.assertEqual(CatalogItem.objects.count(), 0)
        self.assertEqual(CatalogImportReceipt.objects.count(), 0)
        self.assert_clean()

    def test_import_winning_org_lock_commits_before_demotion_then_replay_is_denied(
        self,
    ):
        client, csrf = self.login_client(self.admin)
        inserted, ready, release = Queue(), Queue(), Event()
        raw, key = self.csv_bytes("PROTECTED-A", "PROTECTED-B"), uuid4()

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
            execution = pool.submit(
                self.worker, client, csrf, raw, key, inserted=inserted, release=release
            )
            try:
                importer = inserted.get(timeout=10)
                demotion = pool.submit(demote)
                waiter = ready.get(timeout=10)
                self.assertNotEqual(importer, waiter)
                self.assert_blocked(waiter, importer)
            finally:
                release.set()
            self.assertEqual(execution.result(timeout=15)[0], 201)
            demotion.result(timeout=15)
        self.assertEqual(CatalogItem.objects.count(), 2)
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)
        response = self.client.post(
            self.import_url(self.a),
            {"file": SimpleUploadedFile("retry.csv", raw)},
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IDEMPOTENCY_KEY=str(key),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": IMPORT_DENIAL})
        self.assert_clean()

    def test_rollback_first_attempt_releases_same_key_for_waiting_import(self):
        first, csrf1 = self.login_client(self.admin)
        second, csrf2 = self.login_client(self.peer_admin)
        # Django's test-client exception signal is process-wide. Capturing the
        # intentional first request's 500 as a response prevents its exception
        # from being re-raised by the concurrent successful waiter client.
        first.raise_request_exception = False
        second.raise_request_exception = False
        inserted, ready, release = Queue(), Queue(), Event()
        raw, key = self.csv_bytes("ROLLBACK-A", "ROLLBACK-B"), uuid4()
        with ThreadPoolExecutor(max_workers=2) as pool:
            failing = pool.submit(
                self.worker,
                first,
                csrf1,
                raw,
                key,
                inserted=inserted,
                release=release,
                fail_after_first=True,
            )
            try:
                first_pid = inserted.get(timeout=10)
                waiting = pool.submit(self.worker, second, csrf2, raw, key, ready=ready)
                waiter = ready.get(timeout=10)
                self.assertNotEqual(first_pid, waiter)
                self.assert_blocked(waiter, first_pid)
            finally:
                release.set()
            self.assertEqual(failing.result(timeout=15)[0], "rolled_back")
            success = waiting.result(timeout=15)
        self.assertEqual(success[0], 201)
        self.assertEqual(success[3], "false")
        self.assertEqual(CatalogItem.objects.count(), 2)
        self.assertEqual(CatalogImportReceipt.objects.count(), 1)
        self.assertEqual(
            set(CatalogItem.objects.values_list("sku", flat=True)),
            {"ROLLBACK-A", "ROLLBACK-B"},
        )
        self.assertFalse(
            CatalogImportReceipt.objects.filter(state="processing").exists()
        )
        self.assert_clean()
