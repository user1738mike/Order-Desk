"""Apply the shared login budget to API and Django admin credential entry."""

from ipaddress import ip_address

from asgiref.sync import sync_to_async
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.views.decorators.debug import sensitive_variables

from apps.accounts.login_limits import reserve_login_attempt
from apps.accounts.models import User


def request_peer(request: HttpRequest) -> str:
    try:
        return ip_address(request.META.get("REMOTE_ADDR", "")).compressed
    except ValueError:
        # Missing/invalid peer metadata shares a budget instead of bypassing it.
        return "unknown"


class RateLimitedModelBackend(ModelBackend):
    async def aauthenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: str,
    ) -> User | None:
        # ModelBackend has a separate async implementation. Delegate explicitly
        # so asynchronous callers cannot skip the shared reservation.
        return await sync_to_async(self.authenticate, thread_sensitive=True)(
            request, username=username, password=password, **kwargs
        )

    @sensitive_variables("password")
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: str,
    ) -> User | None:
        email = username if username is not None else kwargs.get("email")
        if not isinstance(email, str) or not isinstance(password, str):
            return None
        if request is not None:
            wait = reserve_login_attempt(email=email, peer=request_peer(request))
            if wait is not None:
                # Django catches PermissionDenied and stops trying backends.
                # The API translates this server-side marker into HTTP 429;
                # the standard admin form keeps its generic login error.
                request.login_retry_after = wait
                raise PermissionDenied
        # Trusted non-HTTP callers can still use Django authenticate() directly.
        return super().authenticate(request, email=email, password=password)
