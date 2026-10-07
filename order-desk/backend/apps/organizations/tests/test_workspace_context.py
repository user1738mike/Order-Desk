"""Guard against accidentally using an unscoped request as tenant authority."""

import uuid

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.test import SimpleTestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.organizations.context import resolve_workspace_context
from apps.organizations.permissions import HasWorkspaceAccess, get_workspace_context


class WorkspaceContextGuardTests(SimpleTestCase):
    def test_context_access_without_the_permission_fails_closed(self) -> None:
        request = Request(APIRequestFactory().get("/"))
        with self.assertRaisesMessage(ImproperlyConfigured, "HasWorkspaceAccess"):
            get_workspace_context(request)

    def test_permission_without_a_uuid_route_scope_never_uses_session_or_headers(
        self,
    ) -> None:
        request = Request(
            APIRequestFactory().get("/", HTTP_X_WORKSPACE_ID=str(uuid.uuid4()))
        )
        for kwargs in ({}, {"workspace_id": "invalid"}):
            view = APIView()
            view.kwargs = kwargs
            with self.subTest(kwargs=kwargs), self.assertRaises(ImproperlyConfigured):
                HasWorkspaceAccess().has_permission(request, view)

    def test_anonymous_context_resolution_is_denied_before_database_access(
        self,
    ) -> None:
        with self.assertRaises(PermissionDenied):
            resolve_workspace_context(user=AnonymousUser(), workspace_id=uuid.uuid4())
