"""Strict reference input: identifiers and factors never pass through floats."""

import re

from django.core.validators import RegexValidator
from rest_framework import serializers

from apps.customers.serializers import (
    AliasRetirementInput,
    IdentifierField,
    VersionedReferenceSerializer,
)
from apps.orders.serializers import StrictInputSerializer
from apps.product_units.models import (
    UNIT_CODE,
    ControlledUnit,
    CustomerProductAlias,
    ProductUnitPolicy,
)


class RatioField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str) or not re.fullmatch(
            r"[0-9]{1,12}(?:\.[0-9]{1,12})?", data, re.ASCII
        ):
            raise serializers.ValidationError(
                "Use a plain positive decimal string (12 digits per part)."
            )
        if not any(char in "123456789" for char in data):
            raise serializers.ValidationError("A factor must be greater than zero.")
        return data


class PrecisionField(serializers.IntegerField):
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, int):
            raise serializers.ValidationError("Use an integer precision limit.")
        return super().to_internal_value(data)


class UnitInput(StrictInputSerializer):
    code = IdentifierField(
        max_length=32, trim_whitespace=False, validators=[RegexValidator(UNIT_CODE)]
    )
    display_name = serializers.CharField(max_length=120)
    is_active = serializers.BooleanField(required=False, default=True)


class UnitUpdateInput(UnitInput):
    code = None


class PolicyInput(StrictInputSerializer):
    catalogue_item_id = serializers.UUIDField()
    requested_token = IdentifierField(max_length=32, trim_whitespace=False)
    requested_unit_id = serializers.UUIDField()
    selling_unit_id = serializers.UUIDField()
    selling_numerator = RatioField()
    selling_denominator = RatioField()
    selling_scale = PrecisionField(min_value=0, max_value=9)
    selling_max_integer_digits = PrecisionField(min_value=1, max_value=18)
    destination_unit_id = serializers.UUIDField(
        required=False, allow_null=True, default=None
    )
    destination_numerator = RatioField(required=False, allow_null=True, default=None)
    destination_denominator = RatioField(required=False, allow_null=True, default=None)
    destination_scale = PrecisionField(
        min_value=0, max_value=9, required=False, allow_null=True, default=None
    )
    destination_max_integer_digits = PrecisionField(
        min_value=1, max_value=18, required=False, allow_null=True, default=None
    )
    provenance = serializers.CharField(max_length=500)

    def validate(self, attrs):
        values = [
            value is not None
            for key, value in attrs.items()
            if key.startswith("destination_")
        ]
        if any(values) and not all(values):
            raise serializers.ValidationError(
                {
                    "destination": "Provide every destination unit/factor/precision "
                    "field or none."
                }
            )
        return attrs


class ProductAliasInput(StrictInputSerializer):
    customer_id = serializers.UUIDField()
    catalogue_item_id = serializers.UUIDField()
    value = IdentifierField(max_length=128, trim_whitespace=False)
    provenance = serializers.CharField(max_length=500)


RetirementInput = AliasRetirementInput


class UnitSerializer(VersionedReferenceSerializer):
    class Meta:
        model = ControlledUnit
        fields = (
            "id",
            "organization_id",
            "code",
            "display_name",
            "is_active",
            "revision",
            "created_by_id",
            "updated_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PolicySerializer(VersionedReferenceSerializer):
    class Meta:
        model = ProductUnitPolicy
        fields = (
            "id",
            "organization_id",
            "catalogue_item_id",
            "requested_token",
            "requested_unit_id",
            "selling_unit_id",
            "selling_numerator",
            "selling_denominator",
            "selling_scale",
            "selling_max_integer_digits",
            "destination_unit_id",
            "destination_numerator",
            "destination_denominator",
            "destination_scale",
            "destination_max_integer_digits",
            "provenance",
            "is_active",
            "retirement_reason",
            "revision",
            "created_by_id",
            "updated_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ProductAliasSerializer(VersionedReferenceSerializer):
    class Meta:
        model = CustomerProductAlias
        fields = (
            "id",
            "organization_id",
            "customer_id",
            "catalogue_item_id",
            "value",
            "provenance",
            "is_active",
            "retirement_reason",
            "revision",
            "created_by_id",
            "updated_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
