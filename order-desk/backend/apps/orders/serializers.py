"""Explicit order output and bounded, identity-free mutation input."""

from collections.abc import Mapping
from decimal import Decimal

from django.urls import reverse
from rest_framework import serializers

from apps.orders.models import (
    MAX_DRAFT_QUANTITY,
    DraftOrder,
    DraftOrderLine,
    OrderDocument,
    OrderDocumentReview,
    OrderStatus,
    PurchaseOrder,
    PurchaseOrderLine,
)


class DraftOrderSummarySerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    initiating_user_id = serializers.UUIDField(read_only=True)
    line_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DraftOrder
        fields = (
            "id",
            "organization_id",
            "status",
            "source_type",
            "customer_name",
            "customer_reference",
            "initiating_user_id",
            "created_at",
            "updated_at",
            "line_count",
        )
        read_only_fields = fields


class DraftOrderCreationSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    initiating_user_id = serializers.UUIDField(read_only=True)
    lines_url = serializers.SerializerMethodField()

    class Meta:
        model = DraftOrder
        fields = (
            "id",
            "organization_id",
            "initiating_user_id",
            "status",
            "source_type",
            "customer_name",
            "customer_reference",
            "original_intake_text",
            "created_at",
            "updated_at",
            "lines_url",
        )
        read_only_fields = fields

    def get_lines_url(self, order: DraftOrder) -> str:
        path = reverse(
            "workspaces:draft-orders:lines",
            kwargs={"workspace_id": order.organization_id, "order_id": order.pk},
        )
        return self.context["request"].build_absolute_uri(path)


class DraftOrderDetailSerializer(DraftOrderSummarySerializer):
    lines_url = serializers.SerializerMethodField()

    class Meta(DraftOrderSummarySerializer.Meta):
        fields = (
            *DraftOrderSummarySerializer.Meta.fields,
            "original_intake_text",
            "lines_url",
        )
        read_only_fields = fields

    def get_lines_url(self, order: DraftOrder) -> str:
        path = reverse(
            "workspaces:draft-orders:lines",
            kwargs={"workspace_id": order.organization_id, "order_id": order.pk},
        )
        return self.context["request"].build_absolute_uri(path)


class DraftOrderReviewSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    customer_name_empty = serializers.SerializerMethodField()
    customer_reference_empty = serializers.SerializerMethodField()
    line_count = serializers.IntegerField(read_only=True)
    unmatched_line_count = serializers.IntegerField(read_only=True)
    missing_quantity_line_count = serializers.IntegerField(read_only=True)
    unresolved_line_count = serializers.IntegerField(read_only=True)
    inactive_catalogue_line_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DraftOrder
        fields = (
            "id",
            "organization_id",
            "customer_name_empty",
            "customer_reference_empty",
            "line_count",
            "unmatched_line_count",
            "missing_quantity_line_count",
            "unresolved_line_count",
            "inactive_catalogue_line_count",
        )
        read_only_fields = fields

    def get_customer_name_empty(self, order: DraftOrder) -> bool:
        return not order.customer_name.strip()

    def get_customer_reference_empty(self, order: DraftOrder) -> bool:
        return not order.customer_reference.strip()


class DraftOrderLineReadSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    order_id = serializers.UUIDField(read_only=True)
    catalogue_item_id = serializers.UUIDField(read_only=True, allow_null=True)
    quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        coerce_to_string=True,
        allow_null=True,
        read_only=True,
    )

    class Meta:
        model = DraftOrderLine
        fields = (
            "id",
            "organization_id",
            "order_id",
            "position",
            "requested_sku",
            "requested_description",
            "quantity",
            "unit",
            "catalogue_item_id",
            "catalogue_sku_snapshot",
            "catalogue_description_snapshot",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StrictInputSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError(
                    {key: ["Unsupported field."] for key in sorted(unknown)}
                )
        return super().to_internal_value(data)


class DraftOrderCustomerFieldsSerializer(StrictInputSerializer):
    customer_name = serializers.CharField(
        max_length=255, allow_blank=True, required=False, trim_whitespace=False
    )
    customer_reference = serializers.CharField(
        max_length=128, allow_blank=True, required=False, trim_whitespace=False
    )

    def validate_customer_name(self, value: str) -> str:
        if value and not value.strip():
            raise serializers.ValidationError(
                "Provide a nonblank value or an empty string."
            )
        return value

    def validate_customer_reference(self, value: str) -> str:
        if value and not value.strip():
            raise serializers.ValidationError(
                "Provide a nonblank value or an empty string."
            )
        return value


class DraftOrderCreateSerializer(DraftOrderCustomerFieldsSerializer):
    original_intake_text = serializers.CharField(
        max_length=10000, allow_blank=True, required=False, trim_whitespace=False
    )


class DraftOrderCustomerUpdateSerializer(DraftOrderCustomerFieldsSerializer):
    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            errors = {
                field: ["Not a valid string."]
                for field in self.fields
                if field in data and not isinstance(data[field], str)
            }
            if errors:
                raise serializers.ValidationError(errors)
        return super().to_internal_value(data)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one customer field.")
        return attrs


class DraftOrderLineCreateSerializer(StrictInputSerializer):
    position = serializers.IntegerField(min_value=1, max_value=2147483647)
    requested_sku = serializers.CharField(
        allow_blank=True, required=False, trim_whitespace=False
    )
    requested_description = serializers.CharField(
        allow_blank=True, required=False, trim_whitespace=False
    )
    quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
        max_value=MAX_DRAFT_QUANTITY,
        allow_null=True,
        required=False,
    )
    unit = serializers.CharField(
        max_length=32, allow_blank=True, required=False, trim_whitespace=False
    )

    def validate(self, attrs):
        if not any(
            attrs.get(field, "").strip()
            for field in ("requested_sku", "requested_description")
        ):
            raise serializers.ValidationError("Provide a requested SKU or description.")
        return attrs


