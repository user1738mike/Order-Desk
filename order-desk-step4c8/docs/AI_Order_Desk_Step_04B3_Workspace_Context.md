# Step 4B.3 — Workspace selection and request tenant context

## Goal

Let a signed-in user select a distributor workspace, and resolve a fresh,
authorized workspace context for each explicitly scoped request. Allow about
20–30 minutes to review, apply, and verify this increment.

Your Step 4B.2 log confirms 136 passing tests, both PostgreSQL concurrency
tests, lint/format checks, and a restricted runtime database role. This patch
adds 34 tests. It costs $0, uses the locked dependencies, and needs no schema
migration, settings change, new service, or image rebuild.

The application authorization boundary is implemented here. PostgreSQL
transaction context and row policies are Step 4C; tenant business APIs must
wait for that verification. The local server remains a development server.

## 1. The contract and design decision

All endpoints below require the existing Django session cookie. The existing
discovery endpoint, `GET /api/v1/workspaces/`, keeps its paginated response.

| Method and path | Behavior |
| --- | --- |
| `GET /api/v1/workspaces/current/` | Returns the selected workspace's current name and membership role. Returns `{"workspace":null}` when no accessible selection exists. |
| `PUT /api/v1/workspaces/current/` | Accepts a JSON UUID string, verifies current membership, and remembers the workspace ID. Requires the current CSRF cookie/token. |
| `DELETE /api/v1/workspaces/current/` | Clears the preference and returns 204 with no body. Repeating it returns 204. Login remains active. Requires CSRF. |
| `GET /api/v1/workspaces/<workspace_id>/context/` | Authorizes the workspace named in the URL and returns its context. Works even without a selection. |

Example selection body; replace the example UUID with one from discovery:

```json
{"workspace_id":"a4366380-e8b7-4760-9f95-b4522a6c9615"}
```

Successful selection, current-workspace, and explicit-context responses share
this shape:

```json
{
  "workspace": {
    "id": "a4366380-e8b7-4760-9f95-b4522a6c9615",
    "name": "Local Alpha Distributor",
    "role": "admin"
  }
}
```

The role comes from the membership row. Viewer, reviewer, and administrator
members can select a workspace; choosing one grants no additional permissions.
Account, membership, and organization activity are checked against current
database state. Operator flags grant no workspace access.

| Condition | Response |
| --- | --- |
| Anonymous request | 403 JSON authentication error. |
| Invalid/missing UUID string, malformed JSON, or extra selection fields | 400 JSON validation error; previous selection preserved. |
| Selection with a non-JSON content type | 415; previous selection preserved. |
| Missing/invalid CSRF or an untrusted Origin on an authenticated mutation | 403; previous selection preserved. |
| Selecting or explicitly addressing an unknown, inactive, revoked, or foreign workspace | The same 403 body: `{"detail":"You do not have access to this workspace."}`. |
| A saved selection becomes unavailable | Current-workspace GET returns `{"workspace":null}`; explicit access remains denied. |

GET does not repair or clear stale session data. This keeps reads side-effect
free. The frontend can display the picker and use PUT or DELETE to change the
preference. No workspace names are disclosed in permission errors.

### ADR-004: a preference in the session, explicit scope in the URL

**Decision:** store only `selected_workspace_id` in the server-side session.
Resolve an immutable `WorkspaceContext` from current membership data after
authentication. Workspace-scoped views get their ID from a UUID URL parameter.

**Why:** two browser tabs share the same session cookie. If Tab A is reviewing
an order in workspace A and Tab B selects B, Tab A's future order request must
still name A in its URL. Implicitly routing writes through the current session
preference could send a valid action to the wrong distributor.

**Consequences:** future business endpoints will use paths such as
`/api/v1/workspaces/<workspace_id>/orders/`. Their permission checks, query
filters, services, and Step 4C database context must use the same authorized
organization ID. Headers and query parameters cannot override the URL scope.
Context stays on the request; there is no process-wide or thread-local state.

