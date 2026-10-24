"""Actual PostgreSQL upload-before-order and preservation/replay contracts."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders import incoming
from apps.orders.extraction_services import process_extraction
from apps.orders.models import DraftOrder, OrderDocument, PurchaseOrder
from apps.orders.revisions import draft_revision
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization

CSV = b"sku,quantity,unit\n00042,1.250,case\n"


class IncomingTests(TransactionTestCase):
    def test_demotion_during_receive_denies_metadata_and_cleans_staged_bytes(self):
        def upload():
            Membership.objects.filter(organization=self.org, user=self.actor).update(
                role=MembershipRole.VIEWER
            )
            return SimpleUploadedFile("demoted.csv", CSV)

        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            incoming.receive(
                actor=self.actor,
                organization_id=self.org.pk,
                operation_key=uuid4(),
                upload=upload,
            )
        self.assertEqual(OrderDocument.objects.count(), 0)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_unknown_commit_retains_original_for_reconciliation(self):
        original = connection._commit
        calls = 0

        def commit():
            nonlocal calls
            calls += 1
            if calls == 2:
                original()
                raise IntegrityError("synthetic acknowledgement lost")
            return original()

        with patch.object(connection, "_commit", side_effect=commit):
            response = self.upload()
        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(OrderDocument.objects.count(), 1)
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 1)
        receipt = self.client.get(self.base, {"operation_key": self.key})
        self.assertEqual(receipt.json()["count"], 1)
        self.assertEqual(self.upload().status_code, 200)

    def test_malformed_unsupported_and_oversized_sources_have_no_rows(self):
        for raw in (b"", b"not a csv", b"a,b\n1,2,3", b"a,b\n\xff,1"):
            response = self.upload(key=str(uuid4()), raw=raw)
            self.assertEqual(response.status_code, 400, response.content)
        with patch("apps.orders.uploads.MAX_ORDER_DOCUMENT_BYTES", len(CSV)):
            self.assertEqual(self.upload(raw=CSV + b" ").status_code, 413)
        self.assertEqual(OrderDocument.objects.count(), 0)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        setting = override_settings(PRIVATE_DOCUMENT_ROOT=self.directory.name)
        setting.enable()
        self.addCleanup(setting.disable)
        self.actor = User.objects.create_user(email="incoming@example.test")
        self.org = create_organization(actor=self.actor, name="Incoming synthetic")
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.csrf = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.base = f"/api/v1/workspaces/{self.org.pk}/incoming/"
        self.key = str(uuid4())

    def upload(self, key=None, raw=CSV):
        return self.client.post(
            self.base,
            {"file": SimpleUploadedFile("request.csv", raw)},
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IDEMPOTENCY_KEY=key or self.key,
        )

    def post(self, path, body):
        return self.client.post(path, body, format="json", HTTP_X_CSRFTOKEN=self.csrf)

    def test_upload_before_order_download_and_replay(self):
        first = self.upload()
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertEqual(DraftOrder.objects.count(), 0)
        row = first.json()
        self.assertIsNone(row["order"])
        self.assertIsNone(row["draft"])
        self.assertNotIn("file", row)
        second = self.upload()
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["id"], row["id"])
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 1)
        response = self.client.get(row["download_url"])
        self.assertEqual(b"".join(response.streaming_content), CSV)
        response.close()
        self.assertIn("no-store", response["Cache-Control"])
        changed = self.upload(raw=CSV.replace(b"1.250", b"2.250"))
        self.assertEqual(changed.status_code, 409)

    def test_duplicate_bytes_visible_but_legitimate_repeat_allowed(self):
        self.assertEqual(self.upload().status_code, 201)
        other = self.upload(key=str(uuid4()))
        self.assertEqual(other.status_code, 201, other.content)
        self.assertEqual(other.json()["duplicate_count"], 1)
        listed = self.client.get(self.base, {"q": "REQUEST", "status": "unlinked"})
        self.assertEqual(listed.json()["count"], 2)

    def test_create_draft_once_and_reconcile_after_edits(self):
        row = self.upload().json()
        path = self.base + row["id"] + "/link/"
        payload = {
            "operation_key": str(uuid4()),
            "customer_name": "Confirmed later",
            "customer_reference": "00007",
        }
        first = self.post(path, payload)
        self.assertEqual(first.status_code, 201, first.content)
        draft_id = first.json()["draft"]
        DraftOrder.objects.filter(pk=draft_id).update(customer_name="Edited locally")
        replay = self.post(path, payload)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json()["draft"], draft_id)
        self.assertEqual(DraftOrder.objects.count(), 1)
        self.assertEqual(
            self.post(path, {**payload, "operation_key": str(uuid4())}).status_code, 409
        )
        self.assertEqual(self.client.get(self.base, {"q": "00007"}).json()["count"], 1)
        DraftOrder.objects.create(
            organization=self.org,
            initiating_user=self.actor,
            customer_reference="00007",
        )
        listed = self.client.get(self.base, {"q": "00007"}).json()
        self.assertEqual(listed["results"][0]["reference_duplicate_count"], 1)

    def test_link_existing_draft_requires_revision_and_same_tenant(self):
        row = self.upload().json()
        draft = DraftOrder.objects.create(
            organization=self.org, initiating_user=self.actor
        )
        path = self.base + row["id"] + "/link/"
        payload = {
            "operation_key": str(uuid4()),
            "draft_id": str(draft.pk),
            "expected_revision": "0" * 64,
        }
        self.assertEqual(self.post(path, payload).status_code, 412)
        payload["expected_revision"] = draft_revision(draft)
        good = self.post(path, payload)
        self.assertEqual(good.status_code, 201, good.content)
        self.assertEqual(good.json()["draft"], str(draft.pk))
        other = create_organization(actor=self.actor, name="Foreign")
        foreign = DraftOrder.objects.create(
            organization=other, initiating_user=self.actor
        )
        row = self.upload(key=str(uuid4())).json()
        response = self.post(
            self.base + row["id"] + "/link/",
            {
                **payload,
                "draft_id": str(foreign.pk),
                "expected_revision": draft_revision(foreign),
            },
        )
        self.assertEqual(response.status_code, 404, response.content)

    def test_extract_without_order_then_review_only_linked_draft(self):
        row = self.upload().json()
        queued = self.post(row["extraction_url"], {})
        self.assertEqual(queued.status_code, 202, queued.content)
        self.assertEqual(
            process_extraction(
                actor=self.actor,
                organization_id=self.org.pk,
                job_id=queued.json()["id"],
            ),
            "succeeded",
        )
        linked = self.post(
            self.base + row["id"] + "/link/", {"operation_key": str(uuid4())}
        )
        draft_id = linked.json()["draft"]
        review = self.client.get(
            row["extraction_url"] + "review/", {"draft_id": draft_id}
        )
        self.assertEqual(review.status_code, 200, review.content)
        self.assertEqual(review.json()["results"][0]["fields"]["sku"]["value"], "00042")
        other = DraftOrder.objects.create(
            organization=self.org, initiating_user=self.actor
        )
        self.assertEqual(
            self.client.get(
                row["extraction_url"] + "review/", {"draft_id": str(other.pk)}
            ).status_code,
            400,
        )

    def test_viewer_revocation_csrf_and_strict_queries(self):
        row = self.upload().json()
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            role=MembershipRole.VIEWER
        )
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(self.upload(key=str(uuid4())).status_code, 403)
        self.assertEqual(
            self.post(
                self.base + row["id"] + "/link/", {"operation_key": str(uuid4())}
            ).status_code,
            403,
        )
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            is_active=False
        )
        self.assertEqual(self.client.get(row["download_url"]).status_code, 403)

    def test_database_rejects_reparenting_and_mutable_original(self):
        row = self.upload().json()
        for fields in ({"original_name": "changed.csv"}, {"source_sha256": "0" * 64}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                OrderDocument.objects.filter(pk=row["id"]).update(**fields)
        self.assertEqual(self.client.get(self.base + "?q=a&q=b").status_code, 400)
        self.assertEqual(
            self.client.get(self.base + "?status=unknown").status_code, 400
        )
        no_csrf = APIClient(enforce_csrf_checks=True)
        no_csrf.force_login(self.actor)
        response = no_csrf.post(
            self.base,
            {"file": SimpleUploadedFile("x.csv", CSV)},
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )
        self.assertEqual(response.status_code, 403)
