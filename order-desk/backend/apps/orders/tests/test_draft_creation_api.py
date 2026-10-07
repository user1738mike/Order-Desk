"""PostgreSQL API tests for protected draft-order creation."""

from uuid import uuid4

from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.models import DraftOrder
from apps.organizations.models import Membership, MembershipRole
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
        other_workspace = create_organization(
            actor=self.user, name="Other Workspace"
        )
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
