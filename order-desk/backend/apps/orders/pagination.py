"""Strict fixed-size pages for draft headers and their separate lines."""

from django.http import QueryDict
from rest_framework.exceptions import ValidationError

from apps.catalog.pagination import FixedPagePagination


def validate_draft_query(params: QueryDict, *, allow_page: bool) -> None:
    allowed = {"page"} if allow_page else set()
    errors = {}
    for key, values in params.lists():
        if key not in allowed:
            errors[key] = ["Unknown query parameter."]
        elif len(values) != 1:
            errors[key] = ["Provide this query parameter once."]
    if errors:
        raise ValidationError(errors)


class DraftOrderPagination(FixedPagePagination):
    def paginate_queryset(self, queryset, request, view=None):
        validate_draft_query(request.query_params, allow_page=True)
        return super().paginate_queryset(queryset, request, view=view)
