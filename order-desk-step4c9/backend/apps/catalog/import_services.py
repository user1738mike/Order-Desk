"""Administrator CSV inspection inside an owned read-only tenant transaction."""

from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from apps.catalog import selectors
from apps.catalog.imports import parse_catalogue_csv
from apps.organizations.context import resolve_workspace_context
from apps.organizations.models import MembershipRole
from apps.organizations.transactions import tenant_scope

if TYPE_CHECKING:
    from apps.accounts.models import User

CATALOG_IMPORT_DRY_RUN_DENIED = (
    "You do not have permission to validate catalogue imports in this workspace."
)
CONFLICT_BATCH_SIZE = 250


def catalogue_import_dry_run(
    *,
    actor: User | AnonymousUser,
    organization_id: UUID,
    data: bytes | Callable[[], bytes],
) -> dict:
    """Authorize before parsing; consume bounded conflict queries and report here."""
    with tenant_scope(user=actor, workspace_id=organization_id) as scope:
        if scope.role != MembershipRole.ADMIN:
            raise PermissionDenied(CATALOG_IMPORT_DRY_RUN_DENIED)
        parsed = parse_catalogue_csv(data() if callable(data) else data)
        # CSV work has completed. Refresh active account/member/workspace and
        # administrator role immediately before reading catalogue state.
        refreshed = resolve_workspace_context(
            user=actor, workspace_id=scope.organization_id
        )
        if refreshed.role != MembershipRole.ADMIN:
            raise PermissionDenied(CATALOG_IMPORT_DRY_RUN_DENIED)
        skus = sorted({row.sku for row in parsed.rows if row.sku is not None})
        existing = set()
        for start in range(0, len(skus), CONFLICT_BATCH_SIZE):
            existing.update(
                selectors.existing_catalog_skus(
                    organization_id=scope.organization_id,
                    skus=skus[start : start + CONFLICT_BATCH_SIZE],
                )
            )
        return parsed.report(existing)
