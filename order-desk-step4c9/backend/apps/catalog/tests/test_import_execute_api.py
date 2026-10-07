"""Atomic CSV execution and durable replay through real session/CSRF requests."""

from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.files.uploadedfile import SimpleUploadedFile, TemporaryUploadedFile
from django.db import DatabaseError, connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.imports import MAX_FILE_BYTES
from apps.catalog.models import CatalogImportReceipt, CatalogItem
from apps.catalog.tests.test_create_api import PUBLIC_FIELDS
from apps.catalog.tests.test_update_api import CatalogUpdateTestCase
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.selection import SELECTED_WORKSPACE_KEY

HEADER = b"sku,description,is_active\n"
VALID = HEADER + b"NEW,Original description,\n"
DENIED = "You do not have permission to import catalogue items in this workspace."


class CatalogImportExecuteAPITests(CatalogUpdateTestCase):
    def setUp(self):
        super().setUp()
        self.import_url = self.execution_url(self.a)
        self.key = uuid4()

    @staticmethod
    def execution_url(workspace):
        return reverse(
            "workspaces:catalog:import-execute", kwargs={"workspace_id": workspace.pk}
        )

    @staticmethod
    def upload(raw, name="../../untrusted.csv", mime="application/octet-stream"):
        return SimpleUploadedFile(name, raw, content_type=mime)

    def execute(
        self, raw=VALID, *, key=None, client=None, csrf=None, url=None, **headers
    ):
        return (client or self.client).post(
            url or self.import_url,
            {"file": self.upload(raw)},
            format="multipart",
            HTTP_X_CSRFTOKEN=csrf or self.csrf,
            HTTP_IDEMPOTENCY_KEY=str(self.key if key is None else key),
            **headers,
        )

    @staticmethod
    def database_state():
        return (
            list(CatalogItem.objects.order_by("id").values()),
            list(CatalogImportReceipt.objects.order_by("id").values()),
        )

    def test_success_exact_payload_normalization_defaults_and_completed_receipt(self):
        response = self.execute(
            HEADER + b' 000-New ," Description, with comma\nnew line ",\nOther,,false\n'
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response["Idempotency-Replayed"], "false")
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "import_id",
                "organization_id",
                "mode",
                "created_count",
                "items",
                "items_truncated",
            },
        )
        UUID(body["import_id"])
        self.assertEqual(body["organization_id"], str(self.a.pk))
        self.assertEqual(body["mode"], "create_only")
        self.assertEqual(body["created_count"], 2)
        self.assertFalse(body["items_truncated"])
        self.assertEqual([row["sku"] for row in body["items"]], ["000-New", "Other"])
        self.assertEqual(
            body["items"][0]["description"], " Description, with comma\nnew line "
        )
        self.assertTrue(body["items"][0]["is_active"])
        self.assertFalse(body["items"][1]["is_active"])
        for row in body["items"]:
            self.assertEqual(set(row), PUBLIC_FIELDS)
            self.assertEqual(row["organization_id"], str(self.a.pk))
            item = CatalogItem.objects.get(pk=row["id"])
            self.assertTrue(item.created_at)
            self.assertTrue(item.updated_at)
        receipt = CatalogImportReceipt.objects.get(pk=body["import_id"])
        self.assertEqual(receipt.initiating_user_id, self.admin.pk)
        self.assertEqual(receipt.state, CatalogImportReceipt.State.COMPLETED)
        self.assertEqual(receipt.response_payload, body)
        self.assertIsNotNone(receipt.completed_at)
        self.assertEqual(len(receipt.request_fingerprint), 64)
        self.assert_private(response)
        self.assert_clean()

    def test_preview_original_order_and_truncation_preserve_all_created_items(self):
        raw = HEADER + b"".join(f"P-{i:03},,\n".encode() for i in reversed(range(30)))
        response = self.execute(raw)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["created_count"], 30)
        self.assertEqual(len(body["items"]), 25)
        self.assertTrue(body["items_truncated"])
        self.assertEqual(body["items"][0]["sku"], "P-029")
        self.assertEqual(body["items"][-1]["sku"], "P-005")
        self.assertEqual(
            CatalogItem.objects.filter(
                organization=self.a, sku__startswith="P-"
            ).count(),
            30,
        )
        self.assertEqual(self.execute(raw).content, response.content)

    def test_replay_is_byte_identical_and_does_not_write_or_parse_again(self):
        first = self.execute()
        self.assertEqual(first.status_code, 201, first.content)
        before = self.database_state()
        with patch(
            "apps.catalog.import_execution.parse_catalogue_csv",
            side_effect=AssertionError("Replay parsed"),
        ):
            replay = self.execute()
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay["Idempotency-Replayed"], "true")
        self.assertEqual(replay.content, first.content)
        self.assertEqual(self.database_state(), before)
        self.assert_private(replay)
        self.assert_clean()

    def test_peer_admin_replay_after_item_update_preserves_original_initiator(self):
        first = self.execute()
        item = first.json()["items"][0]
        changed = self.update(
            {"description": "Changed after import", "is_active": False},
            url=self.item_url(self.a, item["id"]),
        )
        self.assertEqual(changed.status_code, 200)
        peer, csrf = self.login_client(self.peer_admin)
        before = self.database_state()
        replay = self.execute(client=peer, csrf=csrf)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.content, first.content)
        self.assertEqual(self.database_state(), before)
        self.assertEqual(
            CatalogImportReceipt.objects.get().initiating_user_id, self.admin.pk
        )

    def test_filename_mime_and_normalized_uuid_spelling_do_not_change_request(self):
        first = self.execute()
        for spelling in (
            str(self.key).upper(),
            "{" + str(self.key) + "}",
            self.key.hex,
        ):
            replay = self.client.post(
                self.import_url,
                {"file": self.upload(VALID, name="another.pdf", mime="text/plain")},
                format="multipart",
                HTTP_X_CSRFTOKEN=self.csrf,
                HTTP_IDEMPOTENCY_KEY=spelling,
            )
            self.assertEqual(replay.status_code, 200, replay.content)
            self.assertEqual(replay.content, first.content)

    def test_changed_raw_bytes_conflict_and_preserve_original_receipt(self):
        first = self.execute()
        self.assertEqual(first.status_code, 201)
        before = self.database_state()
        for raw in (
            VALID.replace(b"\n", b"\r\n"),
            b"\xef\xbb\xbf" + VALID,
            HEADER + b"OTHER,,\n",
        ):
            conflict = self.execute(raw)
            self.assertEqual(conflict.status_code, 409, conflict.content)
            self.assertEqual(set(conflict.json()), {"detail"})
            self.assertEqual(self.database_state(), before)
            self.assert_clean()

    def test_workspace_local_keys_and_skus_are_independent(self):
        first = self.execute()
        second = self.execute(url=self.execution_url(self.b))
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertNotEqual(first.json()["import_id"], second.json()["import_id"])
        self.assertEqual(second.json()["organization_id"], str(self.b.pk))
        self.assertEqual(
            CatalogImportReceipt.objects.filter(idempotency_key=self.key).count(), 2
        )
        self.assertEqual(CatalogItem.objects.filter(sku="NEW").count(), 2)

    def test_missing_malformed_keys_are_400_and_leave_no_reservation(self):
        before = self.database_state()
        for key in (
            None,
            "",
            "not-a-uuid",
            "1",
            "00000000-0000-0000-0000-00000000000Z",
        ):
            headers = {} if key is None else {"HTTP_IDEMPOTENCY_KEY": key}
            response = self.client.post(
                self.import_url,
                {"file": self.upload(VALID)},
                format="multipart",
                HTTP_X_CSRFTOKEN=self.csrf,
                **headers,
            )
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(self.database_state(), before)
            self.assert_clean()

    def test_nonadministrator_denial_precedes_key_bytes_parser_and_receipts(self):
        for actor in (self.viewer, self.reviewer):
            client, csrf = self.login_client(actor)
            with patch(
                "apps.catalog.import_execution.parse_catalogue_csv",
                side_effect=AssertionError("CSV parsed"),
            ):
                response = self.execute(b"bad", key="bad-key", client=client, csrf=csrf)
            self.assertEqual(response.status_code, 403, response.content)
            self.assertEqual(response.json(), {"detail": DENIED})
        self.assertFalse(CatalogImportReceipt.objects.exists())

    def test_replay_requires_current_admin_and_denies_demoted_role(self):
        first = self.execute()
        self.assertEqual(first.status_code, 201)
        before = self.database_state()
        Membership.objects.filter(pk=self.admin_membership.pk).update(
            role=MembershipRole.VIEWER
        )
        denied = self.execute()
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json(), {"detail": DENIED})
        self.assertEqual(self.database_state(), before)
        self.assert_clean()

    def test_first_and_replay_require_active_user_membership_and_workspace(self):
        self.assertEqual(self.execute().status_code, 201)
        before = self.database_state()
        for model, pk in (
            (type(self.admin), self.admin.pk),
            (Membership, self.admin_membership.pk),
            (Organization, self.a.pk),
        ):
            model.objects.filter(pk=pk).update(is_active=False)
            self.assertEqual(self.execute().status_code, 403)
            self.assertEqual(self.execute(key=uuid4()).status_code, 403)
            model.objects.filter(pk=pk).update(is_active=True)
            self.assertEqual(self.database_state(), before)
            self.assert_clean()

    def test_anonymous_expired_operator_missing_and_inaccessible_workspaces(self):
        anonymous = APIClient(enforce_csrf_checks=True)
        self.assertEqual(self.execute(client=anonymous).status_code, 403)
        operator, csrf = self.login_client(self.outsider)
        self.assertEqual(self.execute(client=operator, csrf=csrf).status_code, 403)
        self.assertEqual(
            self.execute(
                url=self.import_url.replace(str(self.a.pk), str(uuid4()))
            ).status_code,
            403,
        )
        peer, peer_csrf = self.login_client(self.peer_admin)
        self.assertEqual(
            self.execute(
                client=peer, csrf=peer_csrf, url=self.execution_url(self.b)
            ).status_code,
            403,
        )
        Session.objects.filter(
            session_key=self.client.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.execute().status_code, 403)
        self.assertFalse(CatalogImportReceipt.objects.exists())
        self.assert_clean()

    def test_csrf_is_required_for_first_execution_and_replay(self):
        for completed in (False, True):
            if completed:
                self.assertEqual(self.execute().status_code, 201)
            before = self.database_state()
            for token in (None, "invalid"):
                headers = {} if token is None else {"HTTP_X_CSRFTOKEN": token}
                response = self.client.post(
                    self.import_url,
                    {"file": self.upload(VALID)},
                    format="multipart",
                    HTTP_IDEMPOTENCY_KEY=str(self.key),
                    **headers,
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.database_state(), before)

    def test_multipart_shape_query_fields_and_media_reject_without_writes(self):
        before = self.database_state()
        for data in (
            {},
            {"file": "not a file"},
            {"wrong": self.upload(VALID)},
            {"file": [self.upload(VALID), self.upload(VALID)]},
            {"file": self.upload(VALID), "organization_id": str(self.b.pk)},
            {"file": self.upload(VALID), "initiating_user_id": str(self.peer_admin.pk)},
            {"file": self.upload(VALID), "can_import": "true"},
            {"file": self.upload(VALID), "mode": "upsert"},
        ):
            response = self.client.post(
                self.import_url,
                data,
                format="multipart",
                HTTP_X_CSRFTOKEN=self.csrf,
                HTTP_IDEMPOTENCY_KEY=str(self.key),
            )
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(self.database_state(), before)
        for query in ("organization_id=x", "mode=create_only", "page=1"):
            self.assertEqual(
                self.execute(url=self.import_url + "?" + query).status_code, 400
            )
        response = self.client.post(
            self.import_url,
            {"file": "data"},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IDEMPOTENCY_KEY=str(self.key),
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.database_state(), before)
        self.assert_clean()

    def test_structure_and_invalid_rows_rollback_and_allow_corrected_same_key(self):
        before = self.database_state()
        for raw in (
            b"",
            HEADER,
            b"SKU,description,is_active\nX,,\n",
            HEADER + b"X,too,many,columns\n",
            HEADER + b'X,"unterminated,\n',
            HEADER + b"X,\xff,\n",
            HEADER + b"X,,TRUE\n",
            HEADER + b"VALID,,\n,,\n",
        ):
            response = self.execute(raw)
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(self.database_state(), before)
            self.assert_clean()
        self.assertEqual(self.execute().status_code, 201)

    def test_file_duplicates_invalidate_every_occurrence_and_rollback_valid_rows(self):
        before = self.database_state()
        response = self.execute(HEADER + b"VALID,,\nDUP,,true\n DUP ,,false\n")
        self.assertEqual(response.status_code, 400, response.content)
        report = response.json()["report"]
        self.assertEqual(
            report["summary"], {"rows_total": 3, "rows_ready": 1, "rows_invalid": 2}
        )
        self.assertEqual(
            {
                e["row_number"]
                for e in report["errors"]
                if e["code"] == "duplicate_file_sku"
            },
            {3, 4},
        )
        self.assertEqual(self.database_state(), before)

    def test_existing_active_inactive_conflicts_and_other_tenant_eligibility(self):
        CatalogItem.objects.create(organization=self.a, sku="ARCH", is_active=False)
        CatalogItem.objects.create(organization=self.b, sku="ONLY-B")
        before = self.database_state()
        for sku in (self.item.sku, "ARCH"):
            response = self.execute(HEADER + f"VALID,,\n{sku},,\n".encode())
            self.assertEqual(response.status_code, 409, response.content)
            self.assertEqual(self.database_state(), before)
        self.assertEqual(self.execute(HEADER + b"ONLY-B,,\n").status_code, 201)

    def test_error_report_is_bounded_but_invalid_rows_beyond_preview_prevent_commit(
        self,
    ):
        raw = (
            HEADER
            + b"".join(f"VALID-{i},,\n".encode() for i in range(30))
            + b"DUP,,\n" * 120
        )
        before = self.database_state()
        response = self.execute(raw)
        self.assertEqual(response.status_code, 400, response.content)
        report = response.json()["report"]
        self.assertEqual(
            report["summary"],
            {"rows_total": 150, "rows_ready": 30, "rows_invalid": 120},
        )
        self.assertEqual(len(report["errors"]), 100)
        self.assertTrue(report["errors_truncated"])
        self.assertEqual(self.database_state(), before)

    def test_record_limit_accepts_1000_and_rejects_1001_without_consuming_key(self):
        raw = HEADER + b"".join(f"BOUND-{i},,\n".encode() for i in range(1000))
        before = self.database_state()
        self.assertEqual(self.execute(raw + b"EXTRA,,\n").status_code, 400)
        self.assertEqual(self.database_state(), before)
        result = self.execute(raw)
        self.assertEqual(result.status_code, 201, result.content)
        self.assertEqual(result.json()["created_count"], 1000)
        self.assertEqual(
            CatalogItem.objects.filter(
                organization=self.a, sku__startswith="BOUND-"
            ).count(),
            1000,
        )

    def test_actual_byte_limit_closes_spooled_upload_and_leaves_no_receipt(self):
        created = []
        original = TemporaryUploadedFile.__init__

        def track(instance, *args, **kwargs):
            original(instance, *args, **kwargs)
            created.append(instance)

        before = self.database_state()
        with (
            override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1),
            patch.object(TemporaryUploadedFile, "__init__", track),
        ):
            response = self.execute(b"x" * (MAX_FILE_BYTES + 1))
        self.assertEqual(response.status_code, 413, response.content)
        self.assertTrue(created)
        self.assertTrue(all(upload.closed for upload in created))
        self.assertEqual(self.database_state(), before)
        self.assert_clean()

    def test_bom_multiline_unicode_literal_formula_and_case_are_preserved(self):
        raw = (
            '\ufeffdescription,is_active,sku\r\n"é\r\n東京",false,000-Part\r\n"=SUM(A1)",,part\r\n"@cmd",true,Part\r\n'
        ).encode()
        response = self.execute(raw)
        self.assertEqual(response.status_code, 201, response.content)
        items = response.json()["items"]
        self.assertEqual([item["sku"] for item in items], ["000-Part", "part", "Part"])
        self.assertEqual(
            [item["description"] for item in items], ["é\r\n東京", "=SUM(A1)", "@cmd"]
        )

    def test_url_identity_ignores_session_selection_and_forged_identity_headers(self):
        session = self.client.session
        session[SELECTED_WORKSPACE_KEY] = str(self.b.pk)
        session.save()
        response = self.execute(
            HTTP_X_ORGANIZATION_ID=str(self.b.pk),
            HTTP_X_USER_ID=str(self.peer_admin.pk),
        )
        self.assertEqual(response.status_code, 201, response.content)
        receipt = CatalogImportReceipt.objects.get()
        self.assertEqual(receipt.organization_id, self.a.pk)
        self.assertEqual(receipt.initiating_user_id, self.admin.pk)
        self.assertFalse(
            CatalogItem.objects.filter(organization=self.b, sku="NEW").exists()
        )

    def test_database_failure_after_first_insert_rolls_back_receipt_and_items(self):
        original = CatalogItem.save
        calls = 0

        def fail_second(item, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise DatabaseError("Synthetic unexpected database failure")
            return original(item, *args, **kwargs)

        before = self.database_state()
        raw = HEADER + b"A,,\nB,,\n"
        with (
            patch.object(CatalogItem, "save", fail_second),
            self.assertRaises(DatabaseError),
        ):
            self.execute(raw)
        self.assertEqual(calls, 2)
        self.assertEqual(self.database_state(), before)
        self.assert_clean()
        self.assertEqual(self.execute(raw).status_code, 201)

    def test_response_materializes_inside_write_scope_and_render_needs_no_sql(self):
        touched = []

        def observe(execute, sql, params, many, context):
            if "catalog_catalogitem" in sql or "catalog_catalogimportreceipt" in sql:
                self.assertTrue(connection.in_atomic_block)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT current_setting('transaction_read_only'), "
                        "current_setting('orderdesk.organization_id'), "
                        "current_setting('orderdesk.user_id')"
                    )
                    self.assertEqual(
                        cursor.fetchone(), ("off", str(self.a.pk), str(self.admin.pk))
                    )
                touched.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(observe):
            response = self.execute()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(touched)
        with patch.object(connection, "cursor", side_effect=AssertionError("Late SQL")):
            response.render()
        self.assert_clean()

    def test_methods_options_and_existing_dry_run_create_update_search_remain(self):
        self.assertEqual(
            set(self.client.options(self.import_url)["Allow"].split(", ")),
            {"POST", "OPTIONS"},
        )
        for method in ("get", "head", "put", "patch", "delete"):
            self.assertEqual(
                getattr(self.client, method)(
                    self.import_url, HTTP_X_CSRFTOKEN=self.csrf
                ).status_code,
                405,
            )
        dry_url = reverse(
            "workspaces:catalog:import-dry-run", kwargs={"workspace_id": self.a.pk}
        )
        dry = self.client.post(
            dry_url,
            {"file": self.upload(VALID)},
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(dry.status_code, 200)
        self.assertFalse(CatalogImportReceipt.objects.exists())
        self.assertEqual(self.post({"sku": "STILL-CREATES"}).status_code, 201)
        self.assertEqual(self.update({"is_active": False}).status_code, 200)
        self.assertEqual(
            self.client.get(self.url, {"q": self.item.sku}).status_code, 200
        )
