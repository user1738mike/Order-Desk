"""Public, minimal probes. Never expose exception text or infrastructure details."""

import logging

from django.db import DatabaseError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User

logger = logging.getLogger(__name__)


class HealthView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    http_method_names = ["get", "head", "options"]

    def status_response(self, status: str, *, status_code: int = 200) -> Response:
        response = Response({"status": status}, status=status_code)
        response["Cache-Control"] = "no-store"
        return response


class LivenessView(HealthView):
    def get(self, request: Request) -> Response:
        return self.status_response("ok")


class ReadinessView(HealthView):
    def get(self, request: Request) -> Response:
        try:
            # Also catches unapplied initial migrations or missing runtime grants.
            User.objects.exists()
        except DatabaseError:
            logger.warning("Database readiness check failed.")
            return self.status_response("unavailable", status_code=503)
        return self.status_response("ok")
