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
from threading import Event
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
        for method in (client.post, client.put, client.patch, client.delete):
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
