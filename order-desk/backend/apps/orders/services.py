"""Write orders in an outer, freshly authorized PostgreSQL tenant transaction.

An optional materializer consumes related data before the scope closes. Without
one, callers receive a model whose scalar fields are already loaded; fetching
its relations later does not establish an authorized tenant transaction.
"""

import logging
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.catalog.models import CatalogItem
from apps.orders import selectors
from apps.orders.document_files import bounded_document_file
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
from apps.orders.readiness import evaluate_draft_readiness
from apps.organizations.models import MembershipRole
from apps.organizations.transactions import tenant_scope

Materializer = Callable[[Any], Any]
logger = logging.getLogger(__name__)

DRAFT_LINE_POSITION_CONFLICT = "This draft already has a line at this position."
DRAFT_LINE_EDITABLE_FIELDS = frozenset(
    {"requested_sku", "requested_description", "quantity", "unit"}
)


class DraftLinePositionConflict(Exception):
    """A requested position is already occupied in this draft."""


class DraftLineCatalogueAttachmentConflict(Exception):
    """A requested line is already attached to a catalogue item."""


class DraftAlreadyConverted(Exception):
    """The immutable source cannot be edited after conversion."""


class DraftNotReady(Exception):
    def __init__(self, reasons):
        paths = {
            "customer_name_missing": "customer_name",
            "lines_missing": "lines",
            "quantity_missing": "lines.quantity",
            "catalogue_unmatched": "lines.catalogue_item_id",
            "catalogue_inactive": "lines.catalogue_item_id",
            "catalogue_sku_too_long": "lines.catalogue_sku_snapshot",
        }
        self.reasons = [{**reason, "path": paths[reason["code"]]} for reason in reasons]
        super().__init__("Draft is not ready for conversion.")


class DraftConversionNumberConflict(Exception):
    """The reserved source-derived number belongs to an unrelated order."""


def _require_draft_editable(order) -> None:
    if order.status != DraftOrder.Status.DRAFT:
        raise DraftAlreadyConverted


def _persist_order_record(instance, *, preserve_snapshot=False):
    if preserve_snapshot:
        # Existing clean() normalizes ordinary input. A reviewed stored snapshot
        # must preserve exact strings; apply all validation without normalization.
        instance.clean_fields()
        instance.validate_unique()
        instance.validate_constraints()
    else:
        instance.full_clean()
    instance.save()
    return instance


def convert_draft_to_purchase_order(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    data: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
    materialize: Materializer | None = None,
):
    """Serialize conversion with all cooperating writers; seal source and copy."""
    try:
        with tenant_scope(
            user=actor, workspace_id=organization_id, write=True
        ) as context:
            if context.role not in {MembershipRole.ADMIN}:
                raise PermissionDenied("Workspace administrator access is required.")
            draft = get_object_or_404(
                DraftOrder.objects.select_for_update().filter(
                    organization_id=context.organization_id
                ),
                pk=order_id,
            )
            values = data() if callable(data) else data
            if not isinstance(values, Mapping):
                raise ValidationError("Provide an empty object.")
            if values:
                raise ValidationError(
                    {key: ["Unsupported field."] for key in sorted(values)}
                )
            existing = PurchaseOrder.objects.filter(
                source_draft_id=draft.pk, organization_id=context.organization_id
            ).first()
            if existing is not None:
                return _result(existing, materialize), False
            _require_draft_editable(draft)
            lines = list(
                selectors.draft_lines_for_order(
                    context.organization_id, draft.pk
                ).select_for_update()
            )
            readiness = evaluate_draft_readiness(
                selectors.get_draft_readiness(context.organization_id, draft.pk)
            )
            if not readiness["ready_to_convert"]:
                raise DraftNotReady(readiness["blocking_reasons"])
            number = "DRAFT-" + draft.pk.hex
            if PurchaseOrder.objects.filter(
                organization_id=context.organization_id, purchase_order_number=number
            ).exists():
                raise DraftConversionNumberConflict
            order = _persist_order_record(
                PurchaseOrder(
                    organization_id=context.organization_id,
                    created_by_id=context.user_id,
                    customer_name=draft.customer_name,
                    purchase_order_number=number,
                ),
                preserve_snapshot=True,
            )
            for line in lines:
                _persist_order_record(
                    PurchaseOrderLine(
                        organization_id=context.organization_id,
                        order_id=order.pk,
                        line_number=line.position,
                        sku=line.catalogue_sku_snapshot,
                        description=line.catalogue_description_snapshot,
                        quantity=line.quantity,
                        unit=line.unit,
                    ),
                    preserve_snapshot=True,
                )
            order.source_draft_id = draft.pk
            order.save(update_fields=["source_draft"])
            draft.status = DraftOrder.Status.CONVERTED
            draft.save(update_fields=["status", "updated_at"])
            return _result(order, materialize), True
    except IntegrityError as error:
        diagnostics = getattr(error.__cause__, "diag", None)
        if (
            getattr(error.__cause__, "sqlstate", None) == "23505"
            and getattr(diagnostics, "constraint_name", None)
            == "purchaseorder_org_number_unique"
        ):
            raise DraftConversionNumberConflict from error
        raise


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