class DraftOrderLineUpdateSerializer(StrictInputSerializer):
    requested_sku = serializers.CharField(
        allow_blank=True, required=False, trim_whitespace=False
    )
    requested_description = serializers.CharField(
        allow_blank=True, required=False, trim_whitespace=False
    )
    quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
        max_value=MAX_DRAFT_QUANTITY,
        allow_null=True,
        required=False,
    )
    unit = serializers.CharField(
        max_length=32, allow_blank=True, required=False, trim_whitespace=False
    )


class DraftOrderLineAttachmentSerializer(StrictInputSerializer):
    catalogue_item_id = serializers.UUIDField()


class DraftOrderLineDetachmentSerializer(StrictInputSerializer):
    """Only an empty object is valid for this explicit action."""


class PurchaseOrderCreateSerializer(StrictInputSerializer):
    customer_name = serializers.CharField(max_length=255)
    purchase_order_number = serializers.CharField(max_length=64)
    status = serializers.ChoiceField(
        choices=(OrderStatus.DRAFT, OrderStatus.PENDING_REVIEW),
        default=OrderStatus.DRAFT,
    )
    comments = serializers.CharField(max_length=8000, allow_blank=True, default="")
    source_document = serializers.CharField(
        max_length=255, allow_blank=True, default=""
    )
    is_active = serializers.BooleanField(default=True)


class PurchaseOrderLineCreateSerializer(StrictInputSerializer):
    line_number = serializers.IntegerField(min_value=1)
    sku = serializers.CharField(max_length=128)
    description = serializers.CharField(max_length=8000, allow_blank=True, default="")
    quantity = serializers.DecimalField(
        max_digits=18, decimal_places=4, min_value=Decimal("0.0001")
    )
    unit = serializers.CharField(max_length=32, allow_blank=True, default="ea")


class OrderDocumentCreateSerializer(StrictInputSerializer):
    file = serializers.FileField()


class OrderDocumentReviewCreateSerializer(StrictInputSerializer):
    vendor_name = serializers.CharField(max_length=255, allow_blank=True, default="")
    extracted_order_number = serializers.CharField(
        max_length=64, allow_blank=True, default=""
    )
    line_count = serializers.IntegerField(min_value=0, default=0)
    grand_total = serializers.DecimalField(
        max_digits=18, decimal_places=4, min_value=Decimal("0"), default=Decimal("0")
    )
    status = serializers.ChoiceField(choices=("needs_review",), default="needs_review")
    notes = serializers.CharField(max_length=8000, allow_blank=True, default="")


class DocumentReviewResolveSerializer(StrictInputSerializer):
    status = serializers.ChoiceField(choices=("accepted", "rejected"))
    notes = serializers.CharField(max_length=8000, allow_blank=True, default="")


class OrderReviewActionSerializer(StrictInputSerializer):
    review_note = serializers.CharField(max_length=8000, allow_blank=True, default="")


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderLine
        fields = (
            "id",
            "line_number",
            "sku",
            "description",
            "quantity",
            "unit",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class OrderDocumentReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderDocumentReview
        fields = (
            "id",
            "document",
            "organization",
            "created_by",
            "vendor_name",
            "extracted_order_number",
            "line_count",
            "grand_total",
            "notes",
            "status",
            "resolved_by",
            "resolved_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class OrderDocumentSerializer(serializers.ModelSerializer):
    reviews = OrderDocumentReviewSerializer(many=True, read_only=True)

    class Meta:
        model = OrderDocument
        fields = (
            "id",
            "order",
            "organization",
            "uploaded_by",
            "original_name",
            "content_type",
            "size_bytes",
            "uploaded_at",
            "status",
            "reviews",
        )
        read_only_fields = fields


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)
    documents = OrderDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "customer_name",
            "purchase_order_number",
            "status",
            "is_active",
            "source_document",
            "comments",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_at",
            "updated_at",
            "lines",
            "documents",
        )
        read_only_fields = fields
