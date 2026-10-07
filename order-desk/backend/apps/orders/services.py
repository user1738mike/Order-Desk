"""Write orders in an outer, freshly authorized PostgreSQL tenant transaction.

An optional materializer consumes related data before the scope closes. Without
one, callers receive a model whose scalar fields are already loaded; fetching
its relations later does not establish an authorized tenant transaction.
"""

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.orders.models import (
    DraftOrder,
    DraftOrderLine,
    ExtractionReviewStatus,
    OrderDocument,
    OrderDocumentReview,
    OrderDocumentStatus,
    OrderStatus,
    PurchaseOrder,
    PurchaseOrderLine,
)
from apps.organizations.models import MembershipRole
from apps.organizations.transactions import tenant_scope

Materializer = Callable[[Any], Any]

DRAFT_LINE_POSITION_CONFLICT = "This draft already has a line at this position."


class DraftLinePositionConflict(Exception):
    """A requested position is already occupied in this draft."""


def _result(instance, materialize: Materializer | None):
    return materialize(instance) if materialize is not None else instance


def _require_writer(context) -> None:
    if context.role not in {MembershipRole.ADMIN, MembershipRole.REVIEWER}:
        raise PermissionDenied("Workspace review access is required.")


def create_draft_order(
    *,
    actor,
    organization_id: UUID,
    customer_name: str = "",
    customer_reference: str = "",
    original_intake_text: str = "",
    materialize: Materializer | None = None,
):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = DraftOrder(
            organization_id=organization_id,
            initiating_user_id=actor.pk,
            customer_name=customer_name,
            customer_reference=customer_reference,
            original_intake_text=original_intake_text,
        )
        order.full_clean()
        order.save()
        return _result(order, materialize)


def create_draft_order_line(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    data: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
    materialize: Materializer | None = None,
):
    """Authorize and lock before calling input validation; materialize in scope."""
    try:
        with tenant_scope(
            user=actor, workspace_id=organization_id, write=True
        ) as context:
            _require_writer(context)
            order = get_object_or_404(
                DraftOrder.objects.select_for_update().filter(
                    organization_id=context.organization_id
                ),
                pk=order_id,
            )
            values = data() if callable(data) else data
            allowed = {
                "position",
                "requested_sku",
                "requested_description",
                "quantity",
                "unit",
            }
            unknown = set(values) - allowed
            if unknown:
                raise ValidationError(
                    {key: ["Unsupported field."] for key in sorted(unknown)}
                )
            line = DraftOrderLine(
                organization_id=context.organization_id, order_id=order.pk, **values
            )
            # Validate field types before using a direct caller's position in SQL.
            line.clean_fields()
            if DraftOrderLine.objects.filter(
                order_id=order.pk,
                organization_id=context.organization_id,
                position=line.position,
            ).exists():
                raise DraftLinePositionConflict
            line.full_clean()
            line.save()
            return _result(line, materialize)
    except IntegrityError as error:
        diagnostics = getattr(error.__cause__, "diag", None)
        if (
            getattr(error.__cause__, "sqlstate", None) == "23505"
            and getattr(diagnostics, "constraint_name", None)
            == "draftline_order_position_unique"
        ):
            raise DraftLinePositionConflict from error
        raise


def _locked_order(*, organization_id: UUID, order_id: UUID) -> PurchaseOrder:
    order = (
        PurchaseOrder.objects.select_for_update()
        .filter(pk=order_id, organization_id=organization_id)
        .first()
    )
    if order is None:
        raise ValidationError(
            {"order_id": "Select a valid purchase order in this workspace."}
        )
    return order


def _require_editable_order(order: PurchaseOrder) -> None:
    if not order.is_active or order.status not in {
        OrderStatus.DRAFT,
        OrderStatus.REJECTED,
    }:
        raise ValidationError(
            {"status": "Only active draft or rejected orders can be modified."}
        )


def _require_reviewable_order(order: PurchaseOrder) -> None:
    if not order.is_active or order.status == OrderStatus.APPROVED:
        raise ValidationError(
            {"status": "An inactive or approved order cannot be reviewed."}
        )


def create_purchase_order(
    *,
    actor,
    organization_id: UUID,
    customer_name: str,
    purchase_order_number: str,
    status: str = OrderStatus.DRAFT,
    comments: str = "",
    source_document: str = "",
    is_active: bool = True,
    materialize: Materializer | None = None,
):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        if status not in {OrderStatus.DRAFT, OrderStatus.PENDING_REVIEW}:
            raise ValidationError(
                {"status": "Orders may only be created as draft or pending review."}
            )

        order = PurchaseOrder(
            organization_id=organization_id,
            created_by=actor,
            customer_name=customer_name,
            purchase_order_number=purchase_order_number,
            status=status,
            comments=comments,
            source_document=source_document,
            is_active=is_active,
        )
        order.full_clean()
        order.save()
        return _result(order, materialize)


def submit_purchase_order_for_review(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    materialize: Materializer | None = None,
):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = _locked_order(organization_id=organization_id, order_id=order_id)
        _require_editable_order(order)

        order.status = OrderStatus.PENDING_REVIEW
        order.reviewed_by = None
        order.reviewed_at = None
        order.review_note = ""
        order.full_clean()
        order.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "updated_at",
            ]
        )
        return _result(order, materialize)


def approve_purchase_order(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    review_note: str = "",
    materialize: Materializer | None = None,
):
    return _set_order_decision(
        actor=actor,
        organization_id=organization_id,
        order_id=order_id,
        status=OrderStatus.APPROVED,
        review_note=review_note,
        materialize=materialize,
    )


