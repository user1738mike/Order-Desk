from decimal import Decimal
from tempfile import TemporaryDirectory

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.models import OrderStatus
from apps.orders.services import (
    add_order_line,
    approve_purchase_order,
    create_document_review,
    create_order_document,
    create_purchase_order,
    resolve_document_review,
    submit_purchase_order_for_review,
)
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


class PurchaseOrderServiceTests(TransactionTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(email="orders-service@example.test")
        self.organization = create_organization(actor=self.user, name="Distributor 1")

    def test_create_order_requires_active_membership(self) -> None:
        other_user = User.objects.create_user(email="other@example.test")
        with self.assertRaises(PermissionDenied):
            create_purchase_order(
                actor=other_user,
                organization_id=self.organization.pk,
                customer_name="Acme",
                purchase_order_number="PO-100",
            )

    def test_create_order_and_line_work_in_workspace(self) -> None:
        order = create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Acme",
            purchase_order_number="PO-100",
        )
        line = add_order_line(
            organization_id=self.organization.pk,
            actor=self.user,
            order_id=order.pk,
            line_number=1,
            sku="ABC-123",
            quantity=Decimal("2.50"),
            unit="box",
        )

        self.assertEqual(order.status, OrderStatus.DRAFT)
        self.assertEqual(line.quantity, Decimal("2.50"))
        self.assertEqual(order.organization_id, self.organization.pk)

    def test_submit_and_approve_order_requires_review_access(self) -> None:
        order = create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Acme",
            purchase_order_number="PO-101",
        )
        reviewer = User.objects.create_user(email="reviewer@example.test")
        Membership.objects.create(
            organization=self.organization,
            user=reviewer,
            role=MembershipRole.REVIEWER,
            is_active=True,
        )

        submitted = submit_purchase_order_for_review(
            organization_id=self.organization.pk, actor=self.user, order_id=order.pk
        )
        self.assertEqual(submitted.status, OrderStatus.PENDING_REVIEW)

        approved = approve_purchase_order(
            organization_id=self.organization.pk,
            actor=reviewer,
            order_id=order.pk,
            review_note="Looks good",
        )
        self.assertEqual(approved.status, OrderStatus.APPROVED)
        self.assertEqual(approved.reviewed_by_id, reviewer.pk)
        self.assertEqual(approved.review_note, "Looks good")

        with self.assertRaises(ValidationError):
            add_order_line(
                organization_id=self.organization.pk,
                actor=self.user,
                order_id=order.pk,
                line_number=2,
                sku="XYZ-456",
                quantity=Decimal("1"),
            )


