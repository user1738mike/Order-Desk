"""Localhost-only development; never use this settings module for a live pilot."""

from config.env import comma_list
from config.settings.base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = comma_list("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1")
# Local HTTP cannot send Secure cookies. Production keeps both settings enabled.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
