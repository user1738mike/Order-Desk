"""Explicit approved product/unit references and immutable human decisions.

Requested quantities remain on draft lines; normalized values are separate decisions.
"""

import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from apps.customers.models import ReferenceRecord

UNIT_CODE = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,31}$"
SHA = r"^[0-9a-f]{64}$"


def retirement_constraint(name):
    return models.CheckConstraint(
        condition=models.Q(is_active=True, retirement_reason="")
        | models.Q(is_active=False, retirement_reason__regex=r"\S"),
        name=name,
    )


def positive_ratio(field, name, nullable=False):
    # PostgreSQL numeric NaN compares above every finite value. This bounded
    # positive range excludes it without asking DecimalField to parse NaN.
    condition = models.Q(**{field + "__gt": 0, field + "__lt": 10**12})
    if nullable:
        condition |= models.Q(**{field + "__isnull": True})
    return models.CheckConstraint(condition=condition, name=name)


class ControlledUnit(ReferenceRecord):
    code = models.CharField(max_length=32, validators=[RegexValidator(UNIT_CODE)])
    display_name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization"], name="unit_id_org_unique"
            ),
            models.UniqueConstraint(
                fields=["organization", "code"], name="unit_org_code_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=UNIT_CODE), name="unit_code_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(display_name__regex=r"\S"), name="unit_name_nonblank"
            ),
        ]


class ApprovedRecord(ReferenceRecord):
    provenance = models.CharField(max_length=500)
    is_active = models.BooleanField(default=True)
    retirement_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        abstract = True


class ProductUnitPolicy(ApprovedRecord):
    catalogue_item = models.ForeignKey("catalog.CatalogItem", on_delete=models.PROTECT)
    requested_token = models.CharField(max_length=32)
    requested_unit = models.ForeignKey(
        ControlledUnit, on_delete=models.PROTECT, related_name="requested_policies"
    )
    selling_unit = models.ForeignKey(
        ControlledUnit, on_delete=models.PROTECT, related_name="selling_policies"
    )
    destination_unit = models.ForeignKey(
        ControlledUnit,
        on_delete=models.PROTECT,
        related_name="destination_policies",
        null=True,
        blank=True,
    )
    selling_numerator = models.DecimalField(max_digits=24, decimal_places=12)
    selling_denominator = models.DecimalField(max_digits=24, decimal_places=12)
    selling_scale = models.PositiveSmallIntegerField()
    selling_max_integer_digits = models.PositiveSmallIntegerField()
    destination_numerator = models.DecimalField(
        max_digits=24, decimal_places=12, null=True, blank=True
    )
    destination_denominator = models.DecimalField(
        max_digits=24, decimal_places=12, null=True, blank=True
    )
    destination_scale = models.PositiveSmallIntegerField(null=True, blank=True)
    destination_max_integer_digits = models.PositiveSmallIntegerField(
        null=True, blank=True
    )

    class Meta:
        ordering = ["requested_token", "-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization", "catalogue_item"],
                name="unit_policy_identity_unique",
            ),
            models.UniqueConstraint(
                fields=["organization", "catalogue_item", "requested_token"],
                condition=models.Q(is_active=True),
                name="unit_policy_one_active_token",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    requested_token__regex=r"\S", provenance__regex=r"\S"
                ),
                name="unit_policy_nonblank",
            ),
            retirement_constraint("unit_policy_retirement"),
            positive_ratio("selling_numerator", "unit_selling_numerator_positive"),
            positive_ratio("selling_denominator", "unit_selling_denominator_positive"),
            positive_ratio(
                "destination_numerator", "unit_dest_numerator_positive", nullable=True
            ),
            positive_ratio(
                "destination_denominator",
                "unit_dest_denominator_positive",
                nullable=True,
            ),
            models.CheckConstraint(
                condition=models.Q(
                    selling_scale__range=(0, 9),
                    selling_max_integer_digits__range=(1, 18),
                ),
                name="unit_selling_precision_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    destination_unit__isnull=True,
                    destination_numerator__isnull=True,
                    destination_denominator__isnull=True,
                    destination_scale__isnull=True,
                    destination_max_integer_digits__isnull=True,
                )
                | models.Q(
                    destination_unit__isnull=False,
                    destination_numerator__isnull=False,
                    destination_denominator__isnull=False,
                    destination_scale__isnull=False,
                    destination_max_integer_digits__isnull=False,
                    destination_scale__range=(0, 9),
                    destination_max_integer_digits__range=(1, 18),
                ),
                name="unit_destination_complete",
            ),
        ]


