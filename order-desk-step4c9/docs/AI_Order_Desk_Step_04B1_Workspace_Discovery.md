# Step 4B.1 — authenticated workspace discovery

## Goal

Expose one read-only endpoint, `GET /api/v1/workspaces/`. It returns the
authenticated user's active distributor workspaces, with a bounded page size
and an explicit public field list. Allow about 15–25 minutes to review, apply,
and verify this increment.

Your Step 4A log confirms 63 tests passed on PostgreSQL, including the genuine
concurrency test. We now connect that access foundation to HTTP in small pieces:

| Increment | Result |
| --- | --- |
| **4B.1 — this patch** | Authenticated, read-only workspace discovery. |
| 4B.2 — after verification | Customer session login/logout, anonymous-login CSRF protection, and login attempt controls. |
| 4B.3 — after verification | Workspace selection and a request context that revalidates the current membership. |
| 4C — after Step 4B | PostgreSQL transaction context and row policies for tenant business data, verified as the restricted runtime role. |

This endpoint uses the existing Django database sessions and the Step 4A scoped
selector. Login, selection, order APIs, and database row policies belong to the
following increments. The automated tests exercise ordinary user sessions;
there is no temporary password-based authentication shortcut in this patch.

## 1. Apply the additive patch

Download `AI_Order_Desk_Step_04B1_Workspace_Discovery.zip`. Its paths begin at
your existing project root. It contains four new Python files and this guide.
The existing root URL configuration is edited manually below so your other
routes remain intact.

Run from PowerShell:

```powershell
Set-Location -LiteralPath "C:\Users\HomePC\Desktop\billion1\order-desk" -ErrorAction Stop
docker compose stop api
if ($LASTEXITCODE -ne 0) { throw "Could not stop the local API." }
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\AI_Order_Desk_Step_04B1_Workspace_Discovery.zip" -DestinationPath . -Force -ErrorAction Stop
```

`Set-Location` selects the project you already verified. `stop api` stops the
local server while the files and route are added; the database stays running.
`Expand-Archive` writes the new files to their final locations. Adjust only the
download location if needed. Extract into the existing `order-desk` directory.

### Register one route

Open `backend/config/urls.py`. Inside `urlpatterns`, add this line exactly once:

```python
    path("api/v1/workspaces/", include("apps.organizations.urls")),
```

For the unmodified Step 4A starter, the complete file becomes:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", include("apps.health.urls")),
    path("api/v1/workspaces/", include("apps.organizations.urls")),
]
```

`include` sends matching requests into the organizations module's URL file.
The trailing slash is part of the API contract. Existing shared settings
already register the organizations app and configure JSON and pagination.

## 2. Understand every file

The following source paths all begin with `backend/apps/organizations/`.

| File | Responsibility |
| --- | --- |
| `serializers.py` | Defines the exact public workspace representation: UUID `id` and display `name`, both read-only. |
| `views.py` | Requires a Django session, calls the authorized Step 4A selector with the server-side user, and returns a paginated list. Disables caching and supports only GET, HEAD, and OPTIONS. |
| `urls.py` | Maps this module's empty path to the list view. Its `workspaces:list` name gives tests and future code a stable URL reference. |
| `tests/test_api.py` | Adds 18 HTTP behavior tests using real Django session cookies and ordinary users, with CSRF enforcement enabled for the read requests. |

`backend/config/urls.py` is the one existing source file you edit manually.
`docs/AI_Order_Desk_Step_04B1_Workspace_Discovery.md` is this walkthrough.

### `serializers.py`: the output contract

```python
"""Public workspace fields. Memberships and account details stay internal."""

from rest_framework import serializers

from apps.organizations.models import Organization


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name")
        read_only_fields = fields
```

An explicit field list prevents a later model field from appearing in API
responses automatically. UUIDs become JSON strings. Membership records, user
emails, activity flags, and timestamps are not returned. This response is for
workspace discovery; the current membership role will be resolved with workspace
selection.

### `views.py`: HTTP authentication plus tenant authorization

```python
"""Read-only workspace discovery through the existing access boundary."""

from django.db.models import QuerySet
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.organizations.models import Organization
from apps.organizations.selectors import organizations_for_user
from apps.organizations.serializers import WorkspaceSerializer


