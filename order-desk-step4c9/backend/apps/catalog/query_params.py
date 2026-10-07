"""Separate strict catalogue list-search and exact-SKU query contracts."""

from dataclasses import dataclass

from django.http import QueryDict
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.catalog.models import CatalogItem


@dataclass(frozen=True, slots=True)
class CatalogListQuery:
    q: str | None = None
    is_active: bool | None = None


def _validate_parameters(params: QueryDict, allowed: set[str]) -> None:
    errors = {}
    for key, values in params.lists():
        if key not in allowed:
            errors[key] = ["Unknown query parameter."]
        elif len(values) != 1:
            errors[key] = ["Provide this query parameter once."]
    if errors:
        raise ValidationError(errors)


def _text_parameter(
    params: QueryDict, name: str, *, max_length: int | None = None
) -> str:
    # CharField applies whitespace normalization before length validators and
    # rejects NUL/surrogate text before a database driver can receive it.
    field = serializers.CharField(trim_whitespace=True, max_length=max_length)
    try:
        return field.run_validation(params.get(name, serializers.empty))
    except ValidationError as error:
        raise ValidationError({name: error.detail}) from error


def parse_list_query(params: QueryDict) -> CatalogListQuery:
    """Validate shape/filters; pagination retains its existing page-value 404s."""
    _validate_parameters(params, {"page", "q", "is_active"})
    q = _text_parameter(params, "q", max_length=200) if "q" in params else None
    is_active = None
    if "is_active" in params:
        value = params["is_active"]
        if value not in ("true", "false"):
            raise ValidationError({"is_active": ["Use exactly true or false."]})
        is_active = value == "true"
    return CatalogListQuery(q=q, is_active=is_active)


def parse_exact_sku(params: QueryDict) -> str:
    """Use creation's trim and the actual model limit, without changing case."""
    _validate_parameters(params, {"sku"})
    return _text_parameter(
        params, "sku", max_length=CatalogItem._meta.get_field("sku").max_length
    )
