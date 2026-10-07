"""Workspace writes with explicit authorization and short transaction boundaries."""

from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.organizations.access import (
    WORKSPACE_ACCESS_DENIED,
    require_active_user,
    require_workspace_admin,
)
from apps.organizations.models import Membership, MembershipRole, Organization

if TYPE_CHECKING:
    from apps.accounts.models import User


@transaction.atomic
def create_organization(*, actor: User | AnonymousUser, name: str) -> Organization:
    require_active_user(actor)
    organization = Organization(name=name.strip())
    organization.full_clean()
    organization.save()

    # Both records commit together; never leave a newly created workspace orphaned.
    membership = Membership(
        organization=organization, user=actor, role=MembershipRole.ADMIN
    )
    membership.full_clean()
    membership.save()
    return organization


@transaction.atomic
def add_member(
    *,
    actor: User | AnonymousUser,
    organization_id: UUID,
    user_id: UUID,
    role: MembershipRole = MembershipRole.VIEWER,
) -> Membership:
    require_active_user(actor)
    # All future membership changes must acquire this same organization lock.
    # It serializes changes within a workspace and closes duplicate-add races.
    organization = (
        Organization.objects.select_for_update()
        .filter(pk=organization_id, is_active=True)
        .first()
    )
    if organization is None:
        raise PermissionDenied(WORKSPACE_ACCESS_DENIED)
    require_workspace_admin(user=actor, organization_id=organization.id)

    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise ValidationError({"user_id": "Select an active existing account."})

    membership = Membership(organization=organization, user=user, role=role)
    membership.full_clean()
    membership.save()
    return membership
