"""Bind explicitly scoped API requests after DRF session authentication."""

from uuid import UUID

from django.core.exceptions import ImproperlyConfigured
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.organizations.context import WorkspaceContext, resolve_workspace_context


class HasWorkspaceAccess(BasePermission):
    """Use with IsAuthenticated and a <uuid:workspace_id> URL parameter."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        workspace_id = view.kwargs.get("workspace_id")
        if not isinstance(workspace_id, UUID):
            # A missing route scope is a server configuration error, not a
            # reason to fall back to a cookie, query parameter, or header.
            raise ImproperlyConfigured(
                "HasWorkspaceAccess requires a UUID workspace_id URL parameter."
            )
        request.workspace_context = resolve_workspace_context(
            user=request.user, workspace_id=workspace_id
        )
        return True


def get_workspace_context(request: Request) -> WorkspaceContext:
    context = getattr(request, "workspace_context", None)
    if not isinstance(context, WorkspaceContext):
        raise ImproperlyConfigured(
            "Workspace-scoped views must apply HasWorkspaceAccess."
        )
    return context
