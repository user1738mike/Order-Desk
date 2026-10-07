"""Remember a workspace preference without remembering its permissions."""

from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.base import SessionBase
from django.core.exceptions import PermissionDenied

from apps.organizations.access import require_active_user
from apps.organizations.context import WorkspaceContext, resolve_workspace_context

if TYPE_CHECKING:
    from apps.accounts.models import User

SELECTED_WORKSPACE_KEY = "selected_workspace_id"


def selected_workspace_context(
    *, user: User | AnonymousUser, session: SessionBase
) -> WorkspaceContext | None:
    require_active_user(user)
    value = session.get(SELECTED_WORKSPACE_KEY)
    if not isinstance(value, str):
        return None
    try:
        workspace_id = UUID(value)
    except ValueError:
        return None
    try:
        return resolve_workspace_context(user=user, workspace_id=workspace_id)
    except PermissionDenied:
        # A stale preference grants no access. Keep GET side-effect free;
        # the client can select an accessible workspace or explicitly clear it.
        return None


def select_workspace(
    *, user: User | AnonymousUser, session: SessionBase, workspace_id: UUID
) -> WorkspaceContext:
    context = resolve_workspace_context(user=user, workspace_id=workspace_id)
    # Only write after successful authorization; failed selection preserves the
    # previous preference. Membership, name, and role are never stored here.
    session[SELECTED_WORKSPACE_KEY] = str(context.organization_id)
    return context
