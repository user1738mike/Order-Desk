"""Shared read-only readiness decision over a coherent annotated draft."""


def evaluate_draft_readiness(order) -> dict:
    reasons = []
    counts = (
        ("draft_already_converted", int(order.status == "converted")),
        ("customer_name_missing", int(not order.customer_name.strip())),
        ("lines_missing", int(order.line_count == 0)),
        ("quantity_missing", order.missing_quantity_line_count),
        ("catalogue_unmatched", order.unmatched_line_count),
        ("catalogue_inactive", order.inactive_catalogue_line_count),
        ("catalogue_sku_too_long", order.long_catalogue_sku_line_count),
    )
    for code, count in counts:
        if count:
            reasons.append({"code": code, "count": count})
    return {
        "id": order.pk,
        "organization_id": order.organization_id,
        "ready_to_convert": not reasons,
        "line_count": order.line_count,
        "blocking_reasons": reasons,
    }
