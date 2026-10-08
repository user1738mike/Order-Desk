"""PostgreSQL readiness policy, bounded aggregates and current tenant access."""

from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders import selectors
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.readiness import evaluate_draft_readiness
from apps.orders.serializers import DraftOrderReadinessSerializer
from apps.organizations.context import resolve_workspace_context
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization
from apps.organizations.transactions import tenant_scope


class DraftReadinessTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="readiness@example.test")
        self.organization = create_organization(
            actor=self.user, name="Synthetic readiness"
        )
        self.membership = Membership.objects.get(
            user=self.user, organization=self.organization
        )
        self.draft = DraftOrder.objects.create(
            organization=self.organization,
            initiating_user=self.user,
            customer_name="Buyer",
        )
        self.item = CatalogItem.objects.create(
            organization=self.organization, sku="001-a/B"
        )
        self.url = (
            f"/api/v1/workspaces/{self.organization.pk}/draft-orders/"
            f"{self.draft.pk}/readiness/"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]

    def line(self, position=1, **kwargs):
        values = dict(
            organization=self.organization,
            order=self.draft,
            position=position,
            quantity=1,
            catalogue_item=self.item,
            catalogue_sku_snapshot=self.item.sku,
        )
        values.update(kwargs)
        return DraftOrderLine.objects.create(**values)

    def state(self):
        return [
            list(model.objects.order_by("id").values())
            for model in (DraftOrder, DraftOrderLine, CatalogItem)
        ]

    def test_empty_and_complete_drafts_preserve_business_state(self):
        DraftOrder.objects.filter(pk=self.draft.pk).update(customer_name="")
        before = self.state()
        body = self.client.get(self.url).json()
        self.assertEqual(
            body["blocking_reasons"],
            [
                {"code": "customer_name_missing", "count": 1},
                {"code": "lines_missing", "count": 1},
            ],
        )
        self.assertFalse(body["ready_to_convert"])
        self.assertEqual(self.state(), before)
        DraftOrder.objects.filter(pk=self.draft.pk).update(customer_name="Buyer")
        self.line(quantity="999999999.999", unit="")
        before = self.state()
        for role in MembershipRole.values:
            with self.subTest(role=role):
                Membership.objects.filter(pk=self.membership.pk).update(role=role)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    dict(
                        id=str(self.draft.pk),
                        organization_id=str(self.organization.pk),
                        ready_to_convert=True,
                        line_count=1,
                        blocking_reasons=[],
                    ),
                )
        self.assertEqual(self.state(), before)

    def test_overlapping_and_repeated_line_blockers_and_sku_boundary(self):
        self.line(
            1,
            quantity=None,
            catalogue_item=None,
            catalogue_sku_snapshot="",
            requested_sku="Request",
        )
        self.line(2, catalogue_sku_snapshot="x" * 128)
        self.line(3, catalogue_sku_snapshot="x" * 129)
        CatalogItem.objects.filter(pk=self.item.pk).update(is_active=False)
        before = self.state()
        body = self.client.get(self.url).json()
        self.assertEqual(
            body["blocking_reasons"],
            [
                {"code": "quantity_missing", "count": 1},
                {"code": "catalogue_unmatched", "count": 1},
                {"code": "catalogue_inactive", "count": 2},
                {"code": "catalogue_sku_too_long", "count": 1},
            ],
        )
        self.assertEqual(body["line_count"], 3)
        self.assertEqual(self.state(), before)

    def test_one_statement_zero_serialization_queries_read_only(self):
        self.line()
        with tenant_scope(user=self.user, workspace_id=self.organization.pk):
            with self.assertNumQueries(1):
                order = selectors.get_draft_readiness(
                    self.organization.pk, self.draft.pk
                )
            with self.assertNumQueries(0):
                body = DraftOrderReadinessSerializer(
                    evaluate_draft_readiness(order)
                ).data
            self.assertTrue(body["ready_to_convert"])
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_read_only")
                self.assertEqual(cursor.fetchone()[0], "on")
        self.assertFalse(connection.in_atomic_block)

    def test_current_inactive_access_is_denied(self):
        for target in (self.user, self.organization, self.membership):
            with self.subTest(model=type(target).__name__):
                type(target).objects.filter(pk=target.pk).update(is_active=False)
                self.assertEqual(self.client.get(self.url).status_code, 403)
                type(target).objects.filter(pk=target.pk).update(is_active=True)
        Membership.objects.filter(pk=self.membership.pk).delete()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        outsider = User.objects.create_user(
            email="outsider@example.test", is_superuser=True, is_staff=True
        )
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_revocation_at_tenant_entry_is_denied(self):
        def revoke(**kwargs):
            context = resolve_workspace_context(**kwargs)
            Membership.objects.filter(pk=self.membership.pk).update(is_active=False)
            return context

        with patch(
            "apps.organizations.permissions.resolve_workspace_context",
            side_effect=revoke,
        ):
            self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertFalse(connection.in_atomic_block)

    def test_foreign_missing_malformed_and_anonymous(self):
        other = create_organization(actor=self.user, name="Other readiness")
        foreign = DraftOrder.objects.create(
            organization=other, initiating_user=self.user
        )
        for identity in (foreign.pk, uuid4(), "bad-uuid"):
            with self.subTest(identity=identity):
                self.assertEqual(
                    self.client.get(
                        self.url.replace(str(self.draft.pk), str(identity))
                    ).status_code,
                    404,
                )
        self.assertEqual(APIClient().get(self.url).status_code, 403)

    def test_head_queries_methods_and_cache(self):
        self.assertEqual(self.client.head(self.url).status_code, 200)
        self.assertEqual(self.client.head(self.url).content, b"")
        self.assertIn("no-store", self.client.get(self.url)["Cache-Control"])
        self.assertEqual(self.client.get(self.url + "?page=1").status_code, 400)
        for method in ("post", "patch", "put", "delete"):
            with self.subTest(method=method):
                self.assertEqual(
                    getattr(self.client, method)(
                        self.url, {}, format="json", HTTP_X_CSRFTOKEN=self.token
                    ).status_code,
                    405,
                )
