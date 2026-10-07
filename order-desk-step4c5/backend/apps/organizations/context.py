"""Resolve a workspace from current database state, never from cached roles."""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import AnonymousUser

from apps.organizations.access import require_membership
from apps.organizations.models import MembershipRole

if TYPE_CHECKING:
    from apps.accounts.models import User


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    """Authorization snapshot for one request; do not cache it or enqueue it."""

    organization_id: UUID
    organization_name: str
    user_id: UUID
    membership_id: UUID
    role: MembershipRole


def resolve_workspace_context(
    *, user: User | AnonymousUser, workspace_id: UUID
) -> WorkspaceContext:
    membership = require_membership(user=user, organization_id=workspace_id)
    return WorkspaceContext(
        organization_id=membership.organization_id,
        organization_name=membership.organization.name,
        user_id=membership.user_id,
        membership_id=membership.pk,
        role=MembershipRole(membership.role),
    )
