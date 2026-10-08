import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, TemporaryUploadedFile
from django.db import IntegrityError, connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.document_files import OrderDocumentTooLarge
from apps.orders.models import OrderDocument
from apps.orders.services import create_order_document, create_purchase_order
from apps.orders.uploads import (
    MAX_ORDER_DOCUMENT_BYTES,
    OrderDocumentUploadLimitHandler,
    OrderDocumentUploadTooLarge,
)
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


class OrderDocumentUploadStorageTests(TransactionTestCase):
    def setUp(self) -> None:
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.storage = override_settings(MEDIA_ROOT=self.media.name)
        self.storage.enable()
        self.addCleanup(self.storage.disable)
        self.user = User.objects.create_user(email="document-storage@example.test")
        self.organization = create_organization(
            actor=self.user, name="Document Storage Distributor"
        )
        self.order = create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Storage Buyer",
            purchase_order_number="PO-STORAGE-1",
        )

    def _upload(self, content: bytes = b"document-bytes") -> SimpleUploadedFile:
        return SimpleUploadedFile(
            "purchase_order.pdf",
            content,
            content_type="application/pdf",
        )

    def test_successful_upload_is_persisted(self) -> None:
        document = create_order_document(
            actor=self.user,
            organization_id=self.organization.pk,
            order_id=self.order.pk,
            file=self._upload(),
            original_name="purchase_order.pdf",
            content_type="application/pdf",
            size_bytes=15,
        )

        document.refresh_from_db()
        self.assertEqual(document.size_bytes, 15)
        self.assertTrue(document.file.name.startswith("orders/source_documents/"))
        self.assertTrue(Path(self.media.name, document.file.name).is_file())

    def test_materialization_failure_removes_new_file(self) -> None:
        def fail_materialization(document):
            raise ValidationError({"file": "Materialization failed."})

        with self.assertRaises(ValidationError):
            create_order_document(
                actor=self.user,
                organization_id=self.organization.pk,
                order_id=self.order.pk,
                file=self._upload(),
                original_name="purchase_order.pdf",
                content_type="application/pdf",
                size_bytes=15,
                materialize=fail_materialization,
            )

        self.assertEqual(OrderDocument.objects.count(), 0)
        self.assertEqual(
            [path for path in Path(self.media.name).rglob("*") if path.is_file()],
            [],
        )

    def create(self, **kwargs):
        return create_order_document(
            actor=self.user,
            organization_id=self.organization.pk,
            order_id=self.order.pk,
            file=kwargs.pop("file", self._upload()),
            **kwargs,
        )

    def stored_files(self):
        return [p for p in Path(self.media.name).rglob("*") if p.is_file()]

    def csrf_client(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        return client, token

    @property
    def url(self):
        return (
            f"/api/v1/workspaces/{self.organization.pk}/orders/"
            f"{self.order.pk}/documents/"
        )

    def test_service_bounds_actual_bytes_despite_forged_size(self):
        upload = self._upload(b"x" * 33)
        upload.size = 1
        with (
            patch("apps.orders.document_files.MAX_ORDER_DOCUMENT_BYTES", 32),
            patch.object(OrderDocument, "save") as save,
        ):
            with self.assertRaises(OrderDocumentTooLarge):
                self.create(file=upload, size_bytes=1)
        save.assert_not_called()
        self.assertEqual(self.stored_files(), [])
        self.assertFalse(connection.in_atomic_block)

    def test_limit_boundary_and_actual_http_size_with_csrf(self):
        client, token = self.csrf_client()
        with (
            patch("apps.orders.document_files.MAX_ORDER_DOCUMENT_BYTES", 32),
            patch("apps.orders.uploads.MAX_ORDER_DOCUMENT_BYTES", 32),
        ):
            for length, expected in ((31, 201), (32, 201), (33, 413)):
                with self.subTest(length=length):
                    before = OrderDocument.objects.count()
                    response = client.post(
                        self.url,
                        {"file": self._upload(b"x" * length)},
                        format="multipart",
                        HTTP_X_CSRFTOKEN=token,
                    )
                    self.assertEqual(response.status_code, expected, response.content)
                    self.assertEqual(
                        OrderDocument.objects.count(), before + (expected == 201)
                    )
                    if expected == 201:
                        self.assertEqual(response.json()["size_bytes"], length)

    def test_insert_and_commit_failures_remove_only_new_file(self):
        existing = self.create()
        old_content = Path(self.media.name, existing.file.name).read_bytes()
        for failure in ("insert", "commit"):
            with self.subTest(failure=failure):
                target = OrderDocument if failure == "insert" else connection
                method = "save" if failure == "insert" else "_commit"
                with patch.object(
                    target, method, side_effect=IntegrityError("Synthetic")
                ):
                    with self.assertRaises(IntegrityError):
                        self.create()
                self.assertEqual(OrderDocument.objects.count(), 1)
                self.assertEqual(len(self.stored_files()), 1)
                self.assertEqual(
                    Path(self.media.name, existing.file.name).read_bytes(), old_content
                )
                self.assertFalse(connection.in_atomic_block)

    def test_partial_storage_failure_removes_attempt_file(self):
        storage = OrderDocument._meta.get_field("file").storage
        original = storage.save

        def partial(name, content, **kwargs):
            original(name, content, **kwargs)
            raise OSError("Synthetic storage failure")

        with patch.object(storage, "save", side_effect=partial):
            with self.assertRaises(OSError):
                self.create()
        self.assertEqual(self.stored_files(), [])
        self.assertEqual(OrderDocument.objects.count(), 0)

    def test_existing_storage_name_is_not_overwritten_or_deleted(self):
        storage = OrderDocument._meta.get_field("file").storage
        with (
            patch.object(storage, "exists", return_value=True),
            patch.object(storage, "save") as save,
            patch.object(storage, "delete") as delete,
        ):
            with self.assertRaises(ValidationError):
                self.create()
        save.assert_not_called()
        delete.assert_not_called()

    def test_empty_and_unexpected_input_failures_leave_no_files(self):
        with self.assertRaises(ValidationError):
            self.create(file=self._upload(b""))

        def fail(document):
            raise RuntimeError("Synthetic materialization failure")

        with self.assertRaises(RuntimeError):
            self.create(materialize=fail)
        self.assertEqual(self.stored_files(), [])
        self.assertEqual(OrderDocument.objects.count(), 0)

    def test_cleanup_failure_preserves_original_exception_and_logs_no_private_data(
        self,
    ):
        storage = OrderDocument._meta.get_field("file").storage
        original_error = ValidationError({"file": "Synthetic original failure"})

        def fail(document):
            raise original_error

        with (
            patch.object(
                storage, "delete", side_effect=OSError("PRIVATE-STORAGE-TEXT")
            ),
            self.assertLogs("apps.orders.services", level="ERROR") as logs,
        ):
            with self.assertRaises(ValidationError) as caught:
                self.create(materialize=fail)
        self.assertIs(caught.exception, original_error)
        self.assertEqual(
            logs.output,
            ["ERROR:apps.orders.services:Source document rollback cleanup failed."],
        )
        self.assertEqual(OrderDocument.objects.count(), 0)
        self.assertEqual(len(self.stored_files()), 1)

    def test_existing_file_input_is_copied_and_never_deleted_on_rollback(self):
        existing = self.create()

        def fail(document):
            raise ValidationError("Synthetic")

        with self.assertRaises(ValidationError):
            self.create(file=existing.file, materialize=fail)
        self.assertEqual(len(self.stored_files()), 1)
        self.assertEqual(OrderDocument.objects.count(), 1)
        with existing.file.open("rb"):
            self.assertEqual(existing.file.read(), b"document-bytes")

    def test_validation_and_revocation_do_not_read_or_store_upload(self):
        with self.assertRaises(ValidationError):
            self.create(original_name="x" * 256)
        self.assertEqual(self.stored_files(), [])
        Membership.objects.filter(
            user=self.user, organization=self.organization
        ).update(is_active=False)
        with patch("apps.orders.services.bounded_document_file") as read:
            with self.assertRaises(PermissionDenied):
                self.create()
        read.assert_not_called()
        self.assertEqual(self.stored_files(), [])

    def test_role_and_parent_denial_precede_application_parsing(self):
        client, token = self.csrf_client()
        for role in (MembershipRole.VIEWER, MembershipRole.REVIEWER):
            with self.subTest(role=role):
                Membership.objects.filter(
                    user=self.user, organization=self.organization
                ).update(role=role)
                path = (
                    self.url
                    if role == MembershipRole.VIEWER
                    else self.url.replace(
                        str(self.order.pk), "00000000-0000-0000-0000-000000000001"
                    )
                )
                response = client.post(
                    path, {}, format="multipart", HTTP_X_CSRFTOKEN=token
                )
                self.assertEqual(
                    response.status_code, 403 if role == MembershipRole.VIEWER else 404
                )
        self.assertEqual(self.stored_files(), [])

    def test_duplicate_files_and_aggregate_limit_never_write(self):
        client, token = self.csrf_client()
        with patch("apps.orders.uploads.MAX_ORDER_DOCUMENT_BYTES", 32):
            for sizes, expected in (((8, 8), 400), ((20, 20), 413)):
                with self.subTest(sizes=sizes):
                    response = client.post(
                        self.url,
                        {"file": [self._upload(b"x" * n) for n in sizes]},
                        format="multipart",
                        HTTP_X_CSRFTOKEN=token,
                    )
                    self.assertEqual(response.status_code, expected, response.content)
        self.assertEqual(OrderDocument.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

    def test_chunk_limit_ignores_absent_or_forged_lengths_and_closes_current_file(self):
        for length in (None, 1, MAX_ORDER_DOCUMENT_BYTES * 2):
            with self.subTest(length=length):
                request = SimpleNamespace(upload_handlers=[])
                handler = OrderDocumentUploadLimitHandler(request)
                stream = io.BytesIO()
                request.upload_handlers = [handler, SimpleNamespace(file=stream)]
                handler.new_file("file", "synthetic.pdf", "application/pdf", length)
                handler.receive_data_chunk(b"x" * MAX_ORDER_DOCUMENT_BYTES, 0)
                with self.assertRaises(OrderDocumentUploadTooLarge):
                    handler.receive_data_chunk(b"x", MAX_ORDER_DOCUMENT_BYTES)
                self.assertTrue(stream.closed)

    def test_oversize_during_csrf_closes_temporary_files(self):
        client, token = self.csrf_client()
        created = []
        original = TemporaryUploadedFile.__init__

        def track(instance, *args, **kwargs):
            original(instance, *args, **kwargs)
            created.append(instance)

        with (
            override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1),
            patch.object(TemporaryUploadedFile, "__init__", track),
        ):
            response = client.post(
                self.url,
                {"file": self._upload(b"x" * (MAX_ORDER_DOCUMENT_BYTES + 1))},
                format="multipart",
                HTTP_X_CSRFTOKEN=token,
            )
        self.assertEqual(response.status_code, 413, response.content)
        self.assertTrue(created)
        self.assertTrue(all(upload.closed for upload in created))
        self.assertEqual(self.stored_files(), [])

    def test_missing_and_invalid_csrf_and_anonymous_upload_are_denied(self):
        client, _ = self.csrf_client()
        for token in (None, "invalid"):
            with self.subTest(token=token):
                headers = {} if token is None else {"HTTP_X_CSRFTOKEN": token}
                response = client.post(
                    self.url, {"file": self._upload()}, format="multipart", **headers
                )
                self.assertEqual(response.status_code, 403)
        response = APIClient(enforce_csrf_checks=True).post(
            self.url, {"file": self._upload()}, format="multipart"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.stored_files(), [])

    def test_overloaded_multipart_upload_is_rejected_before_storage_write(self) -> None:
        client = APIClient()
        client.force_login(self.user)
        upload = SimpleUploadedFile(
            "oversized.pdf",
            b"x" * (MAX_ORDER_DOCUMENT_BYTES + 1),
            content_type="application/pdf",
        )

        response = client.post(
            f"/api/v1/workspaces/{self.organization.pk}/orders/{self.order.pk}/documents/",
            {"file": upload},
            format="multipart",
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(OrderDocument.objects.count(), 0)
        self.assertEqual(
            [path for path in Path(self.media.name).rglob("*") if path.is_file()],
            [],
        )
