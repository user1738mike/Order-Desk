"""Application access checks. Operator flags never grant workspace access."""

from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from apps.organizations.models import Membership, MembershipRole

if TYPE_CHECKING:
    from apps.accounts.models import User

WORKSPACE_ACCESS_DENIED = "You do not have access to this workspace."


def require_active_user(user: User | AnonymousUser) -> None:
    if (
        isinstance(user, AnonymousUser)
        or not user.is_authenticated
        or not user.is_active
        or user.pk is None
        or user._state.adding
    ):
        raise PermissionDenied("An active account is required.")
    # Do not let an earlier in-memory user instance override current DB state.
    if not get_user_model().objects.filter(pk=user.pk, is_active=True).exists():
        raise PermissionDenied("An active account is required.")


def require_membership(
    *, user: User | AnonymousUser, organization_id: UUID
) -> Membership:
    require_active_user(user)
    membership = (
        Membership.objects.select_related("organization")
        .filter(
            user_id=user.pk,
            organization_id=organization_id,
            is_active=True,
            organization__is_active=True,
        )
        .first()
    )
    if membership is None:
        # The same error applies to missing, inactive, and unauthorized workspaces.
        raise PermissionDenied(WORKSPACE_ACCESS_DENIED)
    return membership


def require_workspace_admin(
    *, user: User | AnonymousUser, organization_id: UUID
) -> Membership:
    membership = require_membership(user=user, organization_id=organization_id)
    if membership.role != MembershipRole.ADMIN:
        raise PermissionDenied("Workspace administrator access is required.")
    return membership
