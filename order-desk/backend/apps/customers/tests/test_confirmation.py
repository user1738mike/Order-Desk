"""Customer decisions remain explicit, version-bound and historically immutable."""

from decimal import Decimal
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.customers.models import DraftCustomerDecision, OrderCustomerSnapshot
from apps.orders.models import DraftOrder, DraftOrderLine
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


class CustomerConfirmationTests(TransactionTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(PRIVATE_DOCUMENT_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.actor = User.objects.create_user(email="confirmation@example.test")
        self.org = create_organization(actor=self.actor, name="Synthetic confirmation")
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.csrf = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.customers = f"/api/v1/workspaces/{self.org.pk}/customers/"
        incoming = f"/api/v1/workspaces/{self.org.pk}/incoming/"
        source = self.client.post(
            incoming,
            {"file": SimpleUploadedFile("source.csv", b"sku,quantity\n00042,1.250\n")},
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )
        self.assertEqual(source.status_code, 201, source.content)
        link = self.post(
            incoming + source.json()["id"] + "/link/",
            {
                "operation_key": str(uuid4()),
                "customer_name": "Original requested buyer",
                "customer_reference": "PO-00001",
            },
        )
        self.draft = link.json()["draft"]
        self.draft_url = f"/api/v1/workspaces/{self.org.pk}/draft-orders/{self.draft}/"
        self.url = self.customers + f"drafts/{self.draft}/confirmation/"
        account = self.post(
            self.customers,
            {
                "code": "00042",
                "display_name": "Confirmed account Ltd",
                "destination_id": "0000009",
            },
        )
        self.assertEqual(account.status_code, 201, account.content)
        self.account = account.json()

    def post(self, path, body):
        return self.client.post(path, body, format="json", HTTP_X_CSRFTOKEN=self.csrf)

    def patch(self, path, body):
        headers = {}
        if "/customers/" in path:
            headers["HTTP_IF_MATCH"] = (
                '"' + self.client.get(path).json()["revision"] + '"'
            )
        return self.client.patch(
            path, body, format="json", HTTP_X_CSRFTOKEN=self.csrf, **headers
        )

    def preview(self, location=None):
        params = {"customer_id": self.account["id"]}
        if location:
            params["location_id"] = location
        return self.client.get(self.url, params)

    def payload(self, location=None):
        response = self.preview(location)
        self.assertEqual(response.status_code, 200, response.content)
        value = response.json()
        return {
            "operation_key": str(uuid4()),
            "customer_id": self.account["id"],
            "location_id": location,
            "reference_revision": value["candidate"]["reference_revision"],
            "expected_draft_revision": value["draft_revision"],
        }

    def confirm(self, location=None):
        response = self.post(self.url, self.payload(location))
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def codes(self):
        result = self.client.get(self.draft_url + "readiness/")
        self.assertEqual(result.status_code, 200, result.content)
        return {row["code"] for row in result.json()["blocking_reasons"]}

    def test_confirm_applies_canonical_name_preserves_requested_text_and_replays(self):
        self.assertIn("customer_unconfirmed", self.codes())
        payload = self.payload()
        first = self.post(self.url, payload)
        self.assertEqual(first.status_code, 201, first.content)
        decision = first.json()
        self.assertEqual(
            decision["snapshot"]["source_requested"]["customer_name"],
            "Original requested buyer",
        )
        self.assertEqual(decision["snapshot"]["account"]["code"], "00042")
        self.assertEqual(
            DraftOrder.objects.get(pk=self.draft).customer_name, "Confirmed account Ltd"
        )
        replay = self.post(self.url, payload)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json()["id"], decision["id"])
        self.assertEqual(DraftCustomerDecision.objects.count(), 1)
        self.assertNotIn("customer_unconfirmed", self.codes())
        self.assertEqual(
            self.post(self.url, {**payload, "customer_id": str(uuid4())}).status_code,
            409,
        )

    def test_multiple_locations_require_explicit_same_account_selection(self):
        site_url = self.customers + self.account["id"] + "/locations/"
        sites = []
        for code in ("S01", "S02"):
            sites.append(
                self.post(
                    site_url,
                    {
                        "code": code,
                        "display_name": "Site " + code,
                        "destination_id": "DEST-" + code,
                    },
                ).json()
            )
        self.assertEqual(self.preview().status_code, 400)
        decision = self.confirm(sites[1]["id"])
        self.assertEqual(decision["snapshot"]["location"]["code"], "S02")
        other = self.post(
            self.customers, {"code": "OTHER", "display_name": "Other"}
        ).json()
        foreign = self.post(
            self.customers + other["id"] + "/locations/",
            {"code": "OTHER", "display_name": "Wrong account"},
        ).json()
        self.assertEqual(self.preview(foreign["id"]).status_code, 404)

    def test_header_change_retires_decision_and_cannot_resurrect_it(self):
        decision = self.confirm()
        self.assertEqual(
            self.patch(
                self.draft_url, {"customer_reference": "CORRECTED-REF"}
            ).status_code,
            200,
        )
        status = self.client.get(self.url).json()
        self.assertFalse(status["confirmed"])
        history = self.client.get(self.url + "history/").json()["results"]
        self.assertEqual(history[0]["retirement_reason"], "source_identity_changed")
        self.assertEqual(
            self.patch(self.draft_url, {"customer_reference": "PO-00001"}).status_code,
            200,
        )
        self.assertIn("customer_unconfirmed", self.codes())
        with self.assertRaises(IntegrityError), transaction.atomic():
            DraftCustomerDecision.objects.filter(pk=decision["id"]).update(
                is_current=True, retired_at=None, retired_by=None, retirement_reason=""
            )

    def test_material_reference_change_requires_renewed_confirmation(self):
        self.confirm()
        path = self.customers + self.account["id"] + "/"
        self.assertEqual(
            self.patch(path, {"destination_id": "NEW-DEST"}).status_code, 200
        )
        self.assertIn("customer_reference_changed", self.codes())
        self.confirm()
        self.assertNotIn("customer_reference_changed", self.codes())
        self.assertEqual(self.patch(path, {"is_active": False}).status_code, 200)
        self.assertIn("customer_inactive", self.codes())

    def test_stale_draft_and_reference_previews_cannot_authorize_decision(self):
        payload = self.payload()
        self.assertEqual(
            self.patch(
                self.draft_url, {"customer_reference": "Changed elsewhere"}
            ).status_code,
            200,
        )
        self.assertEqual(self.post(self.url, payload).status_code, 412)
        payload = self.payload()
        self.assertEqual(
            self.patch(
                self.customers + self.account["id"] + "/",
                {"display_name": "Changed directory"},
            ).status_code,
            200,
        )
        self.assertEqual(self.post(self.url, payload).status_code, 409)
        self.assertEqual(DraftCustomerDecision.objects.count(), 0)

    def test_reviewer_can_confirm_but_viewer_and_revoked_user_cannot_replay(self):
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            role=MembershipRole.REVIEWER
        )
        payload = self.payload()
        self.assertEqual(self.post(self.url, payload).status_code, 201)
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            role=MembershipRole.VIEWER
        )
        self.assertEqual(self.post(self.url, payload).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            is_active=False
        )
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_conversion_snapshot_survives_later_directory_edits(
        self,
    ):
        self.confirm()
        item = CatalogItem.objects.create(
            organization=self.org, sku="00042", description="Synthetic item"
        )
        DraftOrderLine.objects.create(
            organization_id=self.org.pk,
            order_id=self.draft,
            position=1,
            requested_sku="00042",
            quantity=Decimal("1.250"),
            unit="case",
            catalogue_item=item,
            catalogue_sku_snapshot=item.sku,
            catalogue_description_snapshot=item.description,
        )
        self.assertEqual(self.codes(), set())
        converted = self.post(self.draft_url + "convert/", {})
        self.assertEqual(converted.status_code, 201, converted.content)
        order_id = converted.json()["id"]
        snapshot_url = self.customers + "orders/" + order_id + "/snapshot/"
        original = self.client.get(snapshot_url).json()["snapshot"]
        self.assertEqual(original["payload"]["account"]["destination_id"], "0000009")
        self.assertEqual(
            self.patch(
                self.customers + self.account["id"] + "/",
                {"destination_id": "Later change"},
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get(snapshot_url).json()["snapshot"], original)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrderCustomerSnapshot.objects.filter(order_id=order_id).update(payload={})

    def test_unconfirmed_incoming_order_cannot_finalize_even_when_lines_match(self):
        item = CatalogItem.objects.create(organization=self.org, sku="00042")
        DraftOrderLine.objects.create(
            organization_id=self.org.pk,
            order_id=self.draft,
            position=1,
            requested_sku="00042",
            quantity=Decimal("1.250"),
            catalogue_item=item,
            catalogue_sku_snapshot=item.sku,
        )
        result = self.post(self.draft_url + "convert/", {})
        self.assertEqual(result.status_code, 409, result.content)
        self.assertIn(
            "customer_unconfirmed",
            {row["code"] for row in result.json()["blocking_reasons"]},
        )