@method_decorator(never_cache, name="dispatch")
class WorkspaceListView(ListAPIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    serializer_class = WorkspaceSerializer
    http_method_names = ["get", "head", "options"]

    def get_queryset(self) -> QuerySet[Organization]:
        # Use the server-authenticated user; request parameters cannot choose it.
        return organizations_for_user(user=self.request.user)
```

The request proceeds through these boundaries:

1. Django loads the session and its current account using the configured
   authentication backend.
2. DRF's session authenticator and permission check require a signed-in user.
3. The Step 4A selector checks that the account is still active and filters by
   that user's active membership in each active workspace.
4. DRF orders/paginates that scoped query and serializes only `id` and `name`.

`IsAuthenticated` establishes the caller's identity. The scoped selector
enforces which organizations that identity can see. A generic authenticated
view returning `Organization.objects.all()` would expose other distributors.

The selector is called on every request. Membership or organization deactivation
takes effect on the next request. It orders by name and then UUID, so repeated
names have a stable tie-breaker. This is ordinary offset pagination, suitable
for a user's small workspace list; concurrent changes may still alter pages.

`never_cache` marks both successful responses and handled API errors as
`private, no-store`. Workspace discovery is personal account data, so it must
not be stored in a shared response cache. The serializer reads only organization
fields; there is no per-item related lookup and no N+1 query pattern.

### `urls.py`: module routing

```python
from django.urls import path

from apps.organizations.views import WorkspaceListView

app_name = "workspaces"

urlpatterns = [
    path("", WorkspaceListView.as_view(), name="list"),
]
```

The module is called `organizations` because that is the data/domain term.
The public resource is called `workspaces` because that is the UI term. Both
identify the same distributor organization; there is no additional model.

### `tests/test_api.py`: the security and response checks

The ZIP contains the complete runnable tests. They cover:

- Anonymous and fabricated-identity requests, ordinary user sessions, logged-out
  sessions, and account deactivation.
- Active memberships/workspaces only, next-request revocation, role differences,
  empty membership lists, and no operator-flag bypass.
- An exact public response shape, ignored identity-selection query parameters,
  bounded pagination, duplicate-name ordering, and invalid pages.
- Noncacheable responses and method restrictions that prevent writes.

`APIClient.force_login` creates a real Django test session and cookie without
testing password entry. The request still runs session authentication and the
database access checks. We do not use `force_authenticate`, which would skip
the authenticator. Password entry, login CSRF, and session rotation will get
their own HTTP tests with the login feature in 4B.2.

## 3. API contract

### Request

```http
GET /api/v1/workspaces/?page=1
Cookie: sessionid=<browser-managed-session-cookie>
```

Only `page` is a supported query parameter. Do not construct or copy session
cookie values manually. Pagination uses the Step 3 default of 50 items per page;
clients cannot increase it with a `page_size` query parameter. Unknown query
parameters cannot change the authenticated identity or widen workspace access.

### Successful response

HTTP 200, JSON. The values below are illustrative:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "5cc2fe0d-aa6b-42de-b971-afaa99ce7418",
      "name": "Example Electrical Distributor"
    }
  ]
}
```

`count` counts only accessible workspaces. An authenticated account without
memberships receives HTTP 200 with `count: 0` and `results: []`. Even an
operator/superuser needs an active membership to see a workspace here.

| Situation | Response |
| --- | --- |
| Missing, logged-out, or inactive-user session | HTTP 403, `{"detail":"Authentication credentials were not provided."}` |
| Active session with accessible workspaces | HTTP 200, paginated workspace list. |
| Active session with no accessible workspaces | HTTP 200, empty paginated list. |
| Invalid or out-of-range page | HTTP 404, `{"detail":"Invalid page."}` |
| Authenticated write attempt | No write occurs; HTTP 405 after authentication/CSRF checks, or HTTP 403 if CSRF fails first. |

The 403 for an anonymous session-authenticated API is DRF's standard behavior.
There is no Basic, bearer-token, or user-ID-header authenticator on this view.
GET is a safe method and requires no CSRF token. Future mutations and login
will require CSRF protection; DRF's anonymous CSRF behavior alone is insufficient
for a login endpoint.

## 4. Verify on your PostgreSQL database

From the existing project root:

```powershell
docker compose run --rm manage python manage.py check
if ($LASTEXITCODE -ne 0) { throw "Django configuration checks failed." }
docker compose run --rm manage python manage.py makemigrations --check --dry-run
if ($LASTEXITCODE -ne 0) { throw "Models and committed migrations differ." }
docker compose run --rm manage python manage.py test apps.organizations.tests.test_api --settings=config.settings.test --keepdb --noinput -v 2
if ($LASTEXITCODE -ne 0) { throw "Workspace API tests failed." }
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 2
if ($LASTEXITCODE -ne 0) { throw "Full backend suite failed." }
docker compose run --rm manage ruff check .
if ($LASTEXITCODE -ne 0) { throw "Lint checks failed." }
docker compose run --rm manage ruff format --check .
if ($LASTEXITCODE -ne 0) { throw "Formatting checks failed." }
docker compose up -d --wait --wait-timeout 120 api
if ($LASTEXITCODE -ne 0) { throw "API startup or readiness failed." }
docker compose exec api python manage.py check_runtime_role
if ($LASTEXITCODE -ne 0) { throw "Runtime database privileges are unsafe." }
```

| Command | What it proves |
| --- | --- |
| `check` | Django can import the new serializer, view, and URL configuration. |
| `makemigrations --check --dry-run` | Source matches the committed schema; expect `No changes detected`. |
| Targeted `test ...test_api` | All 18 new HTTP tests pass against PostgreSQL, including ordinary-user session checks. |
| Full `test` | The 63 previous tests plus the 18 new tests pass together: 81 total for the unchanged starter. The existing concurrency test must still run successfully. |
| `ruff check .` | Existing lint and security-oriented rules pass. |
| `ruff format --check .` | The new and existing source follows the project's pinned formatter. |
| `up ... api` | The bind-mounted source starts and passes readiness. |
| `check_runtime_role` | The API still uses the restricted database role. |

Tests use the provisioned `test_orderdesk` database and the existing migration
role. Retain `--keepdb`; no CREATEDB permission is needed. Their users and
workspaces are fixtures in that test database, not your main `orderdesk` DB.

There is no migration to apply and no image rebuild for this source-only patch.
The dependency lock, settings, database roles, and volumes remain as configured.

### Check the running anonymous endpoint

```powershell
$anonymousStatus = $null
try {
    $response = Invoke-WebRequest -UseBasicParsing `
        -Uri "http://127.0.0.1:8000/api/v1/workspaces/" -ErrorAction Stop
    $anonymousStatus = [int]$response.StatusCode
}
catch {
    if ($null -eq $_.Exception.Response) { throw }
    $anonymousStatus = [int]$_.Exception.Response.StatusCode
}
if ($anonymousStatus -ne 403) {
    throw "Expected anonymous workspace access to return 403; got $anonymousStatus."
}
"Anonymous workspace access: HTTP $anonymousStatus (expected)"

