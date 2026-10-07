"""Workspace identities and memberships, separate from global user identities."""

import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


class MembershipRole(models.TextChoices):
    ADMIN = "admin", "Administrator"
    REVIEWER = "reviewer", "Reviewer"
    VIEWER = "viewer", "Viewer"


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=200,
        validators=[RegexValidator(r"\S", "Enter a nonblank organization name.")],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(name__regex=r"\S"),
                name="org_name_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organization_memberships",
    )
    role = models.CharField(
        max_length=16, choices=MembershipRole.choices, default=MembershipRole.VIEWER
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Inactive memberships still occupy the pair; reactivation is explicit.
            models.UniqueConstraint(
                fields=("organization", "user"), name="org_membership_user_unique"
            ),
            # choices validates forms/models; this also guards direct DB writes.
            models.CheckConstraint(
                condition=models.Q(role__in=MembershipRole.values),
                name="org_membership_role_valid",
            ),
        ]

    def __str__(self) -> str:
        # Do not fetch related users or include email addresses in diagnostic labels.
        return f"{self.user_id} / {self.organization_id} ({self.role})"
