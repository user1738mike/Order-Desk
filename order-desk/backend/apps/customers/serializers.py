"""Identifiers remain strings; identity and approval actors are server-owned."""

from django.core.validators import RegexValidator
from rest_framework import serializers

from apps.customers.models import CODE, CustomerAccount, CustomerAlias, CustomerLocation
from apps.customers.revisions import record_revision
from apps.orders.serializers import StrictInputSerializer


def identifier(value):
    if value != value.strip() or any(ord(char) < 32 for char in value):
        raise serializers.ValidationError(
            "Remove outer whitespace or control characters explicitly."
        )
    return value


class IdentifierField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError(
                "Provide a string identifier; preserve leading zeros."
            )
        return identifier(super().to_internal_value(data))


class AccountInput(StrictInputSerializer):
    code = IdentifierField(
        max_length=64, trim_whitespace=False, validators=[RegexValidator(CODE)]
    )
    display_name = serializers.CharField(max_length=255)
    destination_id = IdentifierField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=False,
        validators=[identifier],
    )
    requires_location = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)


class AccountUpdateInput(AccountInput):
    code = None


class LocationInput(StrictInputSerializer):
    code = IdentifierField(
        max_length=64, trim_whitespace=False, validators=[RegexValidator(CODE)]
    )
    display_name = serializers.CharField(max_length=255)
    destination_id = IdentifierField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=False,
        validators=[identifier],
    )
    is_active = serializers.BooleanField(required=False, default=True)


class LocationUpdateInput(LocationInput):
    code = None


class AliasInput(StrictInputSerializer):
    value = IdentifierField(max_length=128, trim_whitespace=False)
    provenance = serializers.CharField(max_length=500)


class AliasRetirementInput(StrictInputSerializer):
    retirement_reason = serializers.CharField(max_length=500)


class VersionedReferenceSerializer(serializers.ModelSerializer):
    revision = serializers.SerializerMethodField()

    def get_revision(self, record):
        return record_revision(record)


class AccountSerializer(VersionedReferenceSerializer):
    class Meta:
        model = CustomerAccount
        fields = (
            "revision",
            "id",
            "organization_id",
            "code",
            "display_name",
            "destination_id",
            "requires_location",
            "is_active",
            "created_by_id",
            "updated_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class LocationSerializer(VersionedReferenceSerializer):
    class Meta:
        model = CustomerLocation
        fields = (
            "revision",
            "id",
            "organization_id",
            "customer_id",
            "code",
            "display_name",
            "destination_id",
            "is_active",
            "created_by_id",
            "updated_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AliasSerializer(VersionedReferenceSerializer):
    approved_by_id = serializers.UUIDField(source="created_by_id", read_only=True)
    approved_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = CustomerAlias
        fields = (
            "revision",
            "id",
            "organization_id",
            "customer_id",
            "value",
            "provenance",
            "is_active",
            "retirement_reason",
            "approved_by_id",
            "approved_at",
            "updated_by_id",
            "updated_at",
        )
        read_only_fields = fields
