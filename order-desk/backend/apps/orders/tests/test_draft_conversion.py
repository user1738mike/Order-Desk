"""Atomic conversion, retries, immutable snapshots and protected API failures."""

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders import services
from apps.orders.models import (
    DraftOrder,
    DraftOrderLine,
    OrderStatus,
    PurchaseOrder,
    PurchaseOrderLine,
)
from apps.organizations.context import resolve_workspace_context
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


class DraftConversionTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="conversion@example.test")
        self.organization = create_organization(
            actor=self.user, name="Synthetic conversion"
        )
        self.membership = Membership.objects.get(
            user=self.user, organization=self.organization
        )
        self.draft = DraftOrder.objects.create(
            organization=self.organization,
            initiating_user=self.user,
            customer_name=" Buyer ",
            customer_reference="Reference",
            original_intake_text="Original request",
        )
        self.item = CatalogItem.objects.create(
            organization=self.organization,
            sku="001-a/B",
            description="Live description",
        )
        self.line = DraftOrderLine.objects.create(
            organization=self.organization,
            order=self.draft,
            position=7,
            requested_sku="Original",
            catalogue_item=self.item,
            catalogue_sku_snapshot="001-a/B",
            catalogue_description_snapshot="Historical description",
            quantity=Decimal("2.125"),
            unit="",
        )
        self.detail = (
            f"/api/v1/workspaces/{self.organization.pk}/draft-orders/{self.draft.pk}/"
        )
        self.url = self.detail + "convert/"
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]

    def post(self, data=None, path=None):
        return self.client.post(
            path or self.url,
            {} if data is None else data,
            format="json",
            HTTP_X_CSRFTOKEN=self.token,
        )

    def convert(self, **kwargs):
        return services.convert_draft_to_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            order_id=self.draft.pk,
            data={},
            **kwargs,
        )

    def assert_unconverted(self):
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, "draft")
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertEqual(PurchaseOrderLine.objects.count(), 0)
        self.assertFalse(connection.in_atomic_block)

    def test_first_conversion_and_lost_response_retry_return_same_order(self):
        before = list(DraftOrderLine.objects.values())
        response = self.post()
        self.assertEqual(response.status_code, 201, response.content)
        result = response.json()
        self.assertEqual(
            set(result),
            {
                "id",
                "organization_id",
                "source_draft_id",
                "purchase_order_number",
                "order_url",
            },
        )
        order = PurchaseOrder.objects.get(pk=result["id"])
        self.assertEqual(order.source_draft_id, self.draft.pk)
        self.assertEqual(order.created_by_id, self.user.pk)
        self.assertEqual(order.customer_name, " Buyer ")
        self.assertEqual(order.status, OrderStatus.DRAFT)
        self.assertEqual(order.purchase_order_number, "DRAFT-" + self.draft.pk.hex)
        line = PurchaseOrderLine.objects.get(order=order)
        self.assertEqual(
            (line.line_number, line.sku, line.description, line.quantity, line.unit),
            (7, "001-a/B", "Historical description", Decimal("2.1250"), ""),
        )
        self.assertNotEqual(line.pk, self.line.pk)
        self.assertEqual(list(DraftOrderLine.objects.values()), before)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, "converted")
        self.assertEqual(
            (self.draft.customer_reference, self.draft.original_intake_text),
            ("Reference", "Original request"),
        )
        old = list(PurchaseOrder.objects.values())
        CatalogItem.objects.filter(pk=self.item.pk).update(
            is_active=False, description="New"
        )
        retry = self.post()
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(retry.json(), result)
        self.assertEqual(list(PurchaseOrder.objects.values()), old)
        self.assertEqual(PurchaseOrderLine.objects.count(), 1)
        body = self.client.get(self.detail + "readiness/").json()
        self.assertFalse(body["ready_to_convert"])
        self.assertEqual(body["blocking_reasons"][0]["code"], "draft_already_converted")

    def test_every_readiness_blocker_prevents_all_writes(self):
        variants = (
            (
                DraftOrder,
                {"customer_name": ""},
                "customer_name_missing",
                "customer_name",
            ),
            (DraftOrderLine, {"quantity": None}, "quantity_missing", "lines.quantity"),
            (
                DraftOrderLine,
                {
                    "catalogue_item": None,
                    "catalogue_sku_snapshot": "",
                    "catalogue_description_snapshot": "",
                },
                "catalogue_unmatched",
                "lines.catalogue_item_id",
            ),
            (
                CatalogItem,
                {"is_active": False},
                "catalogue_inactive",
                "lines.catalogue_item_id",
            ),
            (
                DraftOrderLine,
                {"catalogue_sku_snapshot": "x" * 129},
                "catalogue_sku_too_long",
                "lines.catalogue_sku_snapshot",
            ),
        )
        for model, values, code, path in variants:
            with self.subTest(code=code):
                row = (
                    self.draft
                    if model is DraftOrder
                    else self.line
                    if model is DraftOrderLine
                    else self.item
                )
                original = {key: getattr(row, key) for key in values}
                model.objects.filter(pk=row.pk).update(**values)
                response = self.post()
                self.assertEqual(response.status_code, 409, response.content)
                self.assertEqual(
                    response.json(),
                    {
                        "detail": "draft_not_ready",
                        "blocking_reasons": [{"code": code, "count": 1, "path": path}],
                    },
                )
                self.assert_unconverted()
                model.objects.filter(pk=row.pk).update(**original)
        self.line.delete()
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["blocking_reasons"],
            [{"code": "lines_missing", "count": 1, "path": "lines"}],
        )
        self.assert_unconverted()

    def test_strict_input_query_media_and_methods(self):
        for body in (
            {"customer_name": "Override"},
            {"organization": str(uuid4())},
            {"status": "approved"},
            {"lines": []},
            [],
            "bad",
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 400)
                self.assert_unconverted()
        self.assertEqual(self.post(path=self.url + "?page=1").status_code, 400)
        self.assertEqual(
            self.client.post(
                self.url, {}, format="multipart", HTTP_X_CSRFTOKEN=self.token
            ).status_code,
            415,
        )
        for method in ("get", "head", "patch", "put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url, HTTP_X_CSRFTOKEN=self.token
                )
                self.assertEqual(response.status_code, 405)
        self.assert_unconverted()

    def test_csrf_anonymous_roles_and_active_state(self):
        for token in (None, "bad"):
            headers = {} if token is None else {"HTTP_X_CSRFTOKEN": token}
            self.assertEqual(
                self.client.post(self.url, {}, format="json", **headers).status_code,
                403,
            )
        self.assertEqual(APIClient().post(self.url, {}, format="json").status_code, 403)
        for role in (MembershipRole.REVIEWER, MembershipRole.VIEWER):
            Membership.objects.filter(pk=self.membership.pk).update(role=role)
            self.assertEqual(self.post().status_code, 403)
        Membership.objects.filter(pk=self.membership.pk).update(
            role=MembershipRole.ADMIN
        )
        for row in (self.membership, self.organization, self.user):
            with self.subTest(model=type(row).__name__):
                type(row).objects.filter(pk=row.pk).update(is_active=False)
                self.assertEqual(self.post().status_code, 403)
                type(row).objects.filter(pk=row.pk).update(is_active=True)
        self.assert_unconverted()

    def test_removed_never_member_superuser_and_revocation(self):
        def revoke(**kwargs):
            context = resolve_workspace_context(**kwargs)
            Membership.objects.filter(pk=self.membership.pk).update(is_active=False)
            return context

        with patch(
            "apps.organizations.permissions.resolve_workspace_context",
            side_effect=revoke,
        ):
            self.assertEqual(self.post().status_code, 403)
        Membership.objects.filter(pk=self.membership.pk).delete()
        self.assertEqual(self.post().status_code, 403)
        outsider = User.objects.create_user(
            email="conversion-outsider@example.test", is_staff=True, is_superuser=True
        )
        self.client.force_login(outsider)
        self.assertEqual(self.post().status_code, 403)
        self.assert_unconverted()

    def test_foreign_missing_and_malformed_precede_invalid_input(self):
        other = create_organization(actor=self.user, name="Other conversion")
        draft = DraftOrder.objects.create(organization=other, initiating_user=self.user)
        for identity in (draft.pk, uuid4(), "invalid-uuid"):
            with self.subTest(identity=identity):
                self.assertEqual(
                    self.post(
                        {"unknown": 1},
                        path=self.url.replace(str(self.draft.pk), str(identity)),
                    ).status_code,
                    404,
                )
        self.assert_unconverted()

    def test_failure_during_each_write_and_materialization_rolls_back(self):
        for model, stage in (
            (PurchaseOrder, "order"),
            (PurchaseOrderLine, "line"),
            (PurchaseOrder, "link"),
            (DraftOrder, "status"),
        ):
            original = model.save

            def failing(instance, *args, stage=stage, original=original, **kwargs):
                if stage == "link" and instance.source_draft_id is None:
                    return original(instance, *args, **kwargs)
                raise ValidationError({"__all__": "Synthetic write failure"})

            with self.subTest(stage=stage), patch.object(model, "save", failing):
                response = self.post()
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(
                    response.json(), {"non_field_errors": ["Synthetic write failure"]}
                )
                self.assert_unconverted()
        for error in (
            ValidationError("Synthetic materialization"),
            RuntimeError("Synthetic"),
        ):

            def fail(order, error=error):
                self.assertTrue(connection.in_atomic_block)
                raise error

            with (
                self.subTest(error=type(error).__name__),
                self.assertRaises(type(error)),
            ):
                self.convert(materialize=fail)
            self.assert_unconverted()
        with (
            patch.object(
                connection, "_commit", side_effect=IntegrityError("Synthetic commit")
            ),
            self.assertRaises(IntegrityError),
        ):
            self.convert()
        self.assert_unconverted()

    def test_number_collision_is_not_adopted(self):
        existing = services.create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Other",
            purchase_order_number="DRAFT-" + self.draft.pk.hex,
        )
        response = self.post()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["detail"], "purchase_order_number_conflict")
        existing.refresh_from_db()
        self.assertIsNone(existing.source_draft_id)
        self.assertEqual(PurchaseOrder.objects.count(), 1)
        self.assertEqual(PurchaseOrderLine.objects.count(), 0)

    def test_late_line_failure_rolls_back_prior_inserted_lines(self):
        DraftOrderLine.objects.create(
            organization=self.organization,
            order=self.draft,
            position=8,
            quantity=1,
            catalogue_item=self.item,
            catalogue_sku_snapshot=self.item.sku,
        )
        original = PurchaseOrderLine.save
        calls = 0

        def fail_second(instance, *args, **kwargs):
            nonlocal calls
            calls += 1
            original(instance, *args, **kwargs)
            if calls == 2:
                raise ValidationError("Synthetic after second insert")

        with (
            patch.object(PurchaseOrderLine, "save", fail_second),
            self.assertRaises(ValidationError),
        ):
            self.convert()
        self.assertEqual(calls, 2)
        self.assert_unconverted()
        self.assertEqual(DraftOrderLine.objects.count(), 2)

    def test_exact_snapshot_strings_quantity_limits_and_unrelated_integrity_failure(
        self,
    ):
        DraftOrderLine.objects.filter(pk=self.line.pk).update(
            catalogue_sku_snapshot=" 00001/a-B ", quantity="999999999.999", unit=" x "
        )
        with (
            patch.object(
                PurchaseOrder, "save", side_effect=IntegrityError("Unrelated")
            ),
            self.assertRaises(IntegrityError),
        ):
            self.convert()
        self.assert_unconverted()
        order, _ = self.convert()
        copied = PurchaseOrderLine.objects.get(order=order)
        self.assertEqual(
            (copied.sku, copied.quantity, copied.unit),
            (" 00001/a-B ", Decimal("999999999.9990"), " x "),
        )

    def test_deferred_completion_rejects_missing_link_and_mismatched_copy(self):
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            DraftOrder.objects.filter(pk=self.draft.pk).update(status="converted")
        self.assertEqual(
            caught.exception.__cause__.diag.constraint_name, "draft_conversion_complete"
        )
        self.assert_unconverted()
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            order = PurchaseOrder.objects.create(
                organization=self.organization,
                created_by=self.user,
                customer_name=self.draft.customer_name,
                purchase_order_number="Partial",
            )
            PurchaseOrderLine.objects.create(
                organization=self.organization,
                order=order,
                line_number=self.line.position,
                sku=self.line.catalogue_sku_snapshot,
                quantity=9,
                description=self.line.catalogue_description_snapshot,
            )
            PurchaseOrder.objects.filter(pk=order.pk).update(source_draft=self.draft)
            DraftOrder.objects.filter(pk=self.draft.pk).update(status="converted")
        self.assertEqual(
            caught.exception.__cause__.diag.constraint_name, "draft_conversion_complete"
        )
        self.assert_unconverted()

    def test_source_and_copied_line_mutation_routes_are_frozen(self):
        body = self.post().json()
        before = list(DraftOrderLine.objects.values())
        line_url = self.detail + f"lines/{self.line.pk}/"
        for method, path, values in (
            ("patch", self.detail, {"customer_name": "Changed"}),
            ("post", self.detail + "lines/", {"position": 8, "requested_sku": "New"}),
            ("patch", line_url, {"quantity": "3"}),
            ("post", line_url + "attach/", {"catalogue_item_id": str(self.item.pk)}),
            ("post", line_url + "detach/", {}),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(
                    path, values, format="json", HTTP_X_CSRFTOKEN=self.token
                )
                self.assertEqual(response.status_code, 409, response.content)
                self.assertEqual(response.json()["detail"], "draft_already_converted")
        self.assertEqual(list(DraftOrderLine.objects.values()), before)
        response = self.client.post(
            body["order_url"] + "lines/",
            {"line_number": 8, "sku": "New", "quantity": "1"},
            format="json",
            HTTP_X_CSRFTOKEN=self.token,
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(PurchaseOrderLine.objects.count(), 1)
        for action in ("submit", "approve"):
            response = self.client.post(
                body["order_url"] + action + "/",
                {},
                format="json",
                HTTP_X_CSRFTOKEN=self.token,
            )
            self.assertEqual(response.status_code, 200, response.content)
        replay = self.post()
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), body)
        Membership.objects.filter(pk=self.membership.pk).update(
            role=MembershipRole.REVIEWER
        )
        self.assertEqual(self.post().status_code, 403)

    def test_database_source_completion_uniqueness_tenant_and_immutability(self):
        order, _ = self.convert()
        for model, pk, changes in (
            (DraftOrder, self.draft.pk, {"customer_name": "Changed"}),
            (DraftOrderLine, self.line.pk, {"quantity": 3}),
            (PurchaseOrder, order.pk, {"source_draft": None}),
            (PurchaseOrder, order.pk, {"customer_name": "Changed"}),
            (
                PurchaseOrderLine,
                PurchaseOrderLine.objects.get(order=order).pk,
                {"sku": "Changed"},
            ),
        ):
            # Constraints protect application rows even in maintenance-role tests.
            with (
                self.subTest(model=model.__name__),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                model.objects.filter(pk=pk).update(**changes)
        other = create_organization(actor=self.user, name="Foreign reference")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PurchaseOrder.objects.create(
                organization=other,
                created_by=self.user,
                customer_name="Buyer",
                purchase_order_number="Foreign",
                source_draft=self.draft,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PurchaseOrder.objects.create(
                organization=self.organization,
                created_by=self.user,
                customer_name="Buyer",
                purchase_order_number="Duplicate",
                source_draft=self.draft,
            )
