from django.urls import path

from apps.orders.views import (
    DraftOrderDetailView,
    DraftOrderLineAttachmentView,
    DraftOrderLineDetailView,
    DraftOrderLinesView,
    DraftOrderListCreateView,
    OrderDetailView,
    OrderDocumentListCreateView,
    OrderDocumentReviewListCreateView,
    OrderDocumentReviewResolveView,
    OrderLineCreateView,
    OrderListCreateView,
    OrderReviewActionView,
)

app_name = "orders"

draft_urlpatterns = [
    path("", DraftOrderListCreateView.as_view(), name="list"),
    path("<uuid:order_id>/", DraftOrderDetailView.as_view(), name="detail"),
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
]

urlpatterns = [
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