The context is a snapshot for one request. Revocation and role changes affect
the next request. A sensitive write must recheck authorization within its
transaction; a background job must reauthorize at execution time. Queue IDs
and actor identity, rather than a context carrying cached permissions.

## 2. Apply this patch

Download `AI_Order_Desk_Step_04B3_Workspace_Context.zip`.

The ZIP contains **14 files**: nine new backend files, three replacements of
existing workspace API files, the host verifier, and this guide. The replaced
files are exactly:

- `backend/apps/organizations/serializers.py`
- `backend/apps/organizations/views.py`
- `backend/apps/organizations/urls.py`

They retain discovery's existing behavior. Review or merge any personal changes
to those three files before extracting over them. This guide uses your existing
project root, not a new project directory.

Run in PowerShell:

```powershell
Set-Location -LiteralPath "C:\Users\HomePC\Desktop\billion1\order-desk" -ErrorAction Stop
$pendingChanges = git status --porcelain
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the working tree." }
if ($pendingChanges) { throw "Commit or stash current work before applying the patch." }

docker compose stop api
if ($LASTEXITCODE -ne 0) { throw "Could not stop the local API." }
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\AI_Order_Desk_Step_04B3_Workspace_Context.zip" -DestinationPath . -Force -ErrorAction Stop
git diff --stat
git status --short
```

`Set-Location` selects the project. The clean-tree check protects existing work
from replacement. `stop api` pauses the development server while related source
files are updated; the database keeps running. `Expand-Archive` writes the files
at their intended paths. Adjust the download path if needed. Git's diff shows
tracked replacements; its status also shows the added files.

## 3. Read the files in this order

All paths in this table are relative to
`C:\Users\HomePC\Desktop\billion1\order-desk`.

| File | What it does and why it belongs here |
| --- | --- |
| `backend/apps/organizations/context.py` — new | Defines the immutable, typed workspace context and its resolver. Calls the existing `require_membership` boundary; contains no HTTP or session storage code. |
| `backend/apps/organizations/permissions.py` — new | DRF permission runs after authentication, resolves the URL workspace, and attaches `request.workspace_context`. A helper refuses to return a missing context. Missing route scope is a server configuration error and never falls back to a session/header. |
| `backend/apps/organizations/selection.py` — new | Reads and writes the session preference. Selection writes only after authorization; reads revalidate membership and safely handle stale/malformed stored values. |
| `backend/apps/organizations/serializers.py` — replaced | Retains discovery's ID/name output. Adds strict selection input and public context output. Rejects numeric/boolean IDs and extra fields such as a supplied actor or role. |
| `backend/apps/organizations/views.py` — replaced | Retains discovery and adds the current-workspace and explicit-context handlers. Delegates authorization to the resolver/permission and sets private, no-store responses. |
| `backend/apps/organizations/urls.py` — replaced | Keeps the list route and registers `current/` and `<uuid:workspace_id>/context/` beneath the existing root include. No root URL edit is needed. |
| `backend/apps/organizations/management/__init__.py` — new | Empty package marker for the app's management utilities. |
| `backend/apps/organizations/management/commands/__init__.py` — new | Empty package marker so Django discovers commands. |
| `backend/apps/organizations/management/commands/create_local_workspace.py` — new | Interactive development fixture helper for an existing active account. Uses the existing atomic `create_organization` service; refuses `DEBUG=False`. |
| `backend/apps/organizations/tests/test_workspace_selection.py` — new | 26 API tests using real Django sessions with CSRF enforced. Tests revocation, roles, two tabs, expiry, malformed input/state, and login/logout boundaries. |
| `backend/apps/organizations/tests/test_workspace_context.py` — new | Three checks for missing context/scope and anonymous resolution. Protects against accidentally treating an unscoped request as authorized. |
| `backend/apps/organizations/tests/test_local_workspace_command.py` — new | Five tests for safe fixture creation, validation, cancellation, and refusal under non-development settings. |
| `scripts/verify_workspace_selection.py` — new | Standard-library HTTP verifier for host Python 3.13. Reuses Step 4B.2's cookie/request helper and contacts the loopback API. |
| `docs/AI_Order_Desk_Step_04B3_Workspace_Context.md` — new | This walkthrough and the decision record, committed with the change. |

