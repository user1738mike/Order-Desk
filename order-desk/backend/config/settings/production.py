"""Fail-closed production settings; deployment and serving are a separate step."""

from django.core.exceptions import ImproperlyConfigured

from config.env import boolean, comma_list, required
from config.settings import base
from config.settings.base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = comma_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS or any(
    host in {"*", "localhost", "127.0.0.1", "testserver"} for host in ALLOWED_HOSTS
):
    raise ImproperlyConfigured(
        "Production requires explicit public DJANGO_ALLOWED_HOSTS."
    )
if (
    len(base.SECRET_KEY) < 50
    or len(set(base.SECRET_KEY)) < 5
    or base.SECRET_KEY.startswith("django-insecure-")
):
    raise ImproperlyConfigured("Production requires a strong DJANGO_SECRET_KEY.")

DATABASES["default"]["OPTIONS"].update(  # noqa: F405
    sslmode="verify-full",
    sslrootcert=required("DATABASE_SSLROOTCERT"),
)
CSRF_TRUSTED_ORIGINS = comma_list("DJANGO_CSRF_TRUSTED_ORIGINS")
if any(
    not origin.startswith("https://") or "*" in origin
    for origin in CSRF_TRUSTED_ORIGINS
):
    raise ImproperlyConfigured(
        "Production CSRF origins must be explicit HTTPS origins."
    )
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
# Do not impose a policy on sibling services or submit a domain to preload yet.
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
if boolean("DJANGO_TRUST_PROXY_HTTPS"):
    # Enable only after the trusted proxy strips client-supplied forwarded headers.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
