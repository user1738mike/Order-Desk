"""Verify catalogue reads through the running local HTTP server.

Run from the project root:
    python scripts/verify_catalog_api.py
    python scripts/verify_catalog_api.py --workspace-id <existing-workspace-uuid>

Only numeric loopback HTTP(S) URLs are accepted. Credentials are prompted,
never accepted as arguments, printed, or saved. Existing rows are read without
displaying customer data. No accounts, workspaces, or catalogue rows are created.
"""

import argparse
import getpass
import http.cookiejar
import ipaddress
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from uuid import UUID, uuid4

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
WORKSPACES = "/api/v1/workspaces/"
DENIAL = {"detail": "You do not have access to this workspace."}
ITEM_FIELDS = {
    "id",
    "organization_id",
    "sku",
    "description",
    "is_active",
    "created_at",
    "updated_at",
}
PAGE_FIELDS = {"count", "next", "previous", "results"}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_DISCOVERY_PAGES = 20


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def validate_base_url(value: str) -> str:
    if not isinstance(value, str) or any(ord(char) <= 32 for char in value):
        raise ValueError("Use an HTTP(S) URL with a numeric loopback address.")
    try:
        parsed = urllib.parse.urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as error:
        raise ValueError(
            "Use an HTTP(S) URL with a numeric loopback address."
        ) from error
    if (
        parsed.scheme not in {"http", "https"}
        or not address.is_loopback
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("Use an HTTP(S) origin with a numeric loopback address.")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def request_url(base_url: str, path: str) -> str:
    base_url = validate_base_url(base_url)
    parsed = urllib.parse.urlsplit(path)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or any(ord(char) < 32 for char in path)
    ):
        raise ValueError("Verification requests must stay on the local API origin.")
    return base_url + path


def page_path(base_url: str, link: str, *, endpoint: str) -> tuple[str, int]:
    require(isinstance(link, str), "A pagination link is not a string.")
    target = urllib.parse.urlsplit(
        urllib.parse.urljoin(validate_base_url(base_url) + "/", link)
    )
    base = urllib.parse.urlsplit(base_url)
    try:
        same_origin = (
            target.scheme == base.scheme
            and target.hostname == base.hostname
            and target.port == base.port
        )
    except ValueError as error:
        raise RuntimeError("A pagination link has an invalid origin.") from error
    require(
        same_origin
        and target.username is None
        and target.password is None
        and not target.fragment
        and target.path == endpoint,
        "A pagination link escaped its local workspace endpoint.",
    )
    parameters = urllib.parse.parse_qsl(target.query, keep_blank_values=True)
    # DRF omits ?page=1 from the normal previous link on page two.
    if not parameters:
        return request_url(base_url, target.path), 1
    require(
        len(parameters) == 1 and parameters[0][0] == "page",
        "A pagination link contains unexpected query parameters.",
    )
    value = parameters[0][1]
    require(
        value.isascii() and value.isdecimal() and bool(value.lstrip("0")),
        "A pagination link has an invalid page.",
    )
    try:
        number = int(value)
    except ValueError as error:
        raise RuntimeError("A pagination link has an invalid page.") from error
    return request_url(base_url, target.path + "?" + target.query), number


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even a loopback redirect is unexpected; never forward credentials.
        return None


@dataclass
class Response:
    body: object
    cache_control: str


