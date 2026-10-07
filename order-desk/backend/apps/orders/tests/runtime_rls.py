"""Direct runtime-role checks; run only through the guarded order RLS verifier.

The default connection authenticates as orderdesk_app. Synthetic fixtures use
the separate, audited maintenance connection. No source files are written.
"""

import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from ipaddress import IPv6Address
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone
from psycopg import sql
from rest_framework.test import APIClient

from apps.accounts.login_limits import login_bucket_key
from apps.accounts.models import LoginAttemptBucket, User
from apps.catalog.tests.runtime_rls import OWNER_ALIAS, _forged_policy_context
from apps.orders.models import (
    DraftOrder,
    DraftOrderLine,
    ExtractionReviewStatus,
    OrderDocument,
    OrderDocumentReview,
    PurchaseOrder,
    PurchaseOrderLine,
)
from apps.orders.services import create_document_review, resolve_document_review
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.transactions import tenant_scope

BUSINESS_MODELS = (
    PurchaseOrder,
    PurchaseOrderLine,
    OrderDocument,
    OrderDocumentReview,
)
DRAFT_MODELS = (DraftOrder, DraftOrderLine)


class RuntimeOrderRLSChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.user_ids: list[UUID] = []
        self.workspace_ids: list[UUID] = []
        self.session_keys: list[str] = []
        self.login_bucket_keys: list[str] = []
        self.addCleanup(self._cleanup_fixtures)
        self.rows: dict[UUID, dict[type, object]] = {}
        self.drafts: dict[UUID, dict[type, object]] = {}
        with transaction.atomic(using=OWNER_ALIAS):
            self.admin = self._user()
            self.viewer = self._user()
            self.reviewer = self._user()
            self.outsider = self._user(is_staff=True, is_superuser=True)
            self.a = self._workspace("Synthetic order distributor A")
            self.b = self._workspace("Synthetic order distributor B")
            self.admin_membership = self._membership(
                self.admin, self.a, MembershipRole.ADMIN
            )
            self._membership(self.admin, self.b, MembershipRole.ADMIN)
            self._membership(self.viewer, self.a, MembershipRole.VIEWER)
            self._membership(self.reviewer, self.a, MembershipRole.REVIEWER)
            for workspace in (self.a, self.b):
                self.rows[workspace.pk] = {}
                for model in BUSINESS_MODELS:
                    self.rows[workspace.pk][model] = self._insert(
                        model, workspace, using=OWNER_ALIAS
                    )
                self.drafts[workspace.pk] = {}
                for model in DRAFT_MODELS:
                    self.drafts[workspace.pk][model] = self._insert_draft(
                        model, workspace, using=OWNER_ALIAS
                    )

    def _user(self, **flags: bool) -> User:
        user = User.objects.db_manager(OWNER_ALIAS).create_user(
            email=f"order-rls-{uuid4().hex}@example.test", **flags
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
        connection.close()
        with transaction.atomic(using=OWNER_ALIAS):
            Session.objects.using(OWNER_ALIAS).filter(
                session_key__in=self.session_keys
            ).delete()
            LoginAttemptBucket.objects.using(OWNER_ALIAS).filter(
                key__in=self.login_bucket_keys
            ).delete()
            for model in reversed(DRAFT_MODELS):
                model.objects.using(OWNER_ALIAS).filter(
                    organization_id__in=self.workspace_ids
                ).delete()
            for model in reversed(BUSINESS_MODELS):
                model.objects.using(OWNER_ALIAS).filter(
                    organization_id__in=self.workspace_ids
                ).delete()
            Membership.objects.using(OWNER_ALIAS).filter(
                organization_id__in=self.workspace_ids
            ).delete()
            Organization.objects.using(OWNER_ALIAS).filter(
                pk__in=self.workspace_ids
            ).delete()
            User.objects.using(OWNER_ALIAS).filter(pk__in=self.user_ids).delete()

    def _insert(
        self, model: type, workspace: Organization, *, using: str = "default"
    ) -> object:
        values = {"organization_id": workspace.pk}
        parents = self.rows.get(workspace.pk, {})
        if model is PurchaseOrder:
            values.update(
                created_by_id=self.admin.pk,
                customer_name="Synthetic buyer",
                purchase_order_number=f"RLS-{uuid4().hex}",
            )
        elif model is PurchaseOrderLine:
            values.update(
                order_id=parents[PurchaseOrder].pk,
                line_number=1000 + (uuid4().int % 1000000000),
                sku="SYNTHETIC-SKU",
                quantity=1,
            )
        elif model is OrderDocument:
            values.update(
                order_id=parents[PurchaseOrder].pk,
                uploaded_by_id=self.admin.pk,
                file=f"orders/rls/{uuid4().hex}.pdf",
                original_name="synthetic.pdf",
                content_type="application/pdf",
                size_bytes=10,
            )
        elif model is OrderDocumentReview:
            values.update(
                document_id=parents[OrderDocument].pk,
                created_by_id=self.admin.pk,
                status=ExtractionReviewStatus.ACCEPTED,
                resolved_by_id=self.admin.pk,
                resolved_at=timezone.now(),
            )
        return model.objects.using(using).create(**values)

    def _insert_draft(
        self,
        model: type,
        workspace: Organization,
        *,
        actor: User | None = None,
        using: str = "default",
    ) -> object:
        if model is DraftOrder:
            return DraftOrder.objects.using(using).create(
                organization_id=workspace.pk,
                initiating_user_id=(actor or self.admin).pk,
            )
        if model is DraftOrderLine:
            return DraftOrderLine.objects.using(using).create(
                organization_id=workspace.pk,
                order_id=self.drafts[workspace.pk][DraftOrder].pk,
                position=1000 + (uuid4().int % 1000000000),
                requested_description="Synthetic unresolved line",
            )
        raise ValueError("Unsupported draft model")

    @staticmethod
    def _visible_ids(model: type) -> set[UUID]:
        # Intentionally omit workspace filters: PostgreSQL must enforce scope.
        return set(model.objects.values_list("id", flat=True))

    def _assert_clean(self) -> None:
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting("
                "'orderdesk.organization_id', true), ''), "
                "NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))
        for model in BUSINESS_MODELS:
            self.assertEqual(self._visible_ids(model), set())
        for model in DRAFT_MODELS:
            self.assertEqual(self._visible_ids(model), set())

    def _write_scope(self, user: User | None = None) -> AbstractContextManager:
        return tenant_scope(user=user or self.admin, workspace_id=self.a.pk, write=True)

    def _expect_error(
        self, state: str, scope: AbstractContextManager, action: Callable[[], object]
    ) -> None:
        with self.assertRaises(DatabaseError) as error:
            with scope:
                action()
                # Roll back unexpectedly permitted writes and DDL as well.
                self.fail("A forbidden order database operation succeeded.")
        self.assertEqual(error.exception.__cause__.sqlstate, state)
        self._assert_clean()

    @staticmethod
    def _execute(statement: str | sql.Composed) -> None:
        with connection.cursor() as cursor:
            cursor.execute(statement)

    def _race_review_service(self, action: Callable, choices: tuple[str, str]) -> list:
        ready = Barrier(2, timeout=10)

        def attempt(actor_id: UUID, choice: str) -> dict:
            close_old_connections()
            try:
                actor = User.objects.get(pk=actor_id)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                    cursor.execute(
                        "SELECT current_user, session_user, pg_backend_pid()"
                    )
                    identity = cursor.fetchone()
                self.assertEqual(identity[:2], ("orderdesk_app", "orderdesk_app"))
                ready.wait()
                try:
                    review = action(actor, choice)
                except ValidationError as error:
                    return {
                        "outcome": "denied",
                        "identity": identity,
                        "errors": error.message_dict,
                    }
                return {
                    "outcome": "ok",
                    "identity": identity,
                    "id": review.pk,
                    "status": review.status,
                    "resolved_by": review.resolved_by_id,
                    "resolved_at": review.resolved_at,
                    "notes": review.notes,
                    "actor": actor.pk,
                }
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, actor.pk, choice)
                for actor, choice in zip(
                    (self.admin, self.reviewer), choices, strict=True
                )
            ]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(len({result["identity"][2] for result in results}), 2)
        self.assertCountEqual(
            [result["outcome"] for result in results], ["ok", "denied"]
        )
        denied = next(result for result in results if result["outcome"] == "denied")
        self.assertIn("status", denied["errors"])
        self._assert_clean()
        return results

    def _credential_client(self, user: User) -> tuple[APIClient, str]:
        credential = f"Synthetic-order-RLS-{uuid4().hex}"
        user.set_password(credential)
        user.save(using=OWNER_ALIAS, update_fields=["password"])
        peer = IPv6Address(
            int(IPv6Address("2001:db8::")) | (uuid4().int & ((1 << 96) - 1))
        ).compressed
        self.login_bucket_keys.extend(
            [login_bucket_key("email", user.email), login_bucket_key("peer", peer)]
        )
        client = APIClient(
            enforce_csrf_checks=True, HTTP_HOST="localhost", REMOTE_ADDR=peer
        )
        csrf = client.get("/api/v1/auth/csrf/")
        self.assertEqual(csrf.status_code, 200)
        response = client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": credential},
            format="json",
            HTTP_X_CSRFTOKEN=csrf.json()["csrf_token"],
        )
        cookie = client.cookies.get(settings.SESSION_COOKIE_NAME)
        if cookie is not None:
            self.session_keys.append(cookie.value)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(cookie)
        return client, response.json()["csrf_token"]

    def test_missing_context_exposes_no_business_rows(self) -> None:
        self._assert_clean()

    def test_draft_http_reads_with_real_runtime_sessions(self) -> None:
        for actor in (self.admin, self.reviewer, self.viewer):
            client, _ = self._credential_client(actor)
            path = f"/api/v1/workspaces/{self.a.pk}/draft-orders/"
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["count"], 1)
            row = response.json()["results"][0]
            self.assertEqual(row["id"], str(self.drafts[self.a.pk][DraftOrder].pk))
            self.assertEqual(row["line_count"], 1)
            self.assertNotIn("original_intake_text", row)
            detail_path = f"{path}{row['id']}/"
            detail = client.get(detail_path)
            self.assertEqual(detail.status_code, 200)
            lines = client.get(detail.json()["lines_url"])
            self.assertEqual(lines.status_code, 200)
            self.assertEqual(lines.json()["count"], 1)
            line = lines.json()["results"][0]
            self.assertEqual(line["id"], str(self.drafts[self.a.pk][DraftOrderLine].pk))
            self.assertIsNone(line["quantity"])
            self.assertIsNone(line["catalogue_item_id"])
            foreign = self.drafts[self.b.pk][DraftOrder].pk
            for suffix in ("", "lines/"):
                self.assertEqual(
                    client.get(f"{path}{foreign}/{suffix}").status_code, 404
                )
            self._assert_clean()

    def test_draft_http_refreshes_revoked_membership(self) -> None:
        client, _ = self._credential_client(self.viewer)
        path = f"/api/v1/workspaces/{self.a.pk}/draft-orders/"
        self.assertEqual(client.get(path).status_code, 200)
        Membership.objects.using(OWNER_ALIAS).filter(
            user=self.viewer, organization=self.a
        ).update(is_active=False)
        self.assertEqual(client.get(path).status_code, 403)
        self._assert_clean()

    def test_draft_creation_validation_and_revocation_as_runtime_role(self) -> None:
        client, token = self._credential_client(self.admin)
        path = f"/api/v1/workspaces/{self.a.pk}/draft-orders/"
        original_count = (
            DraftOrder.objects.using(OWNER_ALIAS).filter(organization=self.a).count()
        )
        invalid = client.post(
            path, {"customer_name": "   "}, format="json", HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            DraftOrder.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            original_count,
        )
        created = client.post(path, {}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["organization_id"], str(self.a.pk))
        self.assertEqual(created.json()["initiating_user_id"], str(self.admin.pk))
        Membership.objects.using(OWNER_ALIAS).filter(
            pk=self.admin_membership.pk
        ).update(is_active=False)
        denied = client.post(path, {}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(denied.status_code, 403)
        for suffix in (
            "",
            f"{created.json()['id']}/",
            f"{created.json()['id']}/lines/",
        ):
            self.assertEqual(client.get(path + suffix).status_code, 403)
        self.assertEqual(
            DraftOrder.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            original_count + 1,
        )
        self._assert_clean()

    def test_requested_line_http_creation_conflict_and_revocation(self) -> None:
        for position, actor in enumerate((self.admin, self.reviewer), 1):
            client, token = self._credential_client(actor)
            order = self.drafts[self.a.pk][DraftOrder]
            path = f"/api/v1/workspaces/{self.a.pk}/draft-orders/{order.pk}/lines/"
            body = {"position": position, "requested_sku": "Original requested SKU"}
            created = client.post(path, body, format="json", HTTP_X_CSRFTOKEN=token)
            self.assertEqual(created.status_code, 201, created.content)
            self.assertIsNone(created.json()["quantity"])
            self.assertIsNone(created.json()["catalogue_item_id"])
            self.assertEqual(created.json()["organization_id"], str(self.a.pk))
            self.assertEqual(
                client.post(
                    path, body, format="json", HTTP_X_CSRFTOKEN=token
                ).status_code,
                409,
            )
            foreign = self.drafts[self.b.pk][DraftOrder]
            foreign_path = path.replace(str(order.pk), str(foreign.pk))
            self.assertEqual(
                client.post(
                    foreign_path, body, format="json", HTTP_X_CSRFTOKEN=token
                ).status_code,
                404,
            )
            Membership.objects.using(OWNER_ALIAS).filter(
                user=actor, organization=self.a
            ).update(is_active=False)
            self.assertEqual(
                client.post(
                    path, body, format="json", HTTP_X_CSRFTOKEN=token
                ).status_code,
                403,
            )
            self._assert_clean()
        viewer, token = self._credential_client(self.viewer)
        self.assertEqual(
            viewer.post(path, body, format="json", HTTP_X_CSRFTOKEN=token).status_code,
            403,
        )
        self._assert_clean()

    def test_draft_reads_are_tenant_scoped_without_application_filters(self) -> None:
        for workspace in (self.a, self.b):
            for actor in (self.admin, self.viewer, self.reviewer):
                if actor is not self.admin and workspace is self.b:
                    continue
                with tenant_scope(user=actor, workspace_id=workspace.pk):
                    for model in DRAFT_MODELS:
                        self.assertEqual(
                            self._visible_ids(model),
                            {self.drafts[workspace.pk][model].pk},
                        )
                self._assert_clean()
        with _forged_policy_context(self.a.pk, self.outsider.pk):
            for model in DRAFT_MODELS:
                self.assertEqual(self._visible_ids(model), set())

    def test_draft_missing_context_and_cross_tenant_writes_fail(self) -> None:
        for model in DRAFT_MODELS:
            with self.subTest(model=model):
                self._expect_error(
                    "42501",
                    _forged_policy_context(None, None),
                    lambda model=model: self._insert_draft(model, self.a),
                )
                self._expect_error(
                    "42501",
                    self._write_scope(),
                    lambda model=model: self._insert_draft(model, self.b),
                )

    def test_draft_admin_reviewer_write_and_viewer_write_denial(self) -> None:
        for actor in (self.admin, self.reviewer):
            with self.subTest(actor=actor.pk), self._write_scope(actor):
                header = self._insert_draft(DraftOrder, self.a, actor=actor)
                line = self._insert_draft(DraftOrderLine, self.a, actor=actor)
                self.assertEqual(
                    DraftOrder.objects.filter(pk=header.pk).update(
                        customer_reference="changed"
                    ),
                    1,
                )
                self.assertEqual(
                    DraftOrderLine.objects.filter(pk=line.pk).update(
                        requested_description="changed"
                    ),
                    1,
                )
        with self._write_scope(self.viewer):
            self.assertEqual(
                DraftOrder.objects.filter(
                    pk=self.drafts[self.a.pk][DraftOrder].pk
                ).update(customer_reference="denied"),
                0,
            )
            self.assertEqual(
                DraftOrderLine.objects.filter(
                    pk=self.drafts[self.a.pk][DraftOrderLine].pk
                ).update(requested_description="denied"),
                0,
            )
        for model in DRAFT_MODELS:
            self._expect_error(
                "42501",
                self._write_scope(self.viewer),
                lambda model=model: self._insert_draft(
                    model, self.a, actor=self.viewer
                ),
            )

    def test_draft_forged_initiator_and_immutable_columns_fail(self) -> None:
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: self._insert_draft(DraftOrder, self.a, actor=self.viewer),
        )
        for model, column in (
            (DraftOrder, "id"),
            (DraftOrder, "organization_id"),
            (DraftOrder, "initiating_user_id"),
            (DraftOrder, "created_at"),
            (DraftOrderLine, "id"),
            (DraftOrderLine, "organization_id"),
            (DraftOrderLine, "order_id"),
            (DraftOrderLine, "created_at"),
        ):
            row = self.drafts[self.a.pk][model]
            self._expect_error(
                "42501",
                self._write_scope(),
                lambda model=model, row=row, column=column: model.objects.filter(
                    pk=row.pk
                ).update(**{column: getattr(row, column)}),
            )

    def test_draft_foreign_rows_cannot_be_updated(self) -> None:
        with self._write_scope():
            self.assertEqual(
                DraftOrder.objects.filter(
                    pk=self.drafts[self.b.pk][DraftOrder].pk
                ).update(customer_name="Forbidden"),
                0,
            )
            self.assertEqual(
                DraftOrderLine.objects.filter(
                    pk=self.drafts[self.b.pk][DraftOrderLine].pk
                ).update(requested_description="Forbidden"),
                0,
            )
        self._assert_clean()

    def test_draft_revocation_and_demotion_take_effect_in_existing_context(
        self,
    ) -> None:
        with _forged_policy_context(self.a.pk, self.admin.pk):
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(role=MembershipRole.VIEWER)
            for model in DRAFT_MODELS:
                self.assertEqual(
                    self._visible_ids(model), {self.drafts[self.a.pk][model].pk}
                )
            self.assertEqual(
                DraftOrder.objects.filter(
                    pk=self.drafts[self.a.pk][DraftOrder].pk
                ).update(customer_name="denied"),
                0,
            )
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(is_active=False)
            for model in DRAFT_MODELS:
                self.assertEqual(self._visible_ids(model), set())

    def test_draft_rollback_clears_context_and_row(self) -> None:
        with self.assertRaises(ValueError):
            with self._write_scope():
                row = self._insert_draft(DraftOrder, self.a)
                raise ValueError("Synthetic draft rollback")
        self._assert_clean()
        self.assertFalse(
            DraftOrder.objects.using(OWNER_ALIAS).filter(pk=row.pk).exists()
        )

    def test_missing_or_blank_context_denies_reads_and_inserts(self) -> None:
        for organization_id, user_id in (
            (None, None),
            (None, self.admin.pk),
            (self.a.pk, None),
            ("", self.admin.pk),
            (self.a.pk, ""),
        ):
            for model in (*BUSINESS_MODELS, *DRAFT_MODELS):
                with self.subTest(
                    model=model, organization=organization_id, user=user_id
                ):
                    with _forged_policy_context(organization_id, user_id):
                        self.assertEqual(self._visible_ids(model), set())
                    self._expect_error(
                        "42501",
                        _forged_policy_context(organization_id, user_id),
                        lambda model=model: (
                            self._insert_draft(model, self.a)
                            if model in DRAFT_MODELS
                            else self._insert(model, self.a)
                        ),
                    )

    def test_unfiltered_reads_only_return_current_workspace(self) -> None:
        for workspace in (self.a, self.b):
            with tenant_scope(user=self.admin, workspace_id=workspace.pk):
                for model in BUSINESS_MODELS:
                    self.assertEqual(
                        self._visible_ids(model), {self.rows[workspace.pk][model].pk}
                    )
            self._assert_clean()

    def test_admin_of_both_workspaces_cannot_read_or_update_foreign_rows(self) -> None:
        with self._write_scope():
            for model in BUSINESS_MODELS:
                foreign = self.rows[self.b.pk][model]
                self.assertFalse(model.objects.filter(pk=foreign.pk).exists())
                self.assertEqual(
                    model.objects.filter(pk=foreign.pk).update(
                        organization_id=self.a.pk
                    ),
                    0,
                )

    def test_cross_workspace_inserts_are_denied(self) -> None:
        for model in BUSINESS_MODELS:
            with self.subTest(model=model):
                self._expect_error(
                    "42501",
                    self._write_scope(),
                    lambda model=model: self._insert(model, self.b),
                )

    def test_existing_business_rows_cannot_change_workspace(self) -> None:
        for model in BUSINESS_MODELS:
            with self.subTest(model=model):
                self._expect_error(
                    "42501",
                    self._write_scope(),
                    lambda model=model: model.objects.filter(
                        pk=self.rows[self.a.pk][model].pk
                    ).update(organization_id=self.b.pk),
                )

    def test_foreign_parent_ids_are_rejected_by_composite_foreign_keys(self) -> None:
        for child, parent, field in (
            (PurchaseOrderLine, PurchaseOrder, "order_id"),
            (OrderDocument, PurchaseOrder, "order_id"),
            (OrderDocumentReview, OrderDocument, "document_id"),
        ):
            with self.subTest(child=child):
                self._expect_error(
                    "23503",
                    self._write_scope(),
                    lambda child=child, parent=parent, field=field: (
                        child.objects.filter(pk=self.rows[self.a.pk][child].pk).update(
                            **{field: self.rows[self.b.pk][parent].pk}
                        )
                    ),
                )

    def test_viewer_can_read_all_four_business_tables(self) -> None:
        with tenant_scope(user=self.viewer, workspace_id=self.a.pk):
            for model in BUSINESS_MODELS:
                self.assertEqual(
                    self._visible_ids(model), {self.rows[self.a.pk][model].pk}
                )

    def test_viewer_cannot_insert_or_update_business_rows(self) -> None:
        for model in BUSINESS_MODELS:
            with self.subTest(model=model):
                with self._write_scope(self.viewer):
                    self.assertEqual(
                        model.objects.filter(pk=self.rows[self.a.pk][model].pk).update(
                            organization_id=self.a.pk
                        ),
                        0,
                    )
                self._expect_error(
                    "42501",
                    self._write_scope(self.viewer),
                    lambda model=model: self._insert(model, self.a),
                )

    def test_admin_and_reviewer_can_insert_and_update_current_workspace(self) -> None:
        for user in (self.admin, self.reviewer):
            with self.subTest(user=user.pk), self._write_scope(user):
                for model in BUSINESS_MODELS:
                    row = self._insert(model, self.a)
                    self.assertEqual(
                        model.objects.filter(pk=row.pk).update(
                            organization_id=self.a.pk
                        ),
                        1,
                    )

    def test_nonmember_operator_flags_do_not_bypass_policies(self) -> None:
        with _forged_policy_context(self.a.pk, self.outsider.pk):
            for model in BUSINESS_MODELS:
                self.assertEqual(self._visible_ids(model), set())
        for model in (*BUSINESS_MODELS, *DRAFT_MODELS):
            with self.subTest(model=model):
                self._expect_error(
                    "42501",
                    _forged_policy_context(self.a.pk, self.outsider.pk),
                    lambda model=model: (
                        self._insert_draft(model, self.a)
                        if model in DRAFT_MODELS
                        else self._insert(model, self.a)
                    ),
                )

    def test_revocation_invalidates_existing_context(self) -> None:
        with _forged_policy_context(self.a.pk, self.admin.pk):
            self.assertTrue(self._visible_ids(PurchaseOrder))
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(is_active=False)
            for model in BUSINESS_MODELS:
                self.assertEqual(self._visible_ids(model), set())

    def test_account_and_workspace_deactivation_invalidate_context(self) -> None:
        for model, row in ((User, self.admin), (Organization, self.a)):
            with self.subTest(model=model):
                with _forged_policy_context(self.a.pk, self.admin.pk):
                    model.objects.using(OWNER_ALIAS).filter(pk=row.pk).update(
                        is_active=False
                    )
                    for business_model in BUSINESS_MODELS:
                        self.assertEqual(self._visible_ids(business_model), set())
                    for draft_model in DRAFT_MODELS:
                        self.assertEqual(self._visible_ids(draft_model), set())
                model.objects.using(OWNER_ALIAS).filter(pk=row.pk).update(
                    is_active=True
                )

    def test_demotion_removes_writes_from_existing_context(self) -> None:
        with _forged_policy_context(self.a.pk, self.admin.pk):
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=self.admin_membership.pk
            ).update(role=MembershipRole.VIEWER)
            for model in BUSINESS_MODELS:
                self.assertTrue(self._visible_ids(model))
                self.assertEqual(
                    model.objects.filter(pk=self.rows[self.a.pk][model].pk).update(
                        organization_id=self.a.pk
                    ),
                    0,
                )

    def test_malformed_context_fails_closed(self) -> None:
        for organization_id, user_id in (
            ("not-a-uuid", self.admin.pk),
            (self.a.pk, "not-a-uuid"),
        ):
            for model in (*BUSINESS_MODELS, *DRAFT_MODELS):
                with self.subTest(model=model, organization=organization_id):
                    self._expect_error(
                        "22P02",
                        _forged_policy_context(organization_id, user_id),
                        lambda model=model: self._visible_ids(model),
                    )

    def test_rollback_clears_scope_and_reverses_business_write(self) -> None:
        with self.assertRaises(ValueError):
            with self._write_scope():
                row = self._insert(PurchaseOrder, self.a)
                raise ValueError("Rollback a synthetic order.")
        self._assert_clean()
        self.assertFalse(
            PurchaseOrder.objects.using(OWNER_ALIAS).filter(pk=row.pk).exists()
        )

    def test_read_only_scope_rejects_business_writes(self) -> None:
        self._expect_error(
            "25006",
            tenant_scope(user=self.admin, workspace_id=self.a.pk),
            lambda: PurchaseOrder.objects.filter(
                pk=self.rows[self.a.pk][PurchaseOrder].pk
            ).update(customer_name="Forbidden"),
        )

    def test_delete_and_truncate_are_denied_on_every_business_table(self) -> None:
        for model in (*BUSINESS_MODELS, *DRAFT_MODELS):
            for operation in ("DELETE FROM", "TRUNCATE TABLE"):
                with self.subTest(model=model, operation=operation):
                    # The operation comes only from this fixed list; quote names.
                    statement = sql.SQL("{} public.{}").format(
                        sql.SQL(operation), sql.Identifier(model._meta.db_table)
                    )
                    self._expect_error(
                        "42501",
                        self._write_scope(),
                        lambda statement=statement: self._execute(statement),
                    )

    def test_runtime_cannot_assume_owner_or_disable_rls(self) -> None:
        self._expect_error(
            "42501",
            self._write_scope(),
            lambda: self._execute("SET ROLE orderdesk_migrator"),
        )
        for model in (*BUSINESS_MODELS, *DRAFT_MODELS):
            with self.subTest(model=model):
                statement = sql.SQL(
                    "ALTER TABLE public.{} DISABLE ROW LEVEL SECURITY"
                ).format(sql.Identifier(model._meta.db_table))
                self._expect_error(
                    "42501",
                    self._write_scope(),
                    lambda statement=statement: self._execute(statement),
                )

    def test_row_security_off_cannot_bypass_order_policies(self) -> None:
        def attempt() -> object:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_catalog.set_config('row_security', 'off', true)"
                )
            return self._visible_ids(PurchaseOrder)

        self._expect_error("42501", self._write_scope(), attempt)

        def attempt_draft() -> object:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_catalog.set_config('row_security', 'off', true)"
                )
            return self._visible_ids(DraftOrder)

        self._expect_error("42501", self._write_scope(), attempt_draft)

    def test_concurrent_review_creation_keeps_exactly_one_pending_review(self) -> None:
        document = self.rows[self.a.pk][OrderDocument]

        def create(actor: User, notes: str) -> OrderDocumentReview:
            return create_document_review(
                actor=actor,
                organization_id=self.a.pk,
                document_id=document.pk,
                notes=notes,
            )

        results = self._race_review_service(
            create, ("Admin proposal", "Reviewer proposal")
        )
        winner = next(result for result in results if result["outcome"] == "ok")
        pending = OrderDocumentReview.objects.using(OWNER_ALIAS).get(
            document_id=document.pk,
            status=ExtractionReviewStatus.NEEDS_REVIEW,
        )
        self.assertEqual(pending.pk, winner["id"])
        self.assertEqual(pending.created_by_id, winner["actor"])
        self.assertEqual(pending.notes, winner["notes"])
        self.assertIsNone(pending.resolved_by_id)
        self.assertIsNone(pending.resolved_at)
        document.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(document.status, "pending_review")

    def test_concurrent_resolution_preserves_the_first_terminal_outcome(self) -> None:
        document = self.rows[self.a.pk][OrderDocument]
        review = create_document_review(
            actor=User.objects.get(pk=self.admin.pk),
            organization_id=self.a.pk,
            document_id=document.pk,
        )

        def resolve(actor: User, status: str) -> OrderDocumentReview:
            return resolve_document_review(
                actor=actor,
                organization_id=self.a.pk,
                review_id=review.pk,
                status=status,
                notes=f"Synthetic {status} decision",
            )

        results = self._race_review_service(
            resolve,
            (ExtractionReviewStatus.ACCEPTED, ExtractionReviewStatus.REJECTED),
        )
        winner = next(result for result in results if result["outcome"] == "ok")
        review.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(review.status, winner["status"])
        self.assertEqual(review.resolved_by_id, winner["actor"])
        self.assertEqual(review.resolved_by_id, winner["resolved_by"])
        self.assertEqual(review.resolved_at, winner["resolved_at"])
        self.assertEqual(review.notes, winner["notes"])
        self.assertIsNotNone(review.resolved_at)
        document.refresh_from_db(using=OWNER_ALIAS)
        self.assertEqual(
            document.status,
            "received"
            if winner["status"] == ExtractionReviewStatus.ACCEPTED
            else "rejected",
        )

    def test_credential_http_session_keeps_unfiltered_prefetch_inside_rls(self) -> None:
        client, _ = self._credential_client(self.admin)
        unfiltered = (
            PurchaseOrder.objects.all()
            .prefetch_related("lines", "documents__reviews")
            .order_by("id")
        )
        with patch(
            "apps.orders.views.selectors.purchase_orders_for_workspace",
            return_value=unfiltered,
        ):
            response = client.get(f"/api/v1/workspaces/{self.a.pk}/orders/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        order = data["results"][0]
        self.assertEqual(order["id"], str(self.rows[self.a.pk][PurchaseOrder].pk))
        self.assertEqual(
            [line["id"] for line in order["lines"]],
            [str(self.rows[self.a.pk][PurchaseOrderLine].pk)],
        )
        self.assertEqual(
            [document["id"] for document in order["documents"]],
            [str(self.rows[self.a.pk][OrderDocument].pk)],
        )
        self.assertEqual(
            [review["id"] for review in order["documents"][0]["reviews"]],
            [str(self.rows[self.a.pk][OrderDocumentReview].pk)],
        )
        self._assert_clean()

    def test_credential_http_writes_require_csrf_and_current_reviewer_access(
        self,
    ) -> None:
        reviewer_client, token = self._credential_client(self.reviewer)
        order = self.rows[self.a.pk][PurchaseOrder]
        path = f"/api/v1/workspaces/{self.a.pk}/orders/{order.pk}/lines/"
        values = {"line_number": 2000000001, "sku": "HTTP-SYNTHETIC", "quantity": "2"}
        self.assertEqual(
            reviewer_client.post(path, values, format="json").status_code, 403
        )
        created = reviewer_client.post(
            path, values, format="json", HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["sku"], "HTTP-SYNTHETIC")
        viewer_client, viewer_token = self._credential_client(self.viewer)
        values = {**values, "line_number": 2000000002}
        denied = viewer_client.post(
            path, values, format="json", HTTP_X_CSRFTOKEN=viewer_token
        )
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(
            PurchaseOrderLine.objects.using(OWNER_ALIAS)
            .filter(order_id=order.pk, line_number=2000000002)
            .exists()
        )
        self._assert_clean()
