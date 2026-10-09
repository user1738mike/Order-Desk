"""Organization-filtered reads to consume inside an authorized tenant scope."""

from uuid import UUID

from django.db.models import Count, Prefetch, Q, QuerySet
from django.db.models.functions import Length
from django.db.models.lookups import GreaterThan
from django.shortcuts import get_object_or_404

from apps.orders.models import (
    DraftOrder,
    DraftOrderLine,
    OrderDocument,
    OrderDocumentReview,
    PurchaseOrder,
    PurchaseOrderLine,
)


def draft_orders_for_workspace(organization_id: UUID) -> QuerySet[DraftOrder]:
    return (
        DraftOrder.objects.filter(organization_id=organization_id)
        .annotate(line_count=Count("draft_lines"))
        .order_by("-created_at", "-id")
    )


def get_draft_order(organization_id: UUID, order_id: UUID) -> DraftOrder:
    return get_object_or_404(draft_orders_for_workspace(organization_id), pk=order_id)


def get_draft_review(organization_id: UUID, order_id: UUID) -> DraftOrder:
    lines = Q(draft_lines__organization_id=organization_id)
    unmatched = Q(draft_lines__catalogue_item_id__isnull=True)
    missing_quantity = Q(draft_lines__quantity__isnull=True)
    orders = DraftOrder.objects.filter(organization_id=organization_id).annotate(
        line_count=Count("draft_lines", filter=lines),
        unmatched_line_count=Count("draft_lines", filter=lines & unmatched),
        missing_quantity_line_count=Count(
            "draft_lines", filter=lines & missing_quantity
        ),
        unresolved_line_count=Count(
            "draft_lines", filter=lines & (unmatched | missing_quantity)
        ),
        inactive_catalogue_line_count=Count(
            "draft_lines",
            filter=lines
            & Q(
                draft_lines__catalogue_item__organization_id=organization_id,
                draft_lines__catalogue_item__is_active=False,
            ),
        ),
    )
    return get_object_or_404(orders, pk=order_id)


def get_draft_readiness(organization_id: UUID, order_id: UUID) -> DraftOrder:
    lines = Q(draft_lines__organization_id=organization_id)
    orders = DraftOrder.objects.filter(organization_id=organization_id).annotate(
        line_count=Count("draft_lines", filter=lines),
        unmatched_line_count=Count(
            "draft_lines", filter=lines & Q(draft_lines__catalogue_item_id__isnull=True)
        ),
        missing_quantity_line_count=Count(
            "draft_lines", filter=lines & Q(draft_lines__quantity__isnull=True)
        ),
        inactive_catalogue_line_count=Count(
            "draft_lines",
            filter=lines
            & Q(
                draft_lines__catalogue_item__organization_id=organization_id,
                draft_lines__catalogue_item__is_active=False,
            ),
        ),
        long_catalogue_sku_line_count=Count(
            "draft_lines",
            filter=lines
            & Q(draft_lines__catalogue_item_id__isnull=False)
            & Q(GreaterThan(Length("draft_lines__catalogue_sku_snapshot"), 128)),
        ),
    )
    return get_object_or_404(orders, pk=order_id)


def draft_lines_for_order(
    organization_id: UUID, order_id: UUID
) -> QuerySet[DraftOrderLine]:
    return DraftOrderLine.objects.filter(
        organization_id=organization_id, order_id=order_id
    ).order_by("position", "id")


def get_draft_line(
    organization_id: UUID, order_id: UUID, line_id: UUID
) -> DraftOrderLine:
    return get_object_or_404(
        draft_lines_for_order(organization_id, order_id), pk=line_id
    )


def _reviews(organization_id: UUID) -> QuerySet[OrderDocumentReview]:
    return OrderDocumentReview.objects.filter(
        organization_id=organization_id,
        document__organization_id=organization_id,
        document__order__organization_id=organization_id,
    ).order_by("-created_at", "id")


def _documents(organization_id: UUID) -> QuerySet[OrderDocument]:
    return (
        OrderDocument.objects.filter(
            organization_id=organization_id,
            order__organization_id=organization_id,
        )
        .prefetch_related(Prefetch("reviews", queryset=_reviews(organization_id)))
        .order_by("-uploaded_at", "id")
    )


def purchase_orders_for_workspace(organization_id: UUID) -> QuerySet[PurchaseOrder]:
    return (
        PurchaseOrder.objects.filter(organization_id=organization_id)
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=PurchaseOrderLine.objects.filter(
                    organization_id=organization_id,
                    order__organization_id=organization_id,
                ).order_by("line_number", "id"),
            ),
            Prefetch("documents", queryset=_documents(organization_id)),
        )
        .order_by("-created_at", "id")
    )


def get_purchase_order(organization_id: UUID, order_id: UUID) -> PurchaseOrder:
    return get_object_or_404(
        purchase_orders_for_workspace(organization_id), pk=order_id
    )


def documents_for_order(
    organization_id: UUID, order_id: UUID
) -> QuerySet[OrderDocument]:
    get_object_or_404(PurchaseOrder, pk=order_id, organization_id=organization_id)
    return _documents(organization_id).filter(order_id=order_id)


def get_order_document(
    organization_id: UUID, order_id: UUID, document_id: UUID
) -> OrderDocument:
    return get_object_or_404(
        documents_for_order(organization_id, order_id), pk=document_id
    )


def private_document_parent(organization_id: UUID, order_id: UUID) -> PurchaseOrder:
    return get_object_or_404(
        PurchaseOrder.objects.filter(organization_id=organization_id), pk=order_id
    )


def private_documents_for_order(
    organization_id: UUID, order_id: UUID
) -> QuerySet[OrderDocument]:
    private_document_parent(organization_id, order_id)
    return OrderDocument.objects.filter(
        organization_id=organization_id, order_id=order_id
    ).order_by("-uploaded_at", "id")


def get_private_document(
    organization_id: UUID, order_id: UUID, document_id: UUID
) -> OrderDocument:
    return get_object_or_404(
        private_documents_for_order(organization_id, order_id), pk=document_id
    )


def reviews_for_document(
    organization_id: UUID, order_id: UUID, document_id: UUID
) -> QuerySet[OrderDocumentReview]:
    get_object_or_404(
        OrderDocument,
        pk=document_id,
        organization_id=organization_id,
        order_id=order_id,
        order__organization_id=organization_id,
    )
    return _reviews(organization_id).filter(document_id=document_id)


def get_document_review(
    organization_id: UUID, order_id: UUID, document_id: UUID, review_id: UUID
) -> OrderDocumentReview:
    return get_object_or_404(
        reviews_for_document(organization_id, order_id, document_id),
        pk=review_id,
    )
