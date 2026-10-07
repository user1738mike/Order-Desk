"""Protected partial edits merge locked state and preserve tenant boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.serializers import DraftOrderLineReadSerializer
from apps.orders.services import update_draft_order_line
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DraftLineEditingTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="draft-edit@example.test")
        self.workspace = create_organization(actor=self.user, name="Synthetic edits")
        self.membership = Membership.objects.get(
            user=self.user, organization=self.workspace
        )
        self.order = DraftOrder.objects.create(
            organization=self.workspace,
            initiating_user=self.user,
            original_intake_text="Original synthetic intake",
        )
        self.line = DraftOrderLine.objects.create(
            organization=self.workspace,
            order=self.order,
            position=1,
            requested_sku="Original",
            requested_description="Description",
            quantity=Decimal("1.250"),
            unit="box",
        )
        self.url = self.path(self.order.pk, self.line.pk)
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]

    def path(self, order_id, line_id):
        return (
            f"/api/v1/workspaces/{self.workspace.pk}/draft-orders/"
            f"{order_id}/lines/{line_id}/"
        )

    def edit(self, values, **kwargs):
        return self.client.patch(
            self.url, values, format="json", HTTP_X_CSRFTOKEN=self.token, **kwargs
        )

    def service(self, values, **kwargs):
        return update_draft_order_line(
            actor=self.user,
            organization_id=self.workspace.pk,
            order_id=self.order.pk,
            line_id=self.line.pk,
            data=values,
            **kwargs,
        )

    def state(self):
        return DraftOrderLine.objects.filter(pk=self.line.pk).values().get()

    def assert_clean(self):
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                " NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def test_roles_read_and_writers_edit_preserving_header_and_omitted_fields(self):
        header = DraftOrder.objects.values().get(pk=self.order.pk)
        original = self.state()
        for role in (
            MembershipRole.ADMIN,
            MembershipRole.REVIEWER,
            MembershipRole.VIEWER,
        ):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            read = self.client.get(self.url)
            self.assertEqual(read.status_code, 200, read.content)
            self.assertEqual(
                set(read.json()), set(DraftOrderLineReadSerializer.Meta.fields)
            )
            response = self.edit({"unit": f" {role} "})
            self.assertEqual(
                response.status_code,
                403 if role == MembershipRole.VIEWER else 200,
                response.content,
            )
        after = self.state()
        self.assertEqual(after["unit"], " reviewer ")
        for field in original.keys() - {"unit", "updated_at"}:
            self.assertEqual(after[field], original[field], field)
        self.assertEqual(DraftOrder.objects.values().get(pk=self.order.pk), header)
        self.assertEqual(DraftOrderLine.objects.filter(order=self.order).count(), 1)
        self.assert_clean()

    def test_noop_patches_preserve_timestamp_and_do_not_save(self):
        before = self.state()
        for values in (
            {},
            {"quantity": "1.25"},
            {"requested_sku": "Original", "unit": "box"},
        ):
            with patch.object(
                DraftOrderLine, "save", side_effect=AssertionError("No-op saved")
            ):
                response = self.edit(values)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(self.state(), before)

    def test_changed_patch_advances_only_line_timestamp(self):
        before = self.state()
        later = before["updated_at"] + timedelta(seconds=10)
        with patch("django.utils.timezone.now", return_value=later):
            response = self.edit({"requested_description": " New description "})
        self.assertEqual(response.status_code, 200, response.content)
        after = self.state()
        self.assertEqual(after["updated_at"], later)
        self.assertEqual(after["created_at"], before["created_at"])
        self.assertEqual(after["requested_description"], " New description ")

    def test_clearing_quantity_and_one_identifier_preserves_merged_identity(self):
        response = self.edit({"requested_sku": "", "quantity": None})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["quantity"])
        self.assertEqual(response.json()["requested_description"], "Description")
        before = self.state()
        response = self.edit({"requested_description": " \t\n"})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("non_field_errors", response.json())
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_invalid_and_immutable_fields_never_write(self):
        before = self.state()
        invalid = [
            *(
                {"quantity": value}
                for value in ("0", "-1", "NaN", "Infinity", "1000000000", "1.0001")
            ),
            {"unit": "x" * 33},
            {"requested_sku": None},
            *(
                {field: value}
                for field, value in {
                    "position": 1,
                    "id": str(self.line.pk),
                    "organization_id": str(self.workspace.pk),
                    "order_id": str(self.order.pk),
                    "catalogue_item_id": None,
                    "catalogue_sku_snapshot": "X",
                    "catalogue_description_snapshot": "X",
                    "created_at": "2026-01-01",
                    "updated_at": "2026-01-01",
                    "unexpected": "X",
                }.items()
            ),
        ]
        for values in invalid:
            with self.subTest(values=values):
                response = self.edit(values)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(self.state(), before)
        with self.assertRaises(ValidationError):
            self.service({"position": 2})
        with self.assertRaises(ValidationError):
            self.service({"quantity": Decimal("0")})
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_linked_line_keeps_original_catalogue_snapshots(self):
        item = CatalogItem.objects.create(
            organization=self.workspace,
            sku="Current-SKU",
            description="Current description",
            is_active=False,
        )
        DraftOrderLine.objects.filter(pk=self.line.pk).update(
            catalogue_item=item,
            catalogue_sku_snapshot="Historical-SKU",
            catalogue_description_snapshot="Historical description",
        )
        response = self.edit(
            {"requested_sku": "", "requested_description": "", "quantity": None}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["catalogue_item_id"], str(item.pk))
        self.assertEqual(response.json()["catalogue_sku_snapshot"], "Historical-SKU")
        self.assertEqual(
            response.json()["catalogue_description_snapshot"], "Historical description"
        )

    def test_parent_line_and_workspace_must_all_match_before_parsing(self):
        other = create_organization(actor=self.user, name="Foreign synthetic edits")
        for workspace in (self.workspace, other):
            order = DraftOrder.objects.create(
                organization=workspace, initiating_user=self.user
            )
            line = DraftOrderLine.objects.create(
                organization=workspace, order=order, position=1, requested_sku="Other"
            )
            paths = (
                self.path(self.order.pk, line.pk),
                self.path(order.pk, self.line.pk),
            )
            if workspace == other:
                paths += (self.path(order.pk, line.pk),)
            for path in paths:
                self.assertEqual(self.client.get(path).status_code, 404)
                response = self.client.patch(
                    path,
                    "{",
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=self.token,
                )
                self.assertEqual(response.status_code, 404, response.content)
        for path in (
            self.path(uuid4(), self.line.pk),
            self.path(self.order.pk, uuid4()),
        ):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assert_clean()

    def test_viewer_and_revoked_access_denied_before_parsing(self):
        before = self.state()
        self.membership.role = MembershipRole.VIEWER
        self.membership.save(update_fields=["role"])
        response = self.client.patch(
            self.url, "{", content_type="application/json", HTTP_X_CSRFTOKEN=self.token
        )
        self.assertEqual(response.status_code, 403, response.content)
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.edit({"unit": "changed"}).status_code, 403)
        self.membership.delete()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.edit({}).status_code, 403)
        stranger = User.objects.create_user(email="never-draft-member@example.test")
        self.client.force_login(stranger)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.edit({}).status_code, 403)
        self.assertEqual(self.state(), before)

    def test_inactive_account_and_workspace_denied(self):
        self.workspace.is_active = False
        self.workspace.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.edit({}).status_code, 403)
        self.workspace.is_active = True
        self.workspace.save(update_fields=["is_active"])
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.edit({}).status_code, 403)

    def test_csrf_media_queries_and_methods(self):
        before = self.state()
        self.assertEqual(
            self.client.patch(self.url, {}, format="json").status_code, 403
        )
        self.assertEqual(
            self.client.patch(
                self.url, {}, format="json", HTTP_X_CSRFTOKEN="invalid"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                self.url, {"unit": "x"}, format="multipart", HTTP_X_CSRFTOKEN=self.token
            ).status_code,
            415,
        )
        self.assertEqual(self.client.get(self.url + "?unknown=1").status_code, 400)
        self.assertEqual(
            self.client.patch(
                self.url + "?unknown=1", {}, format="json", HTTP_X_CSRFTOKEN=self.token
            ).status_code,
            400,
        )
        for method in ("put", "post", "delete"):
            self.assertEqual(
                getattr(self.client, method)(
                    self.url, {}, format="json", HTTP_X_CSRFTOKEN=self.token
                ).status_code,
                405,
            )
        head = self.client.head(self.url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertIn("no-store", head["Cache-Control"])
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.edit({}).status_code, 403)
        self.assertEqual(self.state(), before)

    def test_model_validation_translated_and_post_save_error_rolls_back(self):
        before = self.state()
        with patch.object(
            DraftOrderLine,
            "full_clean",
            side_effect=ValidationError({"unit": ["Synthetic invalid unit"]}),
        ):
            response = self.edit({"unit": "changed"})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json(), {"unit": ["Synthetic invalid unit"]})
        with patch(
            "apps.orders.views.DraftOrderLineReadSerializer",
            side_effect=ValidationError("Synthetic materialization failure"),
        ):
            response = self.edit({"unit": "changed"})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            response.json(), {"non_field_errors": ["Synthetic materialization failure"]}
        )
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_response_materializes_inside_scope_and_unexpected_failure_rolls_back(self):
        before = self.state()

        def materialize(line):
            self.assertTrue(connection.in_atomic_block)
            with self.assertNumQueries(0):
                data = DraftOrderLineReadSerializer(line).data
            raise RuntimeError(data["unit"])

        with self.assertRaisesMessage(RuntimeError, "changed"):
            self.service({"unit": "changed"}, materialize=materialize)
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_concurrent_disjoint_patches_preserve_both_changes(self):
        barrier = Barrier(2, timeout=10)

        def attempt(values):
            close_old_connections()
            try:
                barrier.wait()
                self.service(values, materialize=lambda line: line.pk)
                self.assert_clean()
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(attempt, values)
                for values in ({"requested_description": "Edited"}, {"unit": "each"})
            ]
            for future in futures:
                future.result(timeout=20)
        after = self.state()
        self.assertEqual(after["requested_description"], "Edited")
        self.assertEqual(after["unit"], "each")
        self.assertEqual(after["quantity"], Decimal("1.250"))
