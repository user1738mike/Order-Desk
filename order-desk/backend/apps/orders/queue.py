"""Bounded operational headers; consume only inside an authorized tenant scope."""

from django.db.models import F, Q
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.orders.models import OrderStatus, PurchaseOrder


def parse_queue_query(params):
    errors = {}
    for key, values in params.lists():
        if key not in {"page", "q", "status"}:
            errors[key] = ["Unknown query parameter."]
        elif len(values) != 1:
            errors[key] = ["Provide this query parameter once."]
    query = params.get("q", "").strip()
    status = params.get("status", "")
    if len(query) > 200 or any(ord(char) < 32 for char in query):
        errors["q"] = ["Use at most 200 characters without control characters."]
    if status and status not in OrderStatus.values:
        errors["status"] = ["Choose a supported order status."]
    if errors:
        raise ValidationError(errors)
    return query, status


def order_queue(organization_id, *, query="", status=""):
    orders = PurchaseOrder.objects.filter(organization_id=organization_id).annotate(
        customer_reference=F("source_draft__customer_reference")
    )
    if query:
        orders = orders.filter(
            Q(customer_name__icontains=query)
            | Q(purchase_order_number__icontains=query)
            | Q(
                source_draft__organization_id=organization_id,
                source_draft__customer_reference__icontains=query,
            )
        )
    if status:
        orders = orders.filter(status=status)
    return orders.order_by("-created_at", "-id").values(
        *OrderQueueSerializer.Meta.fields
    )


class OrderQueueSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    source_draft_id = serializers.UUIDField(read_only=True, allow_null=True)
    customer_reference = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "organization_id",
            "source_draft_id",
            "customer_name",
            "customer_reference",
            "purchase_order_number",
            "status",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
