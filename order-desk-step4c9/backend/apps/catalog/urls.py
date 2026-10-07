from django.urls import path

from apps.catalog.views import (
    CatalogImportDryRunView,
    CatalogImportExecuteView,
    CatalogItemBySKUView,
    CatalogItemListView,
    CatalogItemUpdateView,
)

app_name = "catalog"

urlpatterns = [
    path("imports/dry-run/", CatalogImportDryRunView.as_view(), name="import-dry-run"),
    path("imports/", CatalogImportExecuteView.as_view(), name="import-execute"),
    path("items/", CatalogItemListView.as_view(), name="items"),
    path("items/by-sku/", CatalogItemBySKUView.as_view(), name="by-sku"),
    path("items/<uuid:item_id>/", CatalogItemUpdateView.as_view(), name="item"),
]