class PurchaseOrderApiTests(TransactionTestCase):
    def setUp(self) -> None:
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        storage = override_settings(MEDIA_ROOT=media.name)
        storage.enable()
        self.addCleanup(storage.disable)
        self.user = User.objects.create_user(email="order-api@example.test")
        self.organization = create_organization(actor=self.user, name="API Distributor")
        self.reviewer = User.objects.create_user(email="order-reviewer@example.test")
        Membership.objects.create(
            organization=self.organization,
            user=self.reviewer,
            role=MembershipRole.REVIEWER,
            is_active=True,
        )
        self.client = APIClient()
        self.client.force_login(self.user)

    def test_workspace_orders_are_listed_and_created(self) -> None:
        create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Acme",
            purchase_order_number="PO-200",
        )

        response = self.client.get(f"/api/v1/workspaces/{self.organization.pk}/orders/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            response.json()["results"][0]["purchase_order_number"], "PO-200"
        )

        create_response = self.client.post(
            f"/api/v1/workspaces/{self.organization.pk}/orders/",
            {
                "customer_name": "Contoso",
                "purchase_order_number": "PO-201",
                "status": OrderStatus.DRAFT,
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.json()["purchase_order_number"], "PO-201")
        self.assertEqual(create_response.json()["status"], OrderStatus.DRAFT)

    def test_review_workflow_is_exposed_on_workspace_routes(self) -> None:
        order = create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Northwind",
            purchase_order_number="PO-300",
        )
        reviewer_client = APIClient()
        reviewer_client.force_login(self.reviewer)

        submit_response = reviewer_client.post(
            f"/api/v1/workspaces/{self.organization.pk}/orders/{order.pk}/submit/",
            format="json",
        )
        self.assertEqual(submit_response.status_code, 200)
        self.assertEqual(submit_response.json()["status"], OrderStatus.PENDING_REVIEW)

        approve_response = reviewer_client.post(
            f"/api/v1/workspaces/{self.organization.pk}/orders/{order.pk}/approve/",
            {"review_note": "Looks good."},
            format="json",
        )
        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(approve_response.json()["status"], OrderStatus.APPROVED)
        self.assertEqual(approve_response.json()["review_note"], "Looks good.")

    def test_order_document_upload_is_scoped_to_workspace(self) -> None:
        order = create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Another Buyer",
            purchase_order_number="PO-301",
        )
        uploaded = create_order_document(
            actor=self.user,
            organization_id=self.organization.pk,
            order_id=order.pk,
            file=SimpleUploadedFile(
                "purchase_order.pdf", b"pdf-bytes", content_type="application/pdf"
            ),
            original_name="purchase_order.pdf",
            content_type="application/pdf",
            size_bytes=9,
        )

        self.assertEqual(uploaded.order_id, order.pk)
        self.assertEqual(uploaded.original_name, "purchase_order.pdf")
        self.assertTrue(uploaded.file.name.startswith("orders/source_documents/"))

        review = create_document_review(
            actor=self.user,
            organization_id=self.organization.pk,
            document_id=uploaded.pk,
            vendor_name="Acme Supply",
            extracted_order_number="PO-301",
            line_count=2,
            grand_total=Decimal("84.25"),
            notes="Matched vendor and order number.",
        )

        self.assertEqual(review.vendor_name, "Acme Supply")
        self.assertEqual(review.status, "needs_review")
        uploaded.refresh_from_db()
        self.assertEqual(uploaded.status, "pending_review")

        accepted = resolve_document_review(
            actor=self.user,
            organization_id=self.organization.pk,
            review_id=review.pk,
            status="accepted",
            notes="Validated against the order.",
        )
        self.assertEqual(accepted.status, "accepted")
        reloaded = type(uploaded).objects.get(pk=uploaded.pk)
        self.assertEqual(reloaded.status, "received")

    def test_document_review_requires_review_access(self) -> None:
        viewer = User.objects.create_user(email="viewer@example.test")
        Membership.objects.create(
            organization=self.organization,
            user=viewer,
            role=MembershipRole.VIEWER,
            is_active=True,
        )
        order = create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Viewer Buyer",
            purchase_order_number="PO-302",
        )
        document = create_order_document(
            actor=self.user,
            organization_id=self.organization.pk,
            order_id=order.pk,
            file=SimpleUploadedFile(
                "viewer.pdf", b"pdf-bytes", content_type="application/pdf"
            ),
            original_name="viewer.pdf",
            content_type="application/pdf",
            size_bytes=10,
        )

        with self.assertRaises(PermissionDenied):
            create_document_review(
                actor=viewer,
                organization_id=self.organization.pk,
                document_id=document.pk,
                vendor_name="Viewer Inc",
            )

    def test_document_review_api_resolves_under_workspace_routes(self) -> None:
        order = create_purchase_order(
            actor=self.user,
            organization_id=self.organization.pk,
            customer_name="Review Buyer",
            purchase_order_number="PO-303",
        )
        document = create_order_document(
            actor=self.user,
            organization_id=self.organization.pk,
            order_id=order.pk,
            file=SimpleUploadedFile(
                "review.pdf", b"pdf-bytes", content_type="application/pdf"
            ),
            original_name="review.pdf",
            content_type="application/pdf",
            size_bytes=11,
        )
        reviewer_client = APIClient()
        reviewer_client.force_login(self.reviewer)

        create_review_response = reviewer_client.post(
            f"/api/v1/workspaces/{self.organization.pk}/orders/{order.pk}/documents/{document.pk}/reviews/",
            {
                "vendor_name": "Acme Supply",
                "extracted_order_number": "PO-303",
                "line_count": 3,
                "grand_total": "42.50",
                "notes": "Ready for review.",
            },
            format="json",
        )
        self.assertEqual(create_review_response.status_code, 201)
        self.assertEqual(create_review_response.json()["status"], "needs_review")

        review_id = create_review_response.json()["id"]
        resolve_response = reviewer_client.post(
            f"/api/v1/workspaces/{self.organization.pk}/orders/{order.pk}/documents/{document.pk}/reviews/{review_id}/resolve/",
            {"status": "accepted", "notes": "Approved after validation."},
            format="json",
        )
        self.assertEqual(resolve_response.status_code, 200)
        self.assertEqual(resolve_response.json()["status"], "accepted")
        document.refresh_from_db()
        self.assertEqual(document.status, "received")
