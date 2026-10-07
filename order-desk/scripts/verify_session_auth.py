"""Verify local browser-session behavior with Python's standard library.

Run from the project root: python scripts/verify_session_auth.py
Credentials are prompted, never accepted as command-line arguments or printed.
This utility contacts only the local API at http://127.0.0.1:8000.
"""

import getpass
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A verification route must answer directly; never forward credentials.
        return None


def request(
    opener: urllib.request.OpenerDirector,
    path: str,
    *,
    method: str = "GET",
    expected: int,
    payload: dict | None = None,
    csrf: str | None = None,
    origin: str | None = None,
) -> dict:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if csrf is not None:
        headers["X-CSRFToken"] = csrf
    if origin is not None:
        headers["Origin"] = origin
    http_request = urllib.request.Request(  # noqa: S310 -- fixed HTTP loopback URL
        BASE_URL + path, data=body, headers=headers, method=method
    )
    try:
        response = opener.open(http_request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        status = response.code
        response_body = response.read()
    if status != expected:
        raise RuntimeError(f"{method} {path}: expected HTTP {expected}; got {status}.")
    print(f"{method} {path}: HTTP {status} (expected)")
    return json.loads(response_body) if response_body else {}


def main() -> None:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )
    request(opener, "/api/v1/workspaces/", expected=403)
    request(opener, "/api/v1/auth/login/", method="POST", payload={}, expected=403)
    csrf = request(opener, "/api/v1/auth/csrf/", expected=200)["csrf_token"]
    request(
        opener,
        "/api/v1/auth/login/",
        method="POST",
        payload={},
        csrf=csrf,
        origin="https://untrusted.example.test",
        expected=403,
    )

    email = input("Existing local account email: ").strip()
    password = getpass.getpass("Password (hidden): ")
    try:
        logged_in = request(
            opener,
            "/api/v1/auth/login/",
            method="POST",
            payload={"email": email, "password": password},
            csrf=csrf,
            origin=BASE_URL,
            expected=200,
        )
    finally:
        del password
    new_csrf = logged_in["csrf_token"]
    request(opener, "/api/v1/workspaces/", expected=200)
    request(opener, "/api/v1/auth/logout/", method="POST", payload={}, expected=403)
    # A token from before login must fail against the rotated CSRF cookie.
    request(
        opener,
        "/api/v1/auth/logout/",
        method="POST",
        payload={},
        csrf=csrf,
        expected=403,
    )
    request(opener, "/api/v1/workspaces/", expected=200)
    for _ in range(2):
        request(
            opener,
            "/api/v1/auth/logout/",
            method="POST",
            payload={},
            csrf=new_csrf,
            origin=BASE_URL,
            expected=204,
        )
    request(opener, "/api/v1/workspaces/", expected=403)
    print("Session login/logout verification passed.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, urllib.error.URLError, ValueError, KeyError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        sys.exit(1)
    except EOFError, KeyboardInterrupt:
        print("Verification cancelled.", file=sys.stderr)
        sys.exit(1)