def update_draft_customer_fields(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    data: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
    materialize: Materializer | None = None,
):
    """Apply customer-only changes to fresh protected, locked draft state."""
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = get_object_or_404(
            DraftOrder.objects.select_for_update().filter(
                organization_id=context.organization_id
            ),
            pk=order_id,
        )
        _require_draft_editable(order)
        values = data() if callable(data) else data
        unknown = set(values) - {"customer_name", "customer_reference"}
        if unknown:
            raise ValidationError(
                {key: ["Unsupported field."] for key in sorted(unknown)}
            )
        if not values:
            raise ValidationError("Provide at least one customer field.")
        invalid = {
            field: ["Not a valid string."]
            for field, value in values.items()
            if not isinstance(value, str)
        }
        if invalid:
            raise ValidationError(invalid)
        changed = []
        for field, value in values.items():
            if getattr(order, field) != value:
                setattr(order, field, value)
                changed.append(field)
        order.full_clean()
        if changed:
            order.save(update_fields=[*changed, "updated_at"])
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
            _require_draft_editable(order)
            values = data() if callable(data) else data
            allowed = DRAFT_LINE_EDITABLE_FIELDS | {"position"}
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


def update_draft_order_line(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    line_id: UUID,
    data: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
    materialize: Materializer | None = None,
):
    """Merge a patch into fresh locked state, preserving successful no-ops."""
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = get_object_or_404(
            DraftOrder.objects.select_for_update().filter(
                organization_id=context.organization_id
            ),
            pk=order_id,
        )
        _require_draft_editable(order)
        line = get_object_or_404(
            DraftOrderLine.objects.select_for_update().filter(
                organization_id=context.organization_id, order_id=order.pk
            ),
            pk=line_id,
        )
        values = data() if callable(data) else data
        unknown = set(values) - DRAFT_LINE_EDITABLE_FIELDS
        if unknown:
            raise ValidationError(
                {key: ["Unsupported field."] for key in sorted(unknown)}
            )
        original = {field: getattr(line, field) for field in values}
        for field, value in values.items():
            setattr(line, field, value)
        line.full_clean()
        changed = [field for field in values if getattr(line, field) != original[field]]
        if changed:
            line.save(update_fields=[*changed, "updated_at"])
        return _result(line, materialize)


