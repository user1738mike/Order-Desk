"""Bound the credential request before JSON decoding or password hashing."""

from io import BytesIO

from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser

MAX_LOGIN_BODY_BYTES = 16 * 1024


class LoginBodyTooLarge(ParseError):
    status_code = 413
    default_detail = "Login request is too large."


class LoginJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        body = stream.read(MAX_LOGIN_BODY_BYTES + 1)
        if len(body) > MAX_LOGIN_BODY_BYTES:
            raise LoginBodyTooLarge
        return super().parse(BytesIO(body), media_type, parser_context)
