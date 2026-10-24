"""Verification URL overlay; the normal application is enabled after its gates."""

from django.urls import include, path

from config.urls import urlpatterns

urlpatterns = [
    *urlpatterns,
    path(
        "api/v1/workspaces/<uuid:workspace_id>/product-units/",
        include("apps.product_units.urls"),
    ),
]
