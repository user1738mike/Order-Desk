"""Unit increment verification; does not activate it on the development API."""

from config.settings.local import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.product_units.apps.ProductUnitsConfig"]  # noqa: F405
ROOT_URLCONF = "config.product_units_urls"
