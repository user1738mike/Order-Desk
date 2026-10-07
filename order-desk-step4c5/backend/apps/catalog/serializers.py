"""Strict catalogue creation input and allowlisted scalar output."""

from collections.abc import Mapping

from rest_framework import serializers

from apps.catalog.models import CatalogItem


class StrictTextField(serializers.CharField):
    def to_internal_value(self, data: object) -> str:
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data: object) -> bool:
        if not isinstance(data, bool):
            self.fail("invalid")
        return data


class CatalogItemCreateSerializer(serializers.Serializer):
    # Both model text fields are unbounded PostgreSQL text; do not invent limits.
    sku = StrictTextField(trim_whitespace=True)
    description = StrictTextField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        default=CatalogItem._meta.get_field("description").get_default(),
    )
    is_active = StrictBooleanField(
        required=False,
        default=CatalogItem._meta.get_field("is_active").get_default(),
    )

    def to_internal_value(self, data: object) -> dict:
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        if any(not isinstance(key, str) for key in data):
            raise serializers.ValidationError(
                {"non_field_errors": ["Object keys must be strings."]}
            )
        unknown = data.keys() - self.fields.keys()
        if unknown:
            raise serializers.ValidationError(
                {key: ["Unknown field."] for key in sorted(unknown)}
            )
        return super().to_internal_value(data)


class CatalogItemSerializer(serializers.ModelSerializer):
    # Read the FK scalar directly, without fetching the organization relation.
    organization_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = CatalogItem
        fields = (
            "id",
            "organization_id",
            "sku",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