The context contains UUIDs for the organization, user, and membership, plus the
organization name and membership role. It holds scalar values rather than a
lazy ORM object. The serialized response exposes only workspace ID/name/role.

For an explicit context request, the order is:

1. Django resolves the session and DRF authenticates the user.
2. `IsAuthenticated` denies anonymous access.
3. `HasWorkspaceAccess` resolves the UUID from the route, checks live membership,
   and builds the context on this DRF request.
4. The handler calls `get_workspace_context(request)` and serializes it.

These are the actual view settings in the patch:

```python
authentication_classes = (SessionAuthentication,)
permission_classes = (IsAuthenticated, HasWorkspaceAccess)
```

Future tenant views must both authorize the workspace and scope their business
queries by `context.organization_id`. A DRF permission class does not add an ORM
query filter or a PostgreSQL row policy automatically.

Selection PUT and DELETE use `SessionAuthentication`, which verifies CSRF for
authenticated unsafe methods. They also require `IsAuthenticated`. Login's
special anonymous-CSRF protection from Step 4B.2 continues to apply unchanged.
The session's absolute eight-hour expiry is preserved when selecting/clearing.
Fresh login and logout already flush the selection along with the session.

## 4. Run the backend checks against your PostgreSQL database

Run from the project root:

```powershell
docker compose run --rm manage python manage.py check
if ($LASTEXITCODE -ne 0) { throw "Django configuration checks failed." }
docker compose run --rm manage python manage.py migrate --check
if ($LASTEXITCODE -ne 0) { throw "An earlier migration is still pending." }
docker compose run --rm manage python manage.py makemigrations --check --dry-run
if ($LASTEXITCODE -ne 0) { throw "Models and committed migrations differ." }
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 2
if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }
docker compose run --rm manage ruff check .
if ($LASTEXITCODE -ne 0) { throw "Lint checks failed." }
docker compose run --rm manage ruff format --check .
if ($LASTEXITCODE -ne 0) { throw "Formatting checks failed." }
python -m py_compile scripts/verify_workspace_selection.py
if ($LASTEXITCODE -ne 0) { throw "The verifier is incompatible with the host Python." }
docker compose up -d --wait --wait-timeout 120 api
if ($LASTEXITCODE -ne 0) { throw "API startup or readiness failed." }
docker compose exec api python manage.py check_runtime_role
if ($LASTEXITCODE -ne 0) { throw "Runtime database privileges are unsafe." }
```

| Check | Expected result |
| --- | --- |
| `check` | No Django configuration issues. |
| `migrate --check` | Exit 0; verifies earlier migrations are applied without applying new ones. |
| `makemigrations --check --dry-run` | `No changes detected`. There is no new model in this patch. |
| `test` | **170 tests pass**, with no skip on PostgreSQL: 136 earlier + 34 new. Uses the provisioned `test_orderdesk` with `--keepdb`, so the role needs no `CREATEDB` grant. |
| Ruff | Lint and formatting pass across the backend. |
| `py_compile` | Host Python parses the verifier; no host package installation needed. |
| API start | API and database become healthy. Source bind mounting picks up the patch. |
| Runtime guard | `Runtime database role is restricted.` |

Both existing concurrency tests should still report `ok`, with no skip:

- `test_concurrent_first_attempts_cannot_exceed_account_budget`
- `test_simultaneous_duplicate_adds_create_one_membership`

The new checks include a real shared-session two-tab test. After Tab B changes
the preference, Tab A's explicit workspace A context still identifies A. The
permission tests also cover missing configuration, user deactivation,
membership deletion/revocation, organization deactivation, and role changes.

