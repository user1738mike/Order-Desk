"""Deterministic exact-SKU evidence; no writes or fuzzy normalization."""

import hashlib
import json

RULE_VERSION = "exact-sku-v1"
MAX_SOURCE_LENGTH = 4096


class CatalogueSuggestionConflict(Exception):
    """Assessed source/catalogue evidence no longer matches current state."""


def catalogue_revision(item):
    evidence = [
        str(item.pk),
        item.sku,
        item.description,
        item.is_active,
        item.updated_at.isoformat(),
    ]
    return hashlib.sha256(
        json.dumps(evidence, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def assess_line(line, items):
    source = line.requested_sku
    normalized = source.strip()
    matches = [item for item in items if item.sku == normalized]
    active = [item for item in matches if item.is_active]
    candidate = (
        active[0] if len(active) == 1 else matches[0] if len(matches) == 1 else None
    )
    if len(source) > MAX_SOURCE_LENGTH:
        state, candidate = "unsupported_sku", None
    elif not normalized:
        state = "empty_sku"
    elif len(active) > 1 or (not active and len(matches) > 1):
        state = "ambiguous"
    elif candidate is None:
        state = "no_match"
    else:
        state = "exact" if candidate.is_active else "inactive"
    attached = next((item for item in items if item.pk == line.catalogue_item_id), None)
    attachment = "none"
    if line.catalogue_item_id:
        if attached is None:
            attachment = "unavailable"
        elif not attached.is_active:
            attachment = "inactive"
        elif attached.sku != normalized:
            attachment = "source_changed"
        elif (line.catalogue_sku_snapshot, line.catalogue_description_snapshot) != (
            attached.sku,
            attached.description,
        ):
            attachment = "snapshot_changed"
        else:
            attachment = "current"
            if candidate is not None and candidate.pk == attached.pk:
                state = "already_attached"
    return {
        "line_id": str(line.pk),
        "position": line.position,
        "source_sku": source[:MAX_SOURCE_LENGTH],
        "source_truncated": len(source) > MAX_SOURCE_LENGTH,
        "normalized_sku": normalized[:MAX_SOURCE_LENGTH],
        "state": state,
        "candidate": None
        if candidate is None
        else {
            "id": str(candidate.pk),
            "sku": candidate.sku,
            "description": candidate.description[:4096],
            "description_truncated": len(candidate.description) > 4096,
            "is_active": candidate.is_active,
            "revision": catalogue_revision(candidate),
        },
        "attachment": {
            "id": str(line.catalogue_item_id) if line.catalogue_item_id else None,
            "state": attachment,
        },
        "checks": {
            "unit": "not_modeled",
            "pricing": "not_modeled",
            "quantity": "not_assessed",
        },
    }
