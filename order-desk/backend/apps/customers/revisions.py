"""Opaque versions include DB-maintained modification time and stable identity."""

import hashlib


def record_revision(record):
    value = f"{record.pk}/{record.updated_at.isoformat()}"
    return hashlib.sha256(value.encode()).hexdigest()
