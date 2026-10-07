"""Short, outermost PostgreSQL transactions with freshly authorized tenant IDs."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db import connection, transaction
from psycopg.pq import TransactionStatus

from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.context import WorkspaceContext, resolve_workspace_context
from apps.organizations.models import Organization

if TYPE_CHECKING:
    from apps.accounts.models import User

ORGANIZATION_SETTING = "orderdesk.organization_id"
USER_SETTING = "orderdesk.user_id"


class TenantScopeError(RuntimeError):
    """The connection state cannot safely start a new tenant transaction."""


def _require_clean_connection() -> None:
    if connection.vendor != "postgresql":
        raise ImproperlyConfigured("Tenant scopes require PostgreSQL.")
    if connection.in_atomic_block or not connection.get_autocommit():
        # Leave the caller's transaction/connection intact when refusing nesting.
        raise TenantScopeError("A tenant scope must own the outer transaction.")

    # Django's flags do not track transactions opened directly through the driver.
    # Refuse those before querying settings or discarding a contaminated session.
    database = connection.connection
    if (
        not database.autocommit
        or database.info.transaction_status != TransactionStatus.IDLE
    ):
        raise TenantScopeError("A tenant scope requires an idle autocommit connection.")

    with connection.cursor() as cursor:
        # Inspect text first: even malformed ambient UUIDs must discard the session.
        cursor.execute(
            "SELECT NULLIF(pg_catalog.current_setting(%s, true), ''), "
            "NULLIF(pg_catalog.current_setting(%s, true), '')",
            [ORGANIZATION_SETTING, USER_SETTING],
        )
        organization_id, user_id = cursor.fetchone()
    if organization_id is not None or user_id is not None:
        connection.close()
        raise TenantScopeError("Discarded a connection with ambient tenant settings.")


@contextmanager
def tenant_scope(
    *, user: User | AnonymousUser, workspace_id: UUID, write: bool = False
) -> Iterator[WorkspaceContext]:
    """Authorize and bind one workspace on Django's default database connection.

    Pass the server-authenticated user and an explicit, parsed workspace UUID.
    Consume all database results inside this block; no lazy QuerySets/relations
    may escape. Exceptions must leave the block before conversion into responses.
    A write scope locks the organization; each service still checks its own roles.
    Nested tenant scopes are forbidden, but same-tenant atomic savepoints are fine.
    """
    if not isinstance(workspace_id, UUID):
        raise TypeError("workspace_id must be a UUID.")
    if not isinstance(write, bool):
        raise TypeError("write must be a bool.")

    _require_clean_connection()
    with transaction.atomic(durable=True):
        with connection.cursor() as cursor:
            # Fresh membership reads after a lock wait need READ COMMITTED snapshots.
            # Both statements are static SQL; never interpolate a caller's value.
            if write:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE"
                )
            else:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY"
                )

        if write:
            # Membership-changing services acquire this same row lock first.
            organization = (
                Organization.objects.select_for_update()
                .filter(pk=workspace_id, is_active=True)
                .first()
            )
            if organization is None:
                raise PermissionDenied(WORKSPACE_ACCESS_DENIED)

        context = resolve_workspace_context(user=user, workspace_id=workspace_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.set_config(%s, %s, true), "
                "pg_catalog.set_config(%s, %s, true)",
                [
                    ORGANIZATION_SETTING,
                    str(context.organization_id),
                    USER_SETTING,
                    str(context.user_id),
                ],
            )
        # PostgreSQL restores the clean baseline on commit or rollback. Do not
        # issue cleanup SQL inside a possibly aborted transaction in a finally.
        yield context
