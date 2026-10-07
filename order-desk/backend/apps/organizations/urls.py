from django.urls import include, path

from apps.orders.urls import draft_urlpatterns
from apps.organizations.views import (
    CurrentWorkspaceView,
    WorkspaceContextView,
    WorkspaceListView,
)

app_name = "workspaces"

urlpatterns = [
    path("", WorkspaceListView.as_view(), name="list"),
    path("current/", CurrentWorkspaceView.as_view(), name="current"),
    path("<uuid:workspace_id>/catalog/", include("apps.catalog.urls")),
    path("<uuid:workspace_id>/orders/", include("apps.orders.urls")),
    path(
        "<uuid:workspace_id>/draft-orders/",
        include((draft_urlpatterns, "draft_orders"), namespace="draft-orders"),
    ),
    path(
        "<uuid:workspace_id>/context/",
        WorkspaceContextView.as_view(),
        name="context",
    ),
]
