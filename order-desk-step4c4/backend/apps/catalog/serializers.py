"""Allowlisted scalar catalogue fields for the read-only collection API."""

from rest_framework import serializers

from apps.catalog.models import CatalogItem


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
