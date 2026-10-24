"""Session/CSRF inbox endpoints; original sources never receive public URLs."""

from uuid import UUID

from django.db import DatabaseError
from django.db.models import Q
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.catalog.pagination import FixedPagePagination
from apps.orders import incoming
from apps.orders.document_files import OrderDocumentTooLarge
from apps.orders.uploads import OrderDocumentUploadTooLarge
from apps.orders.views import DraftOrderWriteView, PrivateOrderDocumentIntakeView
from apps.organizations.transactions import tenant_scope


class IncomingListView(PrivateOrderDocumentIntakeView):
    def get(self, request, workspace_id):
        params = request.query_params
        if set(params) - {"q", "status", "page", "operation_key"} or any(
            len(params.getlist(key)) != 1 for key in params
        ):
            raise ValidationError({"query": "Unsupported or repeated parameter."})
        query = params.get("q", "").strip()
        state = params.get("status", "")
        if len(query) > 200 or any(ord(char) < 32 for char in query):
            raise ValidationError({"q": "Use up to 200 printable characters."})
        if state not in {
            "",
            "unlinked",
            "linked",
            "queued",
            "running",
            "succeeded",
            "failed",
        }:
            raise ValidationError({"status": "Choose a supported inbox state."})
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            rows = incoming.inbox(workspace_id)
            if query:
                rows = rows.filter(
                    Q(original_name__icontains=query)
                    | Q(draft__customer_name__icontains=query)
                    | Q(draft__customer_reference__icontains=query)
                )
            if state in {"unlinked", "linked"}:
                rows = rows.filter(draft__isnull=state == "unlinked")
            elif state:
                rows = rows.filter(processing_status=state)
            if "operation_key" in params:
                try:
                    key = UUID(params["operation_key"])
                except ValueError as error:
                    raise ValidationError(
                        {"operation_key": "Use the original request UUID."}
                    ) from error
                rows = rows.filter(intake_key=key)
            paginator = FixedPagePagination()
            page = paginator.paginate_queryset(rows, request, view=self)
            return paginator.get_paginated_response(
                incoming.IncomingSerializer(page, many=True).data
            )

    def post(self, request, workspace_id):
        if request.query_params:
            raise ValidationError(
                {"query": "No upload query parameters are supported."}
            )
        try:
            key = UUID(request.headers.get("Idempotency-Key", ""))
        except ValueError as error:
            raise ValidationError(
                {
                    "operation_key": "Supply an Idempotency-Key UUID "
                    "and retain it until confirmed."
                }
            ) from error

        def upload():
            if (
                set(request.data) != {"file"}
                or len(request.FILES.getlist("file")) != 1
                or len(request.data.getlist("file")) != 1
            ):
                raise ValidationError(
                    {"file": "Supply exactly one file and no form fields."}
                )
            return request.FILES["file"]

        try:
            result, created = incoming.receive(
                actor=request.user,
                organization_id=workspace_id,
                operation_key=key,
                upload=upload,
            )
        except OrderDocumentTooLarge as error:
            raise OrderDocumentUploadTooLarge() from error
        except DatabaseError:
            return Response(
                {
                    "detail": "Upload outcome unknown. "
                    "Reconcile using the original request key."
                },
                status=503,
            )
        except OSError:
            return Response(
                {
                    "detail": "Private source storage is unavailable. "
                    "Retry after recovery."
                },
                status=503,
            )
        return Response(result, status=201 if created else 200)


class IncomingLinkView(DraftOrderWriteView):
    def post(self, request, workspace_id, document_id):
        if request.query_params:
            raise ValidationError({"query": "No link query parameters are supported."})
        try:
            result, created = incoming.link(
                actor=request.user,
                organization_id=workspace_id,
                document_id=document_id,
                data=lambda: request.data,
            )
        except DatabaseError:
            return Response(
                {
                    "detail": "Draft link outcome unknown. "
                    "Refresh the inbox or replay the identical request."
                },
                status=503,
            )
        return Response(result, status=201 if created else 200)
