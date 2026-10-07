"""Native PostgreSQL multipart/CSRF dry runs without catalogue mutations."""

import io
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.files.uploadedfile import SimpleUploadedFile, TemporaryUploadedFile
from django.db import DatabaseError, connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.import_services import CATALOG_IMPORT_DRY_RUN_DENIED
from apps.catalog.imports import MAX_FILE_BYTES, ParsedImport
from apps.catalog.models import CatalogItem
from apps.catalog.tests.test_update_api import CatalogUpdateTestCase
from apps.catalog.uploads import CatalogUploadLimitHandler, catalogue_upload_bytes
from apps.organizations.models import Membership, Organization
from apps.organizations.selection import SELECTED_WORKSPACE_KEY

HEADER = b"sku,description,is_active\n"


class CatalogImportDryRunAPITests(CatalogUpdateTestCase):
    def setUp(self):
        super().setUp()
        self.dry_url = reverse(
            "workspaces:catalog:import-dry-run", kwargs={"workspace_id": self.a.pk}
        )

    @staticmethod
    def upload(raw):
        return SimpleUploadedFile("../../untrusted.pdf", raw, content_type="text/plain")

    def dry(
        self, raw=HEADER + b"NEW,Description,\n", *, client=None, url=None, **extra
    ):
        return (client or self.client).post(
            url or self.dry_url,
            {"file": self.upload(raw)},
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf,
            **extra,
        )

    @staticmethod
    def catalogue_state():
        return list(CatalogItem.objects.order_by("id").values())

    def test_valid_admin_normalization_defaults_description_and_exact_response(self):
        before = self.catalogue_state()
        response = self.dry(
            HEADER + b' 000-New ," Description, with comma\nnew line ",\n'
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "dry_run",
                "mode",
                "can_import",
                "summary",
                "errors",
                "errors_truncated",
                "preview",
                "preview_truncated",
            },
        )
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["mode"], "create_only")
        self.assertTrue(body["can_import"])
        self.assertEqual(
            body["summary"], {"rows_total": 1, "rows_ready": 1, "rows_invalid": 0}
        )
        self.assertEqual(
            body["preview"],
            [
                {
                    "row_number": 2,
                    "sku": "000-New",
                    "description": " Description, with comma\nnew line ",
                    "is_active": True,
                }
            ],
        )
        self.assertEqual(self.catalogue_state(), before)
        self.assert_private(response)
        self.assert_clean()

    def test_existing_active_inactive_duplicate_and_other_tenant_semantics(self):
        CatalogItem.objects.create(organization=self.a, sku="ARCH", is_active=False)
        CatalogItem.objects.create(organization=self.b, sku="ONLY-B")
        before = self.catalogue_state()
        raw = (
            HEADER
            + (
                self.item.sku
                + ",,true\nARCH,,false\nONLY-B,,\nDUP,,true\n DUP ,,false\n"
                "dup,,true\n,,TRUE\n"
            ).encode()
        )
        response = self.dry(raw)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["summary"], {"rows_total": 7, "rows_ready": 2, "rows_invalid": 5}
        )
        self.assertFalse(body["can_import"])
        self.assertEqual({row["sku"] for row in body["preview"]}, {"ONLY-B", "dup"})
        duplicate_rows = {
            e["row_number"] for e in body["errors"] if e["code"] == "duplicate_file_sku"
        }
        self.assertEqual(duplicate_rows, {5, 6})
        self.assertEqual(self.catalogue_state(), before)
        self.assert_clean()

    def test_entire_file_summary_and_bounded_output(self):
        raw = (
            HEADER
            + b"DUP,,\n" * 120
            + b"".join(f"READY-{i},,\n".encode() for i in range(30))
        )
        body = self.dry(raw).json()
        self.assertEqual(
            body["summary"], {"rows_total": 150, "rows_ready": 30, "rows_invalid": 120}
        )
        self.assertEqual(len(body["errors"]), 100)
        self.assertTrue(body["errors_truncated"])
        self.assertEqual(len(body["preview"]), 25)
        self.assertTrue(body["preview_truncated"])
        self.assertFalse(body["can_import"])

    def test_structure_encoding_headers_empty_and_record_limits_reject_whole_file(self):
        before = self.catalogue_state()
        for raw in (
            b"",
            HEADER,
            HEADER + b"\n",
            b"SKU,description,is_active\nX,,\n",
            b"sku,sku,is_active\nX,,\n",
            HEADER + b"X,too,few,columns\n",
            HEADER + b'X,"unterminated,\n',
            HEADER + b"X,\xff,\n",
            HEADER + b"X,,\n" * 1001,
        ):
            with self.subTest(raw=raw[:40]):
                self.assertEqual(self.dry(raw).status_code, 400)
                self.assertEqual(self.catalogue_state(), before)
                self.assert_clean()

    def test_bom_header_order_crlf_and_logical_multiline_record_numbers(self):
        raw = (
            '\ufeffdescription,is_active,sku\r\n"é\r\n東京",false,NEW\r\n'
            "\r\n,TRUE,BAD\r\n"
        ).encode()
        body = self.dry(raw).json()
        self.assertEqual(
            body["summary"], {"rows_total": 2, "rows_ready": 1, "rows_invalid": 1}
        )
        self.assertEqual(body["preview"][0]["description"], "é\r\n東京")
        self.assertFalse(body["preview"][0]["is_active"])
        self.assertEqual(body["errors"][0]["row_number"], 4)

    def test_upload_shape_and_query_allowlist(self):
        for data in (
            {},
            {"file": "ordinary form value"},
            {"wrong": self.upload(HEADER)},
            {"file": [self.upload(HEADER), self.upload(HEADER)]},
            {"file": self.upload(HEADER), "organization_id": str(self.b.pk)},
            {"file": self.upload(HEADER), "mode": "upsert"},
        ):
            with self.subTest(fields=list(data)):
                response = self.client.post(
                    self.dry_url, data, format="multipart", HTTP_X_CSRFTOKEN=self.csrf
                )
                self.assertEqual(response.status_code, 400)
                self.assert_clean()
        for query in ("page=1", "file=x", "organization_id=x", "mode=create_only"):
            self.assertEqual(self.dry(url=self.dry_url + "?" + query).status_code, 400)

    def test_nonmultipart_media_is_rejected_after_authorization(self):
        response = self.client.post(
            self.dry_url, {"file": "data"}, format="json", HTTP_X_CSRFTOKEN=self.csrf
        )
        self.assertEqual(response.status_code, 415)

    def test_upload_size_guard_is_installed_before_csrf_and_closes_temporary_files(
        self,
    ):
        created = []
        original = TemporaryUploadedFile.__init__

        def track(instance, *args, **kwargs):
            original(instance, *args, **kwargs)
            created.append(instance)

        with (
            override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1),
            patch.object(TemporaryUploadedFile, "__init__", track),
        ):
            response = self.dry(b"x" * (MAX_FILE_BYTES + 1))
        self.assertEqual(response.status_code, 413, response.content)
        self.assertTrue(created)
        self.assertTrue(all(file.closed for file in created))
        self.assert_clean()

    def test_chunk_guard_uses_actual_bytes_without_trusting_length_metadata(self):
        request = type("UploadRequest", (), {})()
        handler = CatalogUploadLimitHandler(request)
        file = io.BytesIO()
        other = type("UploadHandler", (), {"file": file})()
        request.upload_handlers = [handler, other]
        handler.new_file("file", "fake.csv", "text/csv", 1)
        handler.receive_data_chunk(b"x" * MAX_FILE_BYTES, 0)
        from apps.catalog.imports import ImportUploadTooLarge

        with self.assertRaises(ImportUploadTooLarge):
            handler.receive_data_chunk(b"x", MAX_FILE_BYTES)
        self.assertTrue(file.closed)

    def test_bounded_final_read_does_not_trust_uploaded_size(self):
        from django.http import QueryDict
        from django.utils.datastructures import MultiValueDict

        upload = self.upload(b"x" * (MAX_FILE_BYTES + 1))
        upload.size = 1
        data = MultiValueDict({"file": [upload]})
        request = type(
            "ParsedRequest",
            (),
            {"query_params": QueryDict(), "data": data, "FILES": data},
        )()
        from apps.catalog.imports import ImportUploadTooLarge

        with self.assertRaises(ImportUploadTooLarge):
            catalogue_upload_bytes(request)
        self.assertEqual(upload.tell(), MAX_FILE_BYTES + 1)
        upload.close()

    def test_normal_temporary_upload_cleanup_after_structural_failure(self):
        created = []
        original = TemporaryUploadedFile.__init__

        def track(instance, *args, **kwargs):
            original(instance, *args, **kwargs)
            created.append(instance)

        with (
            override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1),
            patch.object(TemporaryUploadedFile, "__init__", track),
        ):
            self.assertEqual(self.dry(b"bad\n").status_code, 400)
        self.assertTrue(created)
        self.assertTrue(all(file.closed for file in created))

    def test_role_denial_precedes_csv_validation_and_conflict_queries(self):
        for actor in (self.viewer, self.reviewer):
            client, csrf = self.login_client(actor)
            with patch(
                "apps.catalog.import_services.parse_catalogue_csv",
                side_effect=AssertionError("CSV parsed"),
            ):
                response = client.post(
                    self.dry_url,
                    {"file": self.upload(b"malformed")},
                    format="multipart",
                    HTTP_X_CSRFTOKEN=csrf,
                )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": CATALOG_IMPORT_DRY_RUN_DENIED})
            self.assert_clean()

    def test_anonymous_expired_inactive_accounts_memberships_workspaces_and_operator(
        self,
    ):
        anonymous = APIClient(enforce_csrf_checks=True)
        self.assertEqual(self.dry(client=anonymous).status_code, 403)
        operator, csrf = self.login_client(self.outsider)
        self.assertEqual(
            operator.post(
                self.dry_url,
                {"file": self.upload(b"bad")},
                format="multipart",
                HTTP_X_CSRFTOKEN=csrf,
            ).status_code,
            403,
        )
        for model, pk in (
            (type(self.admin), self.admin.pk),
            (Membership, self.admin_membership.pk),
            (Organization, self.a.pk),
        ):
            model.objects.filter(pk=pk).update(is_active=False)
            self.assertEqual(self.dry().status_code, 403)
            model.objects.filter(pk=pk).update(is_active=True)
        self.assertEqual(
            self.dry(
                url=self.dry_url.replace(str(self.a.pk), str(uuid4()))
            ).status_code,
            403,
        )
        Session.objects.filter(
            session_key=self.client.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.dry().status_code, 403)
        self.assert_clean()

    def test_csrf_is_standard_and_required(self):
        for token in (None, "invalid"):
            headers = {} if token is None else {"HTTP_X_CSRFTOKEN": token}
            response = self.client.post(
                self.dry_url,
                {"file": self.upload(HEADER + b"X,,\n")},
                format="multipart",
                **headers,
            )
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.dry().status_code, 200)

    def test_url_identity_ignores_session_preference_and_forged_headers(self):
        session = self.client.session
        session[SELECTED_WORKSPACE_KEY] = str(self.b.pk)
        session.save()
        response = self.dry(
            HEADER + (self.item.sku + ",,\n").encode(),
            HTTP_X_ORGANIZATION_ID=str(self.b.pk),
            HTTP_X_USER_ID=str(self.outsider.pk),
        )
        self.assertEqual(response.json()["summary"]["rows_invalid"], 1)

    def test_conflict_queries_are_batched_read_only_and_report_is_materialized(self):
        catalogue_queries = []

        def observe(execute, sql, params, many, context):
            if "catalog_catalogitem" in sql:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT current_setting('transaction_read_only'), "
                        "current_setting('orderdesk.organization_id')"
                    )
                    self.assertEqual(cursor.fetchone(), ("on", str(self.a.pk)))
                self.assertIn("SELECT", sql)
                catalogue_queries.append(sql)
            return execute(sql, params, many, context)

        original = ParsedImport.report

        def report(parsed, existing):
            self.assertTrue(connection.in_atomic_block)
            with self.assertNumQueries(0):
                return original(parsed, existing)

        raw = HEADER + b"".join(f"NEW-{i},,\n".encode() for i in range(1000))
        with (
            connection.execute_wrapper(observe),
            patch.object(ParsedImport, "report", report),
        ):
            response = self.dry(raw)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(catalogue_queries), 4)
        self.assertEqual(response.json()["summary"]["rows_ready"], 1000)
        with patch.object(connection, "cursor", side_effect=AssertionError("Late SQL")):
            response.render()
        self.assert_clean()

    def test_database_and_report_failures_cleanup_and_preserve_catalogue(self):
        before = self.catalogue_state()
        for target, error in (
            (
                "apps.catalog.import_services.selectors.existing_catalog_skus",
                DatabaseError("Synthetic database failure"),
            ),
            (
                "apps.catalog.imports.ParsedImport.report",
                ValueError("Synthetic report failure"),
            ),
        ):
            with patch(target, side_effect=error), self.assertRaises(type(error)):
                self.dry()
            self.assert_clean()
            self.assertEqual(self.catalogue_state(), before)
        self.assertEqual(self.dry().status_code, 200)

    def test_demoted_during_pure_parse_is_rechecked_before_catalogue_lookup(self):
        from apps.catalog.imports import parse_catalogue_csv

        def demote(raw):
            result = parse_catalogue_csv(raw)
            # Outside connection: read scope forbids changing membership here.
            from django.db import connections

            other = connection.copy(alias="dry_run_demotion")
            connections["dry_run_demotion"] = other
            try:
                Membership.objects.using("dry_run_demotion").filter(
                    pk=self.admin_membership.pk
                ).update(role="viewer")
            finally:
                other.close()
                del connections["dry_run_demotion"]
            return result

        with patch("apps.catalog.import_services.parse_catalogue_csv", demote):
            response = self.dry()
        self.assertEqual(response.status_code, 403)
        self.assert_clean()

    def test_methods_options_and_existing_endpoints_are_preserved(self):
        self.assertEqual(
            set(self.client.options(self.dry_url)["Allow"].split(", ")),
            {"POST", "OPTIONS"},
        )
        for method in ("get", "head", "put", "patch", "delete"):
            response = getattr(self.client, method)(
                self.dry_url, HTTP_X_CSRFTOKEN=self.csrf
            )
            self.assertEqual(response.status_code, 405)
        self.assertEqual(self.post({"sku": "STILL-CREATES"}).status_code, 201)
        self.assertEqual(self.update({"is_active": False}).status_code, 200)
        self.assertEqual(
            self.client.get(self.url, {"q": self.item.sku}).status_code, 200
        )
