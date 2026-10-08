"""Aggregate stale-write protection, with real PostgreSQL transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.revisions import DraftRevisionConflict
from apps.orders.services import update_draft_customer_fields, update_draft_order_line
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DraftRevisionTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="revision@example.test")
        self.organization = create_organization(actor=self.user, name="Revision tests")
        self.draft = DraftOrder.objects.create(
            organization=self.organization,
            initiating_user=self.user,
            customer_name="Client",
        )
        self.line = DraftOrderLine.objects.create(
            organization=self.organization,
            order=self.draft,
            position=1,
            requested_sku="0001.Case",
            quantity="1.234",
            unit="ea",
        )
        self.item = CatalogItem.objects.create(
            organization=self.organization, sku="0001.Case"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.csrf = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.url = (
            f"/api/v1/workspaces/{self.organization.pk}/draft-orders/{self.draft.pk}/"
        )

    def revision(self):
        response = self.client.get(self.url + "revision/")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["id"], str(self.draft.pk))
        self.assertEqual(body["organization_id"], str(self.organization.pk))
        self.assertRegex(body["revision"], r"^[0-9a-f]{64}$")
        self.assertEqual(response["ETag"], f'"{body["revision"]}"')
        return body["revision"]

    def mutate(self, method, suffix, data, revision):
        return getattr(self.client, method)(
            self.url + suffix,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IF_MATCH=f'"{revision}"',
        )

    def test_stale_header_is_412_without_save_or_open_transaction(self):
        old = self.revision()
        self.assertEqual(
            self.mutate("patch", "", {"customer_name": "Winner"}, old).status_code, 200
        )
        with patch.object(DraftOrder, "save") as save:
            response = self.mutate("patch", "", {"customer_name": "Stale"}, old)
        self.assertEqual(response.status_code, 412, response.content)
        self.assertEqual(response.json(), {"detail": "draft_revision_conflict"})
        save.assert_not_called()
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.customer_name, "Winner")
        self.assertFalse(connection.in_atomic_block)

    def test_all_line_actions_change_aggregate_and_reject_stale_header(self):
        actions = (
            ("post", "lines/", {"position": 2, "requested_sku": "Other"}, 201),
            ("patch", f"lines/{self.line.pk}/", {"quantity": "2.345"}, 200),
            (
                "post",
                f"lines/{self.line.pk}/attach/",
                {"catalogue_item_id": str(self.item.pk)},
                200,
            ),
            ("post", f"lines/{self.line.pk}/detach/", {}, 200),
        )
        for method, suffix, data, status in actions:
            with self.subTest(suffix=suffix):
                old = self.revision()
                response = self.mutate(method, suffix, data, old)
                self.assertEqual(response.status_code, status, response.content)
                self.assertNotEqual(self.revision(), old)
                self.assertEqual(
                    self.mutate(
                        "patch", "", {"customer_name": "Stale"}, old
                    ).status_code,
                    412,
                )

    def test_noop_stays_stable_and_legacy_line_write_is_detected(self):
        old = self.revision()
        self.assertEqual(
            self.mutate("patch", "", {"customer_name": "Client"}, old).status_code, 200
        )
        self.assertEqual(self.revision(), old)
        update_draft_order_line(
            actor=self.user,
            organization_id=self.organization.pk,
            order_id=self.draft.pk,
            line_id=self.line.pk,
            data={"unit": "box"},
        )
        self.assertEqual(
            self.mutate("patch", "", {"customer_reference": "Stale"}, old).status_code,
            412,
        )

    def test_each_stale_line_action_is_rejected_before_save(self):
        old = self.revision()
        response = self.mutate("patch", "", {"customer_name": "New header"}, old)
        self.assertEqual(response.status_code, 200, response.content)
        before = list(DraftOrderLine.objects.filter(order=self.draft).values())
        actions = (
            ("post", "lines/", {"position": 2, "requested_sku": "Other"}),
            ("patch", f"lines/{self.line.pk}/", {"quantity": "2.345"}),
            (
                "post",
                f"lines/{self.line.pk}/attach/",
                {"catalogue_item_id": str(self.item.pk)},
            ),
            ("post", f"lines/{self.line.pk}/detach/", {}),
        )
        for method, suffix, data in actions:
            with (
                self.subTest(suffix=suffix),
                patch.object(DraftOrderLine, "save") as save,
            ):
                response = self.mutate(method, suffix, data, old)
                self.assertEqual(response.status_code, 412, response.content)
                self.assertEqual(response.json(), {"detail": "draft_revision_conflict"})
                save.assert_not_called()
                self.assertFalse(connection.in_atomic_block)
                self.assertEqual(
                    list(DraftOrderLine.objects.filter(order=self.draft).values()),
                    before,
                )

    def test_stale_conversion_denied_but_authorized_replay_keeps_same_order(self):
        old = self.revision()
        response = self.mutate(
            "post",
            f"lines/{self.line.pk}/attach/",
            {"catalogue_item_id": str(self.item.pk)},
            old,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.mutate("post", "convert/", {}, old).status_code, 412)
        current = self.revision()
        first = self.mutate("post", "convert/", {}, current)
        self.assertEqual(first.status_code, 201, first.content)
        replay = self.mutate("post", "convert/", {}, current)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), first.json())

    def test_permission_header_and_foreign_revision_boundaries(self):
        old = self.revision()
        response = self.client.patch(
            self.url,
            {"customer_name": "Invalid"},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IF_MATCH="*",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("If-Match", response.json())
        Membership.objects.filter(
            user=self.user, organization=self.organization
        ).update(role=MembershipRole.VIEWER)
        self.assertEqual(
            self.mutate("patch", "", {"customer_name": "Denied"}, old).status_code, 403
        )
        owner = User.objects.create_user(email="revision-other@example.test")
        other = create_organization(actor=owner, name="Other")
        foreign = DraftOrder.objects.create(organization=other, initiating_user=owner)
        root = self.url.rsplit(str(self.draft.pk), 1)[0]
        response = self.client.get(f"{root}{foreign.pk}/revision/")
        self.assertEqual(response.status_code, 404)

    def test_two_connections_same_revision_allow_exactly_one_winner(self):
        revision = self.revision()
        barrier = Barrier(2)

        def edit(value):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                update_draft_customer_fields(
                    actor=self.user,
                    organization_id=self.organization.pk,
                    order_id=self.draft.pk,
                    data={"customer_name": value},
                    expected_revision=revision,
                )
                return value
            except DraftRevisionConflict:
                return None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(edit, ("First", "Second")))
        winners = [value for value in results if value is not None]
        self.assertEqual(len(winners), 1)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.customer_name, winners[0])
