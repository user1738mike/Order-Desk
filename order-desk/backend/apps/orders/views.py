"""Session-authenticated order APIs materialize data inside tenant transactions."""

import re
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from django.http import FileResponse, Http404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import UnsupportedMediaType, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders import selectors, services
from apps.orders.document_files import OrderDocumentTooLarge
from apps.orders.document_intake import create_private_document
from apps.orders.pagination import DraftOrderPagination, validate_draft_query
from apps.orders.private_documents import open_document, original_filename
from apps.orders.readiness import evaluate_draft_readiness
from apps.orders.revisions import DraftRevisionConflict, draft_revision
from apps.orders.serializers import (
    DocumentReviewResolveSerializer,
    DraftOrderConversionInputSerializer,
    DraftOrderConversionSerializer,
    DraftOrderCreateSerializer,
    DraftOrderCreationSerializer,
    DraftOrderCustomerUpdateSerializer,
    DraftOrderDetailSerializer,
    DraftOrderLineAttachmentSerializer,
    DraftOrderLineCreateSerializer,
    DraftOrderLineDetachmentSerializer,
    DraftOrderLineReadSerializer,
    DraftOrderLineUpdateSerializer,
    DraftOrderReadinessSerializer,
    DraftOrderReviewSerializer,
    DraftOrderSummarySerializer,
    OrderDocumentCreateSerializer,
    OrderDocumentReviewCreateSerializer,
    OrderDocumentReviewSerializer,
    OrderDocumentSerializer,
    OrderReviewActionSerializer,
    PrivateDocumentSerializer,
    PurchaseOrderCreateSerializer,
    PurchaseOrderLineCreateSerializer,
    PurchaseOrderLineSerializer,
    PurchaseOrderSerializer,
)
from apps.orders.uploads import (
    OrderDocumentUploadLimitHandler,
    OrderDocumentUploadTooLarge,
)
from apps.organizations.permissions import HasWorkspaceAccess
from apps.organizations.transactions import tenant_scope


class DraftOrderSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request: Request) -> None:
        # Match catalogue's transport guard: do not parse DRF input during CSRF.
        super().enforce_csrf(request._request)


@method_decorator(never_cache, name="dispatch")
class DraftOrderReadView(APIView):
    authentication_classes = (DraftOrderSessionAuthentication,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)
    http_method_names = ["get", "head", "options"]


class DraftOrderWriteView(DraftOrderReadView):
    http_method_names = ["get", "head", "post", "options"]

    def handle_exception(self, exc):
        # Translate only after the service has exited and rolled back its scope.
        if isinstance(exc, DraftRevisionConflict):
            return Response({"detail": "draft_revision_conflict"}, status=412)
        if isinstance(exc, services.DraftAlreadyConverted):
            return Response({"detail": "draft_already_converted"}, status=409)
        if isinstance(exc, services.DraftNotReady):
            return Response(
                {"detail": "draft_not_ready", "blocking_reasons": exc.reasons},
                status=409,
            )
        if isinstance(exc, services.DraftConversionNumberConflict):
            return Response({"detail": "purchase_order_number_conflict"}, status=409)
        if isinstance(exc, DjangoValidationError):
            if hasattr(exc, "message_dict"):
                details = {
                    "non_field_errors" if key == "__all__" else key: messages
                    for key, messages in exc.message_dict.items()
                }
            else:
                details = {"non_field_errors": exc.messages}
            exc = ValidationError(details)
        return super().handle_exception(exc)


def expected_draft_revision(request: Request) -> str | None:
    value = request.headers.get("If-Match")
    if value is None:
        return None
    match = re.fullmatch(r'"([0-9a-f]{64})"', value)
    if not match:
        raise ValidationError({"If-Match": ["Provide one quoted draft revision."]})
    return match[1]


class DraftOrderRevisionView(DraftOrderReadView):
    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            validate_draft_query(request.query_params, allow_page=False)
            order = selectors.get_draft_order(scope.organization_id, order_id)
            revision = draft_revision(order)
            return Response(
                {
                    "id": order.pk,
                    "organization_id": scope.organization_id,
                    "revision": revision,
                },
                headers={"ETag": f'"{revision}"'},
            )


class DraftOrderListCreateView(DraftOrderWriteView):
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
            materialize=lambda order: (
                DraftOrderCreationSerializer(order, context={"request": request}).data
            ),
            **data.validated_data,
        )
        return Response(result, status=201)


