"""Read-only catalogue responses materialized inside a fresh tenant transaction."""

from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors
from apps.catalog.pagination import CatalogPagination
from apps.catalog.serializers import CatalogItemSerializer
from apps.organizations.permissions import HasWorkspaceAccess
from apps.organizations.transactions import tenant_scope


@method_decorator(never_cache, name="dispatch")
class CatalogItemListView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)
    http_method_names = ["get", "head", "options"]

    def get(self, request: Request, workspace_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            items = selectors.catalog_items_for_workspace(
                organization_id=scope.organization_id
            )
            pagination = CatalogPagination()
            page = pagination.paginate_queryset(items, request, view=self)
            # Count, slice evaluation, and all serializer access occur in this scope.
            return pagination.get_paginated_response(
                CatalogItemSerializer(page, many=True).data
            )
