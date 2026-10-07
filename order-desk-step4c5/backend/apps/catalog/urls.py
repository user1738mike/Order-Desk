from django.urls import path

from apps.catalog.views import CatalogItemListView

app_name = "catalog"

urlpatterns = [
    path("items/", CatalogItemListView.as_view(), name="items"),
]
