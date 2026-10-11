"""Credential-free collectstatic build; never an application runtime module."""

import os

# These public placeholders are unused by collectstatic. No deployment environment
# or credentials are read into a build layer.
for name, value in {
    "DJANGO_SECRET_KEY": "public-static-build-placeholder-only",
    "DATABASE_NAME": "unused",
    "DATABASE_USER": "unused",
    "DATABASE_PASSWORD": "unused",
    "DATABASE_HOST": "unused",
}.items():
    os.environ[name] = value

from config.settings.base import *  # noqa: E402, F403

STATIC_ROOT = "/static-output"
STORAGES = {
    "default": {"BACKEND": "apps.orders.document_storage.DocumentSourceStorage"},
    "staticfiles": {"BACKEND": "apps.web.static_storage.ModuleManifestStorage"},
}