**Verification performed before delivery:** 170 tests ran; 168 passed and the
two existing PostgreSQL-only concurrency tests were skipped because PostgreSQL
is unavailable in this execution environment. The checks used temporary SQLite
settings confined to verification; those settings are excluded from the patch.
Django configuration and migration-drift checks, backend and host-verifier Ruff
checks, host-compatible syntax parsing, and the real HTTP verifier passed.
Your PostgreSQL run above is the remaining environment-specific verification.

## 5. Create two synthetic workspaces for the existing local account

If this account already has two accessible workspaces, skip fixture creation.
Use the ordinary account from your Step 4B.2 sign-in. If you have not created
one yet, first run `docker compose exec api python manage.py create_local_account`
and follow its email and hidden-password prompts. Otherwise run the workspace
command twice:

```powershell
docker compose exec api python manage.py create_local_workspace
if ($LASTEXITCODE -ne 0) { throw "First local workspace creation failed." }
docker compose exec api python manage.py create_local_workspace
if ($LASTEXITCODE -ne 0) { throw "Second local workspace creation failed." }
```

At each prompt, enter the email of your existing Step 4B.2 local account. Use
synthetic names such as `Local Alpha Distributor` and `Local Beta Distributor`.
The command trims and validates the name, creates the organization and its
administrator membership together, and prints the workspace UUID. It keeps
`is_staff` and `is_superuser` unchanged. No password is needed for this trusted
local fixture command; the following HTTP verification requires your login.

Each invocation intentionally creates a new workspace. Names are not globally
unique, so rerunning the command is not an upsert. The command is available
through the local CLI and is blocked when `DEBUG=False`. Customer onboarding
and membership administration will get their own authorized flows later.

## 6. Verify the running API with real cookies

Run interactively from PowerShell:

```powershell
python scripts/verify_workspace_selection.py
if ($LASTEXITCODE -ne 0) { throw "Live workspace selection verification failed." }
```

Enter the existing account email and its password when prompted. Password input
is hidden. The script prints methods, paths, and status codes, and finishes with:

```text
Workspace selection/context verification passed.
```

The verifier uses the first two workspaces on the discovery page. It checks
selection persistence, denied mutation without CSRF, generic denial for a
random inaccessible workspace, preservation of the previous preference after
failure, explicit context after switching workspaces, clearing twice, continuing
login after clearing, and denial after logout. It clears the selection and logs
out at the end. It creates no workspaces or memberships.

This is an HTTP acceptance check rather than a replacement for the revocation
tests. Its helper disables proxies and redirects, maintains cookies in memory,
and never saves or prints passwords, session cookies, or CSRF tokens.

Verify service health:

```powershell
docker compose ps
$live = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/v1/health/live/" -ErrorAction Stop
$ready = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/v1/health/ready/" -ErrorAction Stop
$live.StatusCode
$live.Content
$ready.StatusCode
$ready.Content
```

Both responses should be HTTP 200 with `{"status":"ok"}`. No credentials,
cookie values, or environment contents are needed in the verification log.

## 7. Tools and common pitfalls

Use the existing lock file and installed tooling. This increment introduces no
external service or dependency. All components below run on your machine at $0.
Alternatives are context for future decisions; none is needed for this patch.

| Existing tool | Fit and maturity | License / hosting | Viable alternative |
| --- | --- | --- | --- |
| Django sessions, ORM, and test runner | Established built-ins handle session invalidation, validated membership queries, transactions, and test databases. | BSD-3-Clause; self-hosted in the current container. Managed hosting is optional later. | Django's file-backed session backend for a single host; database sessions suit multiple processes. |
| Django REST Framework | Established Django ecosystem tool supplies authenticated request handling, CSRF-aware sessions, serializers, and permission hooks. | BSD-3-Clause; runs inside the same Django process. | Django native JSON views with explicit validation and permission handling. |
| PostgreSQL | Existing transactional database stores memberships and sessions; will also enforce business-row policies in 4C. | Permissive PostgreSQL License; current local container. Managed PostgreSQL is optional later. | Separate PostgreSQL databases per tenant, with higher operational cost. |
| Ruff | Existing project linter/formatter; its pinned release is MIT-licensed and includes upstream notices. | MIT; runs locally in the existing image. | Flake8 and Black as separate lint/format tools. |

