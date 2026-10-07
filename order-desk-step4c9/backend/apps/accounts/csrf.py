"""A generic JSON CSRF error for API requests; retain Django's HTML elsewhere."""

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    if request.path.startswith("/api/"):
        response = JsonResponse({"detail": "CSRF verification failed."}, status=403)
        response["Cache-Control"] = "private, no-store"
        return response
    return django_csrf_failure(request, reason=reason)
