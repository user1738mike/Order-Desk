"""Explicit, permission-scoped reads for use by future API and domain modules."""

from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet

from apps.organizations.access import require_active_user, require_workspace_admin
from apps.organizations.models import Membership, MembershipRole, Organization

if TYPE_CHECKING:
    from apps.accounts.models import User


def organizations_for_user(*, user: User | AnonymousUser) -> QuerySet[Organization]:
    require_active_user(user)
    return Organization.objects.filter(
        is_active=True,
        memberships__user_id=user.pk,
        memberships__is_active=True,
        memberships__user__is_active=True,
    ).order_by("name", "id")


def memberships_for_organization(
    *, user: User | AnonymousUser, organization_id: UUID
) -> QuerySet[Membership]:
    membership = require_workspace_admin(user=user, organization_id=organization_id)
    # Keep the permission predicates in the lazy query too: constructing this
    # QuerySet must not preserve access after the actor's membership is revoked.
    return Membership.objects.filter(
        organization_id=membership.organization_id,
        organization__is_active=True,
        organization__memberships__user_id=user.pk,
        organization__memberships__user__is_active=True,
        organization__memberships__is_active=True,
        organization__memberships__role=MembershipRole.ADMIN,
    ).order_by("created_at", "id")
