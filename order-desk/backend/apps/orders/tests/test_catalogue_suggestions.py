"""Exact database equality, protected acceptance and real PostgreSQL races."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.catalog.services import update_catalog_item
from apps.orders.matching import assess_line
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.tests import test_draft_creation_api as fixtures
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CatalogueSuggestionTests(TransactionTestCase):
    def setUp(self):
        fixtures.DraftOrderCreationAPITests.setUp(self)
        self.draft = DraftOrder.objects.create(
            organization=self.organization,
            initiating_user=self.user,
            customer_name="Synthetic buyer",
        )
        self.item = CatalogItem.objects.create(
            organization=self.organization,
            sku="0001.Mixed-Case",
            description="Synthetic catalogue",
        )
        self.line = DraftOrderLine.objects.create(
            organization=self.organization,
            order=self.draft,
            position=1,
            requested_sku="0001.Mixed-Case",
            requested_description="Manual description",
            quantity="1.234",
            unit="ea",
        )
        self.detail = self.url + f"{self.draft.pk}/"
        self.suggestions = self.detail + "suggestions/"
        self.acceptance = self.detail + f"lines/{self.line.pk}/accept-suggestion/"

    def assessment(self):
        response = self.client.get(self.suggestions)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        row = data["results"][0]
        return {
            "catalogue_item_id": row["candidate"]["id"],
            "rule_version": data["rule_version"],
            "source_sku": row["normalized_sku"],
            "catalogue_revision": row["candidate"]["revision"],
        }, data["draft_revision"]

    def accept(self, body, revision, **kwargs):
        return self.client.post(
            self.acceptance,
            body,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf_token,
            HTTP_IF_MATCH=f'"{revision}"',
            **kwargs,
        )

    def test_exact_assessment_is_read_only_and_dimensions_are_unchecked(self):
        before = (
            list(DraftOrderLine.objects.values()),
            list(DraftOrder.objects.values()),
            list(CatalogItem.objects.values()),
        )
        with (
            patch.object(DraftOrderLine, "save") as line_save,
            patch.object(DraftOrder, "save") as draft_save,
            patch.object(CatalogItem, "save") as item_save,
        ):
            data = self.client.get(self.suggestions).json()
            self.assertEqual(data["results"][0]["state"], "exact")
            self.assertEqual(
                data["results"][0]["checks"],
                {
                    "unit": "not_modeled",
                    "pricing": "not_modeled",
                    "quantity": "not_assessed",
                },
            )
            line_save.assert_not_called()
            draft_save.assert_not_called()
            item_save.assert_not_called()
        self.assertEqual(
            before,
            (
                list(DraftOrderLine.objects.values()),
                list(DraftOrder.objects.values()),
                list(CatalogItem.objects.values()),
            ),
        )
        self.assertFalse(connection.in_atomic_block)
        self.assertIn("no-store", self.client.get(self.suggestions)["Cache-Control"])

    def test_database_exactness_preserves_case_punctuation_zeros_and_unicode(self):
        for code, expected in [
            ("  \t0001.Mixed-Case\u2003", "exact"),
            ("0001.mixed-case", "no_match"),
            ("1.Mixed-Case", "no_match"),
            ("0001.MixedCase", "no_match"),
            ("0001.Mixed\u2010Case", "no_match"),
            ("", "empty_sku"),
        ]:
            with self.subTest(code=code):
                DraftOrderLine.objects.filter(pk=self.line.pk).update(
                    requested_sku=code
                )
                row = self.client.get(self.suggestions).json()["results"][0]
                self.assertEqual(row["state"], expected)
                self.assertEqual(row["source_sku"], code)

    def test_inactive_empty_missing_and_foreign_catalogue_do_not_become_matches(self):
        self.item.is_active = False
        self.item.save()
        self.assertEqual(
            self.client.get(self.suggestions).json()["results"][0]["state"], "inactive"
        )
        outsider = User.objects.create_user(email="foreign-matching@example.test")
        foreign = create_organization(actor=outsider, name="Foreign")
        CatalogItem.objects.create(
            organization=foreign, sku="FOREIGN-ONLY", description="PRIVATE"
        )
        DraftOrderLine.objects.filter(pk=self.line.pk).update(
            requested_sku="FOREIGN-ONLY"
        )
        data = self.client.get(self.suggestions).json()
        self.assertEqual(data["results"][0]["state"], "no_match")
        self.assertNotIn("PRIVATE", str(data))

    def test_attached_state_and_changed_source_snapshot_or_active_state(self):
        body, revision = self.assessment()
        self.assertEqual(self.accept(body, revision).status_code, 200)
        self.assertEqual(
            self.client.get(self.suggestions).json()["results"][0]["state"],
            "already_attached",
        )
        for change, state in [
            ({"requested_sku": "another"}, "source_changed"),
            (
                {
                    "requested_sku": self.item.sku,
                    "catalogue_description_snapshot": "older",
                },
                "snapshot_changed",
            ),
        ]:
            with self.subTest(state=state):
                DraftOrderLine.objects.filter(pk=self.line.pk).update(**change)
                self.assertEqual(
                    self.client.get(self.suggestions).json()["results"][0][
                        "attachment"
                    ]["state"],
                    state,
                )
        self.item.is_active = False
        self.item.save()
        self.assertEqual(
            self.client.get(self.suggestions).json()["results"][0]["attachment"][
                "state"
            ],
            "inactive",
        )

    def test_ambiguity_rule_never_selects_arbitrary_identity(self):
        items = [
            SimpleNamespace(pk=uuid4(), sku=self.line.requested_sku, is_active=True)
            for _ in range(2)
        ]
        self.assertEqual(assess_line(self.line, items)["state"], "ambiguous")
        self.assertIsNone(assess_line(self.line, items)["candidate"])

    def test_admin_and_reviewer_accept_without_changing_requested_values(self):
        for role in (MembershipRole.ADMIN, MembershipRole.REVIEWER):
            with self.subTest(role=role):
                Membership.objects.filter(pk=self.membership.pk).update(role=role)
                DraftOrderLine.objects.filter(pk=self.line.pk).update(
                    catalogue_item=None,
                    catalogue_sku_snapshot="",
                    catalogue_description_snapshot="",
                )
                body, revision = self.assessment()
                response = self.accept(body, revision)
                self.assertEqual(response.status_code, 200, response.content)
                self.line.refresh_from_db()
                self.assertEqual(self.line.catalogue_item_id, self.item.pk)
                self.assertEqual(
                    (
                        self.line.requested_sku,
                        self.line.requested_description,
                        self.line.quantity,
                        self.line.unit,
                    ),
                    ("0001.Mixed-Case", "Manual description", Decimal("1.234"), "ea"),
                )
                self.assertNotEqual(
                    self.client.get(self.suggestions).json()["draft_revision"], revision
                )
                self.assertTrue(
                    self.client.get(self.detail + "readiness/").json()[
                        "ready_to_convert"
                    ]
                )

    def test_viewer_can_assess_but_cannot_accept(self):
        Membership.objects.filter(pk=self.membership.pk).update(
            role=MembershipRole.VIEWER
        )
        body, revision = self.assessment()
        self.assertEqual(self.accept(body, revision).status_code, 403)
        self.line.refresh_from_db()
        self.assertIsNone(self.line.catalogue_item_id)

    def test_validation_requires_revision_exact_body_and_current_dependencies(self):
        body, revision = self.assessment()
        for data in (
            {},
            {**body, "unknown": 1},
            {**body, "source_sku": 1},
            {**body, "catalogue_revision": "bad"},
            {**body, "rule_version": "fuzzy"},
        ):
            with self.subTest(data=data), patch.object(DraftOrderLine, "save") as saved:
                self.assertEqual(self.accept(data, revision).status_code, 400)
                saved.assert_not_called()
        self.assertEqual(
            self.client.post(
                self.acceptance, body, format="json", HTTP_X_CSRFTOKEN=self.csrf_token
            ).status_code,
            400,
        )
        for data in (
            {**body, "source_sku": "OTHER"},
            {**body, "catalogue_revision": "a" * 64},
        ):
            self.assertEqual(self.accept(data, revision).status_code, 409)
        self.assertEqual(self.accept(body, "b" * 64).status_code, 412)
        self.item.is_active = False
        self.item.save()
        self.assertEqual(self.accept(body, revision).status_code, 409)

    def test_catalogue_description_change_and_source_edit_conflict(self):
        body, revision = self.assessment()
        update_catalog_item(
            actor=self.user,
            organization_id=self.organization.pk,
            item_id=self.item.pk,
            data={"description": "Changed"},
        )
        self.assertEqual(self.accept(body, revision).status_code, 409)
        body, revision = self.assessment()
        DraftOrderLine.objects.filter(pk=self.line.pk).update(requested_sku="CHANGED")
        self.assertEqual(self.accept(body, revision).status_code, 412)

    def test_repeat_acceptance_is_safe_and_current_revision_noop_keeps_timestamps(self):
        body, revision = self.assessment()
        self.assertEqual(self.accept(body, revision).status_code, 200)
        self.assertEqual(self.accept(body, revision).status_code, 412)
        body, current = self.assessment()
        before = (
            list(DraftOrderLine.objects.values()),
            list(DraftOrder.objects.values()),
        )
        self.assertEqual(self.accept(body, current).status_code, 200)
        self.assertEqual(
            before,
            (list(DraftOrderLine.objects.values()), list(DraftOrder.objects.values())),
        )
        self.assertEqual(DraftOrderLine.objects.count(), 1)

    def test_csrf_session_tenant_and_method_boundaries(self):
        body, revision = self.assessment()
        self.assertEqual(
            self.client.post(
                self.acceptance, body, format="json", HTTP_IF_MATCH=f'"{revision}"'
            ).status_code,
            403,
        )
        # Dedicated malformed token client is not conflated with a valid session.
        another = APIClient(enforce_csrf_checks=True)
        another.force_login(self.user)
        self.assertEqual(
            another.post(
                self.acceptance,
                body,
                format="json",
                HTTP_X_CSRFTOKEN="invalid",
                HTTP_IF_MATCH=f'"{revision}"',
            ).status_code,
            403,
        )
        another.logout()
        self.assertEqual(another.get(self.suggestions).status_code, 403)
        for target in (str(uuid4()), "malformed"):
            self.assertEqual(
                self.client.get(
                    self.suggestions.replace(str(self.draft.pk), target)
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.post(
                    self.acceptance.replace(str(self.line.pk), target),
                    body,
                    format="json",
                    HTTP_X_CSRFTOKEN=self.csrf_token,
                    HTTP_IF_MATCH=f'"{self.client.get(self.suggestions).json()["draft_revision"]}"',
                ).status_code,
                404,
            )
        self.assertEqual(
            self.client.post(
                self.suggestions, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf_token
            ).status_code,
            405,
        )
        self.assertEqual(self.client.get(self.acceptance).status_code, 405)

    def test_revoked_or_inactive_user_workspace_membership_denied(self):
        for model, pk, changes in [
            (Membership, self.membership.pk, {"is_active": False}),
            (User, self.user.pk, {"is_active": False}),
            (type(self.organization), self.organization.pk, {"is_active": False}),
        ]:
            body, revision = self.assessment()
            model.objects.filter(pk=pk).update(**changes)
            self.assertEqual(self.client.get(self.suggestions).status_code, 403)
            self.assertEqual(self.accept(body, revision).status_code, 403)
            model.objects.filter(pk=pk).update(is_active=True)

    def test_pagination_bounds_and_one_catalogue_query_for_the_whole_page(self):
        with CaptureQueriesContext(connection) as single:
            self.assertEqual(self.client.get(self.suggestions).status_code, 200)
        single_queries = list(single.captured_queries)
        DraftOrderLine.objects.bulk_create(
            [
                DraftOrderLine(
                    organization=self.organization,
                    order=self.draft,
                    position=i,
                    requested_sku=self.item.sku,
                )
                for i in range(2, 52)
            ]
        )
        with CaptureQueriesContext(connection) as many:
            result = self.client.get(self.suggestions).json()
        many_queries = list(many.captured_queries)
        self.assertEqual(result["count"], 51)
        self.assertEqual(len(result["results"]), 50)
        self.assertEqual(
            [row["position"] for row in result["results"]], list(range(1, 51))
        )
        self.assertEqual(
            len(self.client.get(self.suggestions + "?page=2").json()["results"]), 1
        )
        for queries in (single_queries, many_queries):
            self.assertEqual(
                sum('FROM "catalog_catalogitem"' in query["sql"] for query in queries),
                1,
            )
        self.assertEqual(len(single_queries), len(many_queries))
        for query in (
            "?unknown=1",
            "?page=1&page=2",
            "?page_size=1",
            "?page=0",
            "?page=bad",
        ):
            self.assertIn(
                self.client.get(self.suggestions + query).status_code, (400, 404)
            )

    def test_oversized_source_is_bounded_and_not_silently_matched(self):
        DraftOrderLine.objects.filter(pk=self.line.pk).update(requested_sku="X" * 4097)
        row = self.client.get(self.suggestions).json()["results"][0]
        self.assertEqual(row["state"], "unsupported_sku")
        self.assertTrue(row["source_truncated"])
        self.assertEqual(len(row["source_sku"]), 4096)
        self.assertIsNone(row["candidate"])

    def test_foreign_draft_line_and_catalogue_identifiers_are_unavailable(self):
        other = create_organization(actor=self.user, name="Other authorized workspace")
        foreign = DraftOrder.objects.create(
            organization=other, initiating_user=self.user
        )
        line = DraftOrderLine.objects.create(
            organization=other, order=foreign, position=1, requested_sku=self.item.sku
        )
        item = CatalogItem.objects.create(
            organization=other, sku=self.item.sku, description="PRIVATE"
        )
        body, revision = self.assessment()
        self.assertEqual(
            self.client.get(
                self.suggestions.replace(str(self.draft.pk), str(foreign.pk))
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                self.acceptance.replace(str(self.line.pk), str(line.pk)),
                body,
                format="json",
                HTTP_X_CSRFTOKEN=self.csrf_token,
                HTTP_IF_MATCH=f'"{revision}"',
            ).status_code,
            404,
        )
        self.assertEqual(
            self.accept(
                {**body, "catalogue_item_id": str(item.pk)}, revision
            ).status_code,
            404,
        )
        self.line.refresh_from_db()
        self.assertIsNone(self.line.catalogue_item_id)

    def test_revocation_between_permission_resolution_and_write_scope_is_denied(self):
        from apps.organizations.context import resolve_workspace_context

        body, revision = self.assessment()

        def revoke(*, user, workspace_id):
            Membership.objects.filter(pk=self.membership.pk).update(is_active=False)
            return resolve_workspace_context(user=user, workspace_id=workspace_id)

        with (
            patch(
                "apps.organizations.transactions.resolve_workspace_context",
                side_effect=revoke,
            ),
            patch.object(DraftOrderLine, "save") as saved,
        ):
            self.assertEqual(self.accept(body, revision).status_code, 403)
            saved.assert_not_called()

    def _race_request(self, barrier, method, path, body, revision=None):
        close_old_connections()
        try:
            client = APIClient(enforce_csrf_checks=True)
            client.force_login(User.objects.get(pk=self.user.pk))
            token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
            barrier.wait(timeout=10)
            kwargs = {"format": "json", "HTTP_X_CSRFTOKEN": token}
            if revision:
                kwargs["HTTP_IF_MATCH"] = f'"{revision}"'
            response = getattr(client, method)(path, body, **kwargs)
            return response.status_code
        finally:
            connections["default"].close()

    def test_two_simultaneous_acceptances_commit_one_attachment(self):
        body, revision = self.assessment()
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [
                pool.submit(
                    self._race_request, barrier, "post", self.acceptance, body, revision
                )
                for _ in range(2)
            ]
            self.assertCountEqual(
                [future.result(timeout=20) for future in results], [200, 412]
            )
        self.assertEqual(DraftOrderLine.objects.count(), 1)

    def test_acceptance_vs_manual_edit_serializes_on_draft_revision(self):
        body, revision = self.assessment()
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            accepting = pool.submit(
                self._race_request, barrier, "post", self.acceptance, body, revision
            )
            editing = pool.submit(
                self._race_request,
                barrier,
                "patch",
                self.detail + f"lines/{self.line.pk}/",
                {"requested_sku": "Manual winner"},
                revision,
            )
            self.assertIn(
                (accepting.result(timeout=20), editing.result(timeout=20)),
                ((200, 412), (412, 200)),
            )
        self.line.refresh_from_db()
        self.assertTrue(
            (
                self.line.catalogue_item_id == self.item.pk
                and self.line.requested_sku == self.item.sku
            )
            or (
                self.line.catalogue_item_id is None
                and self.line.requested_sku == "Manual winner"
            )
        )

    def test_acceptance_vs_catalogue_deactivation_has_only_serial_outcomes(self):
        body, revision = self.assessment()
        barrier = Barrier(2)
        item_path = (
            f"/api/v1/workspaces/{self.organization.pk}/catalog/items/{self.item.pk}/"
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            accepting = pool.submit(
                self._race_request, barrier, "post", self.acceptance, body, revision
            )
            deactivating = pool.submit(
                self._race_request, barrier, "patch", item_path, {"is_active": False}
            )
            outcome = accepting.result(timeout=20)
            self.assertEqual(deactivating.result(timeout=20), 200)
        self.assertIn(outcome, (200, 409))
        self.line.refresh_from_db()
        self.assertEqual(
            self.line.catalogue_item_id, self.item.pk if outcome == 200 else None
        )
        readiness = self.client.get(self.detail + "readiness/").json()
        self.assertFalse(readiness["ready_to_convert"])

    def test_converted_source_denies_acceptance(self):
        body, revision = self.assessment()
        self.assertEqual(self.accept(body, revision).status_code, 200)
        current = self.client.get(self.suggestions).json()["draft_revision"]
        response = self.client.post(
            self.detail + "convert/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf_token,
            HTTP_IF_MATCH=f'"{current}"',
        )
        self.assertEqual(response.status_code, 201, response.content)
        current = self.client.get(self.suggestions).json()["draft_revision"]
        with patch.object(DraftOrderLine, "save") as save:
            self.assertEqual(self.accept(body, current).status_code, 409)
            save.assert_not_called()
