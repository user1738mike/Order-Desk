from django.urls import path

from apps.orders.views import (
    DocumentExtractionApplyView,
    DocumentExtractionRetryView,
    DocumentExtractionReviewView,
    DocumentExtractionView,
    DraftOrderConversionView,
    DraftOrderDetailView,
    DraftOrderLineAttachmentView,
    DraftOrderLineDetachmentView,
    DraftOrderLineDetailView,
    DraftOrderLinesView,
    DraftOrderListCreateView,
    DraftOrderReadinessView,
    DraftOrderReviewView,
    DraftOrderRevisionView,
    DraftOrderSuggestionAcceptanceView,
    DraftOrderSuggestionsView,
    OrderDetailView,
    OrderDocumentDownloadView,
    OrderDocumentListCreateView,
    OrderDocumentReviewListCreateView,
    OrderDocumentReviewResolveView,
    OrderExportDownloadView,
    OrderExportView,
    OrderLineCreateView,
    OrderListCreateView,
    OrderQueueView,
    OrderReviewActionView,
    PrivateOrderDocumentIntakeView,
)

app_name = "orders"

draft_urlpatterns = [
    path(
        "<uuid:order_id>/suggestions/",
        DraftOrderSuggestionsView.as_view(),
        name="suggestions",
    ),
    path(
        "<uuid:order_id>/lines/<uuid:line_id>/accept-suggestion/",
        DraftOrderSuggestionAcceptanceView.as_view(),
        name="line-accept-suggestion",
    ),
    path("", DraftOrderListCreateView.as_view(), name="list"),
    path("<uuid:order_id>/", DraftOrderDetailView.as_view(), name="detail"),
    path(
        "<uuid:order_id>/convert/", DraftOrderConversionView.as_view(), name="convert"
    ),
    path("<uuid:order_id>/review/", DraftOrderReviewView.as_view(), name="review"),
    path(
        "<uuid:order_id>/revision/", DraftOrderRevisionView.as_view(), name="revision"
    ),
    path(
        "<uuid:order_id>/readiness/",
        DraftOrderReadinessView.as_view(),
        name="readiness",
    ),
    path("<uuid:order_id>/lines/", DraftOrderLinesView.as_view(), name="lines"),
    path(
        "<uuid:order_id>/lines/<uuid:line_id>/",
        DraftOrderLineDetailView.as_view(),
        name="line-detail",
    ),
    path(
        "<uuid:order_id>/lines/<uuid:line_id>/attach/",
        DraftOrderLineAttachmentView.as_view(),
        name="line-catalogue-attach",
    ),
    path(
        "<uuid:order_id>/lines/<uuid:line_id>/detach/",
        DraftOrderLineDetachmentView.as_view(),
        name="line-catalogue-detach",
    ),
]

urlpatterns = [
    path("queue/", OrderQueueView.as_view(), name="queue"),
    path("<uuid:order_id>/exports/", OrderExportView.as_view(), name="exports"),
    path(
        "<uuid:order_id>/exports/<uuid:artifact_id>/download/",
        OrderExportDownloadView.as_view(),
        name="export-download",
    ),
    path(
        "<uuid:order_id>/documents/<uuid:document_id>/extraction/review/",
        DocumentExtractionReviewView.as_view(),
        name="document-extraction-review",
    ),
    path(
        "<uuid:order_id>/documents/<uuid:document_id>/extraction/apply/",
        DocumentExtractionApplyView.as_view(),
        name="document-extraction-apply",
    ),
    path(
        "<uuid:order_id>/documents/<uuid:document_id>/extraction/",
        DocumentExtractionView.as_view(),
        name="document-extraction",
    ),
    path(
        "<uuid:order_id>/documents/<uuid:document_id>/extraction/retry/",
        DocumentExtractionRetryView.as_view(),
        name="document-extraction-retry",
    ),
    path(
        "<uuid:order_id>/documents/intake/",
        PrivateOrderDocumentIntakeView.as_view(),
        name="private-document-intake",
    ),
    path(
        "<uuid:order_id>/documents/<uuid:document_id>/download/",
        OrderDocumentDownloadView.as_view(),
        name="document-download",
    ),
    path("", OrderListCreateView.as_view(), name="list-create"),
    path("<uuid:order_id>/", OrderDetailView.as_view(), name="detail"),
    path("<uuid:order_id>/lines/", OrderLineCreateView.as_view(), name="lines"),
    path(
        "<uuid:order_id>/documents/",
        OrderDocumentListCreateView.as_view(),
        name="documents",
    ),
    path(
        "<uuid:order_id>/documents/<uuid:document_id>/reviews/",
        OrderDocumentReviewListCreateView.as_view(),
        name="document-reviews",
    ),
    path(
        "<uuid:order_id>/documents/<uuid:document_id>/reviews/<uuid:review_id>/resolve/",
        OrderDocumentReviewResolveView.as_view(),
        name="document-review-resolve",
    ),
    path(
        "<uuid:order_id>/submit/",
        OrderReviewActionView.as_view(action="submit"),
        name="submit",
    ),
    path(
        "<uuid:order_id>/approve/",
        OrderReviewActionView.as_view(action="approve"),
        name="approve",
    ),
    path(
        "<uuid:order_id>/reject/",
        OrderReviewActionView.as_view(action="reject"),
        name="reject",
    ),
]
