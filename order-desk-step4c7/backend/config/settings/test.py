"""PostgreSQL tests use the dedicated database provisioned by dbsetup."""

from config.settings.local import *  # noqa: F403

DEBUG = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
