"""Check workspace selection against the running local API, using real cookies.

Run from the project root: python scripts/verify_workspace_selection.py
The existing local account must have at least two accessible workspaces.
No credentials or tokens are accepted as arguments, printed, or saved.
"""

import getpass
import http.cookiejar
import sys
import urllib.error
import urllib.request
import uuid

import verify_session_auth as session_auth

CURRENT = "/api/v1/workspaces/current/"
ROLES = {"admin", "reviewer", "viewer"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def check_workspace(response: dict, workspace_id: str) -> dict:
    workspace = response.get("workspace")
    require(isinstance(workspace, dict), "A workspace context was not returned.")
    require(set(workspace) == {"id", "name", "role"}, "Unexpected context fields.")
    require(
        workspace["id"] == workspace_id, "The workspace scope changed unexpectedly."
    )
    require(workspace["role"] in ROLES, "The membership role is invalid.")
    return workspace


def main() -> None:
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        session_auth.NoRedirect(),
        urllib.request.HTTPCookieProcessor(cookies),
    )
    session_auth.request(opener, CURRENT, expected=403)
    csrf = session_auth.request(opener, "/api/v1/auth/csrf/", expected=200)[
        "csrf_token"
    ]
    email = input("Existing local account email: ").strip()
    password = getpass.getpass("Password (hidden): ")
    try:
        logged_in = session_auth.request(
            opener,
            "/api/v1/auth/login/",
            method="POST",
            payload={"email": email, "password": password},
            csrf=csrf,
            origin=session_auth.BASE_URL,
            expected=200,
        )
    finally:
        del password
    csrf = logged_in["csrf_token"]
    current = session_auth.request(opener, CURRENT, expected=200)
    require(current == {"workspace": None}, "Fresh login retained a workspace choice.")
    available = session_auth.request(opener, "/api/v1/workspaces/", expected=200)
    require(
        len(available["results"]) >= 2,
        "Create two local workspaces for this account first.",
    )
    first, second = [row["id"] for row in available["results"][:2]]

    def select(workspace_id: str) -> dict:
        return session_auth.request(
            opener,
            CURRENT,
            method="PUT",
            payload={"workspace_id": workspace_id},
            csrf=csrf,
            origin=session_auth.BASE_URL,
            expected=200,
        )

    first_context = check_workspace(select(first), first)
    check_workspace(session_auth.request(opener, CURRENT, expected=200), first)
    # An unsafe request without a CSRF header must leave the previous choice intact.
    session_auth.request(
        opener,
        CURRENT,
        method="PUT",
        payload={"workspace_id": second},
        expected=403,
    )
    check_workspace(session_auth.request(opener, CURRENT, expected=200), first)
    missing = str(uuid.uuid4())
    for path, method, payload in (
        (CURRENT, "PUT", {"workspace_id": missing}),
        (f"/api/v1/workspaces/{missing}/context/", "GET", None),
    ):
        denied = session_auth.request(
            opener, path, method=method, payload=payload, csrf=csrf, expected=403
        )
        require(
            denied == {"detail": "You do not have access to this workspace."},
            "Unavailable workspaces did not receive the generic denial.",
        )
    check_workspace(session_auth.request(opener, CURRENT, expected=200), first)

    # Two browser tabs share cookies. A selection change is a UI preference;
    # an explicit URL still resolves its own authorized workspace.
    check_workspace(select(second), second)
    check_workspace(session_auth.request(opener, CURRENT, expected=200), second)
    explicit_first = session_auth.request(
        opener, f"/api/v1/workspaces/{first}/context/", expected=200
    )
    require(
        check_workspace(explicit_first, first) == first_context,
        "Selecting another workspace changed the explicit context.",
    )
    check_workspace(
        session_auth.request(
            opener, f"/api/v1/workspaces/{second}/context/", expected=200
        ),
        second,
    )

    session_auth.request(opener, CURRENT, method="DELETE", expected=403)
    check_workspace(session_auth.request(opener, CURRENT, expected=200), second)
    for _ in range(2):
        session_auth.request(
            opener,
            CURRENT,
            method="DELETE",
            csrf=csrf,
            origin=session_auth.BASE_URL,
            expected=204,
        )
    require(
        session_auth.request(opener, CURRENT, expected=200) == {"workspace": None},
        "Clearing did not remove the preference.",
    )
    check_workspace(
        session_auth.request(
            opener, f"/api/v1/workspaces/{first}/context/", expected=200
        ),
        first,
    )
    session_auth.request(
        opener,
        "/api/v1/auth/logout/",
        method="POST",
        csrf=csrf,
        origin=session_auth.BASE_URL,
        expected=204,
    )
    session_auth.request(opener, CURRENT, expected=403)
    session_auth.request(opener, f"/api/v1/workspaces/{first}/context/", expected=403)
    print("Workspace selection/context verification passed.")


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
