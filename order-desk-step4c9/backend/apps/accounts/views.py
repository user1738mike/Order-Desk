"""Same-origin browser sessions with CSRF checks before credential processing."""

import logging
from datetime import timedelta

from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_variables
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.parsers import LoginJSONParser
from apps.accounts.serializers import LoginSerializer, SessionUserSerializer

SESSION_LIFETIME = timedelta(hours=8)
INVALID_CREDENTIALS = "Invalid email or password."
logger = logging.getLogger(__name__)


@method_decorator(never_cache, name="dispatch")
class CsrfTokenView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    http_method_names = ["get", "head", "options"]

    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request._request)})


@method_decorator([never_cache, csrf_protect], name="dispatch")
class SessionMutationView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (AllowAny,)
    http_method_names = ["post", "options"]


class SessionLoginView(SessionMutationView):
    parser_classes = (LoginJSONParser,)

    @sensitive_variables("serializer")
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = authenticate(request._request, **serializer.validated_data)
        except DatabaseError:
            logger.warning("Login database is unavailable.")
            return Response(
                {"detail": "Sign-in is temporarily unavailable."}, status=503
            )
        wait = getattr(request._request, "login_retry_after", None)
        if wait is not None:
            return Response(
                {"detail": "Too many login attempts. Try again later."},
                status=429,
                headers={"Retry-After": str(wait)},
            )
        if user is None:
            raise ValidationError({"detail": INVALID_CREDENTIALS})

        # Drop the old identity/preferences, including any future workspace
        # selection. Every successful sign-in gets a fresh server-side session.
        request.session.flush()
        django_login(request._request, user)
        request.session.set_expiry(timezone.now() + SESSION_LIFETIME)
        return Response(
            {
                "user": SessionUserSerializer(user).data,
                # Django rotates the CSRF secret on login. Return the new token.
                "csrf_token": get_token(request._request),
            }
        )


class SessionLogoutView(SessionMutationView):
    def post(self, request: Request) -> Response:
        # Also safe to repeat after expiry/logout when valid CSRF is supplied.
        django_logout(request._request)
        return Response(status=204)
