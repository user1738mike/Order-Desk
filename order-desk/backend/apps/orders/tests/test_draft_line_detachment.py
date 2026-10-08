"""Protected detachment preserves requests and validates identity after locking."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.serializers import DraftOrderLineReadSerializer
from apps.orders.services import (
    detach_catalogue_item_from_draft_order_line,
    update_draft_order_line,
)
from apps.orders.tests import test_concurrency
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.services import create_organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DraftLineDetachmentTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="draft-detach@example.test")
        self.workspace = create_organization(actor=self.user, name="Synthetic detach")
        self.membership = Membership.objects.get(
            user=self.user, organization=self.workspace
        )
        self.order = DraftOrder.objects.create(
            organization=self.workspace,
            initiating_user=self.user,
            original_intake_text="Original intake",
        )
        self.item = CatalogItem.objects.create(
            organization=self.workspace,
            sku="Current",
            description="Current description",
            is_active=False,
        )
        self.line = DraftOrderLine.objects.create(
            organization=self.workspace,
            order=self.order,
            position=1,
            requested_sku=" Original ",
            requested_description="",
            quantity=None,
            unit=" box ",
            catalogue_item=self.item,
            catalogue_sku_snapshot="Historical",
            catalogue_description_snapshot="Historical description",
        )
        self.url = (
            f"/api/v1/workspaces/{self.workspace.pk}/draft-orders/"
            f"{self.order.pk}/lines/{self.line.pk}/detach/"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]

    def detach(self, body=None):
        return self.client.post(
            self.url,
            {} if body is None else body,
            format="json",
            HTTP_X_CSRFTOKEN=self.token,
        )

    def service(self, **kwargs):
        return detach_catalogue_item_from_draft_order_line(
            actor=self.user,
            organization_id=self.workspace.pk,
            order_id=self.order.pk,
            line_id=self.line.pk,
            data={},
            **kwargs,
        )

    def state(self):
        return DraftOrderLine.objects.values().get(pk=self.line.pk)

    def assert_clean(self):
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                " NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def test_writer_roles_preserve_request_header_catalogue_and_line_identity(self):
        header = DraftOrder.objects.values().get(pk=self.order.pk)
        catalogue = CatalogItem.objects.values().get(pk=self.item.pk)
        for role in (MembershipRole.ADMIN, MembershipRole.REVIEWER):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            DraftOrderLine.objects.filter(pk=self.line.pk).update(
                catalogue_item=self.item,
                catalogue_sku_snapshot="Historical",
                catalogue_description_snapshot="Historical description",
            )
            before = self.state()
            later = before["updated_at"] + timedelta(seconds=10)
            with patch("django.utils.timezone.now", return_value=later):
                response = self.detach()
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(
                set(response.json()), set(DraftOrderLineReadSerializer.Meta.fields)
            )
            after = self.state()
            self.assertIsNone(after["catalogue_item_id"])
            self.assertEqual(after["catalogue_sku_snapshot"], "")
            self.assertEqual(after["catalogue_description_snapshot"], "")
            self.assertEqual(after["updated_at"], later)
            for field in before.keys() - {
                "catalogue_item_id",
                "catalogue_sku_snapshot",
                "catalogue_description_snapshot",
                "updated_at",
            }:
                self.assertEqual(after[field], before[field], field)
        self.assertEqual(DraftOrder.objects.values().get(pk=self.order.pk), header)
        self.assertEqual(CatalogItem.objects.values().get(pk=self.item.pk), catalogue)
        self.assertEqual(DraftOrderLine.objects.filter(order=self.order).count(), 1)
        self.assert_clean()

    def test_repeated_detachment_is_noop_without_save(self):
        self.assertEqual(self.detach().status_code, 200)
        before = self.state()
        with patch.object(
            DraftOrderLine, "save", side_effect=AssertionError("No-op saved")
        ):
            response = self.detach()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state(), before)

    def test_catalogue_only_identity_denied_until_requested_fields_repaired(self):
        DraftOrderLine.objects.filter(pk=self.line.pk).update(
            requested_sku=" \t", requested_description=""
        )
        before = self.state()
        response = self.detach()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("non_field_errors", response.json())
        self.assertEqual(self.state(), before)
        self.assert_clean()
        detail = self.url.removesuffix("detach/")
        repaired = self.client.patch(
            detail,
            {"requested_description": "Repaired"},
            format="json",
            HTTP_X_CSRFTOKEN=self.token,
        )
        self.assertEqual(repaired.status_code, 200, repaired.content)
        self.assertEqual(self.detach().status_code, 200)
        self.assertEqual(self.state()["requested_description"], "Repaired")

    def test_unknown_fields_and_nonobjects_do_not_write(self):
        before = self.state()
        for body in (
            {"catalogue_item_id": None},
            {"requested_sku": "New"},
            {"position": 1},
            {"unknown": True},
            [],
            "text",
        ):
            response = self.detach(body)
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(self.state(), before)
        with self.assertRaises(ValidationError):
            detach_catalogue_item_from_draft_order_line(
                actor=self.user,
                organization_id=self.workspace.pk,
                order_id=self.order.pk,
                line_id=self.line.pk,
                data={"quantity": None},
            )
        self.assertEqual(self.state(), before)

    def test_current_access_and_role_denied_before_parsing(self):
        before = self.state()

        def malformed():
            return self.client.post(
                self.url,
                "{",
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self.token,
            )

        self.membership.role = MembershipRole.VIEWER
        self.membership.save(update_fields=["role"])
        self.assertEqual(malformed().status_code, 403)
        self.membership.role = MembershipRole.ADMIN
        self.membership.is_active = False
        self.membership.save(update_fields=["role", "is_active"])
        self.assertEqual(malformed().status_code, 403)
        self.membership.delete()
        self.assertEqual(malformed().status_code, 403)
        stranger = User.objects.create_user(email="never-detach@example.test")
        self.client.force_login(stranger)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.assertEqual(malformed().status_code, 403)
        self.assertEqual(self.state(), before)

    def test_parent_and_line_lookup_precede_parsing_and_stay_scoped(self):
        other = create_organization(actor=self.user, name="Foreign detach")
        before = self.state()
        for workspace in (self.workspace, other):
            order = DraftOrder.objects.create(
                organization=workspace, initiating_user=self.user
            )
            line = DraftOrderLine.objects.create(
                organization=workspace, order=order, position=1, requested_sku="Other"
            )
            paths = [
                self.url.replace(str(self.line.pk), str(line.pk)),
                self.url.replace(str(self.order.pk), str(order.pk)),
            ]
            if workspace == other:
                paths.append(
                    self.url.replace(str(self.line.pk), str(line.pk)).replace(
                        str(self.order.pk), str(order.pk)
                    )
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

    def test_csrf_media_queries_methods_and_anonymous(self):
        before = self.state()
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 403)
        self.assertEqual(
            self.client.post(
                self.url, {}, format="json", HTTP_X_CSRFTOKEN="invalid"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                self.url, {}, format="multipart", HTTP_X_CSRFTOKEN=self.token
            ).status_code,
            415,
        )
        self.assertEqual(
            self.client.post(
                self.url + "?unknown=1", {}, format="json", HTTP_X_CSRFTOKEN=self.token
            ).status_code,
            400,
        )
        for method in ("get", "head", "put", "patch", "delete"):
            self.assertEqual(
                getattr(self.client, method)(
                    self.url, {}, format="json", HTTP_X_CSRFTOKEN=self.token
                ).status_code,
                405,
            )
        self.client.logout()
        self.assertEqual(self.detach().status_code, 403)
        self.assertEqual(self.state(), before)

    def test_model_and_post_save_validation_errors_roll_back(self):
        before = self.state()
        with patch.object(
            DraftOrderLine,
            "full_clean",
            side_effect=ValidationError(
                {"requested_sku": ["Synthetic invalid identity"]}
            ),
        ):
            response = self.detach()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"requested_sku": ["Synthetic invalid identity"]}
        )
        with patch(
            "apps.orders.views.DraftOrderLineReadSerializer",
            side_effect=ValidationError("Synthetic materialization failure"),
        ):
            response = self.detach()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"non_field_errors": ["Synthetic materialization failure"]}
        )
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_materialization_inside_scope_and_unexpected_failure_rollback(self):
        before = self.state()

        def materialize(line):
            self.assertTrue(connection.in_atomic_block)
            with self.assertNumQueries(0):
                response = DraftOrderLineReadSerializer(line).data
            self.assertIsNone(response["catalogue_item_id"])
            raise RuntimeError("Synthetic detachment failure")

        with self.assertRaisesMessage(RuntimeError, "Synthetic detachment failure"):
            self.service(materialize=materialize)
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_concurrent_identity_clear_and_detach_commit_only_one_change(self):
        barrier = Barrier(2, timeout=10)

        def attempt(detach):
            close_old_connections()
            try:
                barrier.wait()
                try:
                    if detach:
                        self.service()
                    else:
                        update_draft_order_line(
                            actor=self.user,
                            organization_id=self.workspace.pk,
                            order_id=self.order.pk,
                            line_id=self.line.pk,
                            data={"requested_sku": ""},
                        )
                except ValidationError:
                    return "invalid"
                return "changed"
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, value) for value in (True, False)]
            self.assertCountEqual(
                [future.result(timeout=20) for future in futures],
                ["changed", "invalid"],
            )
        self.line.refresh_from_db()
        self.line.full_clean()
        self.assertTrue(
            self.line.catalogue_item_id is not None or self.line.requested_sku.strip()
        )

    def test_waiting_detachment_observes_committed_demotion(self):
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
                    except PermissionDenied:
                        return "denied"
                return "detached"
            finally:
                connections["default"].close()

        blocker = test_concurrency.DraftOrderConcurrencyTests._pid()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.workspace.pk)
                Membership.objects.filter(pk=self.membership.pk).update(
                    role=MembershipRole.VIEWER
                )
                future = pool.submit(attempt)
                waiter = ready.get(timeout=10)
                test_concurrency.DraftOrderConcurrencyTests._wait_for_block(
                    self, waiter, blocker
                )
            self.assertEqual(future.result(timeout=15), "denied")
        self.assertEqual(self.state(), before)
        self.assert_clean()
