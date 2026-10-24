"""Bounded workspace reference discovery and receipt reconciliation."""

from uuid import UUID

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.catalog.pagination import FixedPagePagination
from apps.customers.views import ReferenceView, parameters, write_key
from apps.orders.views import expected_draft_revision
from apps.organizations.transactions import tenant_scope
from apps.product_units.models import UnitReferenceReceipt
from apps.product_units.references import SPECS, save_reference


class ReferenceListView(ReferenceView):
    kind = None

    def get(self, request, workspace_id, record_id=None):
        params = parameters(
            request,
            set()
            if record_id
            else {"page", "q", "active", "catalogue_item_id", "customer_id"},
        )
        model, _, _, output = SPECS[self.kind]
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            rows = model.objects.filter(organization_id=workspace_id)
            if record_id:
                return Response(output(get_object_or_404(rows, pk=record_id)).data)
            active = params.get("active", "true")
            if active not in {"true", "false", "all"}:
                raise ValidationError({"active": "Choose true, false or all."})
            if active != "all":
                rows = rows.filter(is_active=active == "true")
            for field in ("catalogue_item_id", "customer_id"):
                if field in params:
                    if self.kind == "unit" or (
                        self.kind == "policy" and field == "customer_id"
                    ):
                        raise ValidationError(
                            {field: "Unsupported filter for this reference."}
                        )
                    try:
                        value = UUID(params[field])
                    except ValueError as error:
                        raise ValidationError({field: "Use a UUID."}) from error
                    rows = rows.filter(**{field: value})
            query = params.get("q", "")
            if len(query) > 128 or any(ord(char) < 32 for char in query):
                raise ValidationError({"q": "Use at most 128 printable characters."})
            if query:
                fields = {
                    "unit": ("code", "display_name"),
                    "policy": ("requested_token", "catalogue_item__sku"),
                    "alias": ("value", "catalogue_item__sku"),
                }[self.kind]
                rows = rows.filter(
                    Q(**{fields[0] + "__icontains": query})
                    | Q(**{fields[1] + "__icontains": query})
                )
            paginator = FixedPagePagination()
            page = paginator.paginate_queryset(rows, request, view=self)
            return paginator.get_paginated_response(output(page, many=True).data)

    def post(self, request, workspace_id, record_id=None):
        parameters(request, set())
        if self.kind == "unit" and record_id:
            raise ValidationError("Use PATCH to change a controlled unit.")
        result = self.write(request, workspace_id, record_id)
        return Response(result, status=200 if record_id or result["replayed"] else 201)

    def patch(self, request, workspace_id, record_id):
        parameters(request, set())
        if self.kind != "unit":
            raise ValidationError(
                "Approved mappings are immutable. Retire and explicitly replace them."
            )
        return Response(self.write(request, workspace_id, record_id))

    def write(self, request, workspace_id, record_id):
        return save_reference(
            actor=request.user,
            organization_id=workspace_id,
            kind=self.kind,
            record_id=record_id,
            data=lambda: request.data,
            operation_key=write_key(request),
            expected_revision=expected_draft_revision(request) if record_id else None,
        )


class OperationView(ReferenceView):
    http_method_names = ["get", "head", "options"]

    def get(self, request, workspace_id, operation_key):
        parameters(request, set())
        with tenant_scope(user=request.user, workspace_id=workspace_id):
            receipt = get_object_or_404(
                UnitReferenceReceipt,
                organization_id=workspace_id,
                operation_key=operation_key,
            )
            return Response({**receipt.response, "replayed": True})
