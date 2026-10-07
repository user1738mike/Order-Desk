"""Small, strict environment readers; never include secret values in errors."""

import os

from django.core.exceptions import ImproperlyConfigured


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Set the {name} environment variable.")
    return value


def integer(name: str, default: int, *, minimum: int = 1, maximum: int = 65535) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} must be an integer.") from error
    if not minimum <= value <= maximum:
        raise ImproperlyConfigured(f"{name} is outside its allowed range.")
    return value


def boolean(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name, str(default)).strip().lower()
    if raw in {"1", "true"}:
        return True
    if raw in {"0", "false"}:
        return False
    raise ImproperlyConfigured(f"{name} must be true, false, 1, or 0.")


def comma_list(name: str, *, default: str = "") -> list[str]:
    return [
        item.strip()
        for item in os.environ.get(name, default).split(",")
        if item.strip()
    ]
