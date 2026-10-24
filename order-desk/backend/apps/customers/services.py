"""Reference administration uses the same fresh organization lock as processing."""

import hashlib
import json
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, ValidationError

from apps.customers.models import (
    CustomerAccount,
    CustomerAlias,
    CustomerLocation,
    ReferenceWriteReceipt,
)
from apps.customers.revisions import record_revision
from apps.customers.serializers import (
    AccountInput,
    AccountSerializer,
    AccountUpdateInput,
    AliasInput,
    AliasRetirementInput,
    AliasSerializer,
    LocationInput,
    LocationSerializer,
    LocationUpdateInput,
)
from apps.organizations.models import MembershipRole
from apps.organizations.transactions import tenant_scope


class ReferenceConflict(APIException):
    status_code = 409
    default_detail = (
        "This reference code or active alias already exists. Refresh the directory."
    )


class ReferenceVersionRequired(APIException):
    status_code = 428
    default_detail = (
        "Refresh the current reference record and supply its If-Match version."
    )


class ReferenceVersionChanged(APIException):
    status_code = 412
    default_detail = (
        "Reference data changed. Preserve your proposed values, refresh and "
        "compare before saving."
    )


def require_admin(context):
    if context.role != MembershipRole.ADMIN:
        raise PermissionDenied(
            "Workspace administrator access is required for approved reference data."
        )


def save_reference(
    *,
    actor,
    organization_id,
    kind,
    data,
    customer_id=None,
    record_id=None,
    operation_key=None,
    expected_revision=None,
):
    specs = {
        "account": (
            CustomerAccount,
            AccountInput,
            AccountUpdateInput,
            AccountSerializer,
        ),
        "location": (
            CustomerLocation,
            LocationInput,
            LocationUpdateInput,
            LocationSerializer,
        ),
        "alias": (CustomerAlias, AliasInput, AliasRetirementInput, AliasSerializer),
    }
    model, create_form, update_form, output = specs[kind]
    try:
        with tenant_scope(
            user=actor, workspace_id=organization_id, write=True
        ) as context:
            require_admin(context)
            customer = None
            if kind != "account":
                customer = get_object_or_404(
                    CustomerAccount, organization_id=organization_id, pk=customer_id
                )
            form = (update_form if record_id else create_form)(
                data=data(), partial=bool(record_id)
            )
            form.is_valid(raise_exception=True)
            values = form.validated_data
            operation_key = operation_key or uuid4()
            operation_kind = kind + (".update" if record_id else ".create")
            request_hash = hashlib.sha256(
                json.dumps(
                    {
                        "kind": operation_kind,
                        "customer_id": customer_id,
                        "record_id": record_id,
                        "data": values,
                        "expected_revision": expected_revision,
                    },
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest()
            previous = ReferenceWriteReceipt.objects.filter(
                organization_id=organization_id, operation_key=operation_key
            ).first()
            if previous:
                if previous.request_hash != request_hash:
                    raise ReferenceConflict(
                        "This operation key already identifies a different "
                        "reference write."
                    )
                return {**previous.response, "replayed": True}
            if record_id and not values:
                raise ValidationError(
                    {"fields": "Provide at least one supported change."}
                )
            if (
                kind == "alias"
                and not record_id
                and CustomerAccount.objects.filter(
                    organization_id=organization_id, code=values["value"]
                )
                .exclude(pk=customer.pk)
                .exists()
            ):
                raise ReferenceConflict(
                    "This alias collides with another stable customer code."
                )
            if (
                kind == "account"
                and not record_id
                and CustomerAlias.objects.filter(
                    organization_id=organization_id,
                    value=values["code"],
                    is_active=True,
                ).exists()
            ):
                raise ReferenceConflict(
                    "This code collides with an approved customer alias."
                )
            if record_id:
                filters = {"organization_id": organization_id, "pk": record_id}
                if customer:
                    filters["customer_id"] = customer.pk
                record = get_object_or_404(model.objects.select_for_update(), **filters)
                if expected_revision is None:
                    raise ReferenceVersionRequired
                if record_revision(record) != expected_revision:
                    raise ReferenceVersionChanged
                changed = any(
                    getattr(record, key) != value for key, value in values.items()
                )
                if kind == "alias":
                    if not record.is_active:
                        raise ValidationError(
                            {"alias": "This approval is already retired."}
                        )
                    if not values.get("retirement_reason"):
                        raise ValidationError(
                            {"retirement_reason": "Provide the withdrawal reason."}
                        )
                    record.is_active = False
                    changed = True
                for key, value in values.items():
                    setattr(record, key, value)
                record.updated_by_id = actor.pk
            else:
                changed = True
                if customer and not customer.is_active:
                    raise ValidationError(
                        {
                            "customer": "Reactivate the confirmed account "
                            "before adding reference data."
                        }
                    )
                record = model(
                    organization_id=organization_id,
                    created_by_id=actor.pk,
                    updated_by_id=actor.pk,
                    **values,
                )
                if customer:
                    record.customer_id = customer.pk
            # Inputs validate shape; unique collisions are also enforced by the DB
            # after the organization lock. Do not copy user-supplied tenant/actors.
            if changed:
                record.full_clean(validate_unique=False, validate_constraints=False)
                record.save()
            record.refresh_from_db()
            result = json.loads(json.dumps(output(record).data, default=str))
            result.update(
                operation_key=str(operation_key), replayed=False, changed=changed
            )
            ReferenceWriteReceipt.objects.create(
                organization_id=organization_id,
                customer_id=record.pk if kind == "account" else customer.pk,
                location_id=record.pk if kind == "location" else None,
                alias_id=record.pk if kind == "alias" else None,
                actor_id=actor.pk,
                operation_key=operation_key,
                kind=operation_kind,
                request_hash=request_hash,
                response=result,
            )
            return result
    except IntegrityError as error:
        if getattr(error.__cause__, "sqlstate", None) == "23505":
            raise ReferenceConflict from error
        raise