def reject_purchase_order(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    review_note: str = "",
    materialize: Materializer | None = None,
):
    return _set_order_decision(
        actor=actor,
        organization_id=organization_id,
        order_id=order_id,
        status=OrderStatus.REJECTED,
        review_note=review_note,
        materialize=materialize,
    )


def _set_order_decision(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    status: str,
    review_note: str,
    materialize: Materializer | None,
):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = _locked_order(organization_id=organization_id, order_id=order_id)
        _require_reviewable_order(order)
        if order.status != OrderStatus.PENDING_REVIEW:
            raise ValidationError(
                {"status": "Only pending-review orders can be approved or rejected."}
            )

        order.status = status
        order.reviewed_by = actor
        order.reviewed_at = timezone.now()
        order.review_note = (review_note or "").strip()
        order.full_clean()
        order.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "updated_at",
            ]
        )
        return _result(order, materialize)


def create_order_document(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    file,
    original_name: str = "",
    content_type: str = "",
    size_bytes: int | None = None,
    materialize: Materializer | None = None,
):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = _locked_order(organization_id=organization_id, order_id=order_id)
        _require_editable_order(order)
        if file is None:
            raise ValidationError({"file": "A file is required."})

        document = OrderDocument(
            order=order,
            organization_id=organization_id,
            uploaded_by=actor,
            file=file,
            original_name=original_name or getattr(file, "name", "upload"),
            content_type=(content_type or "").strip(),
            size_bytes=int(size_bytes)
            if size_bytes is not None
            else (getattr(file, "size", 0) or 0),
        )
        document.full_clean()
        document.save()
        return _result(document, materialize)


def create_document_review(
    *,
    actor,
    organization_id: UUID,
    document_id: UUID,
    order_id: UUID | None = None,
    vendor_name: str = "",
    extracted_order_number: str = "",
    line_count: int = 0,
    grand_total: Decimal | int | float = 0,
    status: str = ExtractionReviewStatus.NEEDS_REVIEW,
    notes: str = "",
    materialize: Materializer | None = None,
):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        documents = OrderDocument.objects.filter(
            pk=document_id, organization_id=organization_id
        )
        if order_id is not None:
            documents = documents.filter(order_id=order_id)
        parent_order_id = documents.values_list("order_id", flat=True).first()
        if parent_order_id is None:
            raise ValidationError(
                {"document_id": "Select a valid source document in this workspace."}
            )
        order = _locked_order(organization_id=organization_id, order_id=parent_order_id)
        _require_reviewable_order(order)
        document = documents.select_for_update().get()
        if status != ExtractionReviewStatus.NEEDS_REVIEW:
            raise ValidationError(
                {"status": "Document reviews must start in the needs_review state."}
            )
        if OrderDocumentReview.objects.filter(
            document_id=document_id,
            organization_id=organization_id,
            status=ExtractionReviewStatus.NEEDS_REVIEW,
        ).exists():
            raise ValidationError(
                {"status": "This document already has a pending extraction review."}
            )

        review = OrderDocumentReview(
            document=document,
            organization_id=organization_id,
            created_by=actor,
            vendor_name=vendor_name,
            extracted_order_number=extracted_order_number,
            line_count=line_count,
            grand_total=grand_total,
            status=status,
            notes=notes,
        )
        review.full_clean()
        review.save()
        document.status = OrderDocumentStatus.PENDING_REVIEW
        document.save(update_fields=["status"])
        return _result(review, materialize)


def resolve_document_review(
    *,
    actor,
    organization_id: UUID,
    review_id: UUID,
    status: str,
    notes: str = "",
    order_id: UUID | None = None,
    document_id: UUID | None = None,
    materialize: Materializer | None = None,
):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        reviews = OrderDocumentReview.objects.filter(
            pk=review_id, organization_id=organization_id
        )
        if document_id is not None:
            reviews = reviews.filter(document_id=document_id)
        if order_id is not None:
            reviews = reviews.filter(
                document__order_id=order_id, document__organization_id=organization_id
            )
        parent = reviews.values("document_id", "document__order_id").first()
        if parent is None:
            raise ValidationError(
                {"review_id": "Select a valid document review in this workspace."}
            )
        order = _locked_order(
            organization_id=organization_id, order_id=parent["document__order_id"]
        )
        _require_reviewable_order(order)
        document = OrderDocument.objects.select_for_update().get(
            pk=parent["document_id"], organization_id=organization_id, order_id=order.pk
        )
        review = reviews.select_for_update(of=("self",)).get()
        if review.status != ExtractionReviewStatus.NEEDS_REVIEW:
            raise ValidationError(
                {"status": "A completed extraction review cannot be changed."}
            )
        if status not in {
            ExtractionReviewStatus.ACCEPTED,
            ExtractionReviewStatus.REJECTED,
        }:
            raise ValidationError(
                {"status": "Only accepted or rejected review outcomes are allowed."}
            )

        review.status = status
        review.notes = notes
        review.resolved_by = actor
        review.resolved_at = timezone.now()
        review.full_clean()
        review.save(
            update_fields=[
                "status",
                "notes",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )
        document.status = (
            OrderDocumentStatus.RECEIVED
            if status == ExtractionReviewStatus.ACCEPTED
            else OrderDocumentStatus.REJECTED
        )
        document.save(update_fields=["status"])
        return _result(review, materialize)


def add_order_line(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    line_number: int,
    sku: str,
    description: str = "",
    quantity: Decimal | int | float = 1,
    unit: str = "ea",
    materialize: Materializer | None = None,
):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = _locked_order(organization_id=organization_id, order_id=order_id)
        _require_editable_order(order)
        line = PurchaseOrderLine(
            order=order,
            organization_id=organization_id,
            line_number=line_number,
            sku=sku,
            description=description,
            quantity=quantity,
            unit=unit,
        )
        line.full_clean()
        line.save()
        return _result(line, materialize)
