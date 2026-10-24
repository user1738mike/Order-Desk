"""Tenant-scoped customer discovery; every proposed match requires confirmation."""

from uuid import UUID

from django.db import DatabaseError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.catalog.pagination import FixedPagePagination
from apps.customers.models import CustomerAccount, CustomerAlias, CustomerLocation
from apps.customers.serializers import (
    AccountSerializer,
    AliasSerializer,
    LocationSerializer,
)
from apps.customers.services import save_reference
from apps.orders.views import DraftOrderWriteView, expected_draft_revision
from apps.organizations.transactions import tenant_scope


def parameters(request, allowed):
    params = request.query_params
    if set(params) - set(allowed) or any(
        len(params.getlist(key)) != 1 for key in params
    ):
        raise ValidationError({"query": "Unsupported or repeated query parameter."})
    return params


def write_key(request):
    value = request.headers.get("Idempotency-Key")
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as error:
        raise ValidationError(
            {"operation_key": "Use an Idempotency-Key UUID."}
        ) from error


class ReferenceView(DraftOrderWriteView):
    parser_classes = (JSONParser,)
    http_method_names = ["get", "head", "post", "patch", "options"]

    def handle_exception(self, exc):
        if isinstance(exc, DatabaseError):
            return Response(
                {
                    "detail": "Reference operation unavailable or outcome unknown. "
                    "Reconcile a write using its original operation key."
                },
                status=503,
            )
        return super().handle_exception(exc)


class CustomerListView(ReferenceView):
    def get(self, request, workspace_id):
        params = parameters(request, {"page", "q", "active"})
        query = params.get("q", "").strip()
        if len(query) > 200 or any(ord(char) < 32 for char in query):
            raise ValidationError({"q": "Use up to 200 printable characters."})
        active = params.get("active", "true")
        if active not in {"true", "false", "all"}:
            raise ValidationError({"active": "Choose true, false or all."})
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            rows = CustomerAccount.objects.filter(organization_id=workspace_id)
            if active != "all":
                rows = rows.filter(is_active=active == "true")
            if query:
                rows = rows.filter(
                    Q(code__icontains=query) | Q(display_name__icontains=query)
                )
            paginator = FixedPagePagination()
            page = paginator.paginate_queryset(rows, request, view=self)
            return paginator.get_paginated_response(
                AccountSerializer(page, many=True).data
            )

    def post(self, request, workspace_id):
        parameters(request, set())
        result = save_reference(
            actor=request.user,
            organization_id=workspace_id,
            kind="account",
            data=lambda: request.data,
            operation_key=write_key(request),
        )
        return Response(result, status=200 if result["replayed"] else 201)


class CustomerDetailView(ReferenceView):
    def get(self, request, workspace_id, customer_id):
        parameters(request, set())
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            row = get_object_or_404(
                CustomerAccount, organization_id=workspace_id, pk=customer_id
            )
            return Response(AccountSerializer(row).data)

    def patch(self, request, workspace_id, customer_id):
        parameters(request, set())
        return Response(
            save_reference(
                actor=request.user,
                organization_id=workspace_id,
                kind="account",
                record_id=customer_id,
                data=lambda: request.data,
                operation_key=write_key(request),
                expected_revision=expected_draft_revision(request),
            )
        )


class CustomerChildrenView(ReferenceView):
    kind = None

    def get(self, request, workspace_id, customer_id):
        parameters(request, {"page"})
        model, serializer = {
            "location": (CustomerLocation, LocationSerializer),
            "alias": (CustomerAlias, AliasSerializer),
        }[self.kind]
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            get_object_or_404(
                CustomerAccount, organization_id=workspace_id, pk=customer_id
            )
            rows = model.objects.filter(
                organization_id=workspace_id, customer_id=customer_id
            )
            paginator = FixedPagePagination()
            page = paginator.paginate_queryset(rows, request, view=self)
            return paginator.get_paginated_response(serializer(page, many=True).data)

    def post(self, request, workspace_id, customer_id):
        parameters(request, set())
        result = save_reference(
            actor=request.user,
            organization_id=workspace_id,
            kind=self.kind,
            customer_id=customer_id,
            data=lambda: request.data,
            operation_key=write_key(request),
        )
        return Response(result, status=200 if result["replayed"] else 201)


class CustomerLocationDetailView(ReferenceView):
    def patch(self, request, workspace_id, customer_id, location_id):
        parameters(request, set())
        return Response(
            save_reference(
                actor=request.user,
                organization_id=workspace_id,
                kind="location",
                customer_id=customer_id,
                record_id=location_id,
                data=lambda: request.data,
                operation_key=write_key(request),
                expected_revision=expected_draft_revision(request),
            )
        )


class CustomerAliasRetirementView(ReferenceView):
    def post(self, request, workspace_id, customer_id, alias_id):
        parameters(request, set())
        return Response(
            save_reference(
                actor=request.user,
                organization_id=workspace_id,
                kind="alias",
                customer_id=customer_id,
                record_id=alias_id,
                data=lambda: request.data,
                operation_key=write_key(request),
                expected_revision=expected_draft_revision(request),
            )
        )


