"""Workspace discovery, session preferences, and explicit request context."""

from uuid import UUID

from django.db.models import QuerySet
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import ListAPIView
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.access import require_active_user
from apps.organizations.context import WorkspaceContext
from apps.organizations.models import Organization
from apps.organizations.permissions import HasWorkspaceAccess, get_workspace_context
from apps.organizations.selection import (
    SELECTED_WORKSPACE_KEY,
    select_workspace,
    selected_workspace_context,
)
from apps.organizations.selectors import organizations_for_user
from apps.organizations.serializers import (
    WorkspaceContextSerializer,
    WorkspaceSelectionSerializer,
    WorkspaceSerializer,
)


@method_decorator(never_cache, name="dispatch")
class WorkspaceListView(ListAPIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    serializer_class = WorkspaceSerializer
    http_method_names = ["get", "head", "options"]

    def get_queryset(self) -> QuerySet[Organization]:
        # Use the server-authenticated user; request parameters cannot choose it.
        return organizations_for_user(user=self.request.user)


def workspace_response(context: WorkspaceContext | None) -> Response:
    workspace = (
        WorkspaceContextSerializer(context).data if context is not None else None
    )
    return Response({"workspace": workspace})


@method_decorator(never_cache, name="dispatch")
class CurrentWorkspaceView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)
    http_method_names = ["get", "head", "put", "delete", "options"]

    def get(self, request: Request) -> Response:
        return workspace_response(
            selected_workspace_context(user=request.user, session=request.session)
        )

    def put(self, request: Request) -> Response:
        # SessionAuthentication enforces CSRF before authenticated mutations.
        serializer = WorkspaceSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        context = select_workspace(
            user=request.user,
            session=request.session,
            workspace_id=serializer.validated_data["workspace_id"],
        )
        return workspace_response(context)

    def delete(self, request: Request) -> Response:
        require_active_user(request.user)
        request.session.pop(SELECTED_WORKSPACE_KEY, None)
        return Response(status=204)


@method_decorator(never_cache, name="dispatch")
class WorkspaceContextView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated, HasWorkspaceAccess)
    http_method_names = ["get", "head", "options"]

    def get(self, request: Request, workspace_id: UUID) -> Response:
        # The permission built this context from this URL and current DB state.
        # The shared browser-session selection cannot redirect this request.
        return workspace_response(get_workspace_context(request))
