"""Session-authenticated order APIs materialize data inside tenant transactions."""

from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders import selectors, services
from apps.orders.pagination import DraftOrderPagination, validate_draft_query
from apps.orders.serializers import (
    DocumentReviewResolveSerializer,
    DraftOrderCreateSerializer,
    DraftOrderCreationSerializer,
    DraftOrderDetailSerializer,
    DraftOrderLineReadSerializer,
    DraftOrderSummarySerializer,
    OrderDocumentCreateSerializer,
    OrderDocumentReviewCreateSerializer,
    OrderDocumentReviewSerializer,
    OrderDocumentSerializer,
    OrderReviewActionSerializer,
    PurchaseOrderCreateSerializer,
    PurchaseOrderLineCreateSerializer,
    PurchaseOrderLineSerializer,
    PurchaseOrderSerializer,
)
from apps.organizations.permissions import HasWorkspaceAccess
from apps.organizations.transactions import tenant_scope


@method_decorator(never_cache, name="dispatch")
class DraftOrderReadView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)
    http_method_names = ["get", "head", "options"]


class DraftOrderListCreateView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)

    def get(self, request: Request, workspace_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            paginator = DraftOrderPagination()
            page = paginator.paginate_queryset(
                selectors.draft_orders_for_workspace(scope.organization_id),
                request,
                view=self,
            )
            return paginator.get_paginated_response(
                DraftOrderSummarySerializer(page, many=True).data
            )

    def post(self, request: Request, workspace_id: UUID) -> Response:
        data = DraftOrderCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = services.create_draft_order(
            actor=request.user,
            organization_id=workspace_id,
            materialize=lambda order: DraftOrderCreationSerializer(
                order, context={"request": request}
            ).data,
            **data.validated_data,
        )
        return Response(result, status=201)


class DraftOrderDetailView(DraftOrderReadView):
    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            validate_draft_query(request.query_params, allow_page=False)
            order = selectors.get_draft_order(scope.organization_id, order_id)
            return Response(
                DraftOrderDetailSerializer(order, context={"request": request}).data
            )


class DraftOrderLinesView(DraftOrderReadView):
    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            validate_draft_query(request.query_params, allow_page=True)
            selectors.get_draft_order(scope.organization_id, order_id)
            paginator = DraftOrderPagination()
            page = paginator.paginate_queryset(
                selectors.draft_lines_for_order(scope.organization_id, order_id),
                request,
                view=self,
            )
            return paginator.get_paginated_response(
                DraftOrderLineReadSerializer(page, many=True).data
            )


@method_decorator(never_cache, name="dispatch")
class WorkspaceOrderView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)

    def handle_exception(self, exc):
        # Services have exited their atomic scope before errors reach this layer.
        if isinstance(exc, DjangoValidationError):
            details = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            if isinstance(details, dict) and any(
                key in details for key in ("order_id", "document_id", "review_id")
            ):
                exc = Http404()
            else:
                exc = ValidationError(details)
        elif isinstance(exc, IntegrityError):
            exc = ValidationError("The change conflicts with an existing record.")
        return super().handle_exception(exc)

    def paginated(self, request, queryset, serializer):
        # The caller must be inside its read scope through response serialization.
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(serializer(page, many=True).data)


class OrderListCreateView(WorkspaceOrderView):
    def get(self, request: Request, workspace_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            response = self.paginated(
                request,
                selectors.purchase_orders_for_workspace(workspace_id),
                PurchaseOrderSerializer,
            )
        return response

    def post(self, request: Request, workspace_id: UUID) -> Response:
        data = PurchaseOrderCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = services.create_purchase_order(
            actor=request.user,
            organization_id=workspace_id,
            materialize=lambda order: PurchaseOrderSerializer(order).data,
            **data.validated_data,
        )
        return Response(result, status=201)


class OrderDetailView(WorkspaceOrderView):
    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            order = selectors.get_purchase_order(workspace_id, order_id)
            result = PurchaseOrderSerializer(order).data
        return Response(result)


class OrderLineCreateView(WorkspaceOrderView):
    def post(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        data = PurchaseOrderLineCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = services.add_order_line(
            actor=request.user,
            organization_id=workspace_id,
            order_id=order_id,
            materialize=lambda line: PurchaseOrderLineSerializer(line).data,
            **data.validated_data,
        )
        return Response(result, status=201)


class OrderDocumentListCreateView(WorkspaceOrderView):
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            response = self.paginated(
                request,
                selectors.documents_for_order(workspace_id, order_id),
                OrderDocumentSerializer,
            )
        return response

    def post(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        data = OrderDocumentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        uploaded = data.validated_data["file"]
        result = services.create_order_document(
            actor=request.user,
            organization_id=workspace_id,
            order_id=order_id,
            file=uploaded,
            content_type=getattr(uploaded, "content_type", ""),
            materialize=lambda document: OrderDocumentSerializer(document).data,
        )
        return Response(result, status=201)


class OrderDocumentReviewListCreateView(WorkspaceOrderView):
    def get(
        self, request: Request, workspace_id: UUID, order_id: UUID, document_id: UUID
    ) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            response = self.paginated(
                request,
                selectors.reviews_for_document(workspace_id, order_id, document_id),
                OrderDocumentReviewSerializer,
            )
        return response

    def post(
        self, request: Request, workspace_id: UUID, order_id: UUID, document_id: UUID
    ) -> Response:
        data = OrderDocumentReviewCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = services.create_document_review(
            actor=request.user,
            organization_id=workspace_id,
            order_id=order_id,
            document_id=document_id,
            materialize=lambda review: OrderDocumentReviewSerializer(review).data,
            **data.validated_data,
        )
        return Response(result, status=201)


class OrderDocumentReviewResolveView(WorkspaceOrderView):
    def post(
        self,
        request: Request,
        workspace_id: UUID,
        order_id: UUID,
        document_id: UUID,
        review_id: UUID,
    ) -> Response:
        data = DocumentReviewResolveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = services.resolve_document_review(
            actor=request.user,
            organization_id=workspace_id,
            order_id=order_id,
            document_id=document_id,
            review_id=review_id,
            materialize=lambda review: OrderDocumentReviewSerializer(review).data,
            **data.validated_data,
        )
        return Response(result)


class OrderReviewActionView(WorkspaceOrderView):
    action = ""

    def post(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        data = OrderReviewActionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        action = {
            "submit": services.submit_purchase_order_for_review,
            "approve": services.approve_purchase_order,
            "reject": services.reject_purchase_order,
        }.get(self.action)
        if action is None:
            raise ValidationError({"action": "Unsupported order action."})
        arguments = {
            "actor": request.user,
            "organization_id": workspace_id,
            "order_id": order_id,
            "materialize": lambda order: PurchaseOrderSerializer(order).data,
        }
        if self.action != "submit":
            arguments["review_note"] = data.validated_data["review_note"]
        return Response(action(**arguments))
