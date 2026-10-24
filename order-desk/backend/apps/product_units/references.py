"""Fresh admin authorization, immutable approvals and durable write receipts."""

import json

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.catalog.models import CatalogItem
from apps.customers.confirmation import fingerprint
from apps.customers.models import CustomerAccount
from apps.customers.revisions import record_revision
from apps.customers.services import (
    ReferenceConflict,
    ReferenceVersionChanged,
    ReferenceVersionRequired,
    require_admin,
)
from apps.organizations.transactions import tenant_scope
from apps.product_units.models import (
    ControlledUnit,
    CustomerProductAlias,
    ProductUnitPolicy,
    UnitReferenceReceipt,
)
from apps.product_units.serializers import (
    PolicyInput,
    PolicySerializer,
    ProductAliasInput,
    ProductAliasSerializer,
    RetirementInput,
    UnitInput,
    UnitSerializer,
    UnitUpdateInput,
)

SPECS = {
    "unit": (ControlledUnit, UnitInput, UnitUpdateInput, UnitSerializer),
    "policy": (ProductUnitPolicy, PolicyInput, RetirementInput, PolicySerializer),
    "alias": (
        CustomerProductAlias,
        ProductAliasInput,
        RetirementInput,
        ProductAliasSerializer,
    ),
}


def save_reference(
    *,
    actor,
    organization_id,
    kind,
    data,
    operation_key,
    record_id=None,
    expected_revision=None,
):
    try:
        with tenant_scope(
            user=actor, workspace_id=organization_id, write=True
        ) as context:
            require_admin(context)
            if operation_key is None:
                raise ValidationError(
                    {
                        "operation_key": "Supply an Idempotency-Key UUID "
                        "to reconcile this write."
                    }
                )
            model, create, update, serializer = SPECS[kind]
            form = (update if record_id else create)(
                data=data(), partial=bool(record_id)
            )
            form.is_valid(raise_exception=True)
            values = form.validated_data
            operation_kind = (
                kind + (".update" if kind == "unit" else ".retire")
                if record_id
                else kind + ".create"
            )
            digest = fingerprint(
                {
                    "kind": operation_kind,
                    "id": record_id,
                    "data": values,
                    "revision": expected_revision,
                }
            )
            prior = UnitReferenceReceipt.objects.filter(
                organization_id=organization_id, operation_key=operation_key
            ).first()
            if prior:
                if prior.request_hash != digest:
                    raise ReferenceConflict(
                        "This operation key belongs to a different reference write."
                    )
                return {**prior.response, "replayed": True}
            if record_id:
                row = get_object_or_404(
                    model.objects.select_for_update(),
                    organization_id=organization_id,
                    pk=record_id,
                )
                if expected_revision is None:
                    raise ReferenceVersionRequired
                if record_revision(row) != expected_revision:
                    raise ReferenceVersionChanged
                if not values:
                    raise ValidationError({"fields": "Provide a supported change."})
                if kind != "unit":
                    if not row.is_active or not values.get("retirement_reason"):
                        raise ValidationError(
                            {
                                "retirement_reason": "Retire an active approval "
                                "with a reason."
                            }
                        )
                    values = {**values, "is_active": False}
                changed = any(
                    getattr(row, key) != value for key, value in values.items()
                )
                for key, value in values.items():
                    setattr(row, key, value)
                row.updated_by_id = actor.pk
            else:
                if kind in {"policy", "alias"}:
                    product = get_object_or_404(
                        CatalogItem,
                        organization_id=organization_id,
                        pk=values["catalogue_item_id"],
                    )
                    if not product.is_active:
                        raise ValidationError(
                            {"catalogue_item_id": "Choose an active product."}
                        )
                if kind == "policy":
                    for key in (
                        "requested_unit_id",
                        "selling_unit_id",
                        "destination_unit_id",
                    ):
                        if values[key] is not None:
                            unit = get_object_or_404(
                                ControlledUnit,
                                organization_id=organization_id,
                                pk=values[key],
                            )
                            if not unit.is_active:
                                raise ValidationError(
                                    {key: "Choose an active controlled unit."}
                                )
                if kind == "alias":
                    customer = get_object_or_404(
                        CustomerAccount,
                        organization_id=organization_id,
                        pk=values["customer_id"],
                    )
                    if not customer.is_active:
                        raise ValidationError(
                            {"customer_id": "Choose an active customer."}
                        )
                    if (
                        CatalogItem.objects.filter(
                            organization_id=organization_id, sku=values["value"]
                        )
                        .exclude(pk=product.pk)
                        .exists()
                    ):
                        raise ReferenceConflict(
                            "This alias collides with another stable product SKU."
                        )
                row = model(
                    organization_id=organization_id,
                    created_by_id=actor.pk,
                    updated_by_id=actor.pk,
                    **values,
                )
                changed = True
            if changed:
                row.full_clean(validate_unique=False, validate_constraints=False)
                row.save()
            row.refresh_from_db()
            result = json.loads(json.dumps(serializer(row).data, default=str))
            result.update(
                operation_key=str(operation_key), replayed=False, changed=changed
            )
            UnitReferenceReceipt.objects.create(
                organization_id=organization_id,
                actor_id=actor.pk,
                operation_key=operation_key,
                request_hash=digest,
                kind=operation_kind,
                response=result,
                **{kind + "_id": row.pk},
            )
            return result
    except IntegrityError as error:
        if getattr(error.__cause__, "sqlstate", None) == "23505":
            raise ReferenceConflict(
                "This active token or reference code is already approved."
            ) from error
        raise
