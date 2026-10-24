"""Capture customer readiness in the same SQL snapshot as draft line counts."""

from django.db.models import (
    BooleanField,
    Case,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import JSONObject
from django.utils.dateparse import parse_datetime

from apps.customers.models import CustomerLocation, DraftCustomerDecision
from apps.orders.models import OrderDocument


def annotations(organization_id):
    sites = CustomerLocation.objects.filter(
        organization_id=organization_id,
        customer_id=OuterRef("customer_id"),
        is_active=True,
    )
    decisions = (
        DraftCustomerDecision.objects.filter(
            organization_id=organization_id, draft_id=OuterRef("pk"), is_current=True
        )
        .order_by()
        .annotate(has_sites=Exists(sites))
        .annotate(
            info=JSONObject(
                snapshot=F("snapshot"),
                account_active=F("customer__is_active"),
                account_version=F("customer__updated_at"),
                location_id=F("location_id"),
                location_active=F("location__is_active"),
                location_version=F("location__updated_at"),
                location_required=Case(
                    When(
                        Q(customer__requires_location=True) | Q(has_sites=True),
                        then=Value(True),
                    ),
                    default=Value(False),
                    output_field=BooleanField(),
                ),
            )
        )
        .values("info")
    )
    incoming = OrderDocument.objects.filter(
        organization_id=organization_id, draft_id=OuterRef("pk"), order__isnull=True
    )
    return {
        "customer_confirmation_required": Exists(incoming),
        "customer_confirmation": Subquery(decisions[:1]),
    }


def blockers(order):
    info = order.customer_confirmation
    if info is None:
        return ["customer_unconfirmed"] if order.customer_confirmation_required else []
    if not info["account_active"]:
        return ["customer_inactive"]
    if info["location_id"] and not info["location_active"]:
        return ["customer_location_inactive"]
    if info["location_required"] and info["location_id"] is None:
        return ["customer_location_required"]
    snapshot = info["snapshot"]
    stale = parse_datetime(snapshot["account"]["updated_at"]) != parse_datetime(
        info["account_version"]
    )
    if info["location_id"]:
        stale |= parse_datetime(snapshot["location"]["updated_at"]) != parse_datetime(
            info["location_version"]
        )
    if stale or snapshot["location_required"] != info["location_required"]:
        return ["customer_reference_changed"]
    if snapshot["requested"] != {
        "customer_name": order.customer_name,
        "customer_reference": order.customer_reference,
    }:
        return ["customer_unconfirmed"]
    return []