The selected components add no AGPL or BSL dependency in this step. Preserve
upstream license notices when distributing software. Check the license and
security notes for the exact versions when a future dependency upgrade is
proposed; this step does not upgrade the locked packages.

Common mistakes to avoid:

- Caching a membership role in the session: a later demotion could keep old
  privileges alive. This patch queries membership on each request.
- Routing a business write solely through the session's selected workspace:
  another tab can change the preference. Business requests must name their scope.
- Letting a caller supply an actor ID or an authorization role: selection input
  accepts only the workspace UUID; authentication and membership supply authority.
- Treating an application permission as a query filter: every tenant-owned
  business query still needs its organization scope, with RLS added in 4C.
- Reusing this request context in a job or global variable: authorization can
  change before the job executes and one request's scope must not reach another.
- Testing with `force_authenticate` or disabling CSRF checks: those shortcuts
  would miss cookie, session invalidation, and request-origin failures.

## 8. Review, commit, and stop

After all verification passes:

```powershell
git diff --check
if ($LASTEXITCODE -ne 0) { throw "Whitespace checks failed." }
git diff -- backend/apps/organizations/serializers.py backend/apps/organizations/views.py backend/apps/organizations/urls.py
git status --short
git add -- backend/apps/organizations scripts/verify_workspace_selection.py docs/AI_Order_Desk_Step_04B3_Workspace_Context.md
if ($LASTEXITCODE -ne 0) { throw "Could not stage the change." }
git diff --cached --stat
git commit -m "feat: add workspace selection and request tenant context"
if ($LASTEXITCODE -ne 0) { throw "Could not commit the verified change." }
git status --short
```

Inspect the new files from section 3 as well as Git's replacement diff before
committing. The final working tree should be clean. Keep credentials and
environment files out of commits and pasted output.

### Definition of Done

- [ ] Configuration checks pass; earlier migrations are applied; migration
      drift check reports `No changes detected`.
- [ ] All 170 tests pass on PostgreSQL, including both concurrency tests.
- [ ] Lint, formatting, and host verifier syntax checks pass.
- [ ] The API still runs with the restricted `orderdesk_app` role.
- [ ] The live verifier prints `Workspace selection/context verification passed.`
- [ ] Switching the preference leaves explicit workspace requests correctly scoped.
- [ ] Both health endpoints return HTTP 200 and `{"status":"ok"}`.
- [ ] The reviewed change is committed with a clean working tree.

Stop here. Send the test summary, both concurrency result lines, verifier's
final output, runtime-role check, health responses, and Git status. Use this
exact next prompt:

> Step 4B.3 verified. Here are my migration checks, test summary, both concurrency results, live workspace verifier output, runtime-role check, health responses, and Git status: [paste output]. Start Step 4C.1: design the PostgreSQL tenant context and first RLS boundary, one small step at a time.

## Official references

- [DRF SessionAuthentication and CSRF](https://www.django-rest-framework.org/api-guide/authentication/#sessionauthentication)
- [DRF permission hooks and queryset limitations](https://www.django-rest-framework.org/api-guide/permissions/)
- [Django 5.2 sessions and persistence](https://docs.djangoproject.com/en/5.2/topics/http/sessions/)
- [Django licensing](https://docs.djangoproject.com/en/5.2/faq/general/#how-is-django-licensed)
- [DRF license](https://github.com/encode/django-rest-framework/blob/main/LICENSE.md)
- [Ruff license and upstream notices](https://github.com/astral-sh/ruff/blob/main/LICENSE)
- [PostgreSQL license](https://www.postgresql.org/about/licence/)
