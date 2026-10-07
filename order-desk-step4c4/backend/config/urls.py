from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", include("apps.health.urls")),
    path(
        "api/v1/workspaces/",
        include("apps.organizations.urls", namespace="workspaces"),
    ),
    path("api/v1/auth/", include("apps.accounts.urls")),
]
