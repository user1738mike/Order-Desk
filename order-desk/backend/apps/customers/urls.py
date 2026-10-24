from django.urls import path

from apps.customers.views import (
    CustomerAliasRetirementView,
    CustomerChildrenView,
    CustomerConfirmationHistoryView,
    CustomerConfirmationView,
    CustomerDetailView,
    CustomerImportView,
    CustomerListView,
    CustomerLocationDetailView,
    CustomerOperationView,
    CustomerResolutionView,
    OrderCustomerSnapshotView,
)

urlpatterns = [
    path("operations/<uuid:operation_key>/", CustomerOperationView.as_view()),
    path("imports/validate/", CustomerImportView.as_view()),
    path("imports/create/", CustomerImportView.as_view(execute=True)),
    path("drafts/<uuid:draft_id>/confirmation/", CustomerConfirmationView.as_view()),
    path(
        "drafts/<uuid:draft_id>/confirmation/history/",
        CustomerConfirmationHistoryView.as_view(),
    ),
    path("orders/<uuid:order_id>/snapshot/", OrderCustomerSnapshotView.as_view()),
    path("", CustomerListView.as_view()),
    path("resolve/", CustomerResolutionView.as_view()),
    path("<uuid:customer_id>/", CustomerDetailView.as_view()),
    path(
        "<uuid:customer_id>/locations/", CustomerChildrenView.as_view(kind="location")
    ),
    path(
        "<uuid:customer_id>/locations/<uuid:location_id>/",
        CustomerLocationDetailView.as_view(),
    ),
    path("<uuid:customer_id>/aliases/", CustomerChildrenView.as_view(kind="alias")),
    path(
        "<uuid:customer_id>/aliases/<uuid:alias_id>/retire/",
        CustomerAliasRetirementView.as_view(),
    ),
]
