"""Protected manual catalogue attachment contract tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.http import Http404
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.serializers import DraftOrderLineReadSerializer
from apps.orders.services import (
    DraftLineCatalogueAttachmentConflict,
    attach_catalogue_item_to_draft_order_line,
)
from apps.orders.tests import test_concurrency
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.services import create_organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DraftLineAttachmentTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="draft-attach@example.test")
        self.workspace = create_organization(
            actor=self.user, name="Synthetic attachment workspace"
        )
        self.membership = Membership.objects.get(
            user=self.user, organization=self.workspace
        )
        self.other = create_organization(
            actor=self.user, name="Foreign attachment workspace"
        )
        self.order = DraftOrder.objects.create(
            organization=self.workspace,
            initiating_user=self.user,
            original_intake_text="Attach the requested item.",
        )
        self.line = DraftOrderLine.objects.create(
            organization=self.workspace,
            order=self.order,
            position=1,
            requested_sku="REQUESTED-SKU",
            requested_description="Requested part",
            quantity=1,
            unit="ea",
        )
        self.item = CatalogItem.objects.create(
            organization=self.workspace,
            sku="CATALOG-SKU",
            description="Catalog description",
        )
        self.url = (
            f"/api/v1/workspaces/{self.workspace.pk}/draft-orders/"
            f"{self.order.pk}/lines/{self.line.pk}/attach/"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]

    def attach(self, body, **kwargs):
        return self.client.post(
            self.url,
            body,
            format="json",
            HTTP_X_CSRFTOKEN=self.token,
            **kwargs,
        )

    def assert_clean(self):
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                " NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def state(self):
        return DraftOrderLine.objects.values().get(pk=self.line.pk)

    def service(self, item_id=None, **kwargs):
        return attach_catalogue_item_to_draft_order_line(
            actor=self.user,
            organization_id=self.workspace.pk,
            order_id=self.order.pk,
            line_id=self.line.pk,
            catalogue_item_id=item_id or self.item.pk,
            **kwargs,
        )

    def test_active_same_workspace_item_snapshots_and_preserves_request(self):
        response = self.attach({"catalogue_item_id": str(self.item.pk)})
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["catalogue_item_id"], str(self.item.pk))
        self.assertEqual(body["catalogue_sku_snapshot"], self.item.sku)
        self.assertEqual(body["catalogue_description_snapshot"], self.item.description)
        self.assertEqual(body["requested_sku"], "REQUESTED-SKU")
        self.assertEqual(body["requested_description"], "Requested part")
        self.assertEqual(body["quantity"], "1.000")
        self.assertEqual(body["unit"], "ea")
        self.line.refresh_from_db()
        self.assertEqual(self.line.catalogue_item_id, self.item.pk)
        self.assertEqual(self.line.catalogue_sku_snapshot, self.item.sku)
        self.assertEqual(
            self.line.catalogue_description_snapshot, self.item.description
        )
        self.assert_clean()

    def test_admin_and_reviewer_can_attach_but_viewer_cannot(self):
        for role in (MembershipRole.ADMIN, MembershipRole.REVIEWER):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            self.line.catalogue_item_id = None
            self.line.catalogue_sku_snapshot = ""
            self.line.catalogue_description_snapshot = ""
            self.line.save(
                update_fields=[
                    "catalogue_item",
                    "catalogue_sku_snapshot",
                    "catalogue_description_snapshot",
                ]
            )
            response = self.attach({"catalogue_item_id": str(self.item.pk)})
            self.assertEqual(response.status_code, 200, response.content)
            self.line.refresh_from_db()
            self.assertEqual(self.line.catalogue_item_id, self.item.pk)

        self.membership.role = MembershipRole.VIEWER
        self.membership.save(update_fields=["role"])
        response = self.attach({"catalogue_item_id": str(self.item.pk)})
        self.assertEqual(response.status_code, 403, response.content)
        self.assert_clean()

    def test_inactive_missing_and_foreign_items_are_denied(self):
        inactive = CatalogItem.objects.create(
            organization=self.workspace,
            sku="INACTIVE-SKU",
            is_active=False,
        )
        foreign_item = CatalogItem.objects.create(
            organization=self.other,
            sku="FOREIGN-SKU",
        )
        for item_id in (inactive.pk, foreign_item.pk, uuid4()):
            response = self.attach({"catalogue_item_id": str(item_id)})
            self.assertEqual(response.status_code, 404, response.content)
            self.line.refresh_from_db()
            self.assertIsNone(self.line.catalogue_item_id)
        self.assert_clean()

    def test_already_attached_line_returns_409_and_is_unchanged(self):
        self.line.catalogue_item = self.item
        self.line.catalogue_sku_snapshot = self.item.sku
        self.line.catalogue_description_snapshot = self.item.description
        self.line.save(
            update_fields=[
                "catalogue_item",
                "catalogue_sku_snapshot",
                "catalogue_description_snapshot",
            ]
        )
        self.line.refresh_from_db()
        before = (
            self.line.catalogue_item_id,
            self.line.catalogue_sku_snapshot,
            self.line.catalogue_description_snapshot,
        )
        response = self.attach({"catalogue_item_id": str(self.item.pk)})
        self.assertEqual(response.status_code, 409, response.content)
        self.line.refresh_from_db()
        after = (
            self.line.catalogue_item_id,
            self.line.catalogue_sku_snapshot,
            self.line.catalogue_description_snapshot,
        )
        self.assertEqual(after, before)
        self.assert_clean()

    def test_invalid_or_immutable_request_fields_do_not_write(self):
        self.line.refresh_from_db()
        before = self.line.catalogue_item_id
        for body in (
            {},
            {"catalogue_item_id": str(self.item.pk), "unknown": True},
            {"catalogue_item_id": "not-a-uuid"},
            {"catalogue_item_id": None},
            {"catalogue_item_id": str(self.item.pk), "position": 2},
        ):
            response = self.attach(body)
            self.assertEqual(response.status_code, 400, response.content)
            self.line.refresh_from_db()
            self.assertEqual(self.line.catalogue_item_id, before)
        self.assert_clean()

    def test_non_json_media_and_unsupported_methods_are_rejected(self):
        response = self.client.post(
            self.url,
            {"catalogue_item_id": str(self.item.pk)},
            format="multipart",
            HTTP_X_CSRFTOKEN=self.token,
        )
        self.assertEqual(response.status_code, 415, response.content)
        for method in ("put", "patch", "delete"):
            response = getattr(self.client, method)(
                self.url,
                {"catalogue_item_id": str(self.item.pk)},
                format="json",
                HTTP_X_CSRFTOKEN=self.token,
            )
            self.assertEqual(response.status_code, 405, response.content)
        self.assert_clean()

    def test_timestamp_header_null_quantity_and_historical_snapshots(self):
        DraftOrderLine.objects.filter(pk=self.line.pk).update(quantity=None)
        before = self.state()
        header = DraftOrder.objects.values().get(pk=self.order.pk)
        later = before["updated_at"] + timedelta(seconds=10)
        with patch("django.utils.timezone.now", return_value=later):
            response = self.attach({"catalogue_item_id": str(self.item.pk)})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["quantity"])
        after = self.state()
        self.assertEqual(after["updated_at"], later)
        for field in before.keys() - {
            "catalogue_item_id",
            "catalogue_sku_snapshot",
            "catalogue_description_snapshot",
            "updated_at",
        }:
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(DraftOrder.objects.values().get(pk=self.order.pk), header)
        self.assertEqual(DraftOrderLine.objects.filter(order=self.order).count(), 1)
        CatalogItem.objects.filter(pk=self.item.pk).update(
            description="Changed", is_active=False
        )
        detail = self.client.get(self.url.removesuffix("attach/"))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            detail.json()["catalogue_description_snapshot"], "Catalog description"
        )
        repeat = self.attach({"catalogue_item_id": str(self.item.pk)})
        self.assertEqual(repeat.status_code, 409)
        self.assertEqual(
            repeat.json(), {"detail": "Already attached to a catalogue item."}
        )
        self.assertEqual(self.state(), after)

    def test_denied_writer_and_revoked_membership_before_parsing(self):
        before = self.state()
        self.membership.role = MembershipRole.VIEWER
        self.membership.save(update_fields=["role"])

        def malformed():
            return self.client.post(
                self.url,
                "{",
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self.token,
            )

        self.assertEqual(malformed().status_code, 403)
        self.membership.role = MembershipRole.ADMIN
        self.membership.is_active = False
        self.membership.save(update_fields=["role", "is_active"])
        self.assertEqual(malformed().status_code, 403)
        self.membership.delete()
        self.assertEqual(malformed().status_code, 403)
        stranger = User.objects.create_user(email="never-attached@example.test")
        self.client.force_login(stranger)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.assertEqual(malformed().status_code, 403)
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_parent_and_line_are_scoped_before_parsing(self):
        before = self.state()
        for workspace in (self.workspace, self.other):
            order = DraftOrder.objects.create(
                organization=workspace, initiating_user=self.user
            )
            line = DraftOrderLine.objects.create(
                organization=workspace, order=order, position=1, requested_sku="Other"
            )
            paths = (
                self.url.replace(str(self.line.pk), str(line.pk)),
                self.url.replace(str(self.order.pk), str(order.pk)),
            )
            if workspace == self.other:
                paths += (
                    self.url.replace(str(self.line.pk), str(line.pk)).replace(
                        str(self.order.pk), str(order.pk)
                    ),
                )
            for url in paths:
                response = self.client.post(
                    url,
                    "{",
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=self.token,
                )
                self.assertEqual(response.status_code, 404, response.content)
        for original in (self.line.pk, self.order.pk):
            response = self.client.post(
                self.url.replace(str(original), str(uuid4())),
                {},
                format="json",
                HTTP_X_CSRFTOKEN=self.token,
            )
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_csrf_queries_anonymous_and_action_read_methods(self):
        before = self.state()
        body = {"catalogue_item_id": str(self.item.pk)}
        self.assertEqual(
            self.client.post(self.url, body, format="json").status_code, 403
        )
        self.assertEqual(
            self.client.post(
                self.url, body, format="json", HTTP_X_CSRFTOKEN="invalid"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                self.url + "?unknown=1",
                body,
                format="json",
                HTTP_X_CSRFTOKEN=self.token,
            ).status_code,
            400,
        )
        for method in ("get", "head"):
            self.assertEqual(getattr(self.client, method)(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.attach(body).status_code, 403)
        self.assertEqual(self.state(), before)

    def test_model_validation_and_materialization_failures_roll_back(self):
        before = self.state()
        with patch.object(
            DraftOrderLine,
            "full_clean",
            side_effect=ValidationError(
                {"catalogue_sku_snapshot": ["Synthetic invalid snapshot"]}
            ),
        ):
            response = self.attach({"catalogue_item_id": str(self.item.pk)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"catalogue_sku_snapshot": ["Synthetic invalid snapshot"]}
        )
        with patch(
            "apps.orders.views.DraftOrderLineReadSerializer",
            side_effect=ValidationError("Synthetic response failure"),
        ):
            response = self.attach({"catalogue_item_id": str(self.item.pk)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"non_field_errors": ["Synthetic response failure"]}
        )
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_materialization_in_scope_and_unexpected_failure_rollback(self):
        before = self.state()

        def materialize(line):
            self.assertTrue(connection.in_atomic_block)
            with self.assertNumQueries(0):
                response = DraftOrderLineReadSerializer(line).data
            self.assertEqual(response["catalogue_item_id"], str(self.item.pk))
            raise RuntimeError("Synthetic attachment failure")

        with self.assertRaisesMessage(RuntimeError, "Synthetic attachment failure"):
            self.service(materialize=materialize)
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_concurrent_attachments_commit_one_winner(self):
        second = CatalogItem.objects.create(
            organization=self.workspace, sku="SECOND", description="Second description"
        )
        barrier = Barrier(2, timeout=10)

        def attempt(item_id):
            close_old_connections()
            try:
                barrier.wait()
                try:
                    self.service(
                        item_id, materialize=lambda line: line.catalogue_item_id
                    )
                except DraftLineCatalogueAttachmentConflict:
                    return ("conflict", item_id)
                return ("attached", item_id)
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, item.pk) for item in (self.item, second)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(
            [outcome for outcome, _ in outcomes], ["attached", "conflict"]
        )
        winner_id = next(
            item_id for outcome, item_id in outcomes if outcome == "attached"
        )
        winner = CatalogItem.objects.get(pk=winner_id)
        after = self.state()
        self.assertEqual(after["catalogue_item_id"], winner_id)
        self.assertEqual(after["catalogue_sku_snapshot"], winner.sku)
        self.assertEqual(after["catalogue_description_snapshot"], winner.description)

    def test_waiting_attachment_observes_committed_deactivation(self):
        self.assert_waiting_change_denies_attachment(deactivate=True)

    def test_waiting_attachment_observes_committed_demotion(self):
        self.assert_waiting_change_denies_attachment(deactivate=False)

    def assert_waiting_change_denies_attachment(self, *, deactivate):
        before = self.state()
        ready = Queue()

        def attempt():
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
                    ready.put(test_concurrency.DraftOrderConcurrencyTests._pid())
                return execute(statement, params, many, context)

            try:
                with connection.execute_wrapper(inspect):
                    try:
                        self.service()
                    except Http404:
                        return "missing"
                    except PermissionDenied:
                        return "denied"
                return "attached"
            finally:
                connections["default"].close()

        blocker = test_concurrency.DraftOrderConcurrencyTests._pid()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.workspace.pk)
                if deactivate:
                    CatalogItem.objects.filter(pk=self.item.pk).update(is_active=False)
                else:
                    Membership.objects.filter(pk=self.membership.pk).update(
                        role=MembershipRole.VIEWER
                    )
                future = pool.submit(attempt)
                waiter = ready.get(timeout=10)
                test_concurrency.DraftOrderConcurrencyTests._wait_for_block(
                    self, waiter, blocker
                )
            self.assertEqual(
                future.result(timeout=15), "missing" if deactivate else "denied"
            )
        self.assertEqual(self.state(), before)
        self.assert_clean()
