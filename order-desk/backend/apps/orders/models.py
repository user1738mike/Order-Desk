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


class PurchaseOrderExport(models.Model):
    """One leased generation from an immutable approved conversion snapshot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    order = models.ForeignKey("PurchaseOrder", on_delete=models.PROTECT)
    profile = models.CharField(max_length=64)
    source_revision = models.CharField(max_length=64)
    payload = models.JSONField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_exports",
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generated_exports",
    )
    status = models.CharField(max_length=16, default="running")
    attempts = models.PositiveSmallIntegerField(default=1)
    claim_token = models.UUIDField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    storage_key = models.CharField(max_length=64, blank=True, default="")
    size_bytes = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    error_code = models.CharField(max_length=32, blank=True, default="")
    completed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "order", "profile", "source_revision"],
                name="export_source_profile_unique",
            ),
            models.UniqueConstraint(
                fields=["storage_key"],
                condition=~models.Q(storage_key=""),
                name="export_storage_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(profile="generic-po-csv-v1"),
                name="export_profile_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(source_revision__regex=r"^[0-9a-f]{64}$"),
                name="export_revision_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(attempts__gte=1, attempts__lte=3),
                name="export_attempts_bounded",
            ),
        ]


class ExtractionApplication(models.Model):
    """An immutable, committed human decision and its repeat-safe response."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    job = models.ForeignKey("DocumentExtractionJob", on_delete=models.PROTECT)
    draft = models.ForeignKey("DraftOrder", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operation_key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    request = models.JSONField()
    decisions = models.JSONField()
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "operation_key"],
                name="application_org_key_unique",
            ),
            models.UniqueConstraint(
                fields=["id", "organization", "job", "draft"],
                name="application_identity_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(payload_hash__regex=r"^[0-9a-f]{64}$"),
                name="application_hash_valid",
            ),
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ExtractionCreatedRow(models.Model):
    """A source row can create a line only once in a particular draft."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    application = models.ForeignKey(ExtractionApplication, on_delete=models.PROTECT)
    job = models.ForeignKey("DocumentExtractionJob", on_delete=models.PROTECT)
    draft = models.ForeignKey("DraftOrder", on_delete=models.PROTECT)
    line = models.ForeignKey("DraftOrderLine", on_delete=models.PROTECT)
    candidate_id = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "draft", "candidate_id"],
                name="extraction_row_create_unique",
            ),
        ]

    def __str__(self) -> str:
        return str(self.pk)


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
                fields=["id", "organization", "order"],
                name="draftline_id_org_order_unique",
            ),
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


class ExtractionJobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded; requires staff review"
    FAILED = "failed", "Failed"


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
    source_sha256 = models.CharField(
        max_length=64, blank=True, default="", db_default="", editable=False
    )
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
            models.CheckConstraint(
                condition=models.Q(source_sha256__regex=r"^[0-9a-f]{64}$")
                | (models.Q(source_sha256="") & ~models.Q(file__startswith="intake/")),
                name="orderdocument_private_source_digest",
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


class DocumentExtractionJob(models.Model):
    """Durable bounded proposals; never purchase-order lines or approval."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    document = models.ForeignKey(
        OrderDocument, on_delete=models.PROTECT, related_name="extraction_jobs"
    )
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="processed_extraction_jobs",
    )
    source_sha256 = models.CharField(max_length=64)
    parser_version = models.CharField(max_length=32, default="order-csv-v1")
    status = models.CharField(
        max_length=16,
        choices=ExtractionJobStatus.choices,
        default=ExtractionJobStatus.QUEUED,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=32, blank=True, default="")
    error_row = models.PositiveIntegerField(null=True, blank=True)
    result = models.JSONField(default=list, blank=True)
    result_pages = models.JSONField(default=list, blank=True)
    parser_metrics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization"], name="extraction_id_org_unique"
            ),
            models.UniqueConstraint(
                fields=("document", "source_sha256", "parser_version"),
                name="extraction_source_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(source_sha256__regex=r"^[0-9a-f]{64}$"),
                name="extraction_digest_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    parser_version__in=["order-csv-v1", "order-text-pdf-v1"]
                ),
                name="extraction_parser_supported",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ExtractionJobStatus.values),
                name="extraction_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(attempts__lte=3), name="extraction_attempts_bounded"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=ExtractionJobStatus.RUNNING,
                        claim_token__isnull=False,
                        lease_expires_at__isnull=False,
                        processed_by__isnull=False,
                        attempts__gt=0,
                    )
                    | (
                        ~models.Q(status=ExtractionJobStatus.RUNNING)
                        & models.Q(
                            claim_token__isnull=True, lease_expires_at__isnull=True
                        )
                    )
                ),
                name="extraction_lease_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status=ExtractionJobStatus.SUCCEEDED, error_code="")
                | (
                    ~models.Q(status=ExtractionJobStatus.SUCCEEDED)
                    & models.Q(result=[])
                ),
                name="extraction_result_state_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status=ExtractionJobStatus.FAILED)
                    & ~models.Q(error_code="")
                )
                | (
                    ~models.Q(status=ExtractionJobStatus.FAILED)
                    & models.Q(error_code="", error_row__isnull=True)
                ),
                name="extraction_error_state_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.pk}:{self.status}"
