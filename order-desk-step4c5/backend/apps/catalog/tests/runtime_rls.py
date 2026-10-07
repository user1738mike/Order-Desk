"""Run explicitly via verify_catalog_rls, never under the owner's Django runner.

The default connection authenticates as orderdesk_app. The separate owner alias
only creates/changes/cleans synthetic fixtures in the guarded test database.
Some tests intentionally forge local settings to bypass application checks and
exercise the database policies themselves; never copy that into services.
"""

import unittest
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from datetime import timedelta
from ipaddress import IPv6Address
from queue import Queue
from secrets import token_urlsafe
from threading import Barrier, Event
from time import monotonic
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.sessions.models import Session
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts.login_limits import login_bucket_key
from apps.accounts.models import LoginAttemptBucket, User
from apps.catalog.models import CatalogItem
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
