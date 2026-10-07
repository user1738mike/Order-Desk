"""Fixed catalogue pages with one optional page parameter and stable errors."""

from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request


def validate_query_parameters(request: Request) -> None:
    errors = {}
    for key, values in request.query_params.lists():
        if key != "page":
            errors[key] = ["Unknown query parameter."]
        elif len(values) != 1:
            errors[key] = ["Provide this query parameter once."]
    if errors:
        raise ValidationError(errors)


class CatalogPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = None
    last_page_strings = ()
    invalid_page_message = "Invalid page."

    def paginate_queryset(self, queryset, request, view=None):
        validate_query_parameters(request)
        return super().paginate_queryset(queryset, request, view=view)

    def get_page_number(self, request, paginator):
        value = request.query_params.get(self.page_query_param, "1")
        if not value.isascii() or not value.isdecimal() or not value.lstrip("0"):
            raise NotFound("Invalid page.")
        return value
