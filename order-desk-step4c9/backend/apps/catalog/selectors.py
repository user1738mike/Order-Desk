"""Explicitly scoped catalogue queries, evaluated inside the caller's tenant scope."""

from uuid import UUID

from django.db.models import Q, QuerySet

from apps.catalog.models import CatalogItem


def catalog_items_for_workspace(
    *, organization_id: UUID, q: str | None = None, is_active: bool | None = None
) -> QuerySet[CatalogItem]:
    """Return a lazy query to consume inside this organization's tenant scope.

    Include inactive identities; matching will choose eligible items separately.
    Database collation determines SKU order; UUID gives a stable secondary order.
    """
    items = CatalogItem.objects.filter(organization_id=organization_id)
    if q is not None:
        # Keep both OR branches inside the existing organization boundary.
        # ORM icontains binds and escapes the entire literal term for LIKE.
        items = items.filter(Q(sku__icontains=q) | Q(description__icontains=q))
    if is_active is not None:
        items = items.filter(is_active=is_active)
    return items.order_by("sku", "id")


def catalog_item_by_sku(*, organization_id: UUID, sku: str) -> QuerySet[CatalogItem]:
    """Return a lazy exact query, including inactive identities, for this scope."""
    return CatalogItem.objects.filter(organization_id=organization_id, sku=sku)


def existing_catalog_skus(*, organization_id: UUID, skus: list[str]) -> QuerySet:
    """Lazy equality lookup; callers supply bounded batches and consume in scope."""
    return CatalogItem.objects.filter(
        organization_id=organization_id, sku__in=skus
    ).values_list("sku", flat=True)