docker compose ps
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health/live/"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health/ready/"
```

The workspace probe must print HTTP 403. Both services should remain healthy,
and both health responses should contain `status: ok`. The try/catch is needed
because PowerShell raises an exception for the deliberately forbidden request.
Connection failures and an unexpected status still fail the verification.

If you already have an operator account and are signed into Django's existing
admin at `http://127.0.0.1:8000/admin/`, open
`http://127.0.0.1:8000/api/v1/workspaces/` in that same browser. You should see
JSON with HTTP 200, commonly an empty list because the operator has no workspace
membership. This is an optional check using the existing operator tooling.
The automated tests verify non-operator sessions with positive membership data.
The customer login flow is the next increment.

### Verification completed while preparing this patch

With Python 3.14.8 and the existing locked dependencies:

- Django system and migration-consistency checks pass.
- All 18 new HTTP tests pass; the full temporary SQLite harness reports
  **80 passed, one PostgreSQL-only concurrency test skipped**.
- Ruff lint and formatting checks pass, and `uv lock --check --offline` passes.

Docker and PostgreSQL execution are unavailable in the preparation environment.
The scratch SQLite harness is excluded from the deliverable. Your PostgreSQL
commands above are the required acceptance check; all 81 tests should pass
with the concurrency test reporting `ok`.

## 5. Review and commit

After verification succeeds:

