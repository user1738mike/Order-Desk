"""Real commit acknowledgement loss cannot duplicate approved reference data."""

from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.customers.models import CustomerAccount, CustomerAlias, ReferenceWriteReceipt
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization

HEADER = b"code,display_name,destination_id,requires_location,is_active\n"
CSV = HEADER + b"00042,Synthetic account,000009,false,true\n"


class CustomerWriteReceiptTests(TransactionTestCase):
    def setUp(self):
        self.actor = User.objects.create_user(email="reference-receipts@example.test")
        self.org = create_organization(
            actor=self.actor, name="Synthetic reference receipts"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.csrf = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.base = f"/api/v1/workspaces/{self.org.pk}/customers/"

    def post(self, body, key, path=None, revision=None):
        return self.client.post(
            path or self.base,
            body,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IDEMPOTENCY_KEY=str(key),
            **({"HTTP_IF_MATCH": '"' + revision + '"'} if revision else {}),
        )

    def upload(self, mode="validate", raw=CSV, key=None):
        return self.client.post(
            self.base + "imports/" + mode + "/",
            {"file": SimpleUploadedFile("customers.csv", raw)},
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IDEMPOTENCY_KEY=str(key or uuid4()),
        )

    def test_lost_committed_response_receipt_and_identical_replay(self):
        key = uuid4()
        body = {"code": "00042", "display_name": "Synthetic account"}
        original = connection._commit
        calls = 0

        def commit():
            nonlocal calls
            calls += 1
            original()
            if calls == 1:
                raise IntegrityError("synthetic acknowledgement loss")

        with patch.object(connection, "_commit", side_effect=commit):
            response = self.post(body, key)
        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(CustomerAccount.objects.count(), 1)
        receipt = self.client.get(self.base + "operations/" + str(key) + "/")
        self.assertEqual(receipt.status_code, 200, receipt.content)
        self.assertEqual(receipt.json()["status"], "committed")
        replay = self.post(body, key)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(replay.json()["id"], receipt.json()["response"]["id"])
        self.assertEqual(ReferenceWriteReceipt.objects.count(), 1)
        self.assertEqual(
            self.post({**body, "display_name": "Different"}, key).status_code, 409
        )

    def test_alias_approval_and_retirement_replay_do_not_create_new_approvals(self):
        account = self.post(
            {"code": "00042", "display_name": "Synthetic"}, uuid4()
        ).json()
        path = self.base + account["id"] + "/aliases/"
        key = uuid4()
        body = {
            "value": "EXPLICIT-ALIAS",
            "provenance": "Synthetic controlled approval",
        }
        alias = self.post(body, key, path)
        self.assertEqual(alias.status_code, 201, alias.content)
        self.assertEqual(self.post(body, key, path).status_code, 200)
        retired = path + alias.json()["id"] + "/retire/"
        retire_key = uuid4()
        reason = {"retirement_reason": "Incorrect mapping"}
        self.assertEqual(
            self.post(
                reason, retire_key, retired, revision=alias.json()["revision"]
            ).status_code,
            200,
        )
        self.assertEqual(
            self.post(
                reason, retire_key, retired, revision=alias.json()["revision"]
            ).status_code,
            200,
        )
        self.assertEqual(CustomerAlias.objects.count(), 1)
        self.assertFalse(CustomerAlias.objects.get().is_active)

    def test_noop_patch_records_receipt_without_invalidating_reference_version(self):
        account = self.post(
            {"code": "00042", "display_name": "Synthetic"}, uuid4()
        ).json()
        result = self.client.patch(
            self.base + account["id"] + "/",
            {"display_name": "Synthetic"},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
            HTTP_IF_MATCH='"' + account["revision"] + '"',
        )
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(result.json()["changed"])
        self.assertEqual(result.json()["updated_at"], account["updated_at"])
        self.assertEqual(ReferenceWriteReceipt.objects.count(), 2)

    def test_missing_or_stale_reference_edit_version_is_rejected(self):
        account = self.post(
            {"code": "00042", "display_name": "Synthetic"}, uuid4()
        ).json()
        url = self.base + account["id"] + "/"
        body = {"display_name": "New saved name"}
        missing = self.client.patch(
            url, body, format="json", HTTP_X_CSRFTOKEN=self.csrf
        )
        self.assertEqual(missing.status_code, 428, missing.content)
        first = self.client.patch(
            url,
            body,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IF_MATCH='"' + account["revision"] + '"',
        )
        self.assertEqual(first.status_code, 200, first.content)
        stale = self.client.patch(
            url,
            {"display_name": "Stale overwrite"},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IF_MATCH='"' + account["revision"] + '"',
        )
        self.assertEqual(stale.status_code, 412, stale.content)
        self.assertEqual(CustomerAccount.objects.get().display_name, "New saved name")

    def test_customer_csv_validation_exact_ids_and_repeat_safe_atomic_create(self):
        checked = self.upload()
        self.assertEqual(checked.status_code, 200, checked.content)
        self.assertTrue(checked.json()["valid"])
        self.assertEqual(CustomerAccount.objects.count(), 0)
        key = uuid4()
        created = self.upload("create", key=key)
        self.assertEqual(created.status_code, 201, created.content)
        account = CustomerAccount.objects.get()
        self.assertEqual((account.code, account.destination_id), ("00042", "000009"))
        replay = self.upload("create", key=key)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json()["original_created"], 1)
        self.assertEqual(CustomerAccount.objects.count(), 1)
        self.assertEqual(
            self.upload(
                "create", raw=CSV.replace(b"000009", b"CHANGED"), key=key
            ).status_code,
            409,
        )
        self.assertEqual(self.upload("create").status_code, 400)

    def test_invalid_mixed_csv_never_partially_writes_and_bounds_apply(self):
        invalid = CSV + b"00042,Duplicate,,false,true\nOTHER,,,false,true\n"
        response = self.upload("create", invalid)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertGreaterEqual(response.json()["error_count"], 2)
        self.assertIn("row", response.json()["errors"][0])
        self.assertEqual(CustomerAccount.objects.count(), 0)
        self.assertEqual(ReferenceWriteReceipt.objects.count(), 0)
        for raw in (b"", b"wrong,header\nA,B\n", HEADER + b"A,\xff,,false,true\n"):
            self.assertEqual(self.upload(raw=raw).status_code, 400)
        self.assertEqual(self.upload(raw=b"a" * 1_048_577).status_code, 413)

    def test_receipts_are_tenant_scoped_and_current_admin_only(self):
        key = uuid4()
        self.post({"code": "00042", "display_name": "Synthetic"}, key)
        url = self.base + "operations/" + str(key) + "/"
        other = create_organization(actor=self.actor, name="Other receipt workspace")
        self.assertEqual(
            self.client.get(url.replace(str(self.org.pk), str(other.pk))).status_code,
            404,
        )
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            role=MembershipRole.REVIEWER
        )
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.upload().status_code, 403)