def request(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    path: str,
    *,
    expected: int,
    method: str = "GET",
    payload: dict | None = None,
    csrf: str | None = None,
) -> Response:
    url = request_url(base_url, path)
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if csrf is not None:
        headers["X-CSRFToken"] = csrf
        headers["Origin"] = base_url
    http_request = urllib.request.Request(  # noqa: S310 -- numeric loopback guard
        url, data=body, headers=headers, method=method
    )
    try:
        response = opener.open(http_request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        status = response.code
        content_type = response.headers.get("Content-Type", "")
        cache_control = response.headers.get("Cache-Control", "")
        response_body = response.read(MAX_RESPONSE_BYTES + 1)
    require(
        len(response_body) <= MAX_RESPONSE_BYTES, "An API response exceeded the limit."
    )
    require(
        status == expected,
        f"{method} {path}: expected HTTP {expected}; got {status}.",
    )
    print(f"{method} {path}: HTTP {status} (expected)")
    # Unmatched UUID routes may return HTML 404s, and HEAD/204 have no body.
    parsed_body = None
    if response_body and "application/json" in content_type.lower():
        parsed_body = json.loads(response_body)
    return Response(parsed_body, cache_control)


def require_private(response: Response) -> None:
    directives = {part.strip().lower() for part in response.cache_control.split(",")}
    require(
        {"private", "no-store", "no-cache"}.issubset(directives),
        "A catalogue response is not private and non-cacheable.",
    )


def validate_catalogue_page(
    response: Response, *, base_url: str, endpoint: str, number: int
) -> dict:
    require_private(response)
    page = response.body
    workspace_id = UUID(urllib.parse.urlsplit(endpoint).path.split("/")[4])
    require(isinstance(page, dict), "The catalogue did not return a JSON object.")
    require(set(page) == PAGE_FIELDS, "Unexpected catalogue pagination fields.")
    count, rows = page["count"], page["results"]
    require(type(count) is int and count >= 0, "The catalogue count is invalid.")
    require(isinstance(rows, list), "Catalogue results are not a list.")
    require(
        len(rows) <= 50 and len(rows) <= count, "Catalogue pagination is unbounded."
    )
    require(
        len(rows) == max(0, min(50, count - (number - 1) * 50)),
        "The page does not match the fixed page size/count.",
    )
    require(
        (page["previous"] is not None) == (number > 1),
        "The previous-page link does not match the page number.",
    )
    seen = set()
    for row in rows:
        require(isinstance(row, dict), "A catalogue item is not a JSON object.")
        require(set(row) == ITEM_FIELDS, "A catalogue item exposes unexpected fields.")
        require(isinstance(row["id"], str), "A catalogue identifier is invalid.")
        require(
            isinstance(row["organization_id"], str),
            "A catalogue organization identifier is invalid.",
        )
        try:
            identity = UUID(row["id"])
            organization_id = UUID(row["organization_id"])
        except ValueError as error:
            raise RuntimeError("A catalogue identifier is invalid.") from error
        require(
            organization_id == workspace_id,
            "A catalogue item belongs to another workspace.",
        )
        require(identity not in seen, "A catalogue page repeats an item.")
        seen.add(identity)
        require(
            isinstance(row["sku"], str)
            and isinstance(row["description"], str)
            and type(row["is_active"]) is bool
            and isinstance(row["created_at"], str)
            and isinstance(row["updated_at"], str),
            "A catalogue item has invalid public field types.",
        )
    for field, expected_page in (("next", number + 1), ("previous", number - 1)):
        link = page[field]
        if link is not None:
            _, linked_page = page_path(base_url, link, endpoint=endpoint)
            require(
                linked_page == expected_page, "A pagination link has the wrong page."
            )
    require(
        (page["next"] is not None) == (count > number * 50),
        "The next-page link does not match the catalogue count.",
    )
    return page


def choose_workspace(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    wanted: UUID | None,
) -> str:
    path = WORKSPACES
    seen = set()
    for _ in range(MAX_DISCOVERY_PAGES):
        result = request(opener, base_url, path, expected=200).body
        require(
            isinstance(result, dict)
            and set(result) == PAGE_FIELDS
            and isinstance(result["results"], list),
            "Workspace discovery returned an unexpected response.",
        )
        for row in result["results"]:
            require(
                isinstance(row, dict)
                and set(row) == {"id", "name"}
                and isinstance(row["id"], str),
                "Workspace discovery returned unexpected fields.",
            )
            try:
                workspace = UUID(row["id"])
            except ValueError as error:
                raise RuntimeError(
                    "Workspace discovery returned an invalid UUID."
                ) from error
            if wanted is None or workspace == wanted:
                return str(workspace)
        link = result["next"]
        if link is None:
            break
        full_url, _ = page_path(base_url, link, endpoint=WORKSPACES)
        require(full_url not in seen, "Workspace discovery repeated a page.")
        seen.add(full_url)
        path = full_url.removeprefix(base_url)
    raise RuntimeError(
        "No matching accessible workspace was found. Use an existing local "
        "account with workspace access and an accessible --workspace-id."
    )


def verify_catalogue(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    workspace_id: str,
    csrf: str,
) -> None:
    endpoint = f"/api/v1/workspaces/{workspace_id}/catalog/items/"
    first = validate_catalogue_page(
        request(opener, base_url, endpoint, expected=200),
        base_url=base_url,
        endpoint=endpoint,
        number=1,
    )
    validate_catalogue_page(
        request(opener, base_url, endpoint + "?page=1", expected=200),
        base_url=base_url,
        endpoint=endpoint,
        number=1,
    )
    if first["next"] is not None:
        full_url, number = page_path(base_url, first["next"], endpoint=endpoint)
        validate_catalogue_page(
            request(opener, base_url, full_url.removeprefix(base_url), expected=200),
            base_url=base_url,
            endpoint=endpoint,
            number=number,
        )
    # HEAD and every safe GET deliberately omit X-CSRFToken.
    require_private(request(opener, base_url, endpoint, method="HEAD", expected=200))
    for query, status in (("page_size=5000", 400), ("page=0", 404)):
        require_private(
            request(
                opener,
                base_url,
                endpoint + "?" + query,
                method="HEAD",
                expected=status,
            )
        )
    for query in (
        "page_size=5000",
        "ordering=-sku",
        "is_active=true",
        "organization_id=" + str(uuid4()),
        "user_id=" + str(uuid4()),
        "page=1&page=2",
    ):
        require_private(request(opener, base_url, endpoint + "?" + query, expected=400))
    for page in ("", "0", "-1", "invalid", "last", "1.5", str(first["count"] + 2)):
        require_private(
            request(opener, base_url, endpoint + "?page=" + page, expected=404)
        )
    missing = f"/api/v1/workspaces/{uuid4()}/catalog/items/"
    denied = request(opener, base_url, missing, expected=403)
    require(
        denied.body == DENIAL,
        "An unavailable workspace did not receive generic denial.",
    )
    require_private(denied)
    request(opener, base_url, missing, method="HEAD", expected=403)
    request(
        opener,
        base_url,
        "/api/v1/workspaces/not-a-uuid/catalog/items/",
        expected=404,
    )
    # POST creates items from Step 4C.5 onward; live verification never submits it.
    for method in ("PUT", "PATCH", "DELETE"):
        require_private(
            request(
                opener,
                base_url,
                endpoint,
                method=method,
                payload={},
                csrf=csrf,
                expected=405,
            )
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--workspace-id", type=UUID)
    args = parser.parse_args(argv)
    base_url = validate_base_url(args.base_url)
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPCookieProcessor(cookies),
    )
    anonymous_endpoint = f"/api/v1/workspaces/{uuid4()}/catalog/items/"
    require_private(request(opener, base_url, anonymous_endpoint, expected=403))
    request(opener, base_url, anonymous_endpoint, method="HEAD", expected=403)
    bootstrap = request(opener, base_url, "/api/v1/auth/csrf/", expected=200).body
    require(
        isinstance(bootstrap, dict) and isinstance(bootstrap.get("csrf_token"), str),
        "CSRF bootstrap did not return a token.",
    )
    email = input("Existing local account email: ").strip()
    password = getpass.getpass("Password (hidden): ")
    login_attempted = False
    failed = False
    try:
        login_attempted = True
        logged_in = request(
            opener,
            base_url,
            "/api/v1/auth/login/",
            method="POST",
            payload={"email": email, "password": password},
            csrf=bootstrap["csrf_token"],
            expected=200,
        ).body
        require(
            isinstance(logged_in, dict)
            and isinstance(logged_in.get("csrf_token"), str),
            "Login did not return the rotated CSRF token.",
        )
        workspace_id = choose_workspace(opener, base_url, args.workspace_id)
        verify_catalogue(opener, base_url, workspace_id, logged_in["csrf_token"])
    except BaseException:
        failed = True
        raise
    finally:
        del password
        if login_attempted:
            try:
                # Refresh even if login returned malformed JSON after setting a
                # session cookie; cleanup must use the rotated CSRF secret.
                cleanup = request(
                    opener, base_url, "/api/v1/auth/csrf/", expected=200
                ).body
                require(
                    isinstance(cleanup, dict)
                    and isinstance(cleanup.get("csrf_token"), str),
                    "Cleanup could not retrieve the current CSRF token.",
                )
                request(
                    opener,
                    base_url,
                    "/api/v1/auth/logout/",
                    method="POST",
                    csrf=cleanup["csrf_token"],
                    expected=204,
                )
            except RuntimeError, urllib.error.URLError, ValueError, TypeError:
                if not failed:
                    raise RuntimeError(
                        "The verifier session could not be logged out."
                    ) from None
                print(
                    "Session cleanup failed; the local verifier session "
                    "may remain active.",
                    file=sys.stderr,
                )
    request(opener, base_url, anonymous_endpoint, expected=403)
    print("Read-only catalogue HTTP verification passed.")


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError,
        urllib.error.URLError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        sys.exit(1)
    except EOFError, KeyboardInterrupt:
        print("Verification cancelled.", file=sys.stderr)
        sys.exit(1)
