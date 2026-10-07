"""Explicitly scoped catalogue queries, evaluated inside the caller's tenant scope."""

from uuid import UUID

from django.db.models import QuerySet

from apps.catalog.models import CatalogItem


def catalog_items_for_workspace(*, organization_id: UUID) -> QuerySet[CatalogItem]:
    """Return a lazy query to consume inside this organization's tenant scope.

    Include inactive identities; matching will choose eligible items separately.
    Database collation determines SKU order; UUID gives a stable secondary order.
    """
    return CatalogItem.objects.filter(organization_id=organization_id).order_by(
        "sku", "id"
    )
