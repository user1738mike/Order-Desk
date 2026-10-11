"""Exact local TLS topology; inherits production's secret/DB/cookie checks."""

from copy import deepcopy

from django.core.exceptions import ImproperlyConfigured

from config.settings.production import *  # noqa: F403

if ALLOWED_HOSTS != ["orderdesk.localhost"]:  # noqa: F405
    raise ImproperlyConfigured("Local deployment requires orderdesk.localhost.")
if CSRF_TRUSTED_ORIGINS != ["https://orderdesk.localhost:8443"]:  # noqa: F405
    raise ImproperlyConfigured("Local deployment requires its exact HTTPS origin.")
if globals().get("SECURE_PROXY_SSL_HEADER") != ("HTTP_X_FORWARDED_PROTO", "https"):
    raise ImproperlyConfigured("Local deployment requires the isolated HTTPS proxy.")

SECURE_HSTS_SECONDS = 60
# Intentional local-host policy: neither sibling HTTPS nor public preload is
# asserted. Only these two checks are acknowledged; other warnings fail startup.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
REQUIRE_PRIVATE_STORAGE_READY = True
# The local server uses two synchronous WSGI workers. Tenant state is SET LOCAL
# in an outermost transaction and contaminated sessions are discarded. Reuse
# bounded connections to avoid a fresh DB TLS handshake on every HTTP request.
DATABASES = deepcopy(DATABASES)  # noqa: F405
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
STORAGES = {
    "default": {"BACKEND": "apps.orders.document_storage.DocumentSourceStorage"},
    "staticfiles": {"BACKEND": "apps.web.static_storage.ModuleManifestStorage"},
}
