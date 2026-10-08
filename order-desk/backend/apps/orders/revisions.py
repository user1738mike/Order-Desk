"""Streaming aggregate fingerprints, compared under the organization write lock."""

import hashlib
import json
from collections.abc import Callable

from apps.orders.models import DraftOrder, DraftOrderLine


class DraftRevisionConflict(Exception):
    """Source changed since the operator loaded it."""


def draft_revision(order: DraftOrder) -> str:
    digest = hashlib.sha256()
    header = (
        order.pk,
        order.organization_id,
        order.initiating_user_id,
        order.status,
        order.source_type,
        order.customer_name,
        order.customer_reference,
        order.original_intake_text,
        order.created_at,
        order.updated_at,
    )
    digest.update(json.dumps(header, default=str, ensure_ascii=True).encode())
    lines = (
        DraftOrderLine.objects.filter(
            organization_id=order.organization_id, order_id=order.pk
        )
        .order_by("position", "id")
        .values_list(
            "id",
            "position",
            "requested_sku",
            "requested_description",
            "quantity",
            "unit",
            "catalogue_item_id",
            "catalogue_sku_snapshot",
            "catalogue_description_snapshot",
            "created_at",
            "updated_at",
        )
    )
    for line in lines.iterator(chunk_size=200):
        digest.update(b"\n")
        digest.update(json.dumps(line, default=str, ensure_ascii=True).encode())
    return digest.hexdigest()


def check_revision(
    order: DraftOrder, expected: str | Callable[[], str | None] | None
) -> None:
    expected = expected() if callable(expected) else expected
    if expected is not None and expected != draft_revision(order):
        raise DraftRevisionConflict
