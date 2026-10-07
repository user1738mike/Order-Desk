"""Scoped catalogue reads, exact lookup, and administrator mutations."""

from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors, services
from apps.catalog.import_services import catalogue_import_dry_run
from apps.catalog.pagination import CatalogPagination
from apps.catalog.query_params import parse_exact_sku, parse_list_query
from apps.catalog.serializers import CatalogItemSerializer
from apps.catalog.uploads import CatalogUploadLimitHandler, catalogue_upload_bytes
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
            query = parse_list_query(request.query_params)
            items = selectors.catalog_items_for_workspace(
                organization_id=scope.organization_id,
                q=query.q,
                is_active=query.is_active,
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


@method_decorator(never_cache, name="dispatch")
class CatalogItemBySKUView(APIView):
    authentication_classes = (CatalogSessionAuthentication,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)
    http_method_names = ["get", "head", "options"]

    def get(self, request: Request, workspace_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            sku = parse_exact_sku(request.query_params)
            item = selectors.catalog_item_by_sku(
                organization_id=scope.organization_id, sku=sku
            ).first()
            if item is None:
                raise NotFound()
            return Response(CatalogItemSerializer(item).data)


@method_decorator(never_cache, name="dispatch")
class CatalogItemUpdateView(APIView):
    authentication_classes = (CatalogSessionAuthentication,)
    parser_classes = (JSONParser,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)
    http_method_names = ["patch", "options"]

    def patch(self, request: Request, workspace_id: UUID, item_id: UUID) -> Response:
        def update_data() -> object:
            if request.query_params:
                raise ValidationError(
                    {key: ["Unknown query parameter."] for key in request.query_params}
                )
            return request.data

        try:
            data = services.update_catalog_item(
                actor=request.user,
                organization_id=workspace_id,
                item_id=item_id,
                data=update_data,
                materialize=lambda item: CatalogItemSerializer(item).data,
            )
        except DjangoValidationError as error:
            if hasattr(error, "message_dict"):
                details = {
                    "non_field_errors" if key == "__all__" else key: messages
                    for key, messages in error.message_dict.items()
                }
            else:
                details = {"non_field_errors": error.messages}
            raise ValidationError(details) from error
        return Response(data, status=200)


@method_decorator(never_cache, name="dispatch")
class CatalogImportUploadView(APIView):
    """Shared transport guard; Django CSRF may parse multipart during authentication."""

    authentication_classes = (CatalogSessionAuthentication,)
    parser_classes = (MultiPartParser,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)
    http_method_names = ["post", "options"]

    def initialize_request(self, request, *args, **kwargs):
        request.upload_handlers.insert(0, CatalogUploadLimitHandler(request))
        return super().initialize_request(request, *args, **kwargs)


class CatalogImportDryRunView(CatalogImportUploadView):
    def post(self, request: Request, workspace_id: UUID) -> Response:
        return Response(
            catalogue_import_dry_run(
                actor=request.user,
                organization_id=workspace_id,
                data=lambda: catalogue_upload_bytes(request),
            )
        )
