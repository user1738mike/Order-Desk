"""Public UI shell; all identity and tenant data comes from protected APIs."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def workspace(request: HttpRequest) -> HttpResponse:
    return render(request, "workspace.html")
