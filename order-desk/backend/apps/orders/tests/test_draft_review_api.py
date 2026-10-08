"""Read-only draft review aggregates respect tenant scope and preserve snapshots."""

from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders import selectors
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.serializers import DraftOrderReviewSerializer
from apps.organizations.context import resolve_workspace_context
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization
from apps.organizations.transactions import tenant_scope


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DraftReviewAPITests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="draft-review@example.test")
        self.organization = create_organization(
            actor=self.user, name="Synthetic review"
        )
        self.membership = Membership.objects.get(
            user=self.user, organization=self.organization
        )
        self.draft = DraftOrder.objects.create(
            organization=self.organization,
            initiating_user=self.user,
            customer_name="Synthetic customer",
            original_intake_text="Original request",
        )
        self.url = (
            f"/api/v1/workspaces/{self.organization.pk}/draft-orders/"
            f"{self.draft.pk}/review/"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.csrf_token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]

    def line(self, position, *, quantity=None, item=None):
        return DraftOrderLine.objects.create(
            organization=self.organization,
            order=self.draft,
            position=position,
            requested_description=f"Synthetic request {position}",
            quantity=quantity,
            catalogue_item=item,
            catalogue_sku_snapshot=item.sku if item else "",
            catalogue_description_snapshot="Historical description" if item else "",
        )

    def state(self):
        return {
            model: list(model.objects.order_by("id").values())
            for model in (DraftOrder, DraftOrderLine, CatalogItem)
        }

    def assert_clean(self):
        self.assertFalse(connection.in_atomic_block)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NULLIF(current_setting('orderdesk.organization_id', true), ''),"
                " NULLIF(current_setting('orderdesk.user_id', true), '')"
            )
            self.assertEqual(cursor.fetchone(), (None, None))

    def test_empty_draft_has_zero_counts_and_observational_customer_flags(self):
        DraftOrder.objects.filter(pk=self.draft.pk).update(customer_name="")
        before = self.state()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json(),
            {
                "id": str(self.draft.pk),
                "organization_id": str(self.organization.pk),
                "customer_name_empty": True,
                "customer_reference_empty": True,
                "line_count": 0,
                "unmatched_line_count": 0,
                "missing_quantity_line_count": 0,
                "unresolved_line_count": 0,
                "inactive_catalogue_line_count": 0,
            },
        )
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_mixed_lines_count_overlaps_once_and_repeated_items_per_line(self):
        active = CatalogItem.objects.create(
            organization=self.organization, sku="Active"
        )
        inactive = CatalogItem.objects.create(
            organization=self.organization, sku="Inactive", is_active=False
        )
        self.line(1)
        self.line(2, quantity=1)
        self.line(3, item=active)
        self.line(4, quantity=2, item=inactive)
        self.line(5, quantity=3, item=inactive)
        before = self.state()
        for role in (
            MembershipRole.ADMIN,
            MembershipRole.REVIEWER,
            MembershipRole.VIEWER,
        ):
            with self.subTest(role=role):
                Membership.objects.filter(pk=self.membership.pk).update(role=role)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200, response.content)
                body = response.json()
                self.assertEqual(set(body), set(DraftOrderReviewSerializer.Meta.fields))
                for field, expected in {
                    "line_count": 5,
                    "unmatched_line_count": 2,
                    "missing_quantity_line_count": 2,
                    "unresolved_line_count": 3,
                    "inactive_catalogue_line_count": 2,
                    "customer_name_empty": False,
                    "customer_reference_empty": True,
                }.items():
                    self.assertEqual(body[field], expected, field)
                self.assertEqual(self.state(), before)
                self.assert_clean()

    def test_customer_and_line_edits_and_deactivation_are_reflected_without_refresh(
        self,
    ):
        item = CatalogItem.objects.create(
            organization=self.organization,
            sku="Active",
            description="Initial catalogue description",
        )
        line = self.line(1)
        self.assertEqual(self.client.get(self.url).json()["unresolved_line_count"], 1)
        detail = self.url.removesuffix("review/")
        line_detail = f"{detail}lines/{line.pk}/"
        for path, values in (
            (detail, {"customer_reference": "REF-42"}),
            (line_detail, {"quantity": "2.000"}),
        ):
            response = self.client.patch(
                path, values, format="json", HTTP_X_CSRFTOKEN=self.csrf_token
            )
            self.assertEqual(response.status_code, 200, response.content)
        attached = self.client.post(
            f"{line_detail}attach/",
            {"catalogue_item_id": str(item.pk)},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )
        self.assertEqual(attached.status_code, 200)
        complete = self.client.get(self.url).json()
        self.assertEqual(complete["unresolved_line_count"], 0)
        self.assertFalse(complete["customer_reference_empty"])
        catalogue_url = (
            f"/api/v1/workspaces/{self.organization.pk}/catalog/items/{item.pk}/"
        )
        changed = self.client.patch(
            catalogue_url,
            {"description": "New description", "is_active": False},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        before = self.state()
        body = self.client.get(self.url).json()
        self.assertEqual(body["unresolved_line_count"], 0)
        self.assertEqual(body["inactive_catalogue_line_count"], 1)
        self.assertEqual(self.state(), before)
        line.refresh_from_db()
        self.assertEqual(
            line.catalogue_description_snapshot, "Initial catalogue description"
        )

    def test_selector_is_one_statement_and_serializer_has_no_queries(self):
        self.line(1)
        with tenant_scope(user=self.user, workspace_id=self.organization.pk):
            with self.assertNumQueries(1):
                order = selectors.get_draft_review(self.organization.pk, self.draft.pk)
            with self.assertNumQueries(0):
                body = DraftOrderReviewSerializer(order).data
            self.assertEqual(body["line_count"], 1)
        self.assert_clean()

    def test_http_materialization_is_inside_read_only_scope(self):
        self.line(1)
        before = self.state()
        original = DraftOrderReviewSerializer.to_representation

        def checked(serializer, instance):
            self.assertTrue(connection.in_atomic_block)
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_read_only")
                self.assertEqual(cursor.fetchone()[0], "on")
            with self.assertNumQueries(0):
                return original(serializer, instance)

        with (
            patch.object(DraftOrderReviewSerializer, "to_representation", new=checked),
            patch.object(DraftOrder, "save") as header_save,
            patch.object(DraftOrderLine, "save") as line_save,
            patch.object(CatalogItem, "save") as item_save,
        ):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for save in (header_save, line_save, item_save):
            save.assert_not_called()
        self.assertEqual(self.state(), before)
        self.assert_clean()

    def test_foreign_parent_and_lines_never_affect_counts_or_leak(self):
        self.line(1, quantity=1)
        foreign_owner = User.objects.create_user(email="foreign-review@example.test")
        other = create_organization(
            actor=foreign_owner, name="Foreign synthetic review"
        )
        for organization, owner in (
            (self.organization, self.user),
            (other, foreign_owner),
        ):
            draft = DraftOrder.objects.create(
                organization=organization, initiating_user=owner
            )
            DraftOrderLine.objects.create(
                organization=organization,
                order=draft,
                position=1,
                requested_sku="Foreign request",
            )
            if organization == other:
                denied = self.client.get(
                    self.url.replace(str(self.draft.pk), str(draft.pk))
                )
                self.assertEqual(denied.status_code, 404)
        response = self.client.get(self.url)
        self.assertEqual(response.json()["line_count"], 1)
        self.assertEqual(response.json()["missing_quantity_line_count"], 0)
        missing = self.client.get(self.url.replace(str(self.draft.pk), str(uuid4())))
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), denied.json())
        for original_id in (self.organization.pk, self.draft.pk):
            self.assertEqual(
                self.client.get(
                    self.url.replace(str(original_id), "not-a-uuid")
                ).status_code,
                404,
            )

    def test_inactive_removed_nonmember_and_operator_access_is_denied(self):
        self.line(1)
        before = self.state()
        outsider = User.objects.create_superuser(
            email="review-outsider@example.test",
            password="synthetic-review-outsider-42",
        )
        for case in (
            "inactive_membership",
            "removed",
            "operator",
            "inactive_user",
            "inactive_workspace",
            "anonymous",
        ):
            with self.subTest(case=case):
                User.objects.filter(pk=self.user.pk).update(is_active=True)
                type(self.organization).objects.filter(pk=self.organization.pk).update(
                    is_active=True
                )
                self.membership, _ = Membership.objects.update_or_create(
                    user=self.user,
                    organization=self.organization,
                    defaults={"is_active": True, "role": MembershipRole.ADMIN},
                )
                self.client.force_login(self.user)
                if case == "inactive_membership":
                    Membership.objects.filter(pk=self.membership.pk).update(
                        is_active=False
                    )
                elif case == "removed":
                    self.membership.delete()
                elif case == "operator":
                    self.client.force_login(outsider)
                elif case == "inactive_user":
                    User.objects.filter(pk=self.user.pk).update(is_active=False)
                elif case == "inactive_workspace":
                    type(self.organization).objects.filter(
                        pk=self.organization.pk
                    ).update(is_active=False)
                else:
                    self.client.logout()
                self.assertEqual(self.client.get(self.url).status_code, 403)
                # Account/workspace state is intentionally changed by this fixture.
                current = self.state()
                self.assertEqual(current[DraftOrder], before[DraftOrder])
                self.assertEqual(current[DraftOrderLine], before[DraftOrderLine])
                self.assert_clean()

    def test_membership_is_rechecked_after_permission_resolution(self):
        def revoke(**kwargs):
            context = resolve_workspace_context(**kwargs)
            Membership.objects.filter(pk=self.membership.pk).update(is_active=False)
            return context

        with patch(
            "apps.organizations.permissions.resolve_workspace_context",
            side_effect=revoke,
        ):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assert_clean()

    def test_methods_queries_head_and_cache_preserve_business_state(self):
        self.line(1)
        before = self.state()
        for query in (
            "?page=1",
            "?page_size=1",
            "?organization_id=" + str(uuid4()),
            "?unknown=1",
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.url + query).status_code, 400)
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf_token
                )
                self.assertEqual(response.status_code, 405)
        head = self.client.head(self.url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertIn("no-store", head["Cache-Control"])
        self.assertEqual(self.client.options(self.url).status_code, 200)
        self.assertEqual(self.state(), before)
        self.assert_clean()
