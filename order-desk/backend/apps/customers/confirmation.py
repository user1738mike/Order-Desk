"""Confirmed account/site decisions, invalidation and frozen snapshots."""

import hashlib
import json

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.customers.models import (
    CustomerAccount,
    CustomerLocation,
    DraftCustomerDecision,
    OrderCustomerSnapshot,
)
from apps.customers.services import ReferenceConflict
from apps.orders.models import DraftOrder, OrderDocument
from apps.orders.revisions import check_revision, draft_revision
from apps.orders.serializers import StrictInputSerializer
from apps.orders.services import _require_draft_editable, _require_preparer
from apps.organizations.transactions import tenant_scope


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def reference(account, location):
    def fields(row):
        return {
            "id": str(row.pk),
            "code": row.code,
            "display_name": row.display_name,
            "destination_id": row.destination_id,
            "updated_at": row.updated_at.isoformat(),
        }

    required = (
        account.requires_location
        or CustomerLocation.objects.filter(
            organization_id=account.organization_id, customer=account, is_active=True
        ).exists()
    )
    return {
        "account": fields(account),
        "location": fields(location) if location else None,
        "location_required": required,
    }


def selected_reference(organization_id, account_id, location_id):
    account = get_object_or_404(
        CustomerAccount, organization_id=organization_id, pk=account_id
    )
    if not account.is_active:
        raise ValidationError({"customer_id": "This customer account is inactive."})
    location = None
    if location_id:
        location = get_object_or_404(
            CustomerLocation,
            organization_id=organization_id,
            customer=account,
            pk=location_id,
        )
        if not location.is_active:
            raise ValidationError(
                {"location_id": "This delivery location is inactive."}
            )
    value = reference(account, location)
    if value["location_required"] and location is None:
        raise ValidationError(
            {"location_id": "Choose an active delivery location for this account."}
        )
    return account, location, value


def current_decision(draft):
    return (
        DraftCustomerDecision.objects.filter(
            organization_id=draft.organization_id, draft=draft, is_current=True
        )
        .select_related("customer", "location")
        .first()
    )


def assessment(draft):
    required = OrderDocument.objects.filter(
        organization_id=draft.organization_id, draft=draft, order__isnull=True
    ).exists()
    decision = current_decision(draft)
    blockers = []
    if decision is None:
        if required:
            blockers.append("customer_unconfirmed")
    elif not decision.customer.is_active:
        blockers.append("customer_inactive")
    elif decision.location_id and not decision.location.is_active:
        blockers.append("customer_location_inactive")
    else:
        value = reference(decision.customer, decision.location)
        if value["location_required"] and decision.location_id is None:
            blockers.append("customer_location_required")
        if fingerprint(value) != decision.reference_revision:
            blockers.append("customer_reference_changed")
        if decision.snapshot["requested"] != {
            "customer_name": draft.customer_name,
            "customer_reference": draft.customer_reference,
        }:
            blockers.append("customer_unconfirmed")
    return {
        "required": required,
        "confirmed": decision is not None and not blockers,
        "blockers": blockers,
        "decision": decision,
    }


class ConfirmationInput(StrictInputSerializer):
    operation_key = serializers.UUIDField()
    customer_id = serializers.UUIDField()
    location_id = serializers.UUIDField(allow_null=True, required=False, default=None)
    reference_revision = serializers.RegexField(r"^[0-9a-f]{64}$")
    expected_draft_revision = serializers.RegexField(r"^[0-9a-f]{64}$")


class DecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DraftCustomerDecision
        fields = (
            "id",
            "organization_id",
            "draft_id",
            "customer_id",
            "location_id",
            "actor_id",
            "reference_revision",
            "snapshot",
            "is_current",
            "created_at",
            "retired_at",
            "retired_by_id",
            "retirement_reason",
        )
        read_only_fields = fields


def confirm(*, actor, organization_id, draft_id, data):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_preparer(context)
        form = ConfirmationInput(data=data())
        form.is_valid(raise_exception=True)
        values = form.validated_data
        digest = fingerprint({**values, "draft_id": str(draft_id)})
        previous = DraftCustomerDecision.objects.filter(
            organization_id=organization_id, operation_key=values["operation_key"]
        ).first()
        if previous:
            if previous.request_hash != digest:
                raise ReferenceConflict(
                    "This request key identifies a different customer confirmation."
                )
            return DecisionSerializer(previous).data, False
        draft = get_object_or_404(
            DraftOrder.objects.select_for_update(),
            organization_id=organization_id,
            pk=draft_id,
        )
        _require_draft_editable(draft)
        check_revision(draft, values["expected_draft_revision"])
        account, location, value = selected_reference(
            organization_id, values["customer_id"], values["location_id"]
        )
        if fingerprint(value) != values["reference_revision"]:
            raise ReferenceConflict(
                "Customer reference data changed. "
                "Refresh and confirm the current account/site."
            )
        DraftCustomerDecision.objects.filter(
            organization_id=organization_id, draft=draft, is_current=True
        ).update(
            is_current=False,
            retired_at=timezone.now(),
            retired_by_id=actor.pk,
            retirement_reason="reconfirmed",
        )
        source_requested = {
            "customer_name": draft.customer_name,
            "customer_reference": draft.customer_reference,
        }
        draft.customer_name = account.display_name
        draft.save(update_fields=["customer_name", "updated_at"])
        snapshot = {
            **value,
            "source_requested": source_requested,
            "requested": {
                "customer_name": draft.customer_name,
                "customer_reference": draft.customer_reference,
            },
            "not_checked": [
                "prices",
                "currency",
                "stock",
                "tax",
                "credit",
                "delivery_promises",
                "destination_acceptance",
            ],
        }
        decision = DraftCustomerDecision.objects.create(
            organization_id=organization_id,
            draft=draft,
            customer=account,
            location=location,
            actor_id=actor.pk,
            operation_key=values["operation_key"],
            request_hash=digest,
            request=json.loads(json.dumps(values, default=str)),
            reference_revision=values["reference_revision"],
            snapshot=snapshot,
        )
        # Applying the canonical name above changes the aggregate revision even
        # when the original text matched; the decision keeps the source text.
        return DecisionSerializer(decision).data, True


def freeze(*, order, draft, actor_id):
    result = assessment(draft)
    if result["blockers"]:
        raise ValidationError(
            {
                "customer": "Confirm the current account and delivery location "
                "before finalizing."
            }
        )
    decision = result["decision"]
    if decision:
        OrderCustomerSnapshot.objects.create(
            organization_id=order.organization_id,
            order=order,
            draft=draft,
            decision=decision,
            payload=decision.snapshot,
            actor_id=actor_id,
        )


def status(draft):
    result = assessment(draft)
    return {
        "draft_id": str(draft.pk),
        "draft_status": draft.status,
        "requested": {
            "customer_name": draft.customer_name,
            "customer_reference": draft.customer_reference,
        },
        "organization_id": str(draft.organization_id),
        "required": result["required"],
        "confirmed": result["confirmed"],
        "blockers": result["blockers"],
        "draft_revision": draft_revision(draft),
        "decision": DecisionSerializer(result["decision"]).data
        if result["decision"]
        else None,
    }
