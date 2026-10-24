from django.urls import path

from apps.orders.incoming_views import IncomingLinkView, IncomingListView
from apps.orders.views import (
    DocumentExtractionApplyView,
    DocumentExtractionRetryView,
    DocumentExtractionReviewView,
    DocumentExtractionView,
    OrderDocumentDownloadView,
)

urlpatterns = [
    path("", IncomingListView.as_view()),
    path("<uuid:document_id>/link/", IncomingLinkView.as_view()),
    path(
        "<uuid:document_id>/download/",
        OrderDocumentDownloadView.as_view(),
        {"order_id": None},
    ),
    path(
        "<uuid:document_id>/extraction/",
        DocumentExtractionView.as_view(),
        {"order_id": None},
    ),
    path(
        "<uuid:document_id>/extraction/retry/",
        DocumentExtractionRetryView.as_view(),
        {"order_id": None},
    ),
    path(
        "<uuid:document_id>/extraction/review/",
        DocumentExtractionReviewView.as_view(),
        {"order_id": None},
    ),
    path(
        "<uuid:document_id>/extraction/apply/",
        DocumentExtractionApplyView.as_view(),
        {"order_id": None},
    ),
]