class DraftOrderDetailView(DraftOrderWriteView):
    http_method_names = ["get", "head", "patch", "options"]

    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            validate_draft_query(request.query_params, allow_page=False)
            order = selectors.get_draft_order(scope.organization_id, order_id)
            return Response(
                DraftOrderDetailSerializer(order, context={"request": request}).data
            )

    def patch(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        def update_data():
            validate_draft_query(request.query_params, allow_page=False)
            if (
                request.content_type.split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                raise UnsupportedMediaType(request.content_type)
            serializer = DraftOrderCustomerUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return serializer.validated_data

        result = services.update_draft_customer_fields(
            expected_revision=lambda: expected_draft_revision(request),
            actor=request.user,
            organization_id=workspace_id,
            order_id=order_id,
            data=update_data,
            materialize=lambda order: (
                DraftOrderDetailSerializer(
                    selectors.get_draft_order(workspace_id, order.pk),
                    context={"request": request},
                ).data
            ),
        )
        return Response(result, status=200)


class DraftOrderReviewView(DraftOrderReadView):
    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            validate_draft_query(request.query_params, allow_page=False)
            order = selectors.get_draft_review(scope.organization_id, order_id)
            return Response(DraftOrderReviewSerializer(order).data)


class DraftOrderReadinessView(DraftOrderReadView):
    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            validate_draft_query(request.query_params, allow_page=False)
            order = selectors.get_draft_readiness(scope.organization_id, order_id)
            return Response(
                DraftOrderReadinessSerializer(evaluate_draft_readiness(order)).data
            )


class DraftOrderConversionView(DraftOrderWriteView):
    http_method_names = ["post", "options"]

    def post(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        def input_data():
            validate_draft_query(request.query_params, allow_page=False)
            if (
                request.content_type.split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                raise UnsupportedMediaType(request.content_type)
            serializer = DraftOrderConversionInputSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return serializer.validated_data

        result, created = services.convert_draft_to_purchase_order(
            expected_revision=lambda: expected_draft_revision(request),
            actor=request.user,
            organization_id=workspace_id,
            order_id=order_id,
            data=input_data,
            materialize=lambda order: DraftOrderConversionSerializer(order).data,
        )
        return Response(result, status=201 if created else 200)


class DraftOrderLinesView(DraftOrderWriteView):
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

    def post(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        def creation_data():
            validate_draft_query(request.query_params, allow_page=False)
            if (
                request.content_type.split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                raise UnsupportedMediaType(request.content_type)
            serializer = DraftOrderLineCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return serializer.validated_data

        try:
            result = services.create_draft_order_line(
                expected_revision=lambda: expected_draft_revision(request),
                actor=request.user,
                organization_id=workspace_id,
                order_id=order_id,
                data=creation_data,
                materialize=lambda line: DraftOrderLineReadSerializer(line).data,
            )
        except services.DraftLinePositionConflict:
            return Response(
                {"detail": services.DRAFT_LINE_POSITION_CONFLICT}, status=409
            )
        return Response(result, status=201)


class DraftOrderLineAttachmentView(DraftOrderWriteView):
    http_method_names = ["post", "options"]

    def post(
        self, request: Request, workspace_id: UUID, order_id: UUID, line_id: UUID
    ) -> Response:
        def attachment_data():
            validate_draft_query(request.query_params, allow_page=False)
            if (
                request.content_type.split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                raise UnsupportedMediaType(request.content_type)
            serializer = DraftOrderLineAttachmentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return serializer.validated_data["catalogue_item_id"]

        try:
            result = services.attach_catalogue_item_to_draft_order_line(
                expected_revision=lambda: expected_draft_revision(request),
                actor=request.user,
                organization_id=workspace_id,
                order_id=order_id,
                line_id=line_id,
                catalogue_item_id=attachment_data,
                materialize=lambda line: DraftOrderLineReadSerializer(line).data,
            )
        except services.DraftLineCatalogueAttachmentConflict:
            return Response(
                {"detail": "Already attached to a catalogue item."},
                status=409,
            )
        return Response(result, status=200)


class DraftOrderLineDetachmentView(DraftOrderWriteView):
    http_method_names = ["post", "options"]

    def post(
        self, request: Request, workspace_id: UUID, order_id: UUID, line_id: UUID
    ) -> Response:
        def detachment_data():
            validate_draft_query(request.query_params, allow_page=False)
            if (
                request.content_type.split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                raise UnsupportedMediaType(request.content_type)
            serializer = DraftOrderLineDetachmentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return serializer.validated_data

        result = services.detach_catalogue_item_from_draft_order_line(
            expected_revision=lambda: expected_draft_revision(request),
            actor=request.user,
            organization_id=workspace_id,
            order_id=order_id,
            line_id=line_id,
            data=detachment_data,
            materialize=lambda line: DraftOrderLineReadSerializer(line).data,
        )
        return Response(result, status=200)


class DraftOrderLineDetailView(DraftOrderWriteView):
    http_method_names = ["get", "head", "patch", "options"]

    def get(
        self, request: Request, workspace_id: UUID, order_id: UUID, line_id: UUID
    ) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id) as scope:
            validate_draft_query(request.query_params, allow_page=False)
            selectors.get_draft_order(scope.organization_id, order_id)
            line = selectors.get_draft_line(scope.organization_id, order_id, line_id)
            return Response(DraftOrderLineReadSerializer(line).data)

    def patch(
        self, request: Request, workspace_id: UUID, order_id: UUID, line_id: UUID
    ) -> Response:
        def update_data():
            validate_draft_query(request.query_params, allow_page=False)
            if (
                request.content_type.split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                raise UnsupportedMediaType(request.content_type)
            serializer = DraftOrderLineUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return serializer.validated_data

        result = services.update_draft_order_line(
            expected_revision=lambda: expected_draft_revision(request),
            actor=request.user,
            organization_id=workspace_id,
            order_id=order_id,
            line_id=line_id,
            data=update_data,
            materialize=lambda line: DraftOrderLineReadSerializer(line).data,
        )
        return Response(result, status=200)


@method_decorator(never_cache, name="dispatch")
class WorkspaceOrderView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)

    def handle_exception(self, exc):
        # Services have exited their atomic scope before errors reach this layer.
        if isinstance(exc, OrderDocumentTooLarge):
            exc = OrderDocumentUploadTooLarge()
        elif isinstance(exc, DjangoValidationError):
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

    def initialize_request(self, request, *args, **kwargs):
        request.upload_handlers.insert(0, OrderDocumentUploadLimitHandler(request))
        return super().initialize_request(request, *args, **kwargs)

    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            response = self.paginated(
                request,
                selectors.documents_for_order(workspace_id, order_id),
                OrderDocumentSerializer,
            )
        return response

    def post(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        def upload_data():
            files = request.FILES
            if len(files.getlist("file")) != 1:
                raise ValidationError({"file": ["Supply exactly one file."]})
            data = OrderDocumentCreateSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            return data.validated_data["file"]

        result = services.create_order_document(
            actor=request.user,
            organization_id=workspace_id,
            order_id=order_id,
            file=upload_data,
            materialize=lambda document: OrderDocumentSerializer(document).data,
        )
        return Response(result, status=201)


class PrivateOrderDocumentIntakeView(OrderDocumentListCreateView):
    """Reuse document metadata; private bounded eligibility is an explicit contract."""

    def get(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            paginator = DraftOrderPagination()
            page = paginator.paginate_queryset(
                selectors.private_documents_for_order(workspace_id, order_id),
                request,
                view=self,
            )
            return paginator.get_paginated_response(
                PrivateDocumentSerializer(page, many=True).data
            )

    def post(self, request: Request, workspace_id: UUID, order_id: UUID) -> Response:
        validate_draft_query(request.query_params, allow_page=False)

        def upload():
            if (
                set(request.data) != {"file"}
                or len(request.FILES.getlist("file")) != 1
                or len(request.data.getlist("file")) != 1
            ):
                raise ValidationError(
                    {"file": ["Supply exactly one file and no form fields."]}
                )
            return request.FILES["file"]

        try:
            result = create_private_document(
                actor=request.user,
                organization_id=workspace_id,
                order_id=order_id,
                upload=upload,
                materialize=lambda document: PrivateDocumentSerializer(document).data,
            )
        except OrderDocumentTooLarge as error:
            raise OrderDocumentUploadTooLarge() from error
        except DatabaseError:
            return Response(
                {
                    "detail": (
                        "Document intake could not be confirmed. "
                        "Check the list before retrying."
                    )
                },
                status=503,
            )
        except OSError:
            return Response(
                {"detail": "Private document storage is unavailable."}, status=503
            )
        return Response(result, status=201)


class OrderDocumentDownloadView(WorkspaceOrderView):
    def get(
        self, request: Request, workspace_id: UUID, order_id: UUID, document_id: UUID
    ):
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            document = selectors.get_private_document(
                workspace_id, order_id, document_id
            )
            key, size, name, content_type = (
                document.file.name,
                document.size_bytes,
                document.original_name,
                document.content_type,
            )
            digest = document.source_sha256
        # Metadata is authorized/materialized before any slow byte delivery.
        try:
            stream = open_document(key, size, digest)
        except OSError:
            return Response({"detail": "Document bytes are unavailable."}, status=503)
        response = FileResponse(
            stream,
            as_attachment=True,
            filename=original_filename(name),
            content_type=content_type
            if content_type in {"application/pdf", "text/csv"}
            else "application/octet-stream",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


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
