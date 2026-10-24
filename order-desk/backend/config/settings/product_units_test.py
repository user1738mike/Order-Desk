"""Isolated verification of the unit increment before development activation."""

from config.settings.product_units_preview import *  # noqa: F403

DEBUG = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
