"""Native protected draft-line services and session/CSRF HTTP contracts."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.serializers import DraftOrderLineReadSerializer
from apps.orders.services import DraftLinePositionConflict, create_draft_order_line
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DraftLineCreationTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="draft-line@example.test")
        self.workspace = create_organization(actor=self.user, name="Synthetic lines")
        self.membership = Membership.objects.get(
            user=self.user, organization=self.workspace
        )
        self.other = create_organization(
            actor=self.user, name="Synthetic foreign lines"
        )
        self.order = DraftOrder.objects.create(
            organization=self.workspace,
            initiating_user=self.user,
            original_intake_text="Keep intake",
        )
        self.foreign = DraftOrder.objects.create(
            organization=self.other, initiating_user=self.user
        )
        self.url = (
            f"/api/v1/workspaces/{self.workspace.pk}/draft-orders/"
            f"{self.order.pk}/lines/"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.body = {"position": 1, "requested_description": "Original description"}

    def post(self, body=None, **kwargs):
        return self.client.post(
            self.url,
            self.body if body is None else body,
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

    def create(self, data, **kwargs):
        return create_draft_order_line(
            actor=self.user,
            organization_id=self.workspace.pk,
            order_id=self.order.pk,
            data=data,
            **kwargs,
        )

    def test_admin_and_reviewer_create_unresolved_lines_and_preserve_header(self):
        original_updated = self.order.updated_at
        for position, role in enumerate(
            (MembershipRole.ADMIN, MembershipRole.REVIEWER), 1
        ):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            response = self.post({**self.body, "position": position})
            self.assertEqual(response.status_code, 201, response.content)
            body = response.json()
            self.assertEqual(set(body), set(DraftOrderLineReadSerializer.Meta.fields))
            self.assertEqual(body["organization_id"], str(self.workspace.pk))
            self.assertEqual(body["order_id"], str(self.order.pk))
            self.assertIsNone(body["quantity"])
            self.assertIsNone(body["catalogue_item_id"])
            self.assertEqual(body["catalogue_sku_snapshot"], "")
            self.assertEqual(body["catalogue_description_snapshot"], "")
            self.assert_clean()
        self.order.refresh_from_db()
        self.assertEqual(self.order.updated_at, original_updated)
        self.assertEqual(self.order.original_intake_text, "Keep intake")
        detail_url = self.url.removesuffix("lines/")
        self.assertEqual(self.client.get(detail_url).json()["line_count"], 2)
        self.assertEqual(self.client.get(self.url).json()["count"], 2)

    def test_quantity_strings_null_and_original_text_are_preserved(self):
        for position, quantity in enumerate(
            (None, "0.001", "1.250", "999999999.999"), 1
        ):
            response = self.post(
                {
                    "position": position,
                    "requested_sku": "  Original-SKU  ",
                    "requested_description": " Keep description ",
                    "quantity": quantity,
                    "unit": " box ",
                }
            )
            self.assertEqual(response.status_code, 201)
            body = response.json()
            self.assertEqual(body["quantity"], quantity)
            self.assertEqual(body["requested_sku"], "  Original-SKU  ")
            self.assertEqual(body["requested_description"], " Keep description ")
            self.assertEqual(body["unit"], " box ")

    def test_invalid_and_system_fields_return_400_without_writes(self):
        invalid = (
            {},
            {"position": 1},
            {"position": 0, "requested_sku": "X"},
            {"position": 2147483648, "requested_sku": "X"},
            {"position": True, "requested_sku": "X"},
            {"position": 1, "requested_description": "\t \n"},
            *(
                {**self.body, "quantity": value}
                for value in ("0", "-1", "NaN", "Infinity", "1.0001", "1000000000")
            ),
            {**self.body, "unit": "x" * 33},
            {**self.body, "requested_sku": None},
            *(
                {**self.body, field: str(uuid4())}
                for field in (
                    "id",
                    "organization_id",
                    "order_id",
                    "catalogue_item_id",
                    "catalogue_sku_snapshot",
                    "created_at",
                    "unknown",
                )
            ),
        )
        for data in invalid:
            with self.subTest(data=data):
                response = self.post(data)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertFalse(DraftOrderLine.objects.exists())
                self.assert_clean()

    def test_duplicate_position_returns_409_without_changing_existing_line(self):
        self.assertEqual(self.post().status_code, 201)
        existing = DraftOrderLine.objects.get()
        response = self.post({**self.body, "requested_description": "Replacement"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"detail": "This draft already has a line at this position."},
        )
        existing.refresh_from_db()
        self.assertEqual(
            existing.requested_description, self.body["requested_description"]
        )
        self.assertEqual(DraftOrderLine.objects.count(), 1)
        self.assert_clean()

    def test_foreign_and_missing_parents_return_404_before_parsing(self):
        for order_id in (self.foreign.pk, uuid4()):
            path = self.url.replace(str(self.order.pk), str(order_id))
            response = self.client.post(
                path,
                "{broken",
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self.token,
            )
            self.assertEqual(response.status_code, 404)
            self.assert_clean()
        self.assertFalse(DraftOrderLine.objects.exists())

    def test_viewer_and_inactive_membership_are_denied_before_parsing(self):
        for active, role in (
            (True, MembershipRole.VIEWER),
            (False, MembershipRole.ADMIN),
        ):
            self.membership.role, self.membership.is_active = role, active
            self.membership.save(update_fields=["role", "is_active"])
            response = self.client.post(
                self.url,
                "{broken",
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self.token,
            )
            self.assertEqual(response.status_code, 403)
            self.assert_clean()
        self.assertFalse(DraftOrderLine.objects.exists())

    def test_removed_and_never_member_users_are_denied(self):
        self.membership.delete()
        self.assertEqual(self.post().status_code, 403)
        outsider = User.objects.create_user(
            email="line-outsider@example.test", is_staff=True, is_superuser=True
        )
        self.client.force_login(outsider)
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(DraftOrderLine.objects.exists())

    def test_csrf_anonymous_query_and_media_guards(self):
        self.assertEqual(
            APIClient().post(self.url, self.body, format="json").status_code, 403
        )
        self.assertEqual(
            self.client.post(self.url, self.body, format="json").status_code, 403
        )
        for query in ("?page=1", "?page=1&page=2", "?unknown=1"):
            response = self.client.post(
                self.url + query, self.body, format="json", HTTP_X_CSRFTOKEN=self.token
            )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.client.post(
                self.url, self.body, format="multipart", HTTP_X_CSRFTOKEN=self.token
            ).status_code,
            415,
        )
        self.assertFalse(DraftOrderLine.objects.exists())

    def test_put_patch_delete_remain_unavailable(self):
        for method in ("put", "patch", "delete"):
            response = getattr(self.client, method)(
                self.url, self.body, format="json", HTTP_X_CSRFTOKEN=self.token
            )
            self.assertEqual(response.status_code, 405)
        self.assertFalse(DraftOrderLine.objects.exists())

    def test_model_validation_is_400_and_materialization_failure_rolls_back(self):
        with patch.object(
            DraftOrderLine,
            "full_clean",
            side_effect=ValidationError({"__all__": ["Invalid line."]}),
        ):
            response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"non_field_errors": ["Invalid line."]})
        self.assertFalse(DraftOrderLine.objects.exists())
        with patch(
            "apps.orders.views.DraftOrderLineReadSerializer",
            side_effect=ValidationError("Invalid response."),
        ):
            self.assertEqual(self.post().status_code, 400)
        self.assertFalse(DraftOrderLine.objects.exists())
        self.assert_clean()

    def test_direct_service_rejects_system_fields_and_validates_native_model(self):
        for data in (
            {**self.body, "organization_id": self.other.pk},
            {**self.body, "quantity": Decimal("0")},
            {"position": 1},
        ):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                self.create(data)
            self.assertFalse(DraftOrderLine.objects.exists())
            self.assert_clean()

    def test_service_materializer_runs_inside_authorized_transaction(self):
        def materialize(line):
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('transaction_read_only')")
                self.assertEqual(cursor.fetchone(), ("off",))
            with self.assertNumQueries(0):
                return dict(DraftOrderLineReadSerializer(line).data)

        result = self.create(self.body, materialize=materialize)
        self.assertEqual(
            result["requested_description"], self.body["requested_description"]
        )
        self.assert_clean()

    def test_unexpected_integrity_error_rolls_back_and_is_not_position_conflict(self):
        with patch.object(
            DraftOrderLine,
            "save",
            side_effect=IntegrityError("Synthetic unrelated constraint"),
        ):
            with self.assertRaises(IntegrityError):
                self.create(self.body)
        self.assertFalse(DraftOrderLine.objects.exists())
        self.assert_clean()

    def test_native_position_constraint_is_mapped_after_rollback(self):
        self.create(self.body)
        # Force the final database guard rather than the cooperative precheck.
        with (
            patch.object(DraftOrderLine, "full_clean"),
            patch.object(DraftOrderLine.objects, "filter") as precheck,
        ):
            precheck.return_value.exists.return_value = False
            with self.assertRaises(DraftLinePositionConflict) as raised:
                self.create(self.body)
        self.assertIsInstance(raised.exception.__cause__, IntegrityError)
        self.assertEqual(DraftOrderLine.objects.count(), 1)
        self.assert_clean()

    def test_two_service_calls_for_same_position_commit_once(self):
        barrier = Barrier(2)

        def attempt():
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                try:
                    create_draft_order_line(
                        actor=actor,
                        organization_id=self.workspace.pk,
                        order_id=self.order.pk,
                        data=self.body,
                    )
                    return "created"
                except DraftLinePositionConflict:
                    return "conflict"
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(results, ["created", "conflict"])
        self.assertEqual(DraftOrderLine.objects.count(), 1)