def attach_catalogue_item_to_draft_order_line(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    line_id: UUID,
    catalogue_item_id: UUID | Callable[[], UUID],
    materialize: Materializer | None = None,
):
    """Attach one active, same-workspace catalogue item to an unmatched line."""
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = get_object_or_404(
            DraftOrder.objects.select_for_update().filter(
                organization_id=context.organization_id
            ),
            pk=order_id,
        )
        _require_draft_editable(order)
        line = get_object_or_404(
            DraftOrderLine.objects.select_for_update().filter(
                organization_id=context.organization_id, order_id=order.pk
            ),
            pk=line_id,
        )
        if line.catalogue_item_id is not None:
            raise DraftLineCatalogueAttachmentConflict
        item_id = (
            catalogue_item_id() if callable(catalogue_item_id) else catalogue_item_id
        )
        item = get_object_or_404(
            # Catalogue writes take our organization lock too. A row write lock
            # here would apply catalogue's admin-only UPDATE policy to reviewers.
            CatalogItem.objects.filter(
                pk=item_id,
                organization_id=context.organization_id,
                is_active=True,
            )
        )
        line.catalogue_item_id = item.pk
        line.catalogue_sku_snapshot = item.sku
        line.catalogue_description_snapshot = item.description
        line.full_clean()
        line.save(
            update_fields=[
                "catalogue_item",
                "catalogue_sku_snapshot",
                "catalogue_description_snapshot",
                "updated_at",
            ]
        )
        return _result(line, materialize)


def detach_catalogue_item_from_draft_order_line(
    *,
    actor,
    organization_id: UUID,
    order_id: UUID,
    line_id: UUID,
    data: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
    materialize: Materializer | None = None,
):
    """Clear catalogue state only when requested identity remains valid."""
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_writer(context)
        order = get_object_or_404(
            DraftOrder.objects.select_for_update().filter(
                organization_id=context.organization_id
            ),
            pk=order_id,
        )
        _require_draft_editable(order)
        line = get_object_or_404(
            DraftOrderLine.objects.select_for_update().filter(
                organization_id=context.organization_id, order_id=order.pk
            ),
            pk=line_id,
        )
        values = data() if callable(data) else data
        if values:
            raise ValidationError(
                {key: ["Unsupported field."] for key in sorted(values)}
            )
        attached = line.catalogue_item_id is not None
        line.catalogue_item_id = None
        line.catalogue_sku_snapshot = ""
        line.catalogue_description_snapshot = ""
        line.full_clean()
        if attached:
            line.save(
                update_fields=[
                    "catalogue_item",
                    "catalogue_sku_snapshot",
                    "catalogue_description_snapshot",
                    "updated_at",
                ]
            )
        return _result(line, materialize)


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
        _persist_order_record(order)
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
    owned_name = None
    storage = OrderDocument._meta.get_field("file").storage
    try:
        with tenant_scope(
            user=actor, workspace_id=organization_id, write=True
        ) as context:
            _require_writer(context)
            order = _locked_order(organization_id=organization_id, order_id=order_id)
            _require_editable_order(order)
            upload = file() if callable(file) else file
            if upload is None:
                raise ValidationError({"file": "A file is required."})

            with bounded_document_file(upload) as bounded:
                document = OrderDocument(
                    order=order,
                    organization_id=organization_id,
                    uploaded_by=actor,
                    file=bounded,
                    original_name=original_name or upload.name,
                    content_type=(
                        content_type or getattr(upload, "content_type", "") or ""
                    ).strip(),
                    size_bytes=int(size_bytes)
                    if size_bytes is not None
                    else bounded.size,
                )
                document.full_clean()
                field = document._meta.get_field("file")
                # A fresh, server-generated name belongs only to this attempt.
                candidate = field.generate_filename(document, uuid4().hex)
                if storage.exists(candidate):
                    raise ValidationError({"file": "Unable to allocate a new file."})
                owned_name = candidate
                owned_name = storage.save(
                    candidate, bounded, max_length=field.max_length
                )
                document.file.name = owned_name
                document.file._committed = True
                document.file._file = None
                document.save()
                return _result(document, materialize)
    except Exception:
        if owned_name is not None:
            try:
                storage.delete(owned_name)
            except Exception:
                # Keep the original error and avoid logging private names/content.
                logger.error("Source document rollback cleanup failed.")
        raise


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
        if order.source_draft_id is not None:
            raise ValidationError({"order": "Converted order lines are immutable."})
        line = PurchaseOrderLine(
            order=order,
            organization_id=organization_id,
            line_number=line_number,
            sku=sku,
            description=description,
            quantity=quantity,
            unit=unit,
        )
        _persist_order_record(line)
        return _result(line, materialize)