class CustomerProductAlias(ApprovedRecord):
    customer = models.ForeignKey("customers.CustomerAccount", on_delete=models.PROTECT)
    catalogue_item = models.ForeignKey("catalog.CatalogItem", on_delete=models.PROTECT)
    value = models.CharField(max_length=128)

    class Meta:
        ordering = ["value", "-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization", "customer", "catalogue_item"],
                name="product_alias_identity_unique",
            ),
            models.UniqueConstraint(
                fields=["organization", "customer", "value"],
                condition=models.Q(is_active=True),
                name="product_alias_one_active_value",
            ),
            models.CheckConstraint(
                condition=models.Q(value__regex=r"\S", provenance__regex=r"\S"),
                name="product_alias_nonblank",
            ),
            retirement_constraint("product_alias_retirement"),
        ]


class UnitReferenceReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    unit = models.ForeignKey(
        ControlledUnit, on_delete=models.PROTECT, null=True, blank=True
    )
    policy = models.ForeignKey(
        ProductUnitPolicy, on_delete=models.PROTECT, null=True, blank=True
    )
    alias = models.ForeignKey(
        CustomerProductAlias, on_delete=models.PROTECT, null=True, blank=True
    )
    operation_key = models.UUIDField()
    request_hash = models.CharField(max_length=64, validators=[RegexValidator(SHA)])
    kind = models.CharField(max_length=24)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "operation_key"],
                name="unit_reference_operation_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(request_hash__regex=SHA),
                name="unit_reference_hash_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=["unit.create", "unit.update"],
                    unit__isnull=False,
                    policy__isnull=True,
                    alias__isnull=True,
                )
                | models.Q(
                    kind__in=["policy.create", "policy.retire"],
                    unit__isnull=True,
                    policy__isnull=False,
                    alias__isnull=True,
                )
                | models.Q(
                    kind__in=["alias.create", "alias.retire"],
                    unit__isnull=True,
                    policy__isnull=True,
                    alias__isnull=False,
                ),
                name="unit_reference_target_typed",
            ),
        ]


class DraftLineUnitDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    draft = models.ForeignKey("orders.DraftOrder", on_delete=models.PROTECT)
    line = models.ForeignKey("orders.DraftOrderLine", on_delete=models.PROTECT)
    catalogue_item = models.ForeignKey("catalog.CatalogItem", on_delete=models.PROTECT)
    policy = models.ForeignKey(ProductUnitPolicy, on_delete=models.PROTECT)
    alias = models.ForeignKey(
        CustomerProductAlias, on_delete=models.PROTECT, null=True, blank=True
    )
    customer_decision = models.ForeignKey(
        "customers.DraftCustomerDecision",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    customer = models.ForeignKey(
        "customers.CustomerAccount", on_delete=models.PROTECT, null=True, blank=True
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    operation_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    reference_revision = models.CharField(max_length=64)
    request = models.JSONField()
    snapshot = models.JSONField()
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    retirement_reason = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization", "draft", "line"],
                name="unit_decision_identity_unique",
            ),
            models.UniqueConstraint(
                fields=["organization", "operation_key"],
                name="unit_decision_operation_unique",
            ),
            models.UniqueConstraint(
                fields=["organization", "line"],
                condition=models.Q(is_current=True),
                name="unit_decision_one_current_line",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    request_hash__regex=SHA, reference_revision__regex=SHA
                ),
                name="unit_decision_hashes_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(customer__isnull=True, customer_decision__isnull=True)
                | models.Q(customer__isnull=False, customer_decision__isnull=False),
                name="unit_customer_identity_complete",
            ),
            models.CheckConstraint(
                condition=models.Q(alias__isnull=True)
                | models.Q(customer_decision__isnull=False, customer__isnull=False),
                name="unit_alias_requires_customer",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    is_current=True,
                    retired_at__isnull=True,
                    retired_by__isnull=True,
                    retirement_reason="",
                )
                | models.Q(
                    is_current=False,
                    retired_at__isnull=False,
                    retirement_reason__regex=r"\S",
                ),
                name="unit_decision_retirement",
            ),
        ]


class OrderLineUnitSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    order = models.ForeignKey("orders.PurchaseOrder", on_delete=models.PROTECT)
    order_line = models.OneToOneField(
        "orders.PurchaseOrderLine",
        on_delete=models.PROTECT,
        related_name="unit_snapshot",
    )
    draft = models.ForeignKey("orders.DraftOrder", on_delete=models.PROTECT)
    draft_line = models.ForeignKey("orders.DraftOrderLine", on_delete=models.PROTECT)
    decision = models.ForeignKey(DraftLineUnitDecision, on_delete=models.PROTECT)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
