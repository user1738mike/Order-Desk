"""Workspace-scoped purchase-order, document, and extraction-review models."""

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models.functions import Length
from django.db.models.lookups import LessThanOrEqual

from apps.catalog.models import CatalogItem
from apps.organizations.models import Organization

MAX_DRAFT_QUANTITY = Decimal("999999999.999")
MAX_ORIGINAL_INTAKE_LENGTH = 10000


class DraftOrder(models.Model):
    """A manual request whose details may still be unresolved."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONVERTED = "converted", "Converted"

    class SourceType(models.TextChoices):
        MANUAL = "manual", "Manual"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="draft_orders"
    )
    initiating_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="initiated_draft_orders",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    source_type = models.CharField(
        max_length=16, choices=SourceType.choices, default=SourceType.MANUAL
    )
    customer_name = models.CharField(max_length=255, blank=True, default="")
    customer_reference = models.CharField(max_length=128, blank=True, default="")
    original_intake_text = models.TextField(
        max_length=MAX_ORIGINAL_INTAKE_LENGTH, blank=True, default=""
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization"], name="draftorder_id_org_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "converted"]),
                name="draftorder_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(source_type="manual"),
                name="draftorder_source_manual",
            ),
            models.CheckConstraint(
                condition=models.Q(customer_name="")
                | models.Q(customer_name__regex=r"\S"),
                name="draftorder_customer_optional_nonblank",
            ),
            models.CheckConstraint(
                condition=models.Q(customer_reference="")
                | models.Q(customer_reference__regex=r"\S"),
                name="draftorder_reference_optional_nonblank",
            ),
            models.CheckConstraint(
                condition=LessThanOrEqual(
                    Length("original_intake_text"), MAX_ORIGINAL_INTAKE_LENGTH
                ),
                name="draftorder_original_text_bounded",
            ),
        ]

    def __str__(self) -> str:
        return str(self.pk)


class DraftOrderLine(models.Model):
    """A requested line, optionally linked to a catalogue snapshot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="draft_order_lines"
    )
    order = models.ForeignKey(
        DraftOrder, on_delete=models.PROTECT, related_name="draft_lines"
    )
    position = models.PositiveIntegerField()
    requested_sku = models.TextField(blank=True, default="")
    requested_description = models.TextField(blank=True, default="")
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.001")),
            MaxValueValidator(MAX_DRAFT_QUANTITY),
        ],
    )
    unit = models.CharField(max_length=32, blank=True, default="")
    catalogue_item = models.ForeignKey(
        CatalogItem,
        on_delete=models.PROTECT,
        related_name="draft_order_lines",
        null=True,
        blank=True,
    )
    catalogue_sku_snapshot = models.TextField(blank=True, default="")
    catalogue_description_snapshot = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order", "position"], name="draftline_order_position_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(position__gt=0), name="draftline_position_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__isnull=True)
                | (
                    models.Q(quantity__gt=0)
                    & models.Q(quantity__lte=MAX_DRAFT_QUANTITY)
                ),
                name="draftline_quantity_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(requested_sku__regex=r"\S")
                | models.Q(requested_description__regex=r"\S")
                | models.Q(
                    catalogue_item__isnull=False,
                    catalogue_sku_snapshot__regex=r"\S",
                ),
                name="draftline_identity_present",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    catalogue_item__isnull=True,
                    catalogue_sku_snapshot="",
                    catalogue_description_snapshot="",
                )
                | models.Q(
                    catalogue_item__isnull=False,
                    catalogue_sku_snapshot__regex=r"\S",
                ),
                name="draftline_catalogue_snapshot_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_id}:{self.position}"


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_REVIEW = "pending_review", "Pending review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class PurchaseOrder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_draft = models.OneToOneField(
        DraftOrder,
        on_delete=models.PROTECT,
        related_name="converted_order",
        null=True,
        blank=True,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    customer_name = models.CharField(
        max_length=255,
        validators=[RegexValidator(r"\S", "Enter a nonblank customer name.")],
    )
    purchase_order_number = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"\S", "Enter a nonblank purchase order number.")],
    )
    status = models.CharField(
        max_length=32,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
    )
    is_active = models.BooleanField(default=True)
    source_document = models.CharField(max_length=255, blank=True, default="")
    comments = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_purchase_orders",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(customer_name__regex=r"\S"),
                name="purchaseorder_customer_name_not_blank",
            ),
            models.CheckConstraint(
                condition=models.Q(purchase_order_number__regex=r"\S"),
                name="purchaseorder_number_not_blank",
            ),
            models.UniqueConstraint(
                fields=("organization", "purchase_order_number"),
                name="purchaseorder_org_number_unique",
            ),
            models.UniqueConstraint(
                fields=("id", "organization"), name="purchaseorder_id_org_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=OrderStatus.values),
                name="purchaseorder_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=(OrderStatus.DRAFT, OrderStatus.PENDING_REVIEW),
                        reviewed_by__isnull=True,
                        reviewed_at__isnull=True,
                    )
                    | models.Q(
                        status__in=(OrderStatus.APPROVED, OrderStatus.REJECTED),
                        reviewed_by__isnull=False,
                        reviewed_at__isnull=False,
                    )
                ),
                name="purchaseorder_review_metadata_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.purchase_order_number

    def clean(self) -> None:
        super().clean()
        if self.source_draft_id is None and isinstance(self.customer_name, str):
            self.customer_name = self.customer_name.strip()
        if isinstance(self.purchase_order_number, str):
            self.purchase_order_number = self.purchase_order_number.strip()
        if (
            self.status in {OrderStatus.APPROVED, OrderStatus.REJECTED}
            and self.reviewed_by_id is None
        ):
            raise ValidationError(
                {"reviewed_by": "A reviewed order must include the reviewer."}
            )


class PurchaseOrderLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="purchase_order_lines",
    )
    line_number = models.PositiveIntegerField()
    sku = models.CharField(
        max_length=128,
        validators=[RegexValidator(r"\S", "Enter a nonblank stock code.")],
    )
    description = models.TextField(blank=True, default="")
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(line_number__gt=0),
                name="purchaseorderline_line_number_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="purchaseorderline_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(sku__regex=r"\S"),
                name="purchaseorderline_sku_not_blank",
            ),
            models.UniqueConstraint(
                fields=("order", "line_number"),
                name="purchaseorderline_order_number_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_id}:{self.line_number}"

    def clean(self) -> None:
        super().clean()
        if isinstance(self.sku, str):
            self.sku = self.sku.strip()
        if isinstance(self.unit, str):
            self.unit = self.unit.strip()


class OrderDocumentStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PENDING_REVIEW = "pending_review", "Pending review"
    REJECTED = "rejected", "Rejected"


class OrderDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="order_documents",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_order_documents",
    )
    file = models.FileField(
        upload_to="orders/source_documents/%Y/%m/%d/",
        max_length=255,
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=32,
        choices=OrderDocumentStatus.choices,
        default=OrderDocumentStatus.RECEIVED,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0),
                name="orderdocument_size_positive",
            ),
            models.UniqueConstraint(
                fields=("id", "organization"), name="orderdocument_id_org_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=OrderDocumentStatus.values),
                name="orderdocument_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.original_name

    def clean(self) -> None:
        super().clean()
        if isinstance(self.original_name, str):
            self.original_name = self.original_name.strip()


class ExtractionReviewStatus(models.TextChoices):
    NEEDS_REVIEW = "needs_review", "Needs review"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


class OrderDocumentReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        OrderDocument,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="order_document_reviews",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="order_document_reviews",
    )
    vendor_name = models.CharField(max_length=255, blank=True, default="")
    extracted_order_number = models.CharField(max_length=64, blank=True, default="")
    line_count = models.PositiveIntegerField(default=0)
    grand_total = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.00")
    )
    notes = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=ExtractionReviewStatus.choices,
        default=ExtractionReviewStatus.NEEDS_REVIEW,
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="resolved_order_document_reviews",
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(vendor_name__regex=r"\S") | models.Q(vendor_name=""),
                name="orderdocumentreview_vendor_name_optional",
            ),
            models.CheckConstraint(
                condition=models.Q(extracted_order_number__regex=r"\S")
                | models.Q(extracted_order_number=""),
                name="orderdocumentreview_number_optional",
            ),
            models.CheckConstraint(
                condition=models.Q(grand_total__gte=0),
                name="orderdocumentreview_total_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ExtractionReviewStatus.values),
                name="orderreview_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=ExtractionReviewStatus.NEEDS_REVIEW,
                        resolved_by__isnull=True,
                        resolved_at__isnull=True,
                    )
                    | models.Q(
                        status__in=(
                            ExtractionReviewStatus.ACCEPTED,
                            ExtractionReviewStatus.REJECTED,
                        ),
                        resolved_by__isnull=False,
                        resolved_at__isnull=False,
                    )
                ),
                name="orderreview_resolution_metadata_valid",
            ),
            models.UniqueConstraint(
                fields=("document",),
                condition=models.Q(status=ExtractionReviewStatus.NEEDS_REVIEW),
                name="orderreview_one_pending_per_doc",
            ),
        ]

    def __str__(self) -> str:
        if self.extracted_order_number:
            return self.extracted_order_number
        return f"Review {self.pk}"

    def clean(self) -> None:
        super().clean()
        if isinstance(self.vendor_name, str):
            self.vendor_name = self.vendor_name.strip()
        if isinstance(self.extracted_order_number, str):
            self.extracted_order_number = self.extracted_order_number.strip()
        if isinstance(self.notes, str):
            self.notes = self.notes.strip()
