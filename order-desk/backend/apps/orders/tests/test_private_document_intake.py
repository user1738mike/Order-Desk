"""Actual installed multipart guards, private bytes, leases and scoped downloads."""

import io
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.document_intake import create_private_document
from apps.orders.models import OrderDocument
from apps.orders.private_documents import open_document, staged_document
from apps.orders.services import create_purchase_order
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization

PDF = b"%PDF-1.7\nSynthetic local source\n%%EOF\n"
CSV = b"sku,quantity\r\n0001.Mixed-Case,1.234\r\n"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PrivateDocumentIntakeTests(TransactionTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(PRIVATE_DOCUMENT_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = User.objects.create_user(email="private-intake@example.test")
        self.organization = create_organization(actor=self.user, name="Private Intake")
        self.order = create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Synthetic",
            purchase_order_number="PRIVATE-1",
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.csrf = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.base = (
            f"/api/v1/workspaces/{self.organization.pk}/orders/"
            f"{self.order.pk}/documents/"
        )
        self.url = self.base + "intake/"

    def upload(self, raw=PDF, name="source.pdf", **headers):
        return self.client.post(
            self.url,
            {
                "file": SimpleUploadedFile(
                    name, raw, content_type="application/octet-stream"
                )
            },
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf,
            **headers,
        )

    def files(self):
        return list(Path(self.directory.name).iterdir())

    def service(self, **kwargs):
        return create_private_document(
            actor=self.user,
            organization_id=self.organization.pk,
            order_id=self.order.pk,
            upload=SimpleUploadedFile("source.pdf", PDF),
            materialize=kwargs.get("materialize", lambda document: document.pk),
        )

    def test_pdf_and_csv_upload_status_and_exact_attachment_bytes(self):
        for raw, name, mime in (
            (PDF, 'untrusted"name.pdf', "application/pdf"),
            (CSV, "source.csv", "text/csv"),
        ):
            with self.subTest(name=name):
                Membership.objects.filter(user=self.user).update(
                    role=MembershipRole.ADMIN
                    if name.endswith(".pdf")
                    else MembershipRole.REVIEWER
                )
                response = self.upload(raw, name)
                self.assertEqual(response.status_code, 201, response.content)
                body = response.json()
                self.assertEqual(body["status"], "received")
                self.assertEqual(body["content_type"], mime)
                self.assertEqual(body["size_bytes"], len(raw))
                self.assertNotIn("file", body)
                download = self.client.get(body["download_url"])
                self.assertEqual(download.status_code, 200)
                self.assertFalse(connection.in_atomic_block)
                self.assertEqual(b"".join(download.streaming_content), raw)
                download.close()
                self.assertTrue(
                    download["Content-Disposition"].startswith("attachment;")
                )
                self.assertEqual(download["X-Content-Type-Options"], "nosniff")
                self.assertIn("no-store", download["Cache-Control"])
                self.assertEqual(download["Content-Type"], mime)
        self.assertEqual(self.client.get(self.url).json()["count"], 2)
        for path in self.files():
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)

    def test_existing_filefield_reads_private_bytes_without_a_public_url(self):
        self.upload()
        document = OrderDocument.objects.get()
        with document.file.open("rb") as source:
            self.assertEqual(source.read(), PDF)
        with self.assertRaises(SuspiciousFileOperation):
            _ = document.file.url
        with self.assertRaises(SuspiciousFileOperation):
            document.file.storage.save(
                document.file.name, SimpleUploadedFile("source.pdf", PDF)
            )

    def test_exclusive_collision_does_not_overwrite_or_unlink_active_source(self):
        with patch(
            "apps.orders.private_documents.uuid4",
            return_value=SimpleNamespace(hex="a" * 32),
        ):
            with staged_document(SimpleUploadedFile("source.pdf", PDF)):
                with self.assertRaises(FileExistsError):
                    with staged_document(SimpleUploadedFile("other.pdf", PDF)):
                        self.fail("Collision must not be accepted.")
                self.assertEqual(self.files()[0].read_bytes(), PDF)
        self.assertEqual(self.files(), [])

    def test_public_root_and_database_commit_failure_have_safe_http_errors(self):
        from django.conf import settings

        with override_settings(
            PRIVATE_DOCUMENT_ROOT=str(Path(settings.STATIC_ROOT) / "private")
        ):
            self.assertEqual(self.upload().status_code, 503)
        original = connection._commit
        calls = 0

        def commit():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise IntegrityError("synthetic")
            return original()

        with patch.object(connection, "_commit", side_effect=commit):
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertIn("could not be confirmed", response.json()["detail"])
        self.assertEqual(len(self.files()), 1)

    @override_settings(DEBUG=True)
    def test_orphan_recovery_bounds_deletions_and_preserves_unrelated_names(self):
        old = time.time() - 172800
        for index in range(105):
            path = Path(self.directory.name) / f"{index:032x}"
            path.write_bytes(b"orphan")
            os.utime(path, (old, old))
        unrelated = Path(self.directory.name) / "unrelated.txt"
        unrelated.write_bytes(b"keep")
        call_command("reconcile_private_documents", verbosity=0)
        self.assertEqual(len(self.files()), 6)
        self.assertEqual(unrelated.read_bytes(), b"keep")

    def test_invalid_empty_type_mismatch_and_bounded_csv_do_not_write(self):
        for raw, name in (
            (b"", "empty.pdf"),
            (b"%PDF-1.7\nno end", "bad.pdf"),
            (CSV, "bad.pdf"),
            (PDF, "bad.csv"),
            (b"<html>x</html>", "bad.html"),
            (b"a,b\n\xff,1", "bad.csv"),
            (b"a,b\n\x00,1", "bad.csv"),
            (b"a,b\n" + b"x" * 4097 + b",1", "bad.csv"),
            (b"a,b\n1,2,3", "bad.csv"),
        ):
            with self.subTest(name=name, length=len(raw)):
                with patch.object(OrderDocument, "save") as save:
                    response = self.upload(raw, name)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("file", response.json())
                save.assert_not_called()
                self.assertEqual(self.files(), [])

    def test_installed_upload_handler_enforces_actual_boundary(self):
        with (
            patch("apps.orders.uploads.MAX_ORDER_DOCUMENT_BYTES", len(PDF)),
            patch("apps.orders.private_documents.MAX_ORDER_DOCUMENT_BYTES", len(PDF)),
        ):
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload(PDF + b" ").status_code, 413)
        self.assertEqual(OrderDocument.objects.count(), 1)

    def test_direct_stream_ignores_forged_size_and_does_not_hold_transaction(self):
        upload = SimpleUploadedFile("source.pdf", PDF)
        upload.size = 1
        case = self

        class CheckedStream(io.BytesIO):
            def read(self, length):
                case.assertFalse(connection.in_atomic_block)
                return super().read(length)

        upload.file = CheckedStream(PDF)
        with staged_document(upload) as staged:
            self.assertEqual(staged["size"], len(PDF))
        self.assertEqual(self.files(), [])

    def test_materialization_and_metadata_failure_cleanup(self):
        with (
            patch.object(
                OrderDocument, "save", side_effect=IntegrityError("synthetic")
            ),
            self.assertRaises(IntegrityError),
        ):
            self.service()
        self.assertEqual(self.files(), [])

        def fail(document):
            raise ValidationError("synthetic")

        with self.assertRaises(ValidationError):
            self.service(materialize=fail)
        self.assertEqual(self.files(), [])
        self.assertEqual(OrderDocument.objects.count(), 0)

    def test_commit_acknowledgement_failure_retains_bytes_for_recovery(self):
        original = connection._commit
        calls = 0

        def commit():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise IntegrityError("synthetic")
            return original()

        with (
            patch.object(connection, "_commit", side_effect=commit),
            self.assertRaises(IntegrityError),
        ):
            self.service()
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(OrderDocument.objects.count(), 0)
        self.assertFalse(connection.in_atomic_block)

    def test_role_revocation_and_foreign_parent_are_denied(self):
        response = self.upload()
        url = response.json()["download_url"]
        membership = Membership.objects.get(
            user=self.user, organization=self.organization
        )
        membership.role = MembershipRole.VIEWER
        membership.save(update_fields=["role"])
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 200)
        membership.is_active = False
        membership.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.upload().status_code, 403)
        membership.is_active = True
        membership.save(update_fields=["is_active"])
        self.assertEqual(
            self.client.get(url.replace(str(self.order.pk), str(uuid4()))).status_code,
            404,
        )

    def test_same_size_source_corruption_is_not_downloaded(self):
        response = self.upload()
        path = self.files()[0]
        path.chmod(0o600)
        path.write_bytes(b"x" * len(PDF))
        path.chmod(0o400)
        self.assertEqual(
            self.client.get(response.json()["download_url"]).status_code, 503
        )

    def test_committed_metadata_survives_lost_commit_acknowledgement(self):
        original = connection._commit
        calls = 0

        def commit():
            nonlocal calls
            calls += 1
            result = original()
            if calls == 2:
                raise IntegrityError("synthetic acknowledgement loss")
            return result

        with patch.object(connection, "_commit", side_effect=commit):
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(OrderDocument.objects.count(), 1)
        self.assertEqual(self.files()[0].read_bytes(), PDF)
        self.assertFalse(connection.in_atomic_block)
        self.assertEqual(self.client.get(self.url).json()["count"], 1)

    def test_revocation_during_streaming_is_rechecked_at_finalization(self):
        original = staged_document
        from contextlib import contextmanager

        @contextmanager
        def revoke(upload):
            with original(upload) as staged:
                Membership.objects.filter(user=self.user).update(is_active=False)
                yield staged

        with patch("apps.orders.document_intake.staged_document", revoke):
            response = self.upload()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.files(), [])
        self.assertEqual(OrderDocument.objects.count(), 0)

    def test_missing_corrupt_traversal_and_symlink_storage_fail_safely(self):
        response = self.upload()
        body = response.json()
        path = self.files()[0]
        path.unlink()
        self.assertEqual(self.client.get(body["download_url"]).status_code, 503)
        for key in (
            "../outside",
            "/etc/passwd",
            "intake/../outside",
            "intake/" + "a" * 32 + "\\outside",
        ):
            with self.subTest(key=key), self.assertRaises(OSError):
                open_document(key, 10)
        with TemporaryDirectory() as outside:
            target = Path(outside) / "bytes"
            target.write_bytes(PDF)
            path.symlink_to(target)
            self.assertEqual(self.client.get(body["download_url"]).status_code, 503)
            self.assertEqual(target.read_bytes(), PDF)
        path.unlink()
        path.write_bytes(b"corrupt")
        path.chmod(0o400)
        self.assertEqual(self.client.get(body["download_url"]).status_code, 503)

    def test_root_symlink_and_bad_permissions_fail_closed(self):
        with TemporaryDirectory() as outer:
            link = Path(outer) / "root"
            link.symlink_to(self.directory.name, target_is_directory=True)
            with override_settings(PRIVATE_DOCUMENT_ROOT=str(link)):
                self.assertEqual(self.upload().status_code, 503)
        Path(self.directory.name).chmod(0o755)
        self.assertEqual(self.upload().status_code, 503)
        Path(self.directory.name).chmod(0o700)

    def test_csrf_unknown_fields_queries_and_unauthenticated_denied(self):
        response = self.client.post(
            self.url,
            {"file": SimpleUploadedFile("source.pdf", PDF)},
            format="multipart",
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            self.url,
            {"file": SimpleUploadedFile("source.pdf", PDF), "status": "received"},
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(self.url + "?page_size=1000").status_code, 400)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.files(), [])

    @override_settings(DEBUG=True)
    def test_orphan_reconciliation_preserves_metadata_recent_and_leased_files(self):
        self.upload()
        committed = self.files()[0]
        orphan = Path(self.directory.name) / uuid4().hex
        orphan.write_bytes(b"old orphan")
        recent = Path(self.directory.name) / uuid4().hex
        recent.write_bytes(b"recent")
        old = time.time() - 172800
        os.utime(committed, (old, old))
        os.utime(orphan, (old, old))
        with staged_document(SimpleUploadedFile("source.pdf", PDF)) as staged:
            leased = Path(self.directory.name) / staged["key"].split("/")[1]
            os.utime(leased, (old, old))
            call_command("reconcile_private_documents", verbosity=0)
            self.assertTrue(leased.exists())
        self.assertTrue(committed.exists())
        self.assertTrue(recent.exists())
        self.assertFalse(orphan.exists())
