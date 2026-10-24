"""Isolated verification of the unit increment before development activation."""

from config.settings.test import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.product_units.apps.ProductUnitsConfig"]  # noqa: F405
ROOT_URLCONF = "config.product_units_urls"