```powershell
git status --short
git add backend/apps/organizations/serializers.py backend/apps/organizations/views.py backend/apps/organizations/urls.py backend/apps/organizations/tests/test_api.py backend/config/urls.py docs/AI_Order_Desk_Step_04B1_Workspace_Discovery.md
git diff --cached --stat
git commit -m "feat: add authenticated workspace discovery"
if ($LASTEXITCODE -ne 0) { throw "Commit failed." }
```

`status` shows the changed paths. `add` stages this increment's exact source and
guide files. `diff --cached --stat` lets you check those paths before `commit`
records the verified increment. Keep secrets and generated caches out of Git.

## Recommended tools

No new library, paid service, or dependency upgrade is needed. Versions below
are the existing project pins. License types were checked in the installed
package metadata.

| Tool | Why it fits / maturity | License | Hosting | Viable alternative |
| --- | --- | --- | --- | --- |
| Django 5.2.17 sessions and ORM | Established framework; reuses database-backed sessions and the reviewed membership selector. | BSD-3-Clause | Existing self-hosted backend; managed application hosting optional later. | Flask with its session/auth and ORM integrations, a larger stack change. |
| DRF 3.18.1 generic views and serializers | Established Django API library; supplies JSON contracts and bounded pagination without custom list plumbing. | BSD-3-Clause | Runs inside the existing backend. | Django `JsonResponse` with manual parsing, pagination, and permission handling. |
| Django test runner plus DRF APIClient | Existing framework tools; exercises session cookies, permissions, and responses together. | BSD-3-Clause | Local PostgreSQL test DB; CI later. | pytest with pytest-django. |
| Ruff 0.16.10 | Maintained linter/formatter; keeps the existing source rules consistent. | MIT | Existing local CLI; no account required. | Black plus Flake8/isort. |

There is no restrictive license introduced by this patch. Installing another
auth framework or a cache/queue service for this one GET endpoint would add
integration work without improving this increment.

## Common pitfalls

- **Authentication without tenant filtering:** every list query must carry the
  user's membership predicates; an authenticated caller is not entitled to all
  organizations.
- **Using client-supplied user IDs as the actor:** use `request.user` from the
  server-side session, as this view does.
- **Exposing every model field:** an explicit serializer field list survives
  later internal model changes safely.
- **Keeping workspace lists in shared caches:** membership revocation must be
  reflected by fresh requests, and one account's list must not be reused for
  another account.
- **Giving operators tenant access automatically:** only active memberships
  supply access, including for a superuser.
- **Unbounded lists:** retain pagination before adding more API resources.
- **Treating a GET test as login verification:** login CSRF, failed attempts,
  and session rotation require their own implementation and tests in 4B.2.
- **Confusing test fixtures with application data:** a live empty list is
  expected when the main database has no memberships for that account.

## Definition of Done — stop after 4B.1

- [ ] The four new Python files are in the existing organizations module.
- [ ] `config/urls.py` registers `/api/v1/workspaces/` exactly once.
- [ ] The 18 workspace API tests pass on PostgreSQL.
- [ ] All 81 backend tests pass on PostgreSQL, including the concurrency test.
- [ ] Django, migration-drift, lint, and formatting checks pass.
- [ ] The running anonymous endpoint returns HTTP 403.
- [ ] The runtime role guard passes and both health checks return `ok`.
- [ ] This increment is reviewed and committed locally.

Send this exact next prompt, followed by your verification output:

> Step 4B.1 verified. Here are my test summaries, anonymous workspace response,
> runtime-role check, and health responses: [paste output]. Start Step 4B.2:
> CSRF-protected session login and logout, one small step at a time.

## Official references

- [DRF session authentication and its CSRF behavior](https://www.django-rest-framework.org/api-guide/authentication/#sessionauthentication)
- [DRF generic views and per-request querysets](https://www.django-rest-framework.org/api-guide/generic-views/#get_querysetself)
- [DRF object permissions and list-query restrictions](https://www.django-rest-framework.org/api-guide/permissions/#limitations-of-object-level-permissions)
- [DRF page-number pagination](https://www.django-rest-framework.org/api-guide/pagination/#pagenumberpagination)
- [Django 5.2 authentication and session behavior](https://docs.djangoproject.com/en/5.2/topics/auth/default/)
- [Django 5.2 CSRF protection](https://docs.djangoproject.com/en/5.2/ref/csrf/)

These references were checked for this increment. Keep the dependency pins;
consult the official docs when changing authentication, pagination, or versions.
