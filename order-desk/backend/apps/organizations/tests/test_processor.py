"""Processing is routine preparation, never reference administration or approval."""

from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.extraction_services import process_extraction
from apps.orders.models import PurchaseOrder
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


class ProcessorTests(TransactionTestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = override_settings(PRIVATE_DOCUMENT_ROOT=folder.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.actor = User.objects.create_user(email="processor@example.test")
        self.org = create_organization(actor=self.actor, name="Synthetic processor")
        self.base = f"/api/v1/workspaces/{self.org.pk}/"
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.csrf = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.account = self.post(
            "customers/", {"code": "00042", "display_name": "Synthetic confirmed"}
        ).json()
        self.item = CatalogItem.objects.create(organization=self.org, sku="00042")
        self.order = PurchaseOrder.objects.create(
            organization=self.org,
            created_by=self.actor,
            customer_name="Synthetic legacy",
            purchase_order_number="PROCESSOR-00001",
            status="pending_review",
        )
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            role=MembershipRole.PROCESSOR
        )

    def post(self, suffix, body, revision=None):
        return self.client.post(
            self.base + suffix,
            body,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            **({"HTTP_IF_MATCH": '"' + revision + '"'} if revision else {}),
        )

    def revision(self, draft):
        return self.client.get(self.base + f"draft-orders/{draft}/revision/").json()[
            "revision"
        ]

    def test_processor_prepares_confirmed_draft_but_cannot_finalize_or_administer(self):
        context = self.client.get(self.base + "context/").json()
        self.assertEqual(context["workspace"]["role"], "processor")
        response = self.post(
            "draft-orders/",
            {"customer_name": "Requested buyer", "customer_reference": "00009"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        draft = response.json()["id"]
        path = f"draft-orders/{draft}/"
        line = self.post(
            path + "lines/",
            {
                "position": 1,
                "requested_sku": "00042",
                "quantity": "1.250",
                "unit": "case",
            },
            self.revision(draft),
        )
        self.assertEqual(line.status_code, 201, line.content)
        attached = self.post(
            path + f"lines/{line.json()['id']}/attach/",
            {"catalogue_item_id": str(self.item.pk)},
            self.revision(draft),
        )
        self.assertEqual(attached.status_code, 200, attached.content)
        confirmation = f"customers/drafts/{draft}/confirmation/"
        preview = self.client.get(
            self.base + confirmation, {"customer_id": self.account["id"]}
        )
        self.assertEqual(preview.status_code, 200, preview.content)
        value = preview.json()
        payload = {
            "operation_key": str(uuid4()),
            "customer_id": self.account["id"],
            "reference_revision": value["candidate"]["reference_revision"],
            "expected_draft_revision": value["draft_revision"],
        }
        self.assertEqual(self.post(confirmation, payload).status_code, 201)
        self.assertEqual(self.post(confirmation, payload).status_code, 200)
        self.assertTrue(
            self.client.get(self.base + path + "readiness/").json()["ready_to_convert"]
        )
        self.assertEqual(
            self.post(path + "convert/", {}, self.revision(draft)).status_code, 403
        )
        for action in ("approve/", "reject/", "submit/", "exports/"):
            denied = self.post(f"orders/{self.order.pk}/" + action, {})
            self.assertEqual(denied.status_code, 403, denied.content)
        for suffix, body in (
            ("customers/", {"code": "DENIED", "display_name": "Denied"}),
            (
                f"customers/{self.account['id']}/aliases/",
                {"value": "Denied", "provenance": "Denied"},
            ),
            ("catalog/items/", {"sku": "DENIED"}),
        ):
            denied = self.post(suffix, body)
            self.assertEqual(denied.status_code, 403, denied.content)
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            role=MembershipRole.VIEWER
        )
        self.assertEqual(self.post(confirmation, payload).status_code, 403)
        self.assertEqual(
            self.post("draft-orders/", {"customer_name": "Denied"}).status_code, 403
        )

    def test_processor_uploads_links_and_runs_bounded_local_extraction(self):
        incoming = self.base + "incoming/"
        response = self.client.post(
            incoming,
            {
                "file": SimpleUploadedFile(
                    "source.csv", b"sku,quantity,unit\n00042,1.250,case\n"
                )
            },
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )
        self.assertEqual(response.status_code, 201, response.content)
        source = response.json()
        link = self.post(
            f"incoming/{source['id']}/link/",
            {
                "operation_key": str(uuid4()),
                "customer_name": "Requested buyer",
                "customer_reference": "00009",
            },
        )
        self.assertEqual(link.status_code, 201, link.content)
        queued = self.client.post(
            source["extraction_url"], {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
        )
        self.assertEqual(queued.status_code, 202, queued.content)

        self.assertEqual(
            process_extraction(
                actor=self.actor,
                organization_id=self.org.pk,
                job_id=UUID(queued.json()["id"]),
            ),
            "succeeded",
        )
        observed = self.client.get(source["extraction_url"])
        self.assertEqual(observed.status_code, 200, observed.content)
        self.assertEqual(observed.json()["job"]["status"], "succeeded")
        draft = link.json()["draft"]
        review = self.client.get(
            source["extraction_url"] + "review/", {"draft_id": draft}
        )
        self.assertEqual(review.status_code, 200, review.content)
        value = review.json()
        payload = {
            "operation_key": str(uuid4()),
            "job_id": queued.json()["id"],
            "draft_id": draft,
            "result_revision": value["result_revision"],
            "expected_draft_revision": value["draft_revision"],
            "mappings": [
                {
                    "candidate_id": value["results"][0]["candidate_id"],
                    "action": "create",
                    "position": 1,
                    "fields": ["sku", "quantity", "unit"],
                    "corrections": {},
                }
            ],
        }
        for expected in (201, 200):
            result = self.client.post(
                source["extraction_url"] + "apply/",
                payload,
                format="json",
                HTTP_X_CSRFTOKEN=self.csrf,
            )
            self.assertEqual(result.status_code, expected, result.content)
        lines = self.client.get(self.base + f"draft-orders/{draft}/lines/").json()
        self.assertEqual(lines["count"], 1)
        self.assertEqual(
            (
                lines["results"][0]["requested_sku"],
                lines["results"][0]["quantity"],
                lines["results"][0]["unit"],
            ),
            ("00042", "1.250", "case"),
        )
