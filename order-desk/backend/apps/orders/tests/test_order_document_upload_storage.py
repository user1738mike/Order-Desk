from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings

from apps.accounts.models import User
from apps.orders.models import OrderDocument
from apps.orders.services import create_order_document, create_purchase_order
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