class CustomerResolutionView(ReferenceView):
    def get(self, request, workspace_id):
        params = parameters(request, {"identifier"})
        value = params.get("identifier", "")
        if (
            not value
            or len(value) > 128
            or value != value.strip()
            or any(ord(char) < 32 for char in value)
        ):
            raise ValidationError(
                {"identifier": "Provide an exact stable code or approved alias."}
            )
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            accounts = {
                row.pk: {
                    "account": AccountSerializer(row).data,
                    "evidence": {"kind": "stable_customer_code"},
                }
                for row in CustomerAccount.objects.filter(
                    organization_id=workspace_id, is_active=True, code=value
                )
            }
            for alias in CustomerAlias.objects.filter(
                organization_id=workspace_id,
                customer__organization_id=workspace_id,
                customer__is_active=True,
                is_active=True,
                value=value,
            ).select_related("customer"):
                accounts.setdefault(
                    alias.customer_id,
                    {
                        "account": AccountSerializer(alias.customer).data,
                        "evidence": {
                            "kind": "approved_exact_alias",
                            "alias": AliasSerializer(alias).data,
                        },
                    },
                )
            return Response(
                {
                    "matches": list(accounts.values()),
                    "requires_confirmation": True,
                    "name_similarity": "not checked",
                    "email_domain": "not checked",
                }
            )


class CustomerConfirmationView(ReferenceView):
    def get(self, request, workspace_id, draft_id):
        from apps.customers.confirmation import fingerprint, selected_reference, status
        from apps.orders import selectors

        params = parameters(request, {"customer_id", "location_id"})
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            draft = selectors.get_draft_order(workspace_id, draft_id)
            result = status(draft)
            result["candidate"] = None
            if params:
                try:
                    customer_id = UUID(params.get("customer_id", ""))
                    location_id = (
                        UUID(params["location_id"]) if "location_id" in params else None
                    )
                except ValueError as error:
                    raise ValidationError(
                        {"selection": "Choose valid account and location IDs."}
                    ) from error
                _, _, value = selected_reference(workspace_id, customer_id, location_id)
                result["candidate"] = {
                    "snapshot": value,
                    "reference_revision": fingerprint(value),
                }
            return Response(result)

    def post(self, request, workspace_id, draft_id):
        from apps.customers.confirmation import confirm

        parameters(request, set())
        try:
            result, created = confirm(
                actor=request.user,
                organization_id=workspace_id,
                draft_id=draft_id,
                data=lambda: request.data,
            )
        except DatabaseError:
            return Response(
                {
                    "detail": "Customer confirmation outcome unknown. "
                    "Reconcile the identical saved request."
                },
                status=503,
            )
        return Response(result, status=201 if created else 200)


class CustomerConfirmationHistoryView(ReferenceView):
    def get(self, request, workspace_id, draft_id):
        from apps.customers.confirmation import DecisionSerializer
        from apps.customers.models import DraftCustomerDecision
        from apps.orders import selectors

        parameters(request, {"page"})
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            selectors.get_draft_order(workspace_id, draft_id)
            rows = DraftCustomerDecision.objects.filter(
                organization_id=workspace_id, draft_id=draft_id
            )
            paginator = FixedPagePagination()
            page = paginator.paginate_queryset(rows, request, view=self)
            return paginator.get_paginated_response(
                DecisionSerializer(page, many=True).data
            )


class OrderCustomerSnapshotView(ReferenceView):
    def get(self, request, workspace_id, order_id):
        from apps.customers.models import OrderCustomerSnapshot
        from apps.orders import selectors

        parameters(request, set())
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            selectors.private_document_parent(workspace_id, order_id)
            row = OrderCustomerSnapshot.objects.filter(
                organization_id=workspace_id, order_id=order_id
            ).first()
            return Response(
                {
                    "order_id": str(order_id),
                    "organization_id": str(workspace_id),
                    "snapshot": {
                        "id": str(row.pk),
                        "decision_id": str(row.decision_id),
                        "payload": row.payload,
                        "actor_id": str(row.actor_id),
                        "created_at": row.created_at,
                    }
                    if row
                    else None,
                }
            )


class CustomerImportView(ReferenceView):
    execute = False
    parser_classes = (MultiPartParser, FormParser)

    def initialize_request(self, request, *args, **kwargs):
        from apps.catalog.uploads import CatalogUploadLimitHandler

        request.upload_handlers.insert(0, CatalogUploadLimitHandler(request))
        return super().initialize_request(request, *args, **kwargs)

    def post(self, request, workspace_id):
        from apps.catalog.uploads import catalogue_upload_bytes
        from apps.customers.imports import import_customers

        try:
            result = import_customers(
                actor=request.user,
                organization_id=workspace_id,
                upload=lambda: catalogue_upload_bytes(request),
                execute=self.execute,
                operation_key=write_key(request),
            )
        except DatabaseError:
            return Response(
                {
                    "detail": "Customer import outcome unknown. "
                    "Search stable codes before retrying; existing accounts "
                    "are never overwritten."
                },
                status=503,
            )
        return Response(
            result, status=201 if result["created"] else 200 if result["valid"] else 400
        )


class CustomerOperationView(ReferenceView):
    def get(self, request, workspace_id, operation_key):
        from apps.customers.models import ReferenceWriteReceipt
        from apps.customers.services import require_admin

        parameters(request, set())
        with tenant_scope(user=request.user, workspace_id=workspace_id) as context:
            require_admin(context)
            receipt = get_object_or_404(
                ReferenceWriteReceipt,
                organization_id=workspace_id,
                operation_key=operation_key,
            )
            return Response(
                {
                    "operation_key": str(receipt.operation_key),
                    "organization_id": str(workspace_id),
                    "status": "committed",
                    "kind": receipt.kind,
                    "actor_id": str(receipt.actor_id),
                    "created_at": receipt.created_at,
                    "source_sha256": receipt.source_sha256,
                    "response": receipt.response,
                }
            )
