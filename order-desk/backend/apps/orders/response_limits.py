"""Explicit legacy nested-response budgets; never silently truncate records."""

from rest_framework.exceptions import APIException

MAX_ORDER_LINES = 500
MAX_ORDER_DOCUMENTS = 50
MAX_DOCUMENT_REVIEWS = 50


class OrderResponseLimitExceeded(APIException):
    status_code = 413
    default_detail = "Order history exceeds the nested response limit."
    default_code = "order_response_limit_exceeded"
