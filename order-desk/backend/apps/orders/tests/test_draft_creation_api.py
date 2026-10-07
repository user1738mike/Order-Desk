"""PostgreSQL API tests for protected draft-order creation."""

from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.models import DraftOrder
from apps.organizations.context import resolve_workspace_context
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.selection import SELECTED_WORKSPACE_KEY
from apps.organizations.services import create_organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DraftOrderCreationAPITests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="draft-create@example.test")
        self.organization = create_organization(
            actor=self.user, name="Draft Creation Workspace"
        )
        self.membership = Membership.objects.get(
            user=self.user, organization=self.organization
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.url = f"/api/v1/workspaces/{self.organization.pk}/draft-orders/"
        self.csrf_token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]

    def post(self, data):
        return self.client.post(
            self.url,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )

    def test_admin_creates_valid_manual_header_with_scalar_response(self):
        response = self.post(
            {
                "customer_name": "Northwind Supply",
                "customer_reference": "CUSTOMER-42",
                "original_intake_text": "Please send the blue parts.",
            }
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["organization_id"], str(self.organization.pk))
        self.assertEqual(body["initiating_user_id"], str(self.user.pk))
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["source_type"], "manual")
        self.assertEqual(body["customer_name"], "Northwind Supply")
        self.assertEqual(body["customer_reference"], "CUSTOMER-42")
        self.assertEqual(body["original_intake_text"], "Please send the blue parts.")
        self.assertTrue(body["lines_url"].endswith(f"{body['id']}/lines/"))

        order = DraftOrder.objects.get(pk=body["id"])
        self.assertEqual(order.organization_id, self.organization.pk)
        self.assertEqual(order.initiating_user_id, self.user.pk)
        self.assertEqual(order.draft_lines.count(), 0)

    def test_reviewer_can_create_and_viewer_cannot(self):
        self.membership.role = MembershipRole.REVIEWER
        self.membership.save(update_fields=["role"])
        response = self.post({})
        self.assertEqual(response.status_code, 201)

        self.membership.role = MembershipRole.VIEWER
        self.membership.save(update_fields=["role"])
        response = self.post({})
        self.assertEqual(response.status_code, 403)

    def test_other_workspace_and_inactive_membership_are_denied(self):
        other_owner = User.objects.create_user(email="other-draft-owner@example.test")
        other_workspace = create_organization(actor=other_owner, name="Other Workspace")
        response = self.client.post(
            f"/api/v1/workspaces/{other_workspace.pk}/draft-orders/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )
        self.assertEqual(response.status_code, 403)

        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        response = self.post({})
        self.assertEqual(response.status_code, 403)

    def test_unknown_fields_and_invalid_values_return_400_without_writes(self):
        for body in (
            {"unknown": True},
            {"customer_name": "   "},
            {"customer_reference": "x" * 129},
            {"original_intake_text": "x" * 10001},
        ):
            with self.subTest(body=body):
                response = self.post(body)
                self.assertEqual(response.status_code, 400)

        self.assertFalse(DraftOrder.objects.exists())

    def test_whitespace_customer_fields_return_field_errors_without_writes(self):
        for field in ("customer_name", "customer_reference"):
            for value in ("   ", "\t\r\n", "\u2003"):
                with self.subTest(field=field, value=value):
                    with patch.object(DraftOrder, "save") as save:
                        response = self.post({field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(
                        response.json(),
                        {field: ["Provide a nonblank value or an empty string."]},
                    )
                    save.assert_not_called()
                    self.assertFalse(DraftOrder.objects.exists())

    def test_empty_customer_fields_preserve_documented_empty_strings(self):
        response = self.post({"customer_name": "", "customer_reference": ""})
        self.assertEqual(response.status_code, 201)
        order = DraftOrder.objects.get(pk=response.json()["id"])
        self.assertEqual(order.customer_name, "")
        self.assertEqual(order.customer_reference, "")

    def test_model_validation_errors_are_stable_400_responses_without_writes(self):
        cases = (
            (
                ValidationError({"customer_name": ["Invalid customer."]}),
                {"customer_name": ["Invalid customer."]},
            ),
            (
                ValidationError({"__all__": ["Invalid draft constraint."]}),
                {"non_field_errors": ["Invalid draft constraint."]},
            ),
            (
                ValidationError(["Invalid draft."]),
                {"non_field_errors": ["Invalid draft."]},
            ),
        )
        for error, expected in cases:
            with self.subTest(expected=expected):
                with (
                    patch.object(DraftOrder, "full_clean", side_effect=error),
                    patch.object(DraftOrder, "save") as save,
                ):
                    response = self.post({})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), expected)
                save.assert_not_called()
                self.assertFalse(DraftOrder.objects.exists())
                self.assertFalse(connection.in_atomic_block)

    def test_validation_failure_after_insert_rolls_back_the_draft(self):
        with patch(
            "apps.orders.views.DraftOrderCreationSerializer",
            side_effect=ValidationError({"__all__": ["Invalid materialization."]}),
        ):
            response = self.post({})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"non_field_errors": ["Invalid materialization."]}
        )
        self.assertFalse(DraftOrder.objects.exists())
        self.assertFalse(connection.in_atomic_block)

    def assert_workspace_routes_denied(self):
        self.assertEqual(self.post({}).status_code, 403)
        for suffix in (
            "draft-orders/",
            f"draft-orders/{self.draft.pk}/",
            f"draft-orders/{self.draft.pk}/lines/",
            "orders/",
            "catalog/items/",
            "catalog/items/by-sku/?sku=NO-SUCH-SKU",
        ):
            with self.subTest(suffix=suffix):
                response = self.client.get(
                    f"/api/v1/workspaces/{self.organization.pk}/{suffix}"
                )
                self.assertEqual(response.status_code, 403)
        response = self.client.post(
            f"/api/v1/workspaces/{self.organization.pk}/catalog/items/",
            {"sku": "DENIED-SKU"},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(DraftOrder.objects.count(), 1)

    def prepare_existing_draft_and_selected_workspace(self):
        response = self.post({})
        self.assertEqual(response.status_code, 201)
        self.draft = DraftOrder.objects.get(pk=response.json()["id"])
        session = self.client.session
        session[SELECTED_WORKSPACE_KEY] = str(self.organization.pk)
        session.save()

    def test_inactive_membership_denies_create_and_all_workspace_reads(self):
        self.prepare_existing_draft_and_selected_workspace()
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        self.assert_workspace_routes_denied()

    def test_removed_membership_denies_create_and_all_workspace_reads(self):
        self.prepare_existing_draft_and_selected_workspace()
        self.membership.delete()
        self.assert_workspace_routes_denied()

    def test_never_member_operator_cannot_create_or_read_workspace_data(self):
        self.prepare_existing_draft_and_selected_workspace()
        outsider = User.objects.create_superuser(
            email="draft-outsider@example.test", password="synthetic-draft-outsider-42"
        )
        self.client.force_login(outsider)
        self.assert_workspace_routes_denied()

    def test_tenant_scope_rechecks_revocation_after_initial_permission(self):
        self.prepare_existing_draft_and_selected_workspace()
        prefix = f"/api/v1/workspaces/{self.organization.pk}/"
        routes = (
            ("post", self.url),
            ("get", self.url),
            ("get", f"{self.url}{self.draft.pk}/"),
            ("get", f"{self.url}{self.draft.pk}/lines/"),
            ("get", prefix + "orders/"),
            ("get", prefix + "catalog/items/"),
            ("post", prefix + "catalog/items/"),
        )

        def revoke_after_permission(**kwargs):
            context = resolve_workspace_context(**kwargs)
            Membership.objects.filter(pk=self.membership.pk).update(is_active=False)
            return context

        for method, path in routes:
            with self.subTest(method=method, path=path):
                Membership.objects.filter(pk=self.membership.pk).update(is_active=True)
                with patch(
                    "apps.organizations.permissions.resolve_workspace_context",
                    side_effect=revoke_after_permission,
                ):
                    if method == "post":
                        response = self.client.post(
                            path, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf_token
                        )
                    else:
                        response = self.client.get(path)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(DraftOrder.objects.count(), 1)

    def test_inactive_workspace_denies_create_and_all_workspace_reads(self):
        self.prepare_existing_draft_and_selected_workspace()
        self.organization.is_active = False
        self.organization.save(update_fields=["is_active"])
        self.assert_workspace_routes_denied()

    def test_inactive_user_denies_create_and_all_workspace_reads(self):
        self.prepare_existing_draft_and_selected_workspace()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assert_workspace_routes_denied()

    def test_missing_and_invalid_workspace_ids_are_not_accepted(self):
        self.assertEqual(
            self.client.post(
                f"/api/v1/workspaces/{uuid4()}/draft-orders/",
                {},
                format="json",
                HTTP_X_CSRFTOKEN=self.csrf_token,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/workspaces/not-a-uuid/draft-orders/",
                {},
                format="json",
                HTTP_X_CSRFTOKEN=self.csrf_token,
            ).status_code,
            404,
        )

    def test_write_methods_are_unavailable(self):
        token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        for method in ("post", "put", "patch", "delete"):
            response = getattr(self.client, method)(
                self.url,
                {},
                format="json",
                HTTP_X_CSRFTOKEN=token,
            )
            self.assertEqual(response.status_code, 201 if method == "post" else 405)
