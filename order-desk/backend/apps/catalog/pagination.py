"""Fixed catalogue pages accepting only the strict list-search query contract."""

from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request

from apps.catalog.query_params import parse_list_query


def validate_query_parameters(request: Request) -> None:
    # Retain the standalone paginator's public guard. Views parse first so
    # detailed validation occurs before building catalogue queries in scope.
    parse_list_query(request.query_params)


class FixedPagePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = None
    last_page_strings = ()
    invalid_page_message = "Invalid page."

    def get_page_number(self, request, paginator):
        value = request.query_params.get(self.page_query_param, "1")
        if not value.isascii() or not value.isdecimal() or not value.lstrip("0"):
            raise NotFound("Invalid page.")
        return value


class CatalogPagination(FixedPagePagination):
    def paginate_queryset(self, queryset, request, view=None):
        validate_query_parameters(request)
        return super().paginate_queryset(queryset, request, view=view)
