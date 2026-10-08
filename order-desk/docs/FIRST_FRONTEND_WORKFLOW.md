# First frontend: session, workspace and catalogue

## Scope and implementation

The explicit request authorizes login, workspace selection and read-only
catalogue browsing. The referenced `AI_Order_Desk_First_Frontend_Prompt.md` was
not present at its supplied Downloads path or under that name in the workspace.
It was not treated as an additional source of requirements. ADR-001 specifies
same-origin Django sessions and a product UI, without selecting a JavaScript
framework. This increment uses dependency-free browser ES modules and a Django
template shell, preserving the locked backend and $0 local budget.

Open `http://127.0.0.1:8000/` with the existing local Compose API running. The
root shell contains no customer or account data. JavaScript discovers the current
session through protected APIs. Anonymous callers see sign-in; successful login
opens workspace discovery. A fresh server-validated current selection is restored
on reload. Accounts with no active workspaces get an explicit message.

Catalogue browsing supports literal SKU/description search (200-character API
limit), active/inactive/all filters, 50-row pages and empty/loading/error states.
Workspace discovery has its own load-more control. SKU, description, workspace
name and errors are rendered as text; catalogue active state is not inventory
availability. No catalogue writes, imports, draft controls or account provisioning
UI are introduced.

| Action | Existing API and boundary |
| --- | --- |
| Sign in/out | GET `/api/v1/auth/csrf/`, POST `login/` and `logout/`; fresh CSRF even before login, rotated login token, HttpOnly session cookie, active account and existing login budgets. |
| Discover workspaces | GET `/api/v1/workspaces/`; server-authenticated active memberships/organizations, paginated. |
| Restore/select/clear | GET/PUT/DELETE `/api/v1/workspaces/current/`; server preference revalidated, CSRF on mutations; selection conveys no additional authority. |
| Browse | GET `/api/v1/workspaces/<id>/catalog/items/` with allowlisted page/q/is_active; all active member roles, URL-selected tenant, fresh transaction scope and forced PostgreSQL RLS. |

Requests use relative API paths, same-origin cookies, no-store and rejected
redirects. Credentials and tokens are never put in local/session storage or URLs.
CSRF is fetched for each login, selection and logout. The browser cannot bypass
backend role or tenant checks. Workspace changes clear rows and filters before
loading; aborted/late requests cannot repopulate a previous workspace. Catalogue
403 clears data before refreshing discovery, without reopening a stale selection.
Expired sessions return to sign-in; offline failures offer retry. Unconfirmed
logout is displayed as a failure. Returning to a visible tab or a restored browser
history page revalidates session/context.

Source: `frontend/templates/workspace.html`, `frontend/assets/desk/` (API client,
controller, DOM renderer and responsive stylesheet), `backend/apps/web/` public
GET/HEAD shell, shared template/static settings and the read-only Compose frontend
mount. No Python, database or JavaScript dependencies/migrations were added.

## Local verification

From the application directory:

```powershell
node --test frontend/tests/*.test.js
docker compose run --rm manage python manage.py test apps.web.tests apps.accounts.tests apps.organizations.tests --settings=config.settings.test --keepdb --noinput -v 0
node frontend/tests/browser-smoke.mjs
docker compose run --rm rlscheck python manage.py verify_catalog_rls
```

The Node tests check client state and request construction with fake transports;
they establish no database isolation. The browser harness uses real Chromium,
cookies and CSRF against a short-lived server directly authenticated as
`orderdesk_app` in `test_orderdesk`. Maintenance-role synthetic fixtures are
created separately and cleaned in `finally`; the application database receives
no fixture writes. Preflight refuses an earlier fixture file or occupied ports
8001/9223. Only the harness's named container/browser is stopped. A preexisting
peer login-budget row is retained rather than deleted by cleanup. A test-only
WSGI observer (`frontend/tests/browser_server.py`) records the actual peer's digest
before login, without changing
the peer, HTTP request, authentication or API behavior; newly created peer
counters are removed with the email/session fixtures.

The browser harness requires Docker and Node with built-in WebSocket support
(verified here with Node 24.15.0), plus installed Chromium. Its Windows default is
`C:/Program Files/Google/Chrome/Application/chrome.exe`; set `CHROME_PATH` to an
installed Chromium executable elsewhere. It checks invalid/valid credentials,
selection, viewer reads, search, status, pagination, workspace switch, refresh,
HTML rendered safely as text, mobile width, live membership revocation and logout.
Screenshots/profiles remain ignored under `backend/var/frontend-browser/`; the
temporary credential fixture is deleted. Interrupted runs require reviewing and
cleaning that guarded fixture before rerunning, not blindly overwriting it.

Restricted-role catalogue verification is separate evidence for tenant isolation.
Actual command results are recorded in [project state](PROJECT_STATE.md).

## Remaining work

Production static packaging/collection, HTTPS/proxy serving, deployment, browser
matrix and formal assistive-technology testing remain unverified. Compose still
uses Django's local development server. Source assets are mounted read-only;
the backend-only development image does not package them for a deployment.
Workspace/user provisioning remains an existing operator workflow. Draft review,
readiness and conversion UI are the next separate product increment. Private
storage/content safety, extraction and ERP export retain their prior boundaries.
