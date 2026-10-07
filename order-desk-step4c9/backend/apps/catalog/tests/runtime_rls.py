"""Run explicitly via verify_catalog_rls, never under the owner's Django runner.

The default connection authenticates as orderdesk_app. The separate owner alias
only creates/changes/cleans synthetic fixtures in the guarded test database.
Some tests intentionally forge local settings to bypass application checks and
exercise the database policies themselves; never copy that into services.
"""

import csv
import unittest
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from datetime import timedelta
from io import StringIO
from ipaddress import IPv6Address
from queue import Queue
from secrets import token_urlsafe
from threading import Barrier, Event
from time import monotonic
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.sessions.models import Session
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.db.models import Q
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts.login_limits import login_bucket_key
from apps.accounts.models import LoginAttemptBucket, User
from apps.catalog.models import CatalogImportReceipt, CatalogItem
from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.transactions import TenantScopeError, tenant_scope

OWNER_ALIAS = "catalog_rls_owner"


@contextmanager
def _forged_policy_context(
    organization_id: UUID | str | None, user_id: UUID | str | None
) -> Iterator[None]:
    """Test-only bypass of app authorization, including invalid/missing settings."""
    with transaction.atomic(durable=True):
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE")
            for key, value in (
                ("orderdesk.organization_id", organization_id),
                ("orderdesk.user_id", user_id),
            ):
                if value is not None:
                    cursor.execute(
                        "SELECT pg_catalog.set_config(%s, %s, true)", [key, str(value)]
                    )
        yield


class RuntimeCatalogRLSChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.user_ids: list[UUID] = []
        self.workspace_ids: list[UUID] = []
        self.session_keys: set[str] = set()
        self.login_bucket_keys: set[str] = set()
        self.addCleanup(self._cleanup_fixtures)
        with transaction.atomic(using=OWNER_ALIAS):
            self.admin = self._user()
            self.viewer = self._user()
            self.reviewer = self._user()
            self.outsider = self._user(is_staff=True, is_superuser=True)
            self.a = self._workspace("Synthetic distributor A")
            self.b = self._workspace("Synthetic distributor B")
            self.admin_membership = self._membership(
                self.admin, self.a, MembershipRole.ADMIN
            )
            self._membership(self.admin, self.b, MembershipRole.ADMIN)
            self._membership(self.viewer, self.a, MembershipRole.VIEWER)
            self._membership(self.reviewer, self.a, MembershipRole.REVIEWER)
            self.item_a = CatalogItem.objects.using(OWNER_ALIAS).create(
                organization=self.a, sku="PART-001", description="Fixture A"
            )
            self.archived_a = CatalogItem.objects.using(OWNER_ALIAS).create(
                organization=self.a, sku="ARCH-001", is_active=False
            )
            self.item_b = CatalogItem.objects.using(OWNER_ALIAS).create(
                organization=self.b, sku="PART-001", description="Fixture B"
            )

    def _user(self, **flags: bool) -> User:
        user = User.objects.db_manager(OWNER_ALIAS).create_user(
            email=f"rls-{uuid4().hex}@example.test", **flags
        )
        self.user_ids.append(user.pk)
        return user

    def _workspace(self, name: str) -> Organization:
        workspace = Organization.objects.using(OWNER_ALIAS).create(name=name)
        self.workspace_ids.append(workspace.pk)
        return workspace

    @staticmethod
    def _membership(
        user: User, workspace: Organization, role: MembershipRole
    ) -> Membership:
        return Membership.objects.using(OWNER_ALIAS).create(
            user=user, organization=workspace, role=role
        )

    def _cleanup_fixtures(self) -> None:
        # Close the runtime session first, releasing any failed transaction/locks.
        connection.close()
        with transaction.atomic(using=OWNER_ALIAS):
            CatalogImportReceipt.objects.using(OWNER_ALIAS).filter(
                organization_id__in=self.workspace_ids
            ).delete()
            Session.objects.using(OWNER_ALIAS).filter(
                session_key__in=self.session_keys
            ).delete()
            LoginAttemptBucket.objects.using(OWNER_ALIAS).filter(
                key__in=self.login_bucket_keys
            ).delete()
            CatalogItem.objects.using(OWNER_ALIAS).filter(
                organization_id__in=self.workspace_ids
            ).delete()
            Membership.objects.using(OWNER_ALIAS).filter(
                organization_id__in=self.workspace_ids
            ).delete()
            Organization.objects.using(OWNER_ALIAS).filter(
                pk__in=self.workspace_ids
            ).delete()
            User.objects.using(OWNER_ALIAS).filter(pk__in=self.user_ids).delete()

    @staticmethod
    def _visible_ids() -> set[UUID]:
        # Deliberately no organization filter: this asserts the independent RLS gate.
        return set(CatalogItem.objects.values_list("id", flat=True))

    @staticmethod
    def _context_ids() -> tuple[str | None, str | None]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(pg_catalog.current_setting("
                "'orderdesk.organization_id', true), ''), "
                "NULLIF(pg_catalog.current_setting('orderdesk.user_id', true), '')"
            )
            return cursor.fetchone()

    @staticmethod
    def _pid() -> int:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.pg_backend_pid()")
            return cursor.fetchone()[0]

    @staticmethod
    def _execute(statement: str) -> None:
        with connection.cursor() as cursor:
            cursor.execute(statement)

    def _assert_clean(self) -> None:
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        self.assertEqual(self._context_ids(), (None, None))
        self.assertEqual(self._visible_ids(), set())

    def _expect_error(
        self, state: str, scope: AbstractContextManager, action: Callable[[], object]
    ) -> None:
        with self.assertRaises(DatabaseError) as error:
            with scope:
                action()
                # Unexpected success must ALSO roll back, especially for DDL.
                self.fail("A forbidden database operation unexpectedly succeeded.")
        self.assertEqual(error.exception.__cause__.sqlstate, state)
        self._assert_clean()

    @staticmethod
    def _item_url(workspace: Organization, item_id: UUID) -> str:
        return f"/api/v1/workspaces/{workspace.pk}/catalog/items/{item_id}/"

    @staticmethod
    def _direct_catalogue_patch(
        client: APIClient,
        workspace: Organization,
        item_id: UUID,
        csrf: str,
        payload: object,
    ):
        # Keep real cookie/session authentication and CSRF, omitting only the
        # lifecycle signals that would replace the underlying runtime driver.
        from apps.catalog.views import CatalogItemUpdateView

        request = APIRequestFactory(enforce_csrf_checks=True).patch(
            f"/api/v1/workspaces/{workspace.pk}/catalog/items/{item_id}/",
            payload,
            format="json",
            HTTP_HOST="localhost",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_COOKIE=client.cookies.output(header="", sep=";").strip(),
        )
        SessionMiddleware(lambda _: None).process_request(request)
        AuthenticationMiddleware(lambda _: None).process_request(request)
        return CatalogItemUpdateView.as_view()(
            request, workspace_id=workspace.pk, item_id=item_id
        )

    def _assert_updated(
        self, response, workspace: Organization, item: CatalogItem
    ) -> dict:
        self.assertEqual(response.status_code, 200)
        self._assert_private(response)
        data = response.json()
        self.assertEqual(
            set(data),
            {
                "id",
                "organization_id",
                "sku",
                "description",
                "is_active",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(data["id"], str(item.pk))
        self.assertEqual(data["organization_id"], str(workspace.pk))
        self.assertEqual(data["sku"], item.sku)
        self._assert_clean()
        return data

    def _prepare_patch_transaction(self) -> int:
        # Execute inside the actual HTTP write transaction, after request
        # signals have closed any pre-existing CONN_MAX_AGE=0 connection.
        self.assertTrue(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '8s'")
            cursor.execute("SET LOCAL statement_timeout = '12s'")
            cursor.execute("SELECT current_user, session_user, pg_backend_pid()")
            identity = cursor.fetchone()
        self.assertEqual(identity[:2], ("orderdesk_app", "orderdesk_app"))
        return identity[2]

    def _assert_native_blocked(self, blocked_pid: int, blocking_pid: int) -> None:
        deadline = monotonic() + 4
        pause = Event()
        while monotonic() < deadline:
            with connections[OWNER_ALIAS].cursor() as cursor:
                cursor.execute("SELECT pg_blocking_pids(%s)", [blocked_pid])
                if blocking_pid in cursor.fetchone()[0]:
                    return
            pause.wait(0.02)
        self.fail("The HTTP update race did not acquire the expected native lock.")

    @staticmethod
    def _sku_url(workspace: Organization) -> str:
        return f"/api/v1/workspaces/{workspace.pk}/catalog/items/by-sku/"

    @staticmethod
    def _direct_catalogue_search(
        client: APIClient, workspace: Organization, query: dict, *, exact: bool = False
    ):
        from apps.catalog.views import CatalogItemBySKUView, CatalogItemListView

        suffix = "by-sku/" if exact else ""
        request = APIRequestFactory().get(
            f"/api/v1/workspaces/{workspace.pk}/catalog/items/{suffix}",
            query,
            HTTP_HOST="localhost",
            HTTP_COOKIE=client.cookies.output(header="", sep=";").strip(),
        )
        SessionMiddleware(lambda _: None).process_request(request)
        AuthenticationMiddleware(lambda _: None).process_request(request)
        view = CatalogItemBySKUView if exact else CatalogItemListView
        return view.as_view()(request, workspace_id=workspace.pk)

    def _assert_exact_item(
        self, response, workspace: Organization, item: CatalogItem
    ) -> dict:
        data = self._assert_updated(response, workspace, item)
        self.assertEqual(data["description"], item.description)
        self.assertIs(data["is_active"], item.is_active)
        return data

    def _write_scope(self, user: User | None = None) -> AbstractContextManager:
        return tenant_scope(user=user or self.admin, workspace_id=self.a.pk, write=True)

    def _insert(self, workspace: Organization, sku: str = "NEW-ITEM") -> CatalogItem:
        return CatalogItem.objects.create(organization_id=workspace.pk, sku=sku)

    @staticmethod
    def _items_url(workspace: Organization) -> str:
        return f"/api/v1/workspaces/{workspace.pk}/catalog/items/"

    def _credential_client(self, actor: User) -> tuple[APIClient, str]:
        credential = f"Synthetic-catalogue-RLS-{uuid4().hex}"
        actor.set_password(credential)
        actor.save(using=OWNER_ALIAS, update_fields=["password"])
        peer = IPv6Address(
            int(IPv6Address("2001:db8::")) | (uuid4().int & ((1 << 96) - 1))
        ).compressed
        self.login_bucket_keys.update(
            (login_bucket_key("email", actor.email), login_bucket_key("peer", peer))
        )
        client = APIClient(
            enforce_csrf_checks=True, HTTP_HOST="localhost", REMOTE_ADDR=peer
        )
        csrf = client.get("/api/v1/auth/csrf/")
        self.assertEqual(csrf.status_code, 200)
        login = client.post(
            "/api/v1/auth/login/",
            {"email": actor.email, "password": credential},
            format="json",
            HTTP_X_CSRFTOKEN=csrf.json()["csrf_token"],
        )
        cookie = client.cookies.get(settings.SESSION_COOKIE_NAME)
        if cookie is not None:
            self.session_keys.add(cookie.value)
        self.assertEqual(login.status_code, 200)
        self.assertIsNotNone(cookie)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user, session_user")
            self.assertEqual(cursor.fetchone(), ("orderdesk_app", "orderdesk_app"))
        return client, login.json()["csrf_token"]

    def _assert_private(self, response) -> None:
        directives = {part.strip() for part in response["Cache-Control"].split(",")}
        self.assertTrue({"private", "no-store", "no-cache"} <= directives)

    def _assert_catalogue_response(
        self, response, workspace: Organization, ids: set[UUID]
    ) -> None:
        self.assertEqual(response.status_code, 200)
        self._assert_private(response)
        data = response.json()
        self.assertEqual(set(data), {"count", "next", "previous", "results"})
        self.assertEqual(data["count"], len(ids))
        self.assertEqual({row["id"] for row in data["results"]}, {str(i) for i in ids})
        allowed = {
            "id",
            "organization_id",
            "sku",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        }
        for row in data["results"]:
            self.assertEqual(set(row), allowed)
            self.assertEqual(row["organization_id"], str(workspace.pk))

    @staticmethod
    def _direct_catalogue_read(client: APIClient, workspace: Organization):
        # Keep Django's normal session and authentication middleware while
        # omitting request lifecycle signals that close CONN_MAX_AGE=0 sessions.
        # This proves commit/rollback cleanup on the same real database connection.
        from apps.catalog.views import CatalogItemListView

        request = APIRequestFactory().get(
            f"/api/v1/workspaces/{workspace.pk}/catalog/items/",
            HTTP_HOST="localhost",
            HTTP_COOKIE=client.cookies.output(header="", sep=";").strip(),
        )
        SessionMiddleware(lambda _: None).process_request(request)
        AuthenticationMiddleware(lambda _: None).process_request(request)
        return CatalogItemListView.as_view()(request, workspace_id=workspace.pk)

    @staticmethod
    def _direct_catalogue_post(
        client: APIClient, workspace: Organization, csrf: str, payload: object
    ):
        from apps.catalog.views import CatalogItemListView

        request = APIRequestFactory(enforce_csrf_checks=True).post(
            f"/api/v1/workspaces/{workspace.pk}/catalog/items/",
            payload,
            format="json",
            HTTP_HOST="localhost",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_COOKIE=client.cookies.output(header="", sep=";").strip(),
        )
        SessionMiddleware(lambda _: None).process_request(request)
        AuthenticationMiddleware(lambda _: None).process_request(request)
        return CatalogItemListView.as_view()(request, workspace_id=workspace.pk)

    def _assert_created(self, response, workspace: Organization, sku: str) -> dict:
        self.assertEqual(response.status_code, 201)
        self._assert_private(response)
        data = response.json()
        self.assertEqual(
            set(data),
            {
                "id",
                "organization_id",
                "sku",
                "description",
                "is_active",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(data["organization_id"], str(workspace.pk))
        self.assertEqual(data["sku"], sku)
        UUID(data["id"])
        self._assert_clean()
        return data

    def _http_creation_race(
        self, source: APIClient, csrf: str, sku: str, workspaces: tuple
    ) -> list:
        start = Barrier(2, timeout=10)

        def attempt(workspace: Organization) -> dict:
            client = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")
            client.cookies.update(source.cookies)
            observed = []
            close_old_connections()

            def inspect(execute, statement, params, many, context):
                if (
                    '"organizations_organization"' in statement
                    and "FOR UPDATE" in statement
                ):
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        cursor.execute("SET LOCAL statement_timeout = '10s'")
                if statement.startswith('INSERT INTO "catalog_catalogitem"'):
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT current_user, session_user, pg_backend_pid(), "
                            "current_setting('transaction_read_only'), "
                            "current_setting('orderdesk.organization_id'), "
                            "current_setting('orderdesk.user_id')"
                        )
                        observed.append(cursor.fetchone())
                return execute(statement, params, many, context)

            try:
                start.wait()
                with connection.execute_wrapper(inspect):
                    response = client.post(
                        self._items_url(workspace),
                        {"sku": sku},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                self.assertEqual(len(observed), 1)
                identity = observed[0]
                self.assertEqual(identity[:2], ("orderdesk_app", "orderdesk_app"))
                self.assertEqual(
                    identity[3:], ("off", str(workspace.pk), str(self.admin.pk))
                )
                self._assert_clean()
                return {
                    "status": response.status_code,
                    "data": response.json(),
                    "pid": identity[2],
                }
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt, workspace) for workspace in workspaces]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(len({result["pid"] for result in results}), 2)
        self._assert_clean()
        return results

    def test_missing_both_context_ids_exposes_no_rows(self) -> None:
        self._assert_clean()
        self.assertEqual(
            CatalogItem.objects.filter(pk=self.item_a.pk).update(description="X"), 0
        )

    def test_missing_or_blank_either_id_exposes_no_rows_and_denies_writes(self) -> None:
        for organization_id, user_id in (
            (None, None),
            (None, self.admin.pk),
            (self.a.pk, None),
            ("", self.admin.pk),
            (self.a.pk, ""),
            ("", ""),
        ):
            with self.subTest(organization=organization_id, user=user_id):
                with _forged_policy_context(organization_id, user_id):
                    self.assertEqual(self._visible_ids(), set())
                    self.assertEqual(
                        CatalogItem.objects.filter(pk=self.item_a.pk).update(
                            description="X"
                        ),
                        0,
                    )
                self._expect_error(
                    "42501",
                    _forged_policy_context(organization_id, user_id),
                    lambda: self._insert(self.a),
                )

    def test_unfiltered_scope_a_only_returns_a_including_inactive_items(self) -> None:
        with tenant_scope(user=self.admin, workspace_id=self.a.pk):
            self.assertEqual(self._visible_ids(), {self.item_a.pk, self.archived_a.pk})
        self._assert_clean()

    def test_membership_in_b_does_not_make_b_visible_in_scope_a(self) -> None:
        with self._write_scope():
            with self.assertRaises(CatalogItem.DoesNotExist):
                CatalogItem.objects.get(pk=self.item_b.pk)
            self.assertEqual(
                CatalogItem.objects.filter(pk=self.item_b.pk).update(description="X"), 0
            )

    def test_cross_workspace_insert_is_rejected_for_admin_of_both(self) -> None:
        self._expect_error("42501", self._write_scope(), lambda: self._insert(self.b))

    def test_existing_item_cannot_be_moved_into_another_workspace(self) -> None:
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: CatalogItem.objects.filter(pk=self.item_a.pk).update(
                organization_id=self.b.pk
            ),
        )
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.organization_id, self.a.pk)

    def test_cross_workspace_bulk_insert_aborts_the_whole_statement(self) -> None:
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: CatalogItem.objects.bulk_create(
                [
                    CatalogItem(organization_id=self.a.pk, sku="BULK-A"),
                    CatalogItem(organization_id=self.b.pk, sku="BULK-B"),
                ]
            ),
        )
        self.assertFalse(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization=self.a, sku="BULK-A")
            .exists()
        )

    def test_viewer_and_reviewer_can_read_their_catalogue(self) -> None:
        for user in (self.viewer, self.reviewer):
            with self.subTest(user=user.pk):
                with tenant_scope(user=user, workspace_id=self.a.pk):
                    self.assertEqual(
                        self._visible_ids(), {self.item_a.pk, self.archived_a.pk}
                    )

    def test_viewer_and_reviewer_cannot_insert(self) -> None:
        for user in (self.viewer, self.reviewer):
            with self.subTest(user=user.pk):
                self._expect_error(
                    "42501", self._write_scope(user), lambda: self._insert(self.a)
                )

    def test_viewer_and_reviewer_updates_affect_no_rows(self) -> None:
        for user in (self.viewer, self.reviewer):
            with self.subTest(user=user.pk):
                with self._write_scope(user):
                    self.assertEqual(
                        CatalogItem.objects.filter(pk=self.item_a.pk).update(
                            description="X"
                        ),
                        0,
                    )
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Fixture A")

    def test_a_forged_role_setting_does_not_grant_admin_access(self) -> None:
        with self._write_scope(self.viewer):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_catalog.set_config('orderdesk.role', 'admin', true)"
                )
            self.assertEqual(
                CatalogItem.objects.filter(pk=self.item_a.pk).update(description="X"), 0
            )

    def test_admin_can_create_update_and_deactivate_only_its_own_item(self) -> None:
        with self._write_scope():
            item = self._insert(self.a)
            self.assertEqual(
                CatalogItem.objects.filter(pk=item.pk).update(
                    description="Updated", is_active=False
                ),
                1,
            )
            self.assertIn(item.pk, self._visible_ids())
        item.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(item.description, "Updated")
        self.assertFalse(item.is_active)

    def test_duplicate_sku_within_workspace_is_rejected(self) -> None:
        self._expect_error(
            "23505", self._write_scope(), lambda: self._insert(self.a, "PART-001")
        )

    def test_same_sku_across_workspaces_is_valid_and_case_is_preserved(self) -> None:
        with self._write_scope():
            different_case = self._insert(self.a, "part-001")
            self.assertEqual(different_case.sku, "part-001")
            self.assertIn(self.item_a.pk, self._visible_ids())
        with tenant_scope(user=self.admin, workspace_id=self.b.pk):
            self.assertEqual(self._visible_ids(), {self.item_b.pk})

    def test_inactive_item_still_reserves_its_sku(self) -> None:
        self._expect_error(
            "23505", self._write_scope(), lambda: self._insert(self.a, "ARCH-001")
        )

    def test_database_nonblank_constraint_applies_to_runtime_inserts(self) -> None:
        self._expect_error(
            "23514", self._write_scope(), lambda: self._insert(self.a, "\t\n")
        )

    def test_nonmember_operator_flags_do_not_bypass_database_membership(self) -> None:
        with _forged_policy_context(self.a.pk, self.outsider.pk):
            self.assertEqual(self._visible_ids(), set())
        self._expect_error(
            "42501",
            _forged_policy_context(self.a.pk, self.outsider.pk),
            lambda: self._insert(self.a),
        )

    def test_unknown_organization_or_actor_fails_closed(self) -> None:
        for organization_id, user_id in (
            (uuid4(), self.admin.pk),
            (self.a.pk, uuid4()),
        ):
            with self.subTest(organization=organization_id, user=user_id):
                with _forged_policy_context(organization_id, user_id):
                    self.assertEqual(self._visible_ids(), set())

    def test_disabled_account_invalidates_existing_policy_context(self) -> None:
        with _forged_policy_context(self.a.pk, self.admin.pk):
            self.assertTrue(self._visible_ids())
            User.objects.using(OWNER_ALIAS).filter(pk=self.admin.pk).update(
                is_active=False
            )
            self.assertEqual(self._visible_ids(), set())
            self.assertEqual(
                CatalogItem.objects.filter(pk=self.item_a.pk).update(description="X"), 0
            )

    def test_revoked_membership_invalidates_existing_policy_context(self) -> None:
        with _forged_policy_context(self.a.pk, self.admin.pk):
            self.assertTrue(self._visible_ids())
            with transaction.atomic(using=OWNER_ALIAS):
                Organization.objects.using(OWNER_ALIAS).select_for_update().get(
                    pk=self.a.pk
                )
                Membership.objects.using(OWNER_ALIAS).filter(
                    pk=self.admin_membership.pk
                ).update(is_active=False)
            self.assertEqual(self._visible_ids(), set())

    def test_inactive_organization_invalidates_existing_policy_context(self) -> None:
        with _forged_policy_context(self.a.pk, self.admin.pk):
            self.assertTrue(self._visible_ids())
            Organization.objects.using(OWNER_ALIAS).filter(pk=self.a.pk).update(
                is_active=False
            )
            self.assertEqual(self._visible_ids(), set())

    def test_demotion_is_checked_by_database_even_with_existing_context(self) -> None:
        with _forged_policy_context(self.a.pk, self.admin.pk):
            with transaction.atomic(using=OWNER_ALIAS):
                Organization.objects.using(OWNER_ALIAS).select_for_update().get(
                    pk=self.a.pk
                )
                Membership.objects.using(OWNER_ALIAS).filter(
                    pk=self.admin_membership.pk
                ).update(role=MembershipRole.VIEWER)
            self.assertEqual(self._visible_ids(), {self.item_a.pk, self.archived_a.pk})
            self.assertEqual(
                CatalogItem.objects.filter(pk=self.item_a.pk).update(description="X"), 0
            )

    def test_commits_and_alternating_scopes_leave_no_context_on_reused_connection(
        self,
    ) -> None:
        pid = self._pid()
        for user, workspace, expected in (
            (self.admin, self.a, {self.item_a.pk, self.archived_a.pk}),
            (self.admin, self.b, {self.item_b.pk}),
            (self.viewer, self.a, {self.item_a.pk, self.archived_a.pk}),
        ):
            with tenant_scope(user=user, workspace_id=workspace.pk):
                self.assertEqual(self._visible_ids(), expected)
                self.assertEqual(self._pid(), pid)
            self._assert_clean()
            self.assertEqual(self._pid(), pid)

    def test_rollback_removes_insert_and_context_on_the_same_connection(self) -> None:
        pid = self._pid()
        with self.assertRaises(ValueError):
            with self._write_scope():
                self._insert(self.a, "ROLLBACK")
                raise ValueError("Rollback the synthetic insert.")
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        self.assertFalse(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization=self.a, sku="ROLLBACK")
            .exists()
        )
        with tenant_scope(user=self.admin, workspace_id=self.b.pk):
            self.assertEqual(self._visible_ids(), {self.item_b.pk})

    def test_malformed_uuid_settings_fail_closed(self) -> None:
        for organization_id, user_id in (
            ("not-a-uuid", self.admin.pk),
            (self.a.pk, "not-a-uuid"),
        ):
            with self.subTest(organization=organization_id, user=user_id):
                self._expect_error(
                    "22P02",
                    _forged_policy_context(organization_id, user_id),
                    self._visible_ids,
                )

    def test_ambient_session_context_is_discarded_by_scope_helper(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.set_config('orderdesk.organization_id', %s, false)",
                [str(self.a.pk)],
            )
        with self.assertRaises(TenantScopeError):
            with self._write_scope():
                self.fail("Contaminated connection entered a tenant scope.")
        self.assertIsNone(connection.connection)
        self._assert_clean()

    def test_read_only_scope_rejects_catalogue_dml(self) -> None:
        self._expect_error(
            "25006",
            tenant_scope(user=self.admin, workspace_id=self.a.pk),
            lambda: CatalogItem.objects.filter(pk=self.item_a.pk).update(
                description="X"
            ),
        )

    def test_runtime_delete_is_denied(self) -> None:
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: CatalogItem.objects.filter(pk=self.item_a.pk).delete(),
        )

    def test_runtime_truncate_is_denied(self) -> None:
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: self._execute("TRUNCATE TABLE public.catalog_catalogitem"),
        )

    def test_runtime_cannot_assume_maintenance_owner(self) -> None:
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: self._execute("SET ROLE orderdesk_migrator"),
        )

    def test_runtime_cannot_disable_rls(self) -> None:
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: self._execute(
                "ALTER TABLE public.catalog_catalogitem DISABLE ROW LEVEL SECURITY"
            ),
        )

    def test_runtime_cannot_drop_the_tenant_policy(self) -> None:
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: self._execute(
                "DROP POLICY catalog_tenant_boundary ON public.catalog_catalogitem"
            ),
        )

    def test_row_security_off_does_not_bypass_policies(self) -> None:
        def attempt() -> set[UUID]:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_catalog.set_config('row_security', 'off', true)"
                )
            return self._visible_ids()

        self._expect_error("42501", self._write_scope(), attempt)

    def test_maintenance_owner_can_read_and_clean_without_tenant_context(self) -> None:
        items = set(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization_id__in=self.workspace_ids)
            .values_list("id", flat=True)
        )
        self.assertEqual(items, {self.item_a.pk, self.archived_a.pk, self.item_b.pk})

    def test_demotion_that_wins_org_lock_denies_runtime_catalogue_update(self) -> None:
        ready: Queue[int] = Queue()
        actor_id, workspace_id, item_id = self.admin.pk, self.a.pk, self.item_a.pk

        def attempt_update() -> tuple[MembershipRole, int]:
            close_old_connections()
            try:
                actor = User.objects.get(pk=actor_id)
                self._execute("SET lock_timeout = '5s'")
                ready.put(self._pid())
                with tenant_scope(
                    user=actor, workspace_id=workspace_id, write=True
                ) as context:
                    return context.role, CatalogItem.objects.filter(pk=item_id).update(
                        description="Forbidden race write"
                    )
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic(using=OWNER_ALIAS):
                Organization.objects.using(OWNER_ALIAS).select_for_update().get(
                    pk=workspace_id
                )
                Membership.objects.using(OWNER_ALIAS).filter(
                    pk=self.admin_membership.pk
                ).update(role=MembershipRole.VIEWER)
                with connections[OWNER_ALIAS].cursor() as cursor:
                    cursor.execute("SELECT pg_catalog.pg_backend_pid()")
                    owner_pid = cursor.fetchone()[0]
                future = executor.submit(attempt_update)
                worker_pid = ready.get(timeout=10)
                deadline = monotonic() + 4
                pause = Event()
                while monotonic() < deadline:
                    with connections[OWNER_ALIAS].cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_catalog.pg_blocking_pids(%s)", [worker_pid]
                        )
                        if owner_pid in cursor.fetchone()[0]:
                            break
                    pause.wait(0.02)
                else:
                    self.fail(
                        "The runtime write did not wait for the organization lock."
                    )
            self.assertEqual(future.result(timeout=10), (MembershipRole.VIEWER, 0))
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Fixture A")

    def test_http_active_members_read_allowlisted_history_and_head(self) -> None:
        for actor in (self.admin, self.reviewer, self.viewer):
            with self.subTest(actor=actor.pk):
                client, _ = self._credential_client(actor)
                response = client.get(self._items_url(self.a))
                self._assert_catalogue_response(
                    response, self.a, {self.item_a.pk, self.archived_a.pk}
                )
                rows = {row["id"]: row for row in response.json()["results"]}
                self.assertFalse(rows[str(self.archived_a.pk)]["is_active"])
                self.assertEqual(rows[str(self.item_a.pk)]["sku"], "PART-001")
                head = client.head(self._items_url(self.a))
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b"")
                self._assert_private(head)
                self._assert_clean()

    def test_http_anonymous_expired_and_logged_out_sessions_are_denied(self) -> None:
        anonymous = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")
        response = anonymous.get(self._items_url(self.a))
        self.assertEqual(response.status_code, 403)
        self._assert_private(response)
        expired, _ = self._credential_client(self.admin)
        Session.objects.using(OWNER_ALIAS).filter(
            session_key=expired.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        response = expired.get(self._items_url(self.a))
        self.assertEqual(response.status_code, 403)
        self._assert_private(response)
        logged_out, csrf = self._credential_client(self.admin)
        self.assertEqual(
            logged_out.post(
                "/api/v1/auth/logout/", format="json", HTTP_X_CSRFTOKEN=csrf
            ).status_code,
            204,
        )
        response = logged_out.get(self._items_url(self.a))
        self.assertEqual(response.status_code, 403)
        self._assert_private(response)
        self._assert_clean()

    def test_http_account_deactivation_denies_an_existing_session(self) -> None:
        client, _ = self._credential_client(self.admin)
        self.assertEqual(client.get(self._items_url(self.a)).status_code, 200)
        User.objects.using(OWNER_ALIAS).filter(pk=self.admin.pk).update(is_active=False)
        response = client.get(self._items_url(self.a))
        self.assertEqual(response.status_code, 403)
        self._assert_private(response)
        self._assert_clean()

    def test_http_access_denials_share_one_contract(self) -> None:
        client, _ = self._credential_client(self.viewer)
        urls = (
            self._items_url(self.b),
            f"/api/v1/workspaces/{uuid4()}/catalog/items/",
        )
        for url in urls:
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
                self._assert_private(response)
        Organization.objects.using(OWNER_ALIAS).filter(pk=self.a.pk).update(
            is_active=False
        )
        response = client.get(self._items_url(self.a))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        self._assert_private(response)
        Organization.objects.using(OWNER_ALIAS).filter(pk=self.a.pk).update(
            is_active=True
        )
        Membership.objects.using(OWNER_ALIAS).filter(
            organization=self.a, user=self.viewer
        ).update(is_active=False)
        response = client.get(self._items_url(self.a))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        self._assert_private(response)
        self._assert_clean()

    def test_http_url_workspace_overrides_the_session_preference(self) -> None:
        client, csrf = self._credential_client(self.admin)
        selected = client.put(
            "/api/v1/workspaces/current/",
            {"workspace_id": str(self.b.pk)},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json()["workspace"]["id"], str(self.b.pk))
        self._assert_catalogue_response(
            client.get(self._items_url(self.a)),
            self.a,
            {self.item_a.pk, self.archived_a.pk},
        )
        self._assert_catalogue_response(
            client.get(self._items_url(self.b)), self.b, {self.item_b.pk}
        )
        self._assert_clean()

    def test_http_forged_headers_cookies_and_body_do_not_change_identity(self) -> None:
        client, _ = self._credential_client(self.viewer)
        client.cookies["organization_id"] = str(self.b.pk)
        client.cookies["user_id"] = str(self.admin.pk)
        headers = {
            "HTTP_X_ORGANIZATION_ID": str(self.b.pk),
            "HTTP_X_WORKSPACE_ID": str(self.b.pk),
            "HTTP_X_USER_ID": str(self.admin.pk),
        }
        self._assert_catalogue_response(
            client.get(self._items_url(self.a), **headers),
            self.a,
            {self.item_a.pk, self.archived_a.pk},
        )
        response = client.generic(
            "GET",
            self._items_url(self.a),
            data=(
                '{"organization_id":"'
                + str(self.b.pk)
                + '","user_id":"'
                + str(self.admin.pk)
                + '"}'
            ),
            content_type="application/json",
            **headers,
        )
        self._assert_catalogue_response(
            response, self.a, {self.item_a.pk, self.archived_a.pk}
        )
        foreign = client.get(self._items_url(self.b), **headers)
        self.assertEqual(foreign.status_code, 403)
        self.assertEqual(foreign.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        self._assert_clean()

    def test_http_accessible_empty_catalogue_has_the_exact_empty_shape(self) -> None:
        with transaction.atomic(using=OWNER_ALIAS):
            empty = self._workspace("Synthetic empty distributor")
            self._membership(self.admin, empty, MembershipRole.ADMIN)
        client, _ = self._credential_client(self.admin)
        response = client.get(self._items_url(empty))
        self._assert_catalogue_response(response, empty, set())
        self.assertEqual(
            response.json(),
            {"count": 0, "next": None, "previous": None, "results": []},
        )
        self._assert_clean()

    def test_http_pagination_has_fixed_bounds_and_scoped_links(self) -> None:
        CatalogItem.objects.using(OWNER_ALIAS).bulk_create(
            [CatalogItem(organization=self.a, sku=f"Part/A.{i:03d}") for i in range(49)]
        )
        expected = list(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization=self.a)
            .order_by("sku", "id")
            .values_list("id", flat=True)
        )
        client, _ = self._credential_client(self.admin)
        url = self._items_url(self.a)
        first, second = client.get(url), client.get(url + "?page=2")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_data, second_data = first.json(), second.json()
        self.assertEqual(first_data["count"], 51)
        self.assertEqual(second_data["count"], 51)
        self.assertEqual(len(first_data["results"]), 50)
        self.assertEqual(len(second_data["results"]), 1)
        rows = first_data["results"] + second_data["results"]
        self.assertEqual([row["id"] for row in rows], [str(pk) for pk in expected])
        self.assertEqual({row["organization_id"] for row in rows}, {str(self.a.pk)})
        self.assertIn("Part/A.000", {row["sku"] for row in rows})
        self.assertIsNone(first_data["previous"])
        self.assertIsNone(second_data["next"])
        self.assertEqual(urlsplit(first_data["next"]).path, url)
        self.assertEqual(urlsplit(first_data["next"]).query, "page=2")
        self.assertEqual(urlsplit(second_data["previous"]).path, url)
        self._assert_private(first)
        self._assert_private(second)
        self._assert_clean()

    def test_http_invalid_pages_and_malformed_routes(self) -> None:
        client, _ = self._credential_client(self.admin)
        for value in ("", "abc", "0", "-1", "1.5", "last", "2", "999999"):
            for method in (client.get, client.head):
                with self.subTest(value=value, method=method.__name__):
                    response = method(self._items_url(self.a) + "?page=" + value)
                    self.assertEqual(response.status_code, 404)
                    if method == client.get:
                        self.assertEqual(response.json(), {"detail": "Invalid page."})
                    else:
                        self.assertEqual(response.content, b"")
                    self._assert_private(response)
        for method in (client.get, client.head):
            self.assertEqual(
                method("/api/v1/workspaces/not-a-uuid/catalog/items/").status_code,
                404,
            )
        self._assert_clean()

    def test_http_repeated_and_unsupported_query_parameters_are_rejected(self) -> None:
        client, _ = self._credential_client(self.admin)
        for query in (
            "page=1&page=1",
            "page=1&page=2",
            "page_size=5000",
            f"organization_id={self.b.pk}",
            f"user_id={self.outsider.pk}",
            "ordering=-sku",
            "search=PART",
        ):
            for method in (client.get, client.head):
                with self.subTest(query=query, method=method.__name__):
                    response = method(self._items_url(self.a) + "?" + query)
                    self.assertEqual(response.status_code, 400)
                    self._assert_private(response)
        self._assert_clean()

    def test_http_write_methods_return_405_with_valid_csrf(self) -> None:
        client, csrf = self._credential_client(self.admin)
        before = list(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization=self.a)
            .order_by("id")
            .values("id", "sku", "description", "is_active")
        )
        for method in (client.put, client.patch, client.delete):
            with self.subTest(method=method.__name__):
                response = method(
                    self._items_url(self.a),
                    {"sku": "FORBIDDEN-HTTP-WRITE"},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 405)
                self._assert_private(response)
        after = list(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization=self.a)
            .order_by("id")
            .values("id", "sku", "description", "is_active")
        )
        self.assertEqual(after, before)
        options = client.options(self._items_url(self.a))
        self.assertEqual(options.status_code, 200)
        self.assertEqual(
            {method.strip() for method in options["Allow"].split(",")},
            {"GET", "HEAD", "POST", "OPTIONS"},
        )
        self._assert_clean()

    def test_http_unfiltered_reads_clean_reused_connections(self) -> None:
        client, _ = self._credential_client(self.admin)
        unfiltered = CatalogItem.objects.order_by("sku", "id")
        with patch(
            "apps.catalog.views.selectors.catalog_items_for_workspace",
            return_value=unfiltered,
        ):
            self._assert_catalogue_response(
                client.get(self._items_url(self.a)),
                self.a,
                {self.item_a.pk, self.archived_a.pk},
            )
            self._assert_catalogue_response(
                client.get(self._items_url(self.b)), self.b, {self.item_b.pk}
            )
            pid = self._pid()
            for workspace, expected_ids in (
                (self.a, {str(self.item_a.pk), str(self.archived_a.pk)}),
                (self.b, {str(self.item_b.pk)}),
            ):
                response = self._direct_catalogue_read(client, workspace)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], len(expected_ids))
                self.assertEqual(
                    {row["id"] for row in response.data["results"]}, expected_ids
                )
                self.assertEqual(
                    {row["organization_id"] for row in response.data["results"]},
                    {str(workspace.pk)},
                )
                with patch.object(
                    connection, "cursor", side_effect=AssertionError("Late SQL")
                ):
                    response.render()
                self._assert_clean()
                self.assertEqual(self._pid(), pid)
            with (
                patch(
                    "apps.catalog.views.CatalogItemSerializer",
                    side_effect=ValueError("Synthetic serialization failure"),
                ),
                self.assertRaises(ValueError),
            ):
                self._direct_catalogue_read(client, self.a)
            self._assert_clean()
            self.assertEqual(self._pid(), pid)

            recovered = self._direct_catalogue_read(client, self.b)
            self.assertEqual(recovered.data["count"], 1)
            self.assertEqual(
                recovered.data["results"][0]["organization_id"], str(self.b.pk)
            )
            self._assert_clean()
            self.assertEqual(self._pid(), pid)

    def test_http_create_admin_defaults_and_workspace_readback(self) -> None:
        client, csrf = self._credential_client(self.admin)
        created = self._assert_created(
            client.post(
                self._items_url(self.a),
                {"sku": "  000Ab/c.D-1  "},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ),
            self.a,
            "000Ab/c.D-1",
        )
        self.assertEqual(created["description"], "")
        self.assertIs(created["is_active"], True)
        self._assert_catalogue_response(
            client.get(self._items_url(self.a)),
            self.a,
            {self.item_a.pk, self.archived_a.pk, UUID(created["id"])},
        )
        self._assert_catalogue_response(
            client.get(self._items_url(self.b)), self.b, {self.item_b.pk}
        )
        self._assert_clean()

    def test_http_create_url_ignores_preference_headers_and_cookies(self) -> None:
        client, csrf = self._credential_client(self.admin)
        self.assertEqual(
            client.put(
                "/api/v1/workspaces/current/",
                {"workspace_id": str(self.b.pk)},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            200,
        )
        client.cookies["organization_id"] = str(self.b.pk)
        client.cookies["user_id"] = str(self.outsider.pk)
        created = self._assert_created(
            client.post(
                self._items_url(self.a),
                {
                    "sku": "URL-OWNED",
                    "description": " Synthetic text ",
                    "is_active": False,
                },
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_ORGANIZATION_ID=str(self.b.pk),
                HTTP_X_WORKSPACE_ID=str(self.b.pk),
                HTTP_X_USER_ID=str(self.outsider.pk),
            ),
            self.a,
            "URL-OWNED",
        )
        self.assertFalse(created["is_active"])
        self.assertEqual(created["description"], " Synthetic text ")
        row = CatalogItem.objects.using(OWNER_ALIAS).get(pk=created["id"])
        self.assertEqual(row.organization_id, self.a.pk)

    def test_http_create_nonadministrators_are_denied_before_validation(self) -> None:
        for actor in (self.viewer, self.reviewer):
            client, csrf = self._credential_client(actor)
            for payload in (
                {"sku": "PART-001"},
                {},
                {"organization_id": str(self.b.pk)},
            ):
                with self.subTest(actor=actor.pk, payload=payload):
                    response = client.post(
                        self._items_url(self.a) + "?page=1",
                        payload,
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(
                        response.json(),
                        {
                            "detail": "You do not have permission to create catalogue "
                            "items in this workspace."
                        },
                    )
            malformed = client.generic(
                "POST",
                self._items_url(self.a),
                data=b"{broken",
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
            )
            self.assertEqual(malformed.status_code, 403)
            self.assertEqual(client.get(self._items_url(self.a)).status_code, 200)
            self._assert_clean()

    def test_http_create_missing_foreign_operator_and_inactive_access(self) -> None:
        for actor, url in (
            (self.outsider, self._items_url(self.a)),
            (self.viewer, self._items_url(self.b)),
            (self.admin, f"/api/v1/workspaces/{uuid4()}/catalog/items/"),
        ):
            client, csrf = self._credential_client(actor)
            response = client.post(url, {}, format="json", HTTP_X_CSRFTOKEN=csrf)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        client, csrf = self._credential_client(self.admin)
        for model, pk in (
            (Membership, self.admin_membership.pk),
            (Organization, self.a.pk),
            (User, self.admin.pk),
        ):
            with self.subTest(model=model):
                model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=False)
                response = client.post(
                    self._items_url(self.a),
                    {"sku": "NO-INACTIVE-WRITE"},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 403)
                if model is not User:
                    self.assertEqual(
                        response.json(), {"detail": WORKSPACE_ACCESS_DENIED}
                    )
                model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=True)
        self._assert_clean()

    def test_http_create_protected_fields_and_query_parameters_are_rejected(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        for field in (
            "id",
            "organization",
            "organization_id",
            "user_id",
            "created_at",
            "updated_at",
            "extra",
        ):
            with self.subTest(field=field):
                response = client.post(
                    self._items_url(self.a),
                    {"sku": "PROTECTED", field: str(self.b.pk)},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 400)
                self._assert_clean()
        for query in (
            "page=1",
            "page=1&page=2",
            "page_size=50",
            "ordering=sku",
            "search=x",
            f"organization_id={self.b.pk}",
            f"user_id={self.outsider.pk}",
        ):
            with self.subTest(query=query):
                response = client.post(
                    self._items_url(self.a) + "?" + query,
                    {"sku": "QUERY-REJECTED"},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 400)
                self._assert_clean()
        self.assertEqual(
            CatalogItem.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            2,
        )

    def test_http_create_types_json_and_media_are_validated(self) -> None:
        client, csrf = self._credential_client(self.admin)
        invalid = (
            {},
            [],
            False,
            {"sku": ""},
            {"sku": " \t\n"},
            {"sku": 1},
            {"sku": True},
            {"sku": None},
            {"sku": []},
            {"sku": "TYPE", "description": 1},
            {"sku": "TYPE", "description": None},
            {"sku": "TYPE", "is_active": 1},
            {"sku": "TYPE", "is_active": "true"},
            {"sku": "TYPE", "is_active": None},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(
                    client.post(
                        self._items_url(self.a),
                        payload,
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    ).status_code,
                    400,
                )
                self._assert_clean()
        for content, media, expected in (
            (b"{broken", "application/json", 400),
            (b"sku=TYPE", "text/plain", 415),
        ):
            response = client.generic(
                "POST",
                self._items_url(self.a),
                data=content,
                content_type=media,
                HTTP_X_CSRFTOKEN=csrf,
            )
            self.assertEqual(response.status_code, expected)
            self._assert_clean()
        self.assertEqual(
            CatalogItem.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            2,
        )

    def test_http_create_index_size_limit_is_safe_and_scope_recovers(self) -> None:
        client, csrf = self._credential_client(self.admin)
        # High-entropy text exercises PostgreSQL's actual index-tuple limit;
        # repeated characters can compress and do not establish this boundary.
        large_sku = token_urlsafe(3750)
        response = client.post(
            self._items_url(self.a),
            {"sku": large_sku},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"sku": ["This stock code is too large for the catalogue index."]},
        )
        self._assert_private(response)
        self._assert_clean()
        self.assertEqual(
            CatalogItem.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            2,
        )
        self._assert_created(
            client.post(
                self._items_url(self.a),
                {"sku": "AFTER-INDEX-LIMIT"},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ),
            self.a,
            "AFTER-INDEX-LIMIT",
        )
        self.assertEqual(
            CatalogItem.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            3,
        )

    def test_http_create_duplicates_conflict_and_other_workspaces_reuse_skus(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        for sku in ("PART-001", " PART-001 ", "ARCH-001"):
            with self.subTest(sku=sku):
                response = client.post(
                    self._items_url(self.a),
                    {"sku": sku},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    response.json(),
                    {"detail": "A catalogue item with this stock code already exists."},
                )
                self._assert_clean()
        created = []
        for workspace in (self.a, self.b):
            created.append(
                self._assert_created(
                    client.post(
                        self._items_url(workspace),
                        {"sku": "SHARED-RUNTIME-SKU"},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    ),
                    workspace,
                    "SHARED-RUNTIME-SKU",
                )
            )
        self.assertNotEqual(created[0]["id"], created[1]["id"])
        self._assert_created(
            client.post(
                self._items_url(self.a),
                {"sku": "part-001"},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ),
            self.a,
            "part-001",
        )

    def test_http_create_requires_csrf_and_a_live_authenticated_session(self) -> None:
        client, csrf = self._credential_client(self.admin)
        for token in (None, "invalid-token"):
            headers = {} if token is None else {"HTTP_X_CSRFTOKEN": token}
            self.assertEqual(
                client.post(
                    self._items_url(self.a),
                    {"sku": "CSRF-REJECTED"},
                    format="json",
                    **headers,
                ).status_code,
                403,
            )
        anonymous = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")
        self.assertEqual(
            anonymous.post(
                self._items_url(self.a), {"sku": "PART-001"}, format="json"
            ).status_code,
            403,
        )
        Session.objects.using(OWNER_ALIAS).filter(
            session_key=client.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(
            client.post(
                self._items_url(self.a),
                {"sku": "EXPIRED-REJECTED"},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            403,
        )
        self.assertEqual(
            CatalogItem.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            2,
        )
        self._assert_clean()

    def test_http_create_foreign_construction_is_independently_denied_by_rls(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)

        def forge(*args, **kwargs):
            kwargs["organization_id"] = self.b.pk
            return CatalogItem(*args, **kwargs)

        with (
            patch("apps.catalog.services.CatalogItem", side_effect=forge),
            self.assertRaises(DatabaseError) as error,
        ):
            self._direct_catalogue_post(client, self.a, csrf, {"sku": "FOREIGN-FORGE"})
        self.assertEqual(error.exception.__cause__.sqlstate, "42501")
        self.assertFalse(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization_id__in=self.workspace_ids, sku="FOREIGN-FORGE")
            .exists()
        )
        self._assert_clean()

    def test_http_create_materializes_and_rolls_back_on_a_reused_connection(
        self,
    ) -> None:
        from apps.catalog.serializers import CatalogItemSerializer

        client, csrf = self._credential_client(self.admin)
        pid = self._pid()
        original = CatalogItemSerializer.to_representation

        def serialize(serializer, item):
            self.assertTrue(connection.in_atomic_block)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('transaction_read_only'), "
                    "current_setting('orderdesk.organization_id'), "
                    "current_setting('orderdesk.user_id'), pg_backend_pid()"
                )
                self.assertEqual(
                    cursor.fetchone(), ("off", str(self.a.pk), str(self.admin.pk), pid)
                )
            return original(serializer, item)

        with patch.object(CatalogItemSerializer, "to_representation", serialize):
            response = self._direct_catalogue_post(
                client, self.a, csrf, {"sku": "MATERIALIZED"}
            )
        self.assertEqual(response.status_code, 201)
        with patch.object(connection, "cursor", side_effect=AssertionError("Late SQL")):
            response.render()
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        with (
            patch(
                "apps.catalog.views.CatalogItemSerializer",
                side_effect=ValueError("Synthetic creation serialization failure"),
            ),
            self.assertRaises(ValueError),
        ):
            self._direct_catalogue_post(client, self.a, csrf, {"sku": "ROLLBACK-HTTP"})
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        self.assertFalse(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization=self.a, sku="ROLLBACK-HTTP")
            .exists()
        )
        conflict = self._direct_catalogue_post(
            client, self.a, csrf, {"sku": "PART-001"}
        )
        self.assertEqual(conflict.status_code, 409)
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        recovered = self._direct_catalogue_post(
            client, self.b, csrf, {"sku": "RECOVERED"}
        )
        self.assertEqual(recovered.status_code, 201)
        self.assertEqual(recovered.data["organization_id"], str(self.b.pk))
        self._assert_clean()
        self.assertEqual(self._pid(), pid)

    def test_http_concurrent_creation_uses_native_uniqueness_and_isolation(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        sku = f"RACE-{uuid4().hex}"
        same = self._http_creation_race(client, csrf, sku, (self.a, self.a))
        self.assertCountEqual([result["status"] for result in same], [201, 409])
        conflict = next(result for result in same if result["status"] == 409)
        self.assertEqual(
            conflict["data"],
            {"detail": "A catalogue item with this stock code already exists."},
        )
        self.assertEqual(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization=self.a, sku=sku)
            .count(),
            1,
        )
        shared = f"SHARED-RACE-{uuid4().hex}"
        different = self._http_creation_race(client, csrf, shared, (self.a, self.b))
        self.assertEqual([result["status"] for result in different], [201, 201])
        self.assertEqual(
            {result["data"]["organization_id"] for result in different},
            {str(self.a.pk), str(self.b.pk)},
        )

    def test_http_demotion_winning_the_org_lock_prevents_creation(self) -> None:
        client, csrf = self._credential_client(self.admin)
        ready: Queue[int] = Queue()
        sku = f"DEMOTION-{uuid4().hex}"

        def attempt() -> tuple[int, dict]:
            close_old_connections()

            def inspect(execute, statement, params, many, context):
                if (
                    '"organizations_organization"' in statement
                    and "FOR UPDATE" in statement
                ):
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        cursor.execute("SET LOCAL statement_timeout = '10s'")
                        cursor.execute(
                            "SELECT current_user, session_user, pg_backend_pid()"
                        )
                        identity = cursor.fetchone()
                    self.assertEqual(identity[:2], ("orderdesk_app", "orderdesk_app"))
                    ready.put(identity[2])
                return execute(statement, params, many, context)

            try:
                with connection.execute_wrapper(inspect):
                    response = client.post(
                        self._items_url(self.a),
                        {"sku": sku},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                self._assert_clean()
                return response.status_code, response.json()
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic(using=OWNER_ALIAS):
                Organization.objects.using(OWNER_ALIAS).select_for_update().get(
                    pk=self.a.pk
                )
                Membership.objects.using(OWNER_ALIAS).filter(
                    pk=self.admin_membership.pk
                ).update(role=MembershipRole.VIEWER)
                with connections[OWNER_ALIAS].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    owner_pid = cursor.fetchone()[0]
                future = executor.submit(attempt)
                worker_pid = ready.get(timeout=10)
                deadline = monotonic() + 4
                pause = Event()
                while monotonic() < deadline:
                    with connections[OWNER_ALIAS].cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [worker_pid])
                        if owner_pid in cursor.fetchone()[0]:
                            break
                    pause.wait(0.02)
                else:
                    self.fail(
                        "The HTTP creation did not wait for the organization lock."
                    )
            status, data = future.result(timeout=15)
        self.assertEqual(status, 403)
        self.assertEqual(
            data,
            {
                "detail": "You do not have permission to create catalogue items "
                "in this workspace."
            },
        )
        self.assertFalse(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization=self.a, sku=sku)
            .exists()
        )
        self._assert_clean()

    def test_http_patch_preserves_identity_legacy_sku_and_unsubmitted_fields(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        legacy_sku = "  000Ab/c.D-1  "
        CatalogItem.objects.using(OWNER_ALIAS).filter(pk=self.item_a.pk).update(
            sku=legacy_sku
        )
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        created_at = self.item_a.created_at
        updated_at = self.item_a.updated_at
        text = " \t" + "Long description " * 500 + "\n "
        data = self._assert_updated(
            client.patch(
                self._item_url(self.a, self.item_a.pk),
                {"description": text},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ),
            self.a,
            self.item_a,
        )
        self.assertEqual(data["description"], text)
        self.assertIs(data["is_active"], True)
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.sku, legacy_sku)
        self.assertEqual(self.item_a.organization_id, self.a.pk)
        self.assertEqual(self.item_a.created_at, created_at)
        self.assertGreater(self.item_a.updated_at, updated_at)
        self.assertEqual(self.item_a.description, text)
        self.item_b.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_b.description, "Fixture B")
        self._assert_catalogue_response(
            client.get(self._items_url(self.a)),
            self.a,
            {self.item_a.pk, self.archived_a.pk},
        )
        self._assert_clean()

    def test_http_patch_deactivation_reactivation_and_noop_keep_reserved_sku(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        original_created = self.item_a.created_at
        url = self._item_url(self.a, self.item_a.pk)
        for active in (False, True):
            with self.subTest(active=active):
                data = self._assert_updated(
                    client.patch(
                        url,
                        {"is_active": active},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    ),
                    self.a,
                    self.item_a,
                )
                self.assertIs(data["is_active"], active)
                self.assertEqual(data["description"], "Fixture A")
                again = self._assert_updated(
                    client.patch(
                        url,
                        {"description": "Fixture A", "is_active": active},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    ),
                    self.a,
                    self.item_a,
                )
                self.assertEqual(again, data)
                self._assert_catalogue_response(
                    client.get(self._items_url(self.a)),
                    self.a,
                    {self.item_a.pk, self.archived_a.pk},
                )
                duplicate = client.post(
                    self._items_url(self.a),
                    {"sku": "PART-001"},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(duplicate.status_code, 409)
                self.assertEqual(
                    duplicate.json(),
                    {"detail": "A catalogue item with this stock code already exists."},
                )
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.created_at, original_created)
        self.assertEqual(
            CatalogItem.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            2,
        )
        self._assert_clean()

    def test_http_patch_nonadministrators_are_denied_before_lookup_and_parser(
        self,
    ) -> None:
        denial = {
            "detail": "You do not have permission to update catalogue items "
            "in this workspace."
        }
        for actor in (self.viewer, self.reviewer):
            client, csrf = self._credential_client(actor)
            for item_id in (self.item_a.pk, self.item_b.pk, uuid4()):
                with self.subTest(actor=actor.pk, item_id=item_id):
                    catalogue_sql = []

                    def inspect(
                        execute, sql, params, many, context, catalogue_sql=catalogue_sql
                    ):
                        if '"catalog_catalogitem"' in sql:
                            catalogue_sql.append(sql)
                        return execute(sql, params, many, context)

                    with connection.execute_wrapper(inspect):
                        response = client.generic(
                            "PATCH",
                            self._item_url(self.a, item_id) + "?sku=PART-001",
                            data=b"{broken",
                            content_type="application/json",
                            HTTP_X_CSRFTOKEN=csrf,
                        )
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json(), denial)
                    self.assertEqual(catalogue_sql, [])
                    self._assert_private(response)
                    self._assert_clean()
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Fixture A")

    def test_http_patch_scoped_missing_items_precede_body_and_query_validation(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        for item_id in (self.item_b.pk, uuid4()):
            for body, media in (
                (b"{broken", "application/json"),
                (b"description=forbidden", "text/plain"),
            ):
                with self.subTest(item_id=item_id, media=media):
                    response = client.generic(
                        "PATCH",
                        self._item_url(self.a, item_id) + "?organization_id=x",
                        data=body,
                        content_type=media,
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.json(), {"detail": "Not found."})
                    self._assert_private(response)
                    self._assert_clean()
        self.item_b.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_b.description, "Fixture B")

    def test_http_patch_protected_fields_and_all_query_parameters_are_rejected(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        url = self._item_url(self.a, self.item_a.pk)
        for field in (
            "sku",
            "id",
            "organization",
            "organization_id",
            "user_id",
            "created_at",
            "updated_at",
            "extra",
        ):
            with self.subTest(field=field):
                response = client.patch(
                    url,
                    {"description": "Do not persist", field: str(self.b.pk)},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
                self._assert_clean()
        for query in (
            "page=1",
            "page=1&page=2",
            "page_size=50",
            "ordering=sku",
            "search=x",
            f"organization_id={self.b.pk}",
            f"user_id={self.outsider.pk}",
        ):
            with self.subTest(query=query):
                response = client.patch(
                    url + "?" + query,
                    {"is_active": False},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(query.partition("=")[0], response.json())
                self._assert_clean()
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Fixture A")
        self.assertTrue(self.item_a.is_active)

    def test_http_patch_strict_objects_types_json_and_media(self) -> None:
        client, csrf = self._credential_client(self.admin)
        url = self._item_url(self.a, self.item_a.pk)
        invalid = (
            {},
            [],
            ["description"],
            False,
            "text",
            1,
            {"description": 1},
            {"description": True},
            {"description": None},
            {"description": []},
            {"is_active": 1},
            {"is_active": 0},
            {"is_active": "true"},
            {"is_active": None},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                response = client.patch(
                    url, payload, format="json", HTTP_X_CSRFTOKEN=csrf
                )
                self.assertEqual(response.status_code, 400)
                self.assertIsInstance(response.json(), dict)
                self._assert_clean()
        for body, media, status in (
            (b"null", "application/json", 400),
            (b"{broken", "application/json", 400),
            (b"description=unsupported", "text/plain", 415),
        ):
            response = client.generic(
                "PATCH", url, data=body, content_type=media, HTTP_X_CSRFTOKEN=csrf
            )
            self.assertEqual(response.status_code, status)
            self._assert_clean()
        data = self._assert_updated(
            client.patch(
                url, {"description": ""}, format="json", HTTP_X_CSRFTOKEN=csrf
            ),
            self.a,
            self.item_a,
        )
        self.assertEqual(data["description"], "")
        self.assertIs(data["is_active"], True)

    def test_http_patch_missing_inaccessible_and_inactive_workspace_access(
        self,
    ) -> None:
        for actor, url in (
            (self.outsider, self._item_url(self.a, self.item_a.pk)),
            (self.viewer, self._item_url(self.b, self.item_b.pk)),
            (
                self.admin,
                f"/api/v1/workspaces/{uuid4()}/catalog/items/{self.item_a.pk}/",
            ),
        ):
            client, csrf = self._credential_client(actor)
            response = client.generic(
                "PATCH",
                url,
                data=b"{broken",
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        client, csrf = self._credential_client(self.admin)
        for model, pk in (
            (Membership, self.admin_membership.pk),
            (Organization, self.a.pk),
            (User, self.admin.pk),
        ):
            with self.subTest(model=model):
                model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=False)
                try:
                    response = client.patch(
                        self._item_url(self.a, self.item_a.pk),
                        {"description": "Denied"},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                    self.assertEqual(response.status_code, 403)
                    if model is not User:
                        self.assertEqual(
                            response.json(), {"detail": WORKSPACE_ACCESS_DENIED}
                        )
                finally:
                    model.objects.using(OWNER_ALIAS).filter(pk=pk).update(
                        is_active=True
                    )
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Fixture A")
        self._assert_clean()

    def test_http_patch_requires_csrf_and_a_live_session(self) -> None:
        client, csrf = self._credential_client(self.admin)
        url = self._item_url(self.a, self.item_a.pk)
        for token in (None, "invalid-token"):
            headers = {} if token is None else {"HTTP_X_CSRFTOKEN": token}
            response = client.patch(
                url, {"description": "Denied"}, format="json", **headers
            )
            self.assertEqual(response.status_code, 403)
        anonymous = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")
        self.assertEqual(
            anonymous.patch(url, {"is_active": False}, format="json").status_code,
            403,
        )
        Session.objects.using(OWNER_ALIAS).filter(
            session_key=client.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(
            client.patch(
                url,
                {"description": "Expired"},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            403,
        )
        logged_out, logout_csrf = self._credential_client(self.admin)
        logout = logged_out.post("/api/v1/auth/logout/", HTTP_X_CSRFTOKEN=logout_csrf)
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(
            logged_out.patch(
                url,
                {"description": "Logged out"},
                format="json",
                HTTP_X_CSRFTOKEN=logout_csrf,
            ).status_code,
            403,
        )
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Fixture A")
        self._assert_clean()

    def test_http_patch_url_identity_ignores_session_preference_and_forged_identity(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        self.assertEqual(
            client.put(
                "/api/v1/workspaces/current/",
                {"workspace_id": str(self.b.pk)},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            200,
        )
        client.cookies["organization_id"] = str(self.b.pk)
        client.cookies["user_id"] = str(self.outsider.pk)
        data = self._assert_updated(
            client.patch(
                self._item_url(self.a, self.item_a.pk),
                {"description": "URL workspace owns this update", "is_active": False},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_ORGANIZATION_ID=str(self.b.pk),
                HTTP_X_WORKSPACE_ID=str(self.b.pk),
                HTTP_X_USER_ID=str(self.outsider.pk),
            ),
            self.a,
            self.item_a,
        )
        self.assertFalse(data["is_active"])
        self.item_b.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_b.description, "Fixture B")
        self.assertTrue(self.item_b.is_active)

    def test_http_patch_only_supports_patch_and_options_and_uuid_routes(self) -> None:
        client, csrf = self._credential_client(self.admin)
        url = self._item_url(self.a, self.item_a.pk)
        for method in ("get", "head", "post", "put", "delete"):
            with self.subTest(method=method):
                response = client.generic(method.upper(), url, HTTP_X_CSRFTOKEN=csrf)
                self.assertEqual(response.status_code, 405)
                self.assertEqual(
                    {value.strip() for value in response["Allow"].split(",")},
                    {"PATCH", "OPTIONS"},
                )
                self._assert_private(response)
                self._assert_clean()
        self.assertEqual(client.options(url).status_code, 200)
        for bad_url in (
            f"/api/v1/workspaces/not-a-uuid/catalog/items/{self.item_a.pk}/",
            f"/api/v1/workspaces/{self.a.pk}/catalog/items/not-a-uuid/",
        ):
            self.assertEqual(
                client.patch(
                    bad_url,
                    {"description": "Malformed route"},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                ).status_code,
                404,
            )
        self._assert_clean()

    def test_http_patch_materialization_and_failure_clean_the_reused_connection(
        self,
    ) -> None:
        from apps.catalog.serializers import CatalogItemSerializer

        client, csrf = self._credential_client(self.admin)
        pid = self._pid()
        original = CatalogItemSerializer.to_representation

        def serialize(serializer, item):
            self.assertTrue(connection.in_atomic_block)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_user, session_user, "
                    "current_setting('transaction_read_only'), "
                    "current_setting('orderdesk.organization_id'), "
                    "current_setting('orderdesk.user_id'), pg_backend_pid()"
                )
                self.assertEqual(
                    cursor.fetchone(),
                    (
                        "orderdesk_app",
                        "orderdesk_app",
                        "off",
                        str(self.a.pk),
                        str(self.admin.pk),
                        pid,
                    ),
                )
            return original(serializer, item)

        with patch.object(CatalogItemSerializer, "to_representation", serialize):
            response = self._direct_catalogue_patch(
                client, self.a, self.item_a.pk, csrf, {"description": "Committed"}
            )
        self.assertEqual(response.status_code, 200)
        with patch.object(connection, "cursor", side_effect=AssertionError("Late SQL")):
            response.render()
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        with (
            patch(
                "apps.catalog.views.CatalogItemSerializer",
                side_effect=ValueError("Synthetic update materialization failure"),
            ),
            self.assertRaises(ValueError),
        ):
            self._direct_catalogue_patch(
                client, self.a, self.item_a.pk, csrf, {"description": "Rolled back"}
            )
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Committed")

        def unexpected_native_error(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql.startswith('UPDATE "catalog_catalogitem"'):
                # The genuine UPDATE has run. A real PostgreSQL error must leave
                # its transaction and undo the update, without validation masks.
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 / 0")
            return result

        with (
            connection.execute_wrapper(unexpected_native_error),
            self.assertRaises(DatabaseError) as error,
        ):
            self._direct_catalogue_patch(
                client, self.a, self.item_a.pk, csrf, {"description": "Native rollback"}
            )
        self.assertEqual(error.exception.__cause__.sqlstate, "22012")
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Committed")
        invalid = self._direct_catalogue_patch(
            client, self.a, self.item_a.pk, csrf, {"sku": "IMMUTABLE"}
        )
        self.assertEqual(invalid.status_code, 400)
        missing = self._direct_catalogue_patch(
            client, self.a, self.item_b.pk, csrf, {"description": "Missing"}
        )
        self.assertEqual(missing.status_code, 404)
        recovered = self._direct_catalogue_patch(
            client, self.b, self.item_b.pk, csrf, {"description": "B after rollback"}
        )
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.data["organization_id"], str(self.b.pk))
        self._assert_clean()
        self.assertEqual(self._pid(), pid)

    def test_patch_fields_are_scoped_even_when_sql_has_no_application_filter(
        self,
    ) -> None:
        with self._write_scope():
            # No ORM tenant predicate: both permitted mutable columns are still
            # restricted independently by FORCE RLS to this workspace's rows.
            self.assertEqual(
                CatalogItem.objects.update(
                    description="Scoped raw update", is_active=False
                ),
                2,
            )
        self._assert_clean()
        self.item_b.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_b.description, "Fixture B")
        self.assertTrue(self.item_b.is_active)
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: CatalogItem.objects.filter(pk=self.item_a.pk).update(
                organization_id=self.b.pk
            ),
        )
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.organization_id, self.a.pk)
        self.assertEqual(self.item_a.description, "Scoped raw update")

    def test_http_partial_patch_race_uses_independent_runtime_connections(self) -> None:
        source, csrf = self._credential_client(self.admin)
        start = Barrier(2, timeout=10)

        def attempt(payload: dict) -> tuple[int, dict, int]:
            close_old_connections()
            client = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")
            client.cookies.update(source.cookies)
            prepared = False
            request_pid = None
            write_identities = []

            def inspect(execute, sql, params, many, context):
                nonlocal prepared, request_pid
                if (
                    not prepared
                    and '"organizations_organization"' in sql
                    and "FOR UPDATE" in sql
                ):
                    prepared = True
                    request_pid = self._prepare_patch_transaction()
                if sql.startswith('UPDATE "catalog_catalogitem"'):
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT current_user, session_user, "
                            "current_setting('transaction_read_only'), "
                            "current_setting('orderdesk.organization_id'), "
                            "current_setting('orderdesk.user_id')"
                        )
                        write_identities.append(cursor.fetchone())
                return execute(sql, params, many, context)

            try:
                start.wait()
                with connection.execute_wrapper(inspect):
                    response = client.patch(
                        self._item_url(self.a, self.item_a.pk),
                        payload,
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                self.assertEqual(
                    write_identities,
                    [
                        (
                            "orderdesk_app",
                            "orderdesk_app",
                            "off",
                            str(self.a.pk),
                            str(self.admin.pk),
                        )
                    ],
                )
                self.assertIsNotNone(request_pid)
                self._assert_clean()
                return response.status_code, response.json(), request_pid
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, payload)
                for payload in (
                    {"description": "Independent description edit"},
                    {"is_active": False},
                )
            ]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual([result[0] for result in results], [200, 200])
        self.assertEqual(len({result[2] for result in results}), 2)
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Independent description edit")
        self.assertFalse(self.item_a.is_active)
        self.item_b.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_b.description, "Fixture B")
        self.assertTrue(self.item_b.is_active)
        self._assert_clean()

    def test_http_demotion_winning_org_lock_prevents_patch(self) -> None:
        client, csrf = self._credential_client(self.admin)
        ready: Queue[int] = Queue()

        def attempt() -> tuple[int, dict]:
            close_old_connections()
            prepared = False

            def inspect(execute, sql, params, many, context):
                nonlocal prepared
                if (
                    not prepared
                    and '"organizations_organization"' in sql
                    and "FOR UPDATE" in sql
                ):
                    prepared = True
                    ready.put(self._prepare_patch_transaction())
                return execute(sql, params, many, context)

            try:
                with connection.execute_wrapper(inspect):
                    response = client.patch(
                        self._item_url(self.a, self.item_a.pk),
                        {"description": "Must remain unchanged"},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                self._assert_clean()
                return response.status_code, response.json()
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic(using=OWNER_ALIAS):
                Organization.objects.using(OWNER_ALIAS).select_for_update().get(
                    pk=self.a.pk
                )
                Membership.objects.using(OWNER_ALIAS).filter(
                    pk=self.admin_membership.pk
                ).update(role=MembershipRole.VIEWER)
                with connections[OWNER_ALIAS].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    owner_pid = cursor.fetchone()[0]
                future = executor.submit(attempt)
                request_pid = ready.get(timeout=10)
                self.assertNotEqual(request_pid, owner_pid)
                self._assert_native_blocked(request_pid, owner_pid)
            status, data = future.result(timeout=15)
        self.assertEqual(status, 403)
        self.assertEqual(
            data,
            {
                "detail": "You do not have permission to update catalogue items "
                "in this workspace."
            },
        )
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Fixture A")
        self._assert_clean()

    def test_http_patch_winning_org_lock_commits_before_later_demotion(self) -> None:
        client, csrf = self._credential_client(self.admin)
        updated: Queue[int] = Queue()
        demoter_ready: Queue[int] = Queue()
        release_update = Event()

        def update() -> tuple[int, dict]:
            close_old_connections()
            prepared = False
            request_pid = None

            def inspect(execute, sql, params, many, context):
                nonlocal prepared, request_pid
                if (
                    not prepared
                    and '"organizations_organization"' in sql
                    and "FOR UPDATE" in sql
                ):
                    prepared = True
                    request_pid = self._prepare_patch_transaction()
                result = execute(sql, params, many, context)
                if sql.startswith('UPDATE "catalog_catalogitem"'):
                    self.assertIsNotNone(request_pid)
                    updated.put(request_pid)
                    if not release_update.wait(timeout=10):
                        raise RuntimeError("The native update race release timed out.")
                return result

            try:
                with connection.execute_wrapper(inspect):
                    response = client.patch(
                        self._item_url(self.a, self.item_a.pk),
                        {"description": "Authorized update before demotion"},
                        format="json",
                        HTTP_X_CSRFTOKEN=csrf,
                    )
                self._assert_clean()
                return response.status_code, response.json()
            finally:
                connections["default"].close()

        def demote() -> None:
            # This connection only changes the synthetic control-plane fixture.
            # The tested catalogue UPDATE itself always uses orderdesk_app.
            try:
                with transaction.atomic(using=OWNER_ALIAS):
                    with connections[OWNER_ALIAS].cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '8s'")
                        cursor.execute("SET LOCAL statement_timeout = '12s'")
                        cursor.execute("SELECT pg_backend_pid()")
                        demoter_ready.put(cursor.fetchone()[0])
                    Organization.objects.using(OWNER_ALIAS).select_for_update().get(
                        pk=self.a.pk
                    )
                    Membership.objects.using(OWNER_ALIAS).filter(
                        pk=self.admin_membership.pk
                    ).update(role=MembershipRole.VIEWER)
            finally:
                connections[OWNER_ALIAS].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            update_future = executor.submit(update)
            try:
                update_pid = updated.get(timeout=10)
                demotion_future = executor.submit(demote)
                demoter_pid = demoter_ready.get(timeout=10)
                self.assertNotEqual(update_pid, demoter_pid)
                self._assert_native_blocked(demoter_pid, update_pid)
            finally:
                release_update.set()
            status, data = update_future.result(timeout=15)
            demotion_future.result(timeout=15)
        self.assertEqual(status, 200)
        self.assertEqual(data["description"], "Authorized update before demotion")
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(self.item_a.description, "Authorized update before demotion")
        denied = client.patch(
            self._item_url(self.a, self.item_a.pk),
            {"is_active": False},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(
            denied.json(),
            {
                "detail": "You do not have permission to update catalogue items "
                "in this workspace."
            },
        )
        self.item_a.refresh_from_db(using=OWNER_ALIAS)
        self.assertTrue(self.item_a.is_active)
        self._assert_clean()

    def test_http_search_sku_and_description_are_grouped_within_workspace(self) -> None:
        CatalogItem.objects.using(OWNER_ALIAS).filter(pk=self.item_a.pk).update(
            description="Washer assembly"
        )
        CatalogItem.objects.using(OWNER_ALIAS).filter(pk=self.archived_a.pk).update(
            description="Replacement WASHER"
        )
        CatalogItem.objects.using(OWNER_ALIAS).filter(pk=self.item_b.pk).update(
            description="Foreign description needle"
        )
        for actor in (self.admin, self.reviewer, self.viewer):
            client, _ = self._credential_client(actor)
            for query, ids in (
                ({"q": "  washer \t"}, {self.item_a.pk, self.archived_a.pk}),
                ({"q": "part-"}, {self.item_a.pk}),
                ({"q": "Foreign description needle"}, set()),
            ):
                with self.subTest(actor=actor.pk, query=query):
                    self._assert_catalogue_response(
                        client.get(self._items_url(self.a), query), self.a, ids
                    )
                    head = client.head(self._items_url(self.a), query)
                    self.assertEqual(head.status_code, 200)
                    self.assertEqual(head.content, b"")
                    self._assert_private(head)
                    self._assert_clean()

    def test_http_search_literal_metacharacters_and_unicode_match_in_postgresql(
        self,
    ) -> None:
        literal = "%_'\\"
        item = CatalogItem.objects.using(OWNER_ALIAS).create(
            organization=self.a,
            sku="LITERAL-QUERY",
            description=f"Literal {literal} token and é中文",
        )
        CatalogItem.objects.using(OWNER_ALIAS).filter(pk=self.item_a.pk).update(
            description="A wildcard decoy with other punctuation"
        )
        CatalogItem.objects.using(OWNER_ALIAS).filter(pk=self.item_b.pk).update(
            description=f"Foreign Literal {literal} token and é中文"
        )
        client, _ = self._credential_client(self.admin)
        for query in (literal, "é中文"):
            with self.subTest(query=query):
                self._assert_catalogue_response(
                    client.get(self._items_url(self.a), {"q": query}),
                    self.a,
                    {item.pk},
                )
        self._assert_clean()

    def test_http_search_status_filtered_counts_and_pages_keep_query_links(
        self,
    ) -> None:
        CatalogItem.objects.using(OWNER_ALIAS).filter(
            organization_id__in=(self.a.pk, self.b.pk)
        ).update(description="Filter-match")
        CatalogItem.objects.using(OWNER_ALIAS).bulk_create(
            [
                CatalogItem(
                    organization=self.a,
                    sku=f"FILTER-{index:03d}",
                    description="Filter-match",
                )
                for index in range(51)
            ]
        )
        client, _ = self._credential_client(self.admin)
        query = {"q": "filter-MATCH", "is_active": "true"}
        first = client.get(self._items_url(self.a), query)
        self.assertEqual(first.status_code, 200)
        data = first.json()
        self.assertEqual(data["count"], 52)
        self.assertEqual(len(data["results"]), 50)
        next_link = urlsplit(data["next"])
        self.assertEqual(next_link.path, self._items_url(self.a))
        self.assertEqual(
            parse_qs(next_link.query),
            {"q": [query["q"]], "is_active": ["true"], "page": ["2"]},
        )
        second = client.get(self._items_url(self.a), {**query, "page": "2"})
        self.assertEqual(second.status_code, 200)
        second_data = second.json()
        self.assertEqual(second_data["count"], 52)
        self.assertEqual(len(second_data["results"]), 2)
        self.assertIsNone(second_data["next"])
        previous = urlsplit(second_data["previous"])
        self.assertEqual(previous.path, self._items_url(self.a))
        self.assertEqual(
            parse_qs(previous.query), {"q": [query["q"]], "is_active": ["true"]}
        )
        rows = data["results"] + second_data["results"]
        self.assertTrue(all(row["is_active"] is True for row in rows))
        self.assertTrue(all(row["organization_id"] == str(self.a.pk) for row in rows))
        expected = list(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization=self.a, is_active=True)
            .order_by("sku", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual([row["id"] for row in rows], [str(pk) for pk in expected])
        self._assert_catalogue_response(
            client.get(
                self._items_url(self.a), {"q": "filter-match", "is_active": "false"}
            ),
            self.a,
            {self.archived_a.pk},
        )
        omitted = client.get(self._items_url(self.a), {"q": "filter-match"})
        self.assertEqual(omitted.status_code, 200)
        self.assertEqual(omitted.json()["count"], 53)
        self._assert_clean()

    def test_http_exact_lookup_normalization_case_inactive_and_overlapping_skus(
        self,
    ) -> None:
        CatalogItem.objects.using(OWNER_ALIAS).create(
            organization=self.b, sku="FOREIGN-EXACT-ONLY"
        )
        for actor in (self.admin, self.reviewer, self.viewer):
            client, _ = self._credential_client(actor)
            self._assert_exact_item(
                client.get(self._sku_url(self.a), {"sku": " \tPART-001  "}),
                self.a,
                self.item_a,
            )
            self._assert_exact_item(
                client.get(self._sku_url(self.a), {"sku": "ARCH-001"}),
                self.a,
                self.archived_a,
            )
            for sku in ("part-001", "FOREIGN-EXACT-ONLY", "NOT-PRESENT"):
                with self.subTest(actor=actor.pk, sku=sku):
                    response = client.get(self._sku_url(self.a), {"sku": sku})
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.json(), {"detail": "Not found."})
                    head = client.head(self._sku_url(self.a), {"sku": sku})
                    self.assertEqual(head.status_code, 404)
                    self.assertEqual(head.content, b"")
                    self._assert_clean()
            head = client.head(self._sku_url(self.a), {"sku": "PART-001"})
            self.assertEqual(head.status_code, 200)
            self.assertEqual(head.content, b"")
            self._assert_private(head)
        admin_client, _ = self._credential_client(self.admin)
        self._assert_exact_item(
            admin_client.get(self._sku_url(self.b), {"sku": "PART-001"}),
            self.b,
            self.item_b,
        )
        self._assert_clean()

    def test_http_search_and_exact_queries_remain_strict_safe_read_contracts(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        for path, queries in (
            (
                self._items_url(self.a),
                (
                    "q=",
                    "q=%20%09",
                    "q=" + "x" * 201,
                    "q=part&q=part",
                    "is_active=TRUE",
                    "is_active=",
                    "is_active=false&is_active=false",
                    "page=1&page=1",
                    f"q=part&organization_id={self.b.pk}",
                    "q=part&ordering=sku",
                    "q=part&page_size=1",
                ),
            ),
            (
                self._sku_url(self.a),
                (
                    "",
                    "sku=",
                    "sku=%20%09",
                    "sku=PART-001&sku=PART-001",
                    "sku=PART-001&page=1",
                    "sku=PART-001&q=part",
                    "sku=PART-001&is_active=true",
                    f"sku=PART-001&organization_id={self.b.pk}",
                ),
            ),
        ):
            for query in queries:
                for method in (client.get, client.head):
                    with self.subTest(path=path, query=query, method=method.__name__):
                        response = method(path + ("?" + query if query else ""))
                        self.assertEqual(response.status_code, 400)
                        self._assert_private(response)
                        self._assert_clean()
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = client.generic(
                    method.upper(), self._sku_url(self.a), HTTP_X_CSRFTOKEN=csrf
                )
                self.assertEqual(response.status_code, 405)
                self.assertEqual(
                    {value.strip() for value in response["Allow"].split(",")},
                    {"GET", "HEAD", "OPTIONS"},
                )
        self.assertEqual(client.options(self._sku_url(self.a)).status_code, 200)
        for path in (self._items_url(self.a), self._sku_url(self.a)):
            self.assertEqual(
                client.get(
                    path, {"sku" if "by-sku" in path else "q": "part\x00"}
                ).status_code,
                400,
            )
        self._assert_clean()

    def test_http_search_and_exact_access_precedes_detailed_query_errors(self) -> None:
        anonymous = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")
        for path in (self._items_url(self.a), self._sku_url(self.a)):
            self.assertEqual(
                anonymous.get(path, {"organization_id": "forged"}).status_code, 403
            )
        for actor, workspace_id in (
            (self.outsider, self.a.pk),
            (self.viewer, self.b.pk),
            (self.admin, uuid4()),
        ):
            client, _ = self._credential_client(actor)
            for suffix in ("", "by-sku/"):
                path = f"/api/v1/workspaces/{workspace_id}/catalog/items/{suffix}"
                for method in (client.get, client.head):
                    response = method(path, {"organization_id": "forged"})
                    self.assertEqual(response.status_code, 403)
                    if method == client.get:
                        self.assertEqual(
                            response.json(), {"detail": WORKSPACE_ACCESS_DENIED}
                        )
        client, _ = self._credential_client(self.admin)
        for model, pk in (
            (Membership, self.admin_membership.pk),
            (Organization, self.a.pk),
            (User, self.admin.pk),
        ):
            model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=False)
            try:
                for path in (self._items_url(self.a), self._sku_url(self.a)):
                    self.assertEqual(
                        client.get(path, {"invalid": "query"}).status_code, 403
                    )
            finally:
                model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=True)
        expired, _ = self._credential_client(self.admin)
        Session.objects.using(OWNER_ALIAS).filter(
            session_key=expired.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        for path in (self._items_url(self.a), self._sku_url(self.a)):
            self.assertEqual(expired.get(path, {"invalid": "query"}).status_code, 403)
        self._assert_clean()

    def test_http_search_and_exact_url_scope_ignores_forged_tenant_identity(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        self.assertEqual(
            client.put(
                "/api/v1/workspaces/current/",
                {"workspace_id": str(self.b.pk)},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            200,
        )
        client.cookies.pop(settings.CSRF_COOKIE_NAME, None)
        client.cookies["organization_id"] = str(self.b.pk)
        client.cookies["user_id"] = str(self.outsider.pk)
        headers = {
            "HTTP_X_ORGANIZATION_ID": str(self.b.pk),
            "HTTP_X_WORKSPACE_ID": str(self.b.pk),
            "HTTP_X_USER_ID": str(self.outsider.pk),
        }
        self._assert_catalogue_response(
            client.get(self._items_url(self.a), {"q": "PART"}, **headers),
            self.a,
            {self.item_a.pk},
        )
        self._assert_exact_item(
            client.get(self._sku_url(self.a), {"sku": "PART-001"}, **headers),
            self.a,
            self.item_a,
        )
        self._assert_clean()

    def test_http_search_and_exact_refresh_revocation_before_query_validation(
        self,
    ) -> None:
        client, _ = self._credential_client(self.admin)

        @contextmanager
        def revoke_before_scope(**kwargs):
            # Permission checks have completed; the real owned read scope must
            # refresh membership before looking at this invalid client query.
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(is_active=False)
            with tenant_scope(**kwargs) as scope:
                yield scope

        for path in (self._items_url(self.a), self._sku_url(self.a)):
            try:
                with patch("apps.catalog.views.tenant_scope", revoke_before_scope):
                    response = client.get(path, {"invalid": "query"})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
                self._assert_clean()
            finally:
                Membership.objects.using(OWNER_ALIAS).filter(
                    pk=self.admin_membership.pk
                ).update(is_active=True)

    def test_http_search_and_exact_materialize_inside_read_scope_on_reused_pid(
        self,
    ) -> None:
        from apps.catalog.serializers import CatalogItemSerializer

        client, _ = self._credential_client(self.admin)
        pid = self._pid()
        original = CatalogItemSerializer.to_representation

        def serialize(serializer, item):
            self.assertTrue(connection.in_atomic_block)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_user, session_user, "
                    "current_setting('transaction_read_only'), "
                    "current_setting('orderdesk.organization_id'), "
                    "current_setting('orderdesk.user_id'), pg_backend_pid()"
                )
                self.assertEqual(
                    cursor.fetchone(),
                    (
                        "orderdesk_app",
                        "orderdesk_app",
                        "on",
                        str(self.a.pk),
                        str(self.admin.pk),
                        pid,
                    ),
                )
            return original(serializer, item)

        for exact, query in ((False, {"q": "part"}), (True, {"sku": "PART-001"})):
            with self.subTest(exact=exact):
                with patch.object(
                    CatalogItemSerializer, "to_representation", serialize
                ):
                    response = self._direct_catalogue_search(
                        client, self.a, query, exact=exact
                    )
                self.assertEqual(response.status_code, 200)
                with patch.object(
                    connection, "cursor", side_effect=AssertionError("Late SQL")
                ):
                    response.render()
                self._assert_clean()
                self.assertEqual(self._pid(), pid)
                with (
                    patch(
                        "apps.catalog.views.CatalogItemSerializer",
                        side_effect=ValueError(
                            "Synthetic read materialization failure"
                        ),
                    ),
                    self.assertRaises(ValueError),
                ):
                    self._direct_catalogue_search(client, self.a, query, exact=exact)
                self._assert_clean()
                self.assertEqual(self._pid(), pid)
        for workspace, query, exact, status in (
            (self.a, {"q": ""}, False, 400),
            (self.a, {"sku": "NOT-PRESENT"}, True, 404),
            (self.b, {"q": "PART"}, False, 200),
            (self.b, {"sku": "PART-001"}, True, 200),
        ):
            response = self._direct_catalogue_search(
                client, workspace, query, exact=exact
            )
            self.assertEqual(response.status_code, status)
            self._assert_clean()
            self.assertEqual(self._pid(), pid)

    def test_http_search_without_application_org_filter_still_obeys_rls(self) -> None:
        client, _ = self._credential_client(self.admin)
        CatalogItem.objects.using(OWNER_ALIAS).filter(pk=self.item_b.pk).update(
            description="Foreign description needle"
        )

        def unfiltered(**filters):
            # Test-only omission: actual ORM search/count/page SQL still runs on
            # the direct runtime connection under its restrictive tenant policy.
            items = CatalogItem.objects.order_by("sku", "id")
            if filters["q"] is not None:
                items = items.filter(
                    Q(sku__icontains=filters["q"])
                    | Q(description__icontains=filters["q"])
                )
            if filters["is_active"] is not None:
                items = items.filter(is_active=filters["is_active"])
            return items

        with patch(
            "apps.catalog.views.selectors.catalog_items_for_workspace",
            side_effect=unfiltered,
        ):
            for query, ids in (
                ({"q": "PART-001"}, {self.item_a.pk}),
                ({"q": "Foreign description needle"}, set()),
                ({"q": "001", "is_active": "false"}, {self.archived_a.pk}),
            ):
                self._assert_catalogue_response(
                    client.get(self._items_url(self.a), query), self.a, ids
                )
        self._assert_clean()

    def test_http_exact_without_application_org_filter_still_obeys_rls(self) -> None:
        client, _ = self._credential_client(self.admin)
        CatalogItem.objects.using(OWNER_ALIAS).create(
            organization=self.b, sku="FOREIGN-EXACT-ONLY"
        )

        def unfiltered(**filters):
            return CatalogItem.objects.filter(sku=filters["sku"])

        with patch(
            "apps.catalog.views.selectors.catalog_item_by_sku", side_effect=unfiltered
        ):
            self._assert_exact_item(
                client.get(self._sku_url(self.a), {"sku": "PART-001"}),
                self.a,
                self.item_a,
            )
            self._assert_exact_item(
                client.get(self._sku_url(self.a), {"sku": "ARCH-001"}),
                self.a,
                self.archived_a,
            )
            response = client.get(self._sku_url(self.a), {"sku": "FOREIGN-EXACT-ONLY"})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "Not found."})
        self._assert_clean()

    @staticmethod
    def _import_url(workspace: Organization) -> str:
        return f"/api/v1/workspaces/{workspace.pk}/catalog/imports/dry-run/"

    @staticmethod
    def _csv_bytes(rows: list, *, headers: tuple = ("sku", "description", "is_active")):
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
        return output.getvalue().encode("utf-8")

    @staticmethod
    def _csv_upload(content: bytes) -> SimpleUploadedFile:
        # Synthetic metadata must not influence byte/structure validation.
        return SimpleUploadedFile("synthetic.csv", content, content_type="text/csv")

    def _catalogue_snapshot(self) -> list[tuple]:
        return list(
            CatalogItem.objects.using(OWNER_ALIAS)
            .filter(organization_id__in=self.workspace_ids)
            .order_by("id")
            .values_list(
                "id",
                "organization_id",
                "sku",
                "description",
                "is_active",
                "created_at",
                "updated_at",
            )
        )

    def _post_csv(
        self,
        client: APIClient,
        csrf: str,
        content: bytes,
        *,
        workspace: Organization | None = None,
        **headers,
    ):
        return client.post(
            self._import_url(workspace or self.a),
            {"file": self._csv_upload(content)},
            format="multipart",
            HTTP_X_CSRFTOKEN=csrf,
            **headers,
        )

    def _assert_import_report(
        self, response, *, total: int, ready: int, invalid: int
    ) -> dict:
        self.assertEqual(response.status_code, 200)
        self._assert_private(response)
        data = response.json()
        self.assertEqual(
            set(data),
            {
                "dry_run",
                "mode",
                "can_import",
                "summary",
                "errors",
                "errors_truncated",
                "preview",
                "preview_truncated",
            },
        )
        self.assertIs(data["dry_run"], True)
        self.assertEqual(data["mode"], "create_only")
        self.assertIs(data["can_import"], invalid == 0)
        self.assertEqual(
            data["summary"],
            {"rows_total": total, "rows_ready": ready, "rows_invalid": invalid},
        )
        self.assertLessEqual(len(data["errors"]), 100)
        self.assertLessEqual(len(data["preview"]), 25)
        for error in data["errors"]:
            self.assertTrue({"row_number", "code", "message"} <= set(error))
            self.assertIsInstance(error["row_number"], int)
            self.assertGreaterEqual(error["row_number"], 2)
            self.assertIsInstance(error["code"], str)
            self.assertIsInstance(error["message"], str)
            self.assertTrue(error["message"])
            self.assertLessEqual(len(error["message"]), 200)
        for row in data["preview"]:
            self.assertEqual(
                set(row), {"row_number", "sku", "description", "is_active"}
            )
            self.assertIsInstance(row["row_number"], int)
            self.assertIsInstance(row["sku"], str)
            self.assertIsInstance(row["description"], str)
            self.assertIsInstance(row["is_active"], bool)
        self._assert_clean()
        return data

    @staticmethod
    def _direct_catalogue_import(
        client: APIClient, workspace: Organization, csrf: str, content: bytes
    ):
        from apps.catalog.views import CatalogImportDryRunView

        request = APIRequestFactory(enforce_csrf_checks=True).post(
            RuntimeCatalogRLSChecks._import_url(workspace),
            {"file": RuntimeCatalogRLSChecks._csv_upload(content)},
            format="multipart",
            HTTP_HOST="localhost",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_COOKIE=client.cookies.output(header="", sep=";").strip(),
        )
        SessionMiddleware(lambda _: None).process_request(request)
        AuthenticationMiddleware(lambda _: None).process_request(request)
        return CatalogImportDryRunView.as_view()(request, workspace_id=workspace.pk)

    def test_http_import_valid_unicode_quoting_defaults_and_normalization_write_nothing(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        description = '  Washer, "quoted"\nsecond line  '
        content = b"\xef\xbb\xbf" + self._csv_bytes(
            [
                ("true", description, " \t000Ab/P-1.x  "),
                ("", "", "\u00c9CROU-\u6771\u4eac"),
                ("false", "Archived proposal", "NEW-INACTIVE"),
                ("true", "Long unbounded text", "z" * 5000),
            ],
            headers=("is_active", "description", "sku"),
        )
        data = self._assert_import_report(
            self._post_csv(client, csrf, content), total=4, ready=4, invalid=0
        )
        self.assertEqual(
            data["preview"][0],
            {
                "row_number": 2,
                "sku": "000Ab/P-1.x",
                "description": description,
                "is_active": True,
            },
        )
        self.assertEqual(data["preview"][1]["sku"], "\u00c9CROU-\u6771\u4eac")
        self.assertEqual(data["preview"][1]["row_number"], 3)
        self.assertEqual(data["preview"][1]["description"], "")
        self.assertIs(data["preview"][1]["is_active"], True)
        self.assertIs(data["preview"][2]["is_active"], False)
        self.assertEqual(data["preview"][3]["sku"], "z" * 5000)
        self.assertEqual(data["errors"], [])
        self.assertIs(data["errors_truncated"], False)
        self.assertIs(data["preview_truncated"], False)
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_duplicates_and_active_inactive_conflicts_are_create_only(
        self,
    ) -> None:
        CatalogItem.objects.using(OWNER_ALIAS).create(
            organization=self.b, sku="FOREIGN-IMPORT-ONLY"
        )
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        data = self._assert_import_report(
            self._post_csv(
                client,
                csrf,
                self._csv_bytes(
                    [
                        ("PART-001", "Would overwrite active", "false"),
                        ("ARCH-001", "Would reactivate", "true"),
                        (" DUPLICATE ", "First occurrence", ""),
                        ("DUPLICATE", "Second occurrence", "false"),
                        ("FOREIGN-IMPORT-ONLY", "Foreign does not reserve", ""),
                        ("part-001", "Case-sensitive equality", ""),
                    ]
                ),
            ),
            total=6,
            ready=2,
            invalid=4,
        )
        self.assertEqual({row["row_number"] for row in data["errors"]}, {2, 3, 4, 5})
        self.assertEqual(
            {row["row_number"]: row["code"] for row in data["errors"]},
            {
                2: "existing_workspace_sku",
                3: "existing_workspace_sku",
                4: "duplicate_file_sku",
                5: "duplicate_file_sku",
            },
        )
        self.assertTrue(all(row["field"] == "sku" for row in data["errors"]))
        self.assertEqual(
            {row["sku"] for row in data["preview"]},
            {"FOREIGN-IMPORT-ONLY", "part-001"},
        )
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_unfiltered_conflict_lookup_is_independently_rls_scoped(
        self,
    ) -> None:
        CatalogItem.objects.using(OWNER_ALIAS).create(
            organization=self.b, sku="FOREIGN-IMPORT-ONLY"
        )
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()

        def unfiltered(*, organization_id, skus):
            # Test-only omission of explicit tenant filtering. This queryset is
            # evaluated by the actual service on orderdesk_app under forced RLS.
            return CatalogItem.objects.filter(sku__in=skus).values_list(
                "sku", flat=True
            )

        with patch(
            "apps.catalog.import_services.selectors.existing_catalog_skus",
            side_effect=unfiltered,
        ):
            data = self._assert_import_report(
                self._post_csv(
                    client,
                    csrf,
                    self._csv_bytes(
                        [
                            ("PART-001", "", ""),
                            ("ARCH-001", "", ""),
                            ("FOREIGN-IMPORT-ONLY", "", ""),
                        ]
                    ),
                ),
                total=3,
                ready=1,
                invalid=2,
            )
        self.assertEqual(data["preview"][0]["sku"], "FOREIGN-IMPORT-ONLY")
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_error_and_preview_bounds_keep_complete_summary(self) -> None:
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        rows = [("", "Invalid blank stock code", "") for _ in range(120)]
        rows += [(f"READY-{index:03d}", "", "") for index in range(30)]
        data = self._assert_import_report(
            self._post_csv(client, csrf, self._csv_bytes(rows)),
            total=150,
            ready=30,
            invalid=120,
        )
        self.assertEqual(len(data["errors"]), 100)
        self.assertIs(data["errors_truncated"], True)
        self.assertEqual(len(data["preview"]), 25)
        self.assertIs(data["preview_truncated"], True)
        self.assertEqual(data["preview"][0]["row_number"], 122)
        self.assertEqual(data["preview"][-1]["row_number"], 146)
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_upload_and_record_limits_never_return_partial_success(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        oversized = self._post_csv(client, csrf, b"x" * (1_048_576 + 1))
        self.assertEqual(oversized.status_code, 413)
        self._assert_private(oversized)
        self._assert_clean()
        rows = [(f"BOUNDED-{index:04d}", "", "") for index in range(1001)]
        too_many = self._post_csv(client, csrf, self._csv_bytes(rows))
        self.assertEqual(too_many.status_code, 400)
        self._assert_clean()
        statements = []

        def capture(execute, sql, params, many, context):
            if sql.startswith("SELECT") and '"catalog_catalogitem"' in sql:
                statements.append(sql)
            self.assertFalse(
                sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                and '"catalog_catalogitem"' in sql
            )
            return execute(sql, params, many, context)

        with connection.execute_wrapper(capture):
            data = self._assert_import_report(
                self._post_csv(client, csrf, self._csv_bytes(rows[:1000])),
                total=1000,
                ready=1000,
                invalid=0,
            )
        # Four batches of 250, rather than one catalogue SELECT per data record.
        # _assert_clean adds its independent unfiltered RLS cleanup SELECT.
        self.assertEqual(len(statements), 5)
        self.assertEqual(len(data["preview"]), 25)
        self.assertIs(data["preview_truncated"], True)
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_strict_structure_encoding_and_logical_records(self) -> None:
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        invalid_files = (
            b"",
            b"sku,description,is_active\n",
            b"sku,description,is_active\n\n\n",
            b"sku,description,is_active\nBAD,\xff,true\n",
            b"sku,description\nNEW,description\n",
            b"sku,description,is_active,extra\nNEW,,,x\n",
            b"sku,description,sku\nNEW,,NEW\n",
            b"sku,,is_active\nNEW,,true\n",
            b"SKU,description,is_active\nNEW,,true\n",
            b"sku,description,is_active\nNEW,missing-column\n",
            b"sku,description,is_active\nNEW,,true,extra-column\n",
            b'sku,description,is_active\nNEW,"unterminated,true\n',
        )
        for content in invalid_files:
            with self.subTest(content=content[:80]):
                response = self._post_csv(client, csrf, content)
                self.assertEqual(response.status_code, 400)
                self._assert_private(response)
                self._assert_clean()
        content = self._csv_bytes(
            [("FIRST", "Line one\nLine two", "true"), [], ("LAST", "", "false")]
        )
        data = self._assert_import_report(
            self._post_csv(client, csrf, content), total=2, ready=2, invalid=0
        )
        self.assertEqual([row["row_number"] for row in data["preview"]], [2, 4])
        self.assertEqual(data["preview"][0]["description"], "Line one\nLine two")
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_invalid_values_are_reports_and_do_not_mutate_catalogue(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        data = self._assert_import_report(
            self._post_csv(
                client,
                csrf,
                self._csv_bytes(
                    [
                        (" \t ", "", ""),
                        ("BOOL-CAPS", "", "TRUE"),
                        ("BOOL-NUMBER", "", "1"),
                        ("BOOL-SPACE", "", " true "),
                        ("ZERO\x00BYTE", "", "true"),
                        ("FORMULA-TEXT", "=1+1", ""),
                    ]
                ),
            ),
            total=6,
            ready=1,
            invalid=5,
        )
        self.assertEqual(data["preview"][0]["description"], "=1+1")
        self.assertEqual(data["preview"][0]["row_number"], 7)
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_multipart_is_exact_and_rejects_forged_tenant_fields(
        self,
    ) -> None:
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        content = self._csv_bytes([("NEW-MULTIPART", "", "")])
        payloads = (
            {},
            {"file": "a scalar is not an uploaded file"},
            {"file": [self._csv_upload(content), self._csv_upload(content)]},
            {"other": self._csv_upload(content)},
            {"file": self._csv_upload(content), "extra": "unexpected"},
            {"file": self._csv_upload(content), "organization_id": str(self.b.pk)},
            {"file": self._csv_upload(content), "user_id": str(self.outsider.pk)},
            {"file": self._csv_upload(content), "mode": "upsert"},
        )
        for payload in payloads:
            with self.subTest(fields=tuple(payload)):
                response = client.post(
                    self._import_url(self.a),
                    payload,
                    format="multipart",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 400)
                self._assert_clean()
        for query in ("page=1", "q=NEW", f"organization_id={self.b.pk}"):
            response = client.post(
                self._import_url(self.a) + "?" + query,
                {"file": self._csv_upload(content)},
                format="multipart",
                HTTP_X_CSRFTOKEN=csrf,
            )
            self.assertEqual(response.status_code, 400)
            self._assert_clean()
        response = client.post(
            self._import_url(self.a),
            {"file": "not multipart"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 415)
        self._assert_clean()
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_role_and_workspace_authorization_precedes_csv_details(
        self,
    ) -> None:
        denial = (
            "You do not have permission to validate catalogue imports "
            "in this workspace."
        )
        before = self._catalogue_snapshot()
        for actor in (self.viewer, self.reviewer):
            client, csrf = self._credential_client(actor)
            response = client.post(
                self._import_url(self.a) + "?organization_id=forged",
                {"file": self._csv_upload(b"invalid CSV bytes")},
                format="multipart",
                HTTP_X_CSRFTOKEN=csrf,
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": denial})
            self._assert_clean()
        for actor, workspace_id in (
            (self.outsider, self.a.pk),
            (self.viewer, self.b.pk),
            (self.admin, uuid4()),
        ):
            client, csrf = self._credential_client(actor)
            response = client.post(
                f"/api/v1/workspaces/{workspace_id}/catalog/imports/dry-run/",
                {"file": self._csv_upload(b"invalid CSV")},
                format="multipart",
                HTTP_X_CSRFTOKEN=csrf,
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
            self._assert_clean()
        client, csrf = self._credential_client(self.admin)
        for model, pk in (
            (Membership, self.admin_membership.pk),
            (Organization, self.a.pk),
            (User, self.admin.pk),
        ):
            model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=False)
            try:
                response = self._post_csv(client, csrf, b"invalid CSV")
                self.assertEqual(response.status_code, 403)
                self._assert_clean()
            finally:
                model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=True)
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_requires_csrf_and_a_current_authenticated_session(
        self,
    ) -> None:
        content = self._csv_bytes([("NEW-SESSION", "", "")])
        before = self._catalogue_snapshot()
        anonymous = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")
        self.assertEqual(
            anonymous.post(
                self._import_url(self.a),
                {"file": self._csv_upload(content)},
                format="multipart",
            ).status_code,
            403,
        )
        client, csrf = self._credential_client(self.admin)
        for headers in ({}, {"HTTP_X_CSRFTOKEN": "incorrect"}):
            self.assertEqual(
                client.post(
                    self._import_url(self.a),
                    {"file": self._csv_upload(content)},
                    format="multipart",
                    **headers,
                ).status_code,
                403,
            )
            self._assert_clean()
        expired, token = self._credential_client(self.admin)
        Session.objects.using(OWNER_ALIAS).filter(
            session_key=expired.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self._post_csv(expired, token, content).status_code, 403)
        self._assert_clean()
        self.assertEqual(
            client.post("/api/v1/auth/logout/", HTTP_X_CSRFTOKEN=csrf).status_code,
            204,
        )
        self.assertEqual(self._post_csv(client, csrf, content).status_code, 403)
        self._assert_clean()
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_url_scope_ignores_preference_headers_and_cookies(
        self,
    ) -> None:
        CatalogItem.objects.using(OWNER_ALIAS).create(
            organization=self.b, sku="FOREIGN-IMPORT-ONLY"
        )
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        self.assertEqual(
            client.put(
                "/api/v1/workspaces/current/",
                {"workspace_id": str(self.b.pk)},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            200,
        )
        client.cookies["organization_id"] = str(self.b.pk)
        client.cookies["user_id"] = str(self.outsider.pk)
        data = self._assert_import_report(
            self._post_csv(
                client,
                csrf,
                self._csv_bytes(
                    [("PART-001", "", ""), ("FOREIGN-IMPORT-ONLY", "", "")]
                ),
                HTTP_X_ORGANIZATION_ID=str(self.b.pk),
                HTTP_X_WORKSPACE_ID=str(self.b.pk),
                HTTP_X_USER_ID=str(self.outsider.pk),
            ),
            total=2,
            ready=1,
            invalid=1,
        )
        self.assertEqual(data["preview"][0]["sku"], "FOREIGN-IMPORT-ONLY")
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_refreshes_admin_permission_before_validation(self) -> None:
        from apps.catalog.imports import parse_catalogue_csv

        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()

        @contextmanager
        def demote_before_scope(**kwargs):
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(role=MembershipRole.VIEWER)
            with tenant_scope(**kwargs) as scope:
                yield scope

        try:
            with patch(
                "apps.catalog.import_services.tenant_scope", demote_before_scope
            ):
                response = self._post_csv(client, csrf, b"invalid CSV")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.json(),
                {
                    "detail": (
                        "You do not have permission to validate catalogue imports "
                        "in this workspace."
                    )
                },
            )
            self._assert_clean()
        finally:
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(role=MembershipRole.ADMIN)

        def demote_after_csv(raw):
            parsed = parse_catalogue_csv(raw)
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(role=MembershipRole.VIEWER)
            return parsed

        try:
            with (
                patch(
                    "apps.catalog.import_services.parse_catalogue_csv",
                    side_effect=demote_after_csv,
                ),
                patch(
                    "apps.catalog.import_services.selectors.existing_catalog_skus"
                ) as lookup,
            ):
                response = self._post_csv(
                    client, csrf, self._csv_bytes([("NEW-DEMOTED", "", "")])
                )
            self.assertEqual(response.status_code, 403)
            lookup.assert_not_called()
            self._assert_clean()
        finally:
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(role=MembershipRole.ADMIN)
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_readonly_evaluation_and_failures_clean_reused_connection(
        self,
    ) -> None:
        from apps.catalog.imports import ParsedImport

        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        pid = self._pid()
        observations = []
        original_report = ParsedImport.report
        reports = []

        def report(parsed, existing):
            self.assertTrue(connection.in_atomic_block)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_user, session_user, "
                    "current_setting('transaction_read_only'), "
                    "current_setting('orderdesk.organization_id'), "
                    "current_setting('orderdesk.user_id'), pg_backend_pid()"
                )
                reports.append(cursor.fetchone())
            return original_report(parsed, existing)

        def inspect(execute, sql, params, many, context):
            if sql.startswith("SELECT") and '"catalog_catalogitem"' in sql:
                self.assertTrue(connection.in_atomic_block)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT current_user, session_user, "
                        "current_setting('transaction_read_only'), "
                        "current_setting('orderdesk.organization_id'), "
                        "current_setting('orderdesk.user_id'), pg_backend_pid()"
                    )
                    observations.append(cursor.fetchone())
            return execute(sql, params, many, context)

        content = self._csv_bytes([("NEW-READONLY", "", "")])
        with (
            connection.execute_wrapper(inspect),
            patch.object(ParsedImport, "report", report),
        ):
            response = self._direct_catalogue_import(client, self.a, csrf, content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            observations,
            [
                (
                    "orderdesk_app",
                    "orderdesk_app",
                    "on",
                    str(self.a.pk),
                    str(self.admin.pk),
                    pid,
                )
            ],
        )
        self.assertEqual(reports, observations)
        with patch.object(connection, "cursor", side_effect=AssertionError("Late SQL")):
            response.render()
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        invalid = self._direct_catalogue_import(client, self.a, csrf, b"invalid CSV")
        self.assertEqual(invalid.status_code, 400)
        self._assert_clean()
        self.assertEqual(self._pid(), pid)

        def fail_after_select(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql.startswith("SELECT") and '"catalog_catalogitem"' in sql:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 / 0")
            return result

        with (
            connection.execute_wrapper(fail_after_select),
            self.assertRaises(DatabaseError) as error,
        ):
            self._direct_catalogue_import(client, self.a, csrf, content)
        self.assertEqual(error.exception.__cause__.sqlstate, "22012")
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        with (
            patch.object(
                ParsedImport,
                "report",
                side_effect=ValueError("Synthetic conflict materialization failure"),
            ),
            self.assertRaises(ValueError),
        ):
            self._direct_catalogue_import(client, self.a, csrf, content)
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        recovered = self._direct_catalogue_import(client, self.b, csrf, content)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.data["summary"]["rows_ready"], 1)
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_import_only_supports_post_and_options(self) -> None:
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        for method in ("get", "head", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = client.generic(
                    method.upper(), self._import_url(self.a), HTTP_X_CSRFTOKEN=csrf
                )
                self.assertEqual(response.status_code, 405)
                self.assertEqual(
                    {value.strip() for value in response["Allow"].split(",")},
                    {"POST", "OPTIONS"},
                )
                self._assert_private(response)
                self._assert_clean()
        self.assertEqual(client.options(self._import_url(self.a)).status_code, 200)
        self.assertEqual(self._catalogue_snapshot(), before)

    @staticmethod
    def _execute_import_url(workspace: Organization) -> str:
        return f"/api/v1/workspaces/{workspace.pk}/catalog/imports/"

    @staticmethod
    def _receipt_ids() -> set[UUID]:
        # Independent forced RLS proof: deliberately omit application filtering.
        return set(CatalogImportReceipt.objects.values_list("id", flat=True))

    @staticmethod
    def _receipt_payload(workspace: Organization, receipt_id: UUID) -> dict:
        return {
            "import_id": str(receipt_id),
            "organization_id": str(workspace.pk),
            "mode": "create_only",
            "created_count": 0,
            "items": [],
            "items_truncated": False,
        }

    def _owner_receipt(
        self,
        workspace: Organization,
        *,
        user: User | None = None,
        key: UUID | None = None,
    ) -> CatalogImportReceipt:
        receipt_id = uuid4()
        return CatalogImportReceipt.objects.using(OWNER_ALIAS).create(
            id=receipt_id,
            organization=workspace,
            initiating_user=user or self.admin,
            idempotency_key=key or uuid4(),
            request_fingerprint="a" * 64,
            state=CatalogImportReceipt.State.COMPLETED,
            response_payload=self._receipt_payload(workspace, receipt_id),
            completed_at=timezone.now() + timedelta(seconds=1),
        )

    @staticmethod
    def _insert_processing_receipt(
        workspace: Organization, actor: User
    ) -> CatalogImportReceipt:
        return CatalogImportReceipt.objects.create(
            organization_id=workspace.pk,
            initiating_user_id=actor.pk,
            idempotency_key=uuid4(),
            request_fingerprint="a" * 64,
        )

    def _post_execution(
        self,
        client: APIClient,
        csrf: str,
        raw: bytes,
        key: UUID | str | None,
        *,
        workspace: Organization | None = None,
        **headers,
    ):
        if key is not None:
            headers["HTTP_IDEMPOTENCY_KEY"] = str(key)
        return client.post(
            self._execute_import_url(workspace or self.a),
            {"file": self._csv_upload(raw)},
            format="multipart",
            HTTP_X_CSRFTOKEN=csrf,
            **headers,
        )

    def _assert_execution(
        self,
        response,
        workspace: Organization,
        *,
        count: int,
        replay: bool = False,
    ) -> dict:
        self.assertEqual(response.status_code, 200 if replay else 201)
        self._assert_private(response)
        self.assertEqual(
            response["Idempotency-Replayed"], "true" if replay else "false"
        )
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "import_id",
                "organization_id",
                "mode",
                "created_count",
                "items",
                "items_truncated",
            },
        )
        UUID(body["import_id"])
        self.assertEqual(body["organization_id"], str(workspace.pk))
        self.assertEqual(body["mode"], "create_only")
        self.assertEqual(body["created_count"], count)
        self.assertEqual(len(body["items"]), min(count, 25))
        self.assertIs(body["items_truncated"], count > 25)
        for item in body["items"]:
            self.assertEqual(
                set(item),
                {
                    "id",
                    "organization_id",
                    "sku",
                    "description",
                    "is_active",
                    "created_at",
                    "updated_at",
                },
            )
            self.assertEqual(item["organization_id"], str(workspace.pk))
        self._assert_clean()
        self.assertEqual(self._receipt_ids(), set())
        return body

    @staticmethod
    def _direct_catalogue_execution(
        client: APIClient,
        workspace: Organization,
        csrf: str,
        raw: bytes,
        key: UUID,
    ):
        from apps.catalog.views import CatalogImportExecuteView

        request = APIRequestFactory(enforce_csrf_checks=True).post(
            RuntimeCatalogRLSChecks._execute_import_url(workspace),
            {"file": RuntimeCatalogRLSChecks._csv_upload(raw)},
            format="multipart",
            HTTP_HOST="localhost",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_IDEMPOTENCY_KEY=str(key),
            HTTP_COOKIE=client.cookies.output(header="", sep=";").strip(),
        )
        SessionMiddleware(lambda _: None).process_request(request)
        AuthenticationMiddleware(lambda _: None).process_request(request)
        return CatalogImportExecuteView.as_view()(request, workspace_id=workspace.pk)

    def test_receipt_unfiltered_reads_require_current_tenant_and_administrator(self):
        receipt_a = self._owner_receipt(self.a)
        receipt_b = self._owner_receipt(self.b)
        with tenant_scope(user=self.admin, workspace_id=self.a.pk):
            self.assertEqual(self._receipt_ids(), {receipt_a.pk})
        with tenant_scope(user=self.admin, workspace_id=self.b.pk):
            self.assertEqual(self._receipt_ids(), {receipt_b.pk})
        for actor in (self.viewer, self.reviewer):
            with self.subTest(actor=actor.pk):
                with tenant_scope(user=actor, workspace_id=self.a.pk):
                    self.assertEqual(self._receipt_ids(), set())
        with _forged_policy_context(self.a.pk, self.outsider.pk):
            self.assertEqual(self._receipt_ids(), set())
        with _forged_policy_context(self.a.pk, self.viewer.pk):
            self._execute(
                "SELECT pg_catalog.set_config('orderdesk.role', 'admin', true)"
            )
            self.assertEqual(self._receipt_ids(), set())
        self._assert_clean()
        self.assertEqual(self._receipt_ids(), set())

    def test_receipt_missing_malformed_and_inactive_contexts_fail_closed(self):
        self._owner_receipt(self.a)
        for organization_id, user_id in (
            (None, None),
            (self.a.pk, None),
            (None, self.admin.pk),
            ("", self.admin.pk),
            (self.a.pk, ""),
            (uuid4(), self.admin.pk),
            (self.a.pk, uuid4()),
        ):
            with self.subTest(organization=organization_id, actor=user_id):
                with _forged_policy_context(organization_id, user_id):
                    self.assertEqual(self._receipt_ids(), set())
                self._expect_error(
                    "42501",
                    _forged_policy_context(organization_id, user_id),
                    lambda: self._insert_processing_receipt(self.a, self.admin),
                )
        for organization_id, user_id in (
            ("malformed", self.admin.pk),
            (self.a.pk, "malformed"),
        ):
            self._expect_error(
                "22P02",
                _forged_policy_context(organization_id, user_id),
                self._receipt_ids,
            )
        for model, pk in (
            (User, self.admin.pk),
            (Membership, self.admin_membership.pk),
            (Organization, self.a.pk),
        ):
            model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=False)
            try:
                with _forged_policy_context(self.a.pk, self.admin.pk):
                    self.assertEqual(self._receipt_ids(), set())
                self._expect_error(
                    "42501",
                    _forged_policy_context(self.a.pk, self.admin.pk),
                    lambda: self._insert_processing_receipt(self.a, self.admin),
                )
            finally:
                model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=True)
        self._assert_clean()

    def test_receipt_inserts_bind_tenant_initiator_and_admin_independently(self):
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: self._insert_processing_receipt(self.b, self.admin),
        )
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: self._insert_processing_receipt(self.a, self.viewer),
        )
        for actor in (self.viewer, self.reviewer):
            self._expect_error(
                "42501",
                self._write_scope(actor),
                lambda actor=actor: self._insert_processing_receipt(self.a, actor),
            )
        self.assertFalse(
            CatalogImportReceipt.objects.using(OWNER_ALIAS)
            .filter(organization_id__in=self.workspace_ids)
            .exists()
        )

    def test_receipt_processing_must_complete_inside_same_transaction(self):
        # This check deliberately reaches COMMIT. _expect_error's in-scope
        # unexpected-success assertion would roll back before a deferred trigger.
        with self.assertRaises(DatabaseError) as error:
            with self._write_scope():
                self._insert_processing_receipt(self.a, self.admin)
        self.assertEqual(error.exception.__cause__.sqlstate, "23514")
        self.assertEqual(
            error.exception.__cause__.diag.constraint_name,
            "catalog_import_completed_at_commit",
        )
        self._assert_clean()
        self.assertFalse(
            CatalogImportReceipt.objects.using(OWNER_ALIAS)
            .filter(organization=self.a)
            .exists()
        )
        with self._write_scope():
            receipt = self._insert_processing_receipt(self.a, self.admin)
            self.assertEqual(
                CatalogImportReceipt.objects.filter(pk=receipt.pk).update(
                    state=CatalogImportReceipt.State.COMPLETED,
                    response_payload=self._receipt_payload(self.a, receipt.pk),
                    completed_at=timezone.now(),
                ),
                1,
            )
        receipt.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(receipt.state, CatalogImportReceipt.State.COMPLETED)
        self.assertIsNotNone(receipt.completed_at)
        self._assert_clean()

    def test_receipt_identity_columns_are_not_runtime_updateable(self):
        receipt = self._owner_receipt(self.a)
        for values in (
            {"organization_id": self.b.pk},
            {"initiating_user_id": self.viewer.pk},
            {"idempotency_key": uuid4()},
            {"request_fingerprint": "b" * 64},
            {"mode": "upsert"},
            {"contract_identifier": "forged-contract"},
            {"created_at": timezone.now()},
            {"id": uuid4()},
        ):
            with self.subTest(fields=tuple(values)):
                self._expect_error(
                    "42501",
                    self._write_scope(),
                    lambda values=values: CatalogImportReceipt.objects.filter(
                        pk=receipt.pk
                    ).update(**values),
                )
        receipt.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(receipt.organization_id, self.a.pk)
        self.assertEqual(receipt.initiating_user_id, self.admin.pk)
        self.assertEqual(receipt.request_fingerprint, "a" * 64)

    def test_completed_receipts_are_immutable_even_for_runtime_administrators(self):
        receipt = self._owner_receipt(self.a)
        original = receipt.response_payload
        with self._write_scope():
            self.assertEqual(
                CatalogImportReceipt.objects.filter(pk=receipt.pk).update(
                    state=CatalogImportReceipt.State.PROCESSING,
                    response_payload=None,
                    completed_at=None,
                ),
                0,
            )
            self.assertEqual(
                CatalogImportReceipt.objects.filter(pk=receipt.pk).update(
                    response_payload={"forged": True}
                ),
                0,
            )
        receipt.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(receipt.response_payload, original)
        self.assertEqual(receipt.state, CatalogImportReceipt.State.COMPLETED)
        self._assert_clean()

    def test_runtime_cannot_delete_truncate_or_disable_receipt_rls(self):
        receipt = self._owner_receipt(self.a)
        for action in (
            lambda: CatalogImportReceipt.objects.filter(pk=receipt.pk).delete(),
            lambda: self._execute("TRUNCATE TABLE public.catalog_catalogimportreceipt"),
            lambda: self._execute(
                "ALTER TABLE public.catalog_catalogimportreceipt "
                "DISABLE ROW LEVEL SECURITY"
            ),
        ):
            self._expect_error("42501", self._write_scope(), action)
        self.assertTrue(
            CatalogImportReceipt.objects.using(OWNER_ALIAS)
            .filter(pk=receipt.pk)
            .exists()
        )

    def test_http_execution_commit_and_replay_keep_original_bounded_response(self):
        peer = self._user()
        self._membership(peer, self.a, MembershipRole.ADMIN)
        client, csrf = self._credential_client(self.admin)
        key = uuid4()
        raw = self._csv_bytes(
            [(f"EXECUTE-{index:03d}", f"Original {index}", "") for index in range(26)]
        )
        body = self._assert_execution(
            self._post_execution(client, csrf, raw, key), self.a, count=26
        )
        receipt = CatalogImportReceipt.objects.using(OWNER_ALIAS).get(
            pk=UUID(body["import_id"])
        )
        self.assertEqual(receipt.initiating_user_id, self.admin.pk)
        self.assertEqual(receipt.idempotency_key, key)
        self.assertEqual(receipt.response_payload, body)
        self.assertEqual(receipt.state, CatalogImportReceipt.State.COMPLETED)
        self.assertIsNotNone(receipt.completed_at)
        CatalogItem.objects.using(OWNER_ALIAS).filter(
            pk=UUID(body["items"][0]["id"])
        ).update(description="Edited after import", is_active=False)
        before = self._catalogue_snapshot()
        replay = self._assert_execution(
            self._post_execution(client, csrf, raw, key), self.a, count=26, replay=True
        )
        self.assertEqual(replay, body)
        other, other_csrf = self._credential_client(peer)
        peer_replay = self._assert_execution(
            self._post_execution(other, other_csrf, raw, key),
            self.a,
            count=26,
            replay=True,
        )
        self.assertEqual(peer_replay, body)
        receipt.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(receipt.initiating_user_id, self.admin.pk)
        self.assertEqual(self._catalogue_snapshot(), before)
        changed = self._post_execution(client, csrf, raw + b"\r\n", key)
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(self._catalogue_snapshot(), before)
        self.assertEqual(
            CatalogImportReceipt.objects.using(OWNER_ALIAS)
            .filter(organization=self.a)
            .count(),
            1,
        )
        self._assert_clean()

    def test_http_execution_cross_workspace_keys_and_skus_are_independent(self):
        client, csrf = self._credential_client(self.admin)
        key, raw = uuid4(), self._csv_bytes([("EXECUTE-SHARED", "", "false")])
        first = self._assert_execution(
            self._post_execution(client, csrf, raw, key), self.a, count=1
        )
        second = self._assert_execution(
            self._post_execution(client, csrf, raw, key, workspace=self.b),
            self.b,
            count=1,
        )
        self.assertNotEqual(first["import_id"], second["import_id"])
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        with tenant_scope(user=self.admin, workspace_id=self.a.pk):
            self.assertEqual(self._receipt_ids(), {UUID(first["import_id"])})
        with tenant_scope(user=self.admin, workspace_id=self.b.pk):
            self.assertEqual(self._receipt_ids(), {UUID(second["import_id"])})
        self._assert_clean()

    def test_http_execution_validation_conflicts_and_upload_limits_rollback_receipts(
        self,
    ):
        client, csrf = self._credential_client(self.admin)
        before = self._catalogue_snapshot()
        key = uuid4()
        for raw, expected in (
            (b"invalid CSV", 400),
            (b"sku,description,is_active\nBAD,\xff,true\n", 400),
            (self._csv_bytes([("", "", "true")]), 400),
            (self._csv_bytes([("BAD-BOOLEAN", "", "TRUE")]), 400),
            (self._csv_bytes([("DUPLICATE", "", ""), (" DUPLICATE ", "", "")]), 400),
            (
                self._csv_bytes(
                    [("NEW-BEFORE-CONFLICT", "", ""), ("PART-001", "", "")]
                ),
                409,
            ),
            (self._csv_bytes([("ARCH-001", "", "true")]), 409),
            (b"x" * (1_048_576 + 1), 413),
            (
                self._csv_bytes(
                    [(f"TOO-MANY-{index}", "", "") for index in range(1001)]
                ),
                400,
            ),
        ):
            with self.subTest(status=expected, prefix=raw[:40]):
                response = self._post_execution(client, csrf, raw, key)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(self._catalogue_snapshot(), before)
                self.assertFalse(
                    CatalogImportReceipt.objects.using(OWNER_ALIAS)
                    .filter(organization=self.a)
                    .exists()
                )
                self._assert_clean()
        # A failed attempt never consumes its key; corrected bytes are valid.
        self._assert_execution(
            self._post_execution(
                client, csrf, self._csv_bytes([("CORRECTED-EXECUTION", "", "")]), key
            ),
            self.a,
            count=1,
        )

    def test_http_execution_current_roles_and_access_are_required_even_for_replay(self):
        denial = (
            "You do not have permission to import catalogue items in this workspace."
        )
        raw, key = self._csv_bytes([("AUTH-EXECUTION", "", "")]), uuid4()
        client, csrf = self._credential_client(self.admin)
        self._assert_execution(
            self._post_execution(client, csrf, raw, key), self.a, count=1
        )
        before = self._catalogue_snapshot()
        for actor in (self.viewer, self.reviewer):
            other, token = self._credential_client(actor)
            response = self._post_execution(other, token, b"malformed CSV", key)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": denial})
        for actor, workspace_id in (
            (self.outsider, self.a.pk),
            (self.viewer, self.b.pk),
            (self.admin, uuid4()),
        ):
            other, token = self._credential_client(actor)
            response = other.post(
                f"/api/v1/workspaces/{workspace_id}/catalog/imports/",
                {"file": self._csv_upload(b"malformed")},
                format="multipart",
                HTTP_X_CSRFTOKEN=token,
                HTTP_IDEMPOTENCY_KEY=str(key),
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        Membership.objects.using(OWNER_ALIAS).filter(
            pk=self.admin_membership.pk
        ).update(role=MembershipRole.VIEWER)
        try:
            response = self._post_execution(client, csrf, raw, key)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": denial})
            with _forged_policy_context(self.a.pk, self.admin.pk):
                self.assertEqual(self._receipt_ids(), set())
        finally:
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(role=MembershipRole.ADMIN)
        for model, pk in (
            (Membership, self.admin_membership.pk),
            (Organization, self.a.pk),
            (User, self.admin.pk),
        ):
            model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=False)
            try:
                self.assertEqual(
                    self._post_execution(client, csrf, raw, key).status_code, 403
                )
                self._assert_clean()
            finally:
                model.objects.using(OWNER_ALIAS).filter(pk=pk).update(is_active=True)
        self.assertEqual(self._catalogue_snapshot(), before)

    def test_http_execution_csrf_sessions_keys_and_exact_multipart_are_required(self):
        client, csrf = self._credential_client(self.admin)
        raw = self._csv_bytes([("STRICT-EXECUTION", "", "")])
        before = self._catalogue_snapshot()
        for key in (None, "", "not-a-uuid", str(uuid4()) + "," + str(uuid4())):
            with self.subTest(key=key):
                self.assertEqual(
                    self._post_execution(client, csrf, raw, key).status_code, 400
                )
                self._assert_clean()
        for payload in (
            {},
            {"file": [self._csv_upload(raw), self._csv_upload(raw)]},
            {"file": self._csv_upload(raw), "organization_id": str(self.b.pk)},
            {"file": self._csv_upload(raw), "initiating_user_id": str(self.viewer.pk)},
            {"file": self._csv_upload(raw), "can_import": "true"},
        ):
            response = client.post(
                self._execute_import_url(self.a),
                payload,
                format="multipart",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_IDEMPOTENCY_KEY=str(uuid4()),
            )
            self.assertEqual(response.status_code, 400)
            self._assert_clean()
        response = client.post(
            self._execute_import_url(self.a) + f"?organization_id={self.b.pk}",
            {"file": self._csv_upload(raw)},
            format="multipart",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )
        self.assertEqual(response.status_code, 400)
        for actor_client, headers in (
            (client, {}),
            (client, {"HTTP_X_CSRFTOKEN": "wrong"}),
            (APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost"), {}),
        ):
            response = actor_client.post(
                self._execute_import_url(self.a),
                {"file": self._csv_upload(raw)},
                format="multipart",
                HTTP_IDEMPOTENCY_KEY=str(uuid4()),
                **headers,
            )
            self.assertEqual(response.status_code, 403)
            self._assert_clean()
        expired, token = self._credential_client(self.admin)
        Session.objects.using(OWNER_ALIAS).filter(
            session_key=expired.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(
            self._post_execution(expired, token, raw, uuid4()).status_code, 403
        )
        self.assertEqual(self._catalogue_snapshot(), before)
        self.assertFalse(
            CatalogImportReceipt.objects.using(OWNER_ALIAS)
            .filter(organization=self.a)
            .exists()
        )
        self._assert_clean()

    def test_http_execution_materializes_inside_scope_and_rolls_back_failures(
        self,
    ):
        from apps.catalog.serializers import CatalogItemSerializer

        client, csrf = self._credential_client(self.admin)
        pid = self._pid()
        raw, key = self._csv_bytes([("REUSED-EXECUTION", "", "")]), uuid4()
        original = CatalogItemSerializer.to_representation
        observations = []

        def serialize(serializer, item):
            self.assertTrue(connection.in_atomic_block)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_user, session_user, "
                    "current_setting('transaction_read_only'), "
                    "current_setting('orderdesk.organization_id'), "
                    "current_setting('orderdesk.user_id'), pg_backend_pid()"
                )
                observations.append(cursor.fetchone())
            return original(serializer, item)

        with patch.object(CatalogItemSerializer, "to_representation", serialize):
            response = self._direct_catalogue_execution(client, self.a, csrf, raw, key)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            observations,
            [
                (
                    "orderdesk_app",
                    "orderdesk_app",
                    "off",
                    str(self.a.pk),
                    str(self.admin.pk),
                    pid,
                )
            ],
        )
        with patch.object(connection, "cursor", side_effect=AssertionError("Late SQL")):
            response.render()
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        before = self._catalogue_snapshot()

        def fail_after_completion(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql.startswith("UPDATE") and '"catalog_catalogimportreceipt"' in sql:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 / 0")
            return result

        failed_key = uuid4()
        failed_raw = self._csv_bytes(
            [("ROLLBACK-EXECUTE-A", "", ""), ("ROLLBACK-EXECUTE-B", "", "")]
        )
        with (
            connection.execute_wrapper(fail_after_completion),
            self.assertRaises(DatabaseError) as error,
        ):
            self._direct_catalogue_execution(
                client, self.a, csrf, failed_raw, failed_key
            )
        self.assertEqual(error.exception.__cause__.sqlstate, "22012")
        self.assertEqual(self._catalogue_snapshot(), before)
        self.assertFalse(
            CatalogImportReceipt.objects.using(OWNER_ALIAS)
            .filter(organization=self.a, idempotency_key=failed_key)
            .exists()
        )
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        with (
            patch.object(
                CatalogItemSerializer,
                "to_representation",
                side_effect=ValueError("Synthetic import materialization failure"),
            ),
            self.assertRaises(ValueError),
        ):
            self._direct_catalogue_execution(
                client, self.a, csrf, failed_raw, failed_key
            )
        self.assertEqual(self._catalogue_snapshot(), before)
        self._assert_clean()
        self.assertEqual(self._pid(), pid)
        recovered = self._direct_catalogue_execution(
            client, self.b, csrf, failed_raw, failed_key
        )
        self.assertEqual(recovered.status_code, 201)
        self._assert_clean()
        self.assertEqual(self._pid(), pid)

    def test_http_execution_only_supports_post_and_options(self):
        client, csrf = self._credential_client(self.admin)
        for method in ("get", "head", "put", "patch", "delete"):
            response = client.generic(
                method.upper(), self._execute_import_url(self.a), HTTP_X_CSRFTOKEN=csrf
            )
            self.assertEqual(response.status_code, 405)
            self.assertEqual(
                {part.strip() for part in response["Allow"].split(",")},
                {"POST", "OPTIONS"},
            )
            self._assert_private(response)
            self._assert_clean()
        self.assertEqual(
            client.options(self._execute_import_url(self.a)).status_code, 200
        )

    def test_http_concurrent_execution_receipt_and_sku_conflicts_use_runtime_role(self):
        source, csrf = self._credential_client(self.admin)

        def race(raws, keys):
            barrier = Barrier(2, timeout=10)

            def attempt(raw, key):
                client = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")
                client.cookies.update(source.cookies)
                close_old_connections()
                prepared = False
                request_pid = None

                def inspect(execute, sql, params, many, context):
                    nonlocal prepared, request_pid
                    if (
                        not prepared
                        and "organizations_organization" in sql
                        and "FOR UPDATE" in sql
                    ):
                        prepared = True
                        request_pid = self._prepare_patch_transaction()
                    if sql.startswith("INSERT") and '"catalog_catalogitem"' in sql:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT current_user, session_user, "
                                "current_setting('transaction_read_only'), "
                                "current_setting('orderdesk.organization_id'), "
                                "current_setting('orderdesk.user_id')"
                            )
                            self.assertEqual(
                                cursor.fetchone(),
                                (
                                    "orderdesk_app",
                                    "orderdesk_app",
                                    "off",
                                    str(self.a.pk),
                                    str(self.admin.pk),
                                ),
                            )
                    return execute(sql, params, many, context)

                try:
                    barrier.wait()
                    with connection.execute_wrapper(inspect):
                        response = self._post_execution(client, csrf, raw, key)
                    self.assertTrue(prepared)
                    self._assert_clean()
                    return (
                        response.status_code,
                        response.json(),
                        request_pid,
                        response.get("Idempotency-Replayed"),
                    )
                finally:
                    connections["default"].close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(attempt, raw, key)
                    for raw, key in zip(raws, keys, strict=True)
                ]
                results = [future.result(timeout=25) for future in futures]
            self.assertEqual(len({result[2] for result in results}), 2)
            self.assertFalse(
                CatalogImportReceipt.objects.using(OWNER_ALIAS)
                .filter(
                    organization=self.a, state=CatalogImportReceipt.State.PROCESSING
                )
                .exists()
            )
            return results

        raw = self._csv_bytes([("RUNTIME-SAME-A", "", ""), ("RUNTIME-SAME-B", "", "")])
        key = uuid4()
        same = race((raw, raw), (key, key))
        self.assertCountEqual([result[0] for result in same], [201, 200])
        self.assertEqual(same[0][1], same[1][1])
        self.assertCountEqual([result[3] for result in same], ["false", "true"])

        key = uuid4()
        changed = race(
            (
                self._csv_bytes([("RUNTIME-KEY-A", "", "")]),
                self._csv_bytes([("RUNTIME-KEY-B", "", "")]),
            ),
            (key, key),
        )
        self.assertCountEqual([result[0] for result in changed], [201, 409])
        changed_conflict = next(result[1] for result in changed if result[0] == 409)
        self.assertEqual(
            changed_conflict,
            {
                "detail": (
                    "This idempotency key has already been used for a different "
                    "catalogue import."
                )
            },
        )

        overlap = race(
            (
                self._csv_bytes(
                    [("RUNTIME-OVERLAP", "", ""), ("RUNTIME-UNIQUE-A", "", "")]
                ),
                self._csv_bytes(
                    [("RUNTIME-OVERLAP", "", ""), ("RUNTIME-UNIQUE-B", "", "")]
                ),
            ),
            (uuid4(), uuid4()),
        )
        self.assertCountEqual([result[0] for result in overlap], [201, 409])
        winner = next(result[1] for result in overlap if result[0] == 201)
        self.assertEqual(
            set(
                CatalogItem.objects.using(OWNER_ALIAS)
                .filter(organization=self.a, sku__startswith="RUNTIME-UNIQUE-")
                .values_list("sku", flat=True)
            ),
            {row["sku"] for row in winner["items"] if "UNIQUE" in row["sku"]},
        )
        self.assertEqual(
            CatalogImportReceipt.objects.using(OWNER_ALIAS)
            .filter(organization=self.a)
            .count(),
            3,
        )
        self._assert_clean()
