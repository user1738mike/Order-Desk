"""Catalogue reads and administrator creation in fresh tenant transactions."""

from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors, services
from apps.catalog.pagination import CatalogPagination
from apps.catalog.serializers import CatalogItemSerializer
from apps.organizations.permissions import HasWorkspaceAccess
from apps.organizations.transactions import tenant_scope


class CatalogSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request: Request) -> None:
        # Django checks the real HttpRequest without triggering DRF's POST
        # property, which would parse JSON before protected authorization.
        super().enforce_csrf(request._request)


@method_decorator(never_cache, name="dispatch")
class CatalogItemListView(APIView):
    authentication_classes = (CatalogSessionAuthentication,)
    parser_classes = (JSONParser,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)
    http_method_names = ["get", "head", "post", "options"]

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

    def post(self, request: Request, workspace_id: UUID) -> Response:
        def creation_data() -> object:
            # Invoked only after the service's protected, fresh admin check.
            if request.query_params:
                raise ValidationError(
                    {key: ["Unknown query parameter."] for key in request.query_params}
                )
            return request.data

        try:
            data = services.create_catalog_item(
                actor=request.user,
                organization_id=workspace_id,
                data=creation_data,
                materialize=lambda item: CatalogItemSerializer(item).data,
            )
        except services.CatalogSKUConflict:
            return Response({"detail": services.CATALOG_SKU_CONFLICT}, status=409)
        except DjangoValidationError as error:
            if hasattr(error, "message_dict"):
                details = {
                    "non_field_errors" if key == "__all__" else key: messages
                    for key, messages in error.message_dict.items()
                }
            else:
                details = {"non_field_errors": error.messages}
            raise ValidationError(details) from error
        return Response(data, status=201)
