from django.urls import path

from apps.catalog.views import (
    CatalogItemBySKUView,
    CatalogItemListView,
    CatalogItemUpdateView,
)

app_name = "catalog"

urlpatterns = [
    path("items/", CatalogItemListView.as_view(), name="items"),
    path("items/by-sku/", CatalogItemBySKUView.as_view(), name="by-sku"),
    path("items/<uuid:item_id>/", CatalogItemUpdateView.as_view(), name="item"),
]
