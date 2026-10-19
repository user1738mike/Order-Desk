"""Operational HTTP diagnostics without request data or exception payloads."""

import json
import logging
import re
from datetime import UTC, datetime

METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
)


class RedactedHttpFormatter(logging.Formatter):
    def format(self, record):
        # Do not call getMessage(), formatException() or the base formatter:
        # database exception details, arguments and request attributes can contain
        # customer fields or credentials. Retain failure classification instead.
        request = getattr(record, "request", None)
        method = getattr(request, "method", None)
        route = getattr(getattr(request, "resolver_match", None), "view_name", None)
        request_id = getattr(request, "META", {}).get("HTTP_X_REQUEST_ID")
        status = getattr(record, "status_code", None)
        error_type = type(record.exc_info[1]).__name__ if record.exc_info else None
        return json.dumps(
            {
                "time": datetime.fromtimestamp(record.created, UTC).isoformat(
                    timespec="milliseconds"
                ),
                "event": "http_error"
                if record.levelno >= logging.ERROR
                else "http_event",
                "level": record.levelname,
                "status": status
                if type(status) is int and 100 <= status <= 599
                else None,
                "method": method
                if isinstance(method, str) and method in METHODS
                else "OTHER",
                "route": route
                if isinstance(route, str) and re.fullmatch(r"[\w:-]{1,128}", route)
                else None,
                "error_type": error_type,
                "request_id": request_id
                if isinstance(request_id, str)
                and re.fullmatch(r"[0-9a-f]{32}", request_id)
                else None,
            },
            separators=(",", ":"),
        )
