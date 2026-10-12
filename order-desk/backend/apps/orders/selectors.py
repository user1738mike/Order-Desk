"""Organization-filtered reads to consume inside an authorized tenant scope."""

from uuid import UUID

from django.db.models import Count, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce, Length
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
from apps.orders.response_limits import (
    MAX_DOCUMENT_REVIEWS,
    MAX_ORDER_DOCUMENTS,
    MAX_ORDER_LINES,
)


def draft_orders_for_workspace(organization_id: UUID) -> QuerySet[DraftOrder]:
    # Pagination count must read headers only. A grouped outer join forces RLS
    # checks over every line before limiting the page; this indexed subquery is
    # evaluated only for returned headers and stays in the same statement scope.
    line_totals = (
        DraftOrderLine.objects.filter(
            organization_id=organization_id, order_id=OuterRef("pk")
        )
        .order_by()
        .values("order_id")
        .annotate(total=Count("pk"))
        .values("total")
    )
    return (
        DraftOrder.objects.filter(organization_id=organization_id)
        .annotate(line_count=Coalesce(Subquery(line_totals), 0))
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
        .prefetch_related(
            Prefetch(
                "reviews",
                queryset=_reviews(organization_id)[: MAX_DOCUMENT_REVIEWS + 1],
                to_attr="_bounded_reviews",
            )
        )
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
                ).order_by("line_number", "id")[: MAX_ORDER_LINES + 1],
                to_attr="_bounded_lines",
            ),
            Prefetch(
                "documents",
                queryset=_documents(organization_id)[: MAX_ORDER_DOCUMENTS + 1],
                to_attr="_bounded_documents",
            ),
        )
        .order_by("-created_at", "id")
    )


def get_purchase_order(organization_id: UUID, order_id: UUID) -> PurchaseOrder:
    return get_object_or_404(
        purchase_orders_for_workspace(organization_id), pk=order_id
    )


def get_export_order(organization_id: UUID, order_id: UUID) -> PurchaseOrder:
    """Scalar parent only; export lines have their own bounded snapshot query."""
    return get_object_or_404(
        PurchaseOrder, organization_id=organization_id, pk=order_id
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


def current_extraction_job(organization_id, order_id, document_id):
    from apps.orders.extraction_services import parser_version
    from apps.orders.models import DocumentExtractionJob

    document = get_private_document(organization_id, order_id, document_id)
    return DocumentExtractionJob.objects.filter(
        organization_id=organization_id,
        document=document,
        source_sha256=document.source_sha256,
        parser_version=parser_version(document.content_type),
    ).first()


def get_extraction_job(organization_id, order_id, document_id):
    job = current_extraction_job(organization_id, order_id, document_id)
    if job is None:
        from django.http import Http404

        raise Http404
    return job


def get_extraction_job_by_id(organization_id, job_id):
    from apps.orders.models import DocumentExtractionJob

    return get_object_or_404(
        DocumentExtractionJob.objects.select_related("document").filter(
            organization_id=organization_id, document__organization_id=organization_id
        ),
        pk=job_id,
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


def catalogue_items_for_draft_lines(organization_id, lines):
    """One equality batch for a fixed-size page, including inactive attachments."""
    from django.db.models import Q

    from apps.catalog.models import CatalogItem

    codes = {
        line.requested_sku.strip()
        for line in lines
        if len(line.requested_sku) <= 4096 and line.requested_sku.strip()
    }
    attached = {line.catalogue_item_id for line in lines if line.catalogue_item_id}
    return (
        CatalogItem.objects.filter(organization_id=organization_id)
        .filter(Q(sku__in=codes) | Q(pk__in=attached))
        .order_by("sku", "id")
    )
