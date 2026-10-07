from django.urls import path

from apps.catalog.views import CatalogItemListView, CatalogItemUpdateView

app_name = "catalog"

urlpatterns = [
    path("items/", CatalogItemListView.as_view(), name="items"),
    path("items/<uuid:item_id>/", CatalogItemUpdateView.as_view(), name="item"),
]
