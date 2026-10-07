# Step 4C.4 — Read-only tenant-scoped catalogue API

This increment exposes the committed `CatalogItem` boundary through browser
sessions. It adds no dependency, model, migration, catalogue write handler,
import, search, matching, order-processing feature, or frontend screen.
Creation remains Step 4C.5.

## Contract

`GET /api/v1/workspaces/<workspace-uuid>/catalog/items/` and optional `?page=2`.
The reverse name is `workspaces:catalog:items` with `workspace_id`.

Active admin, reviewer, and viewer members may read an active workspace. The
URL UUID selects the workspace. A session selection is only a UI preference;
headers, cookies, bodies, and query parameters cannot replace the authenticated
actor or route tenant. Authorization is refreshed inside the existing outer
read-only tenant transaction. Safe GET and HEAD require no CSRF token.

Anonymous, expired, and logged-out sessions preserve the existing HTTP 403
session contract. Missing, inactive, and inaccessible workspaces all return
HTTP 403 with `{"detail":"You do not have access to this workspace."}`.
Malformed UUID paths preserve the existing router's HTTP 404 behavior.

Successful responses contain exactly `count`, `next`, `previous`, and `results`.
Items expose only `id`, `organization_id`, `sku`, `description`, `is_active`,
`created_at`, and `updated_at`. The organization ID is read directly from the
foreign-key scalar. Inactive identities remain visible. An accessible empty
catalogue returns `{"count":0,"next":null,"previous":null,"results":[]}`.

Pages contain at most 50 items, ordered by `sku`, then `id`, using the installed
PostgreSQL collation. SKU case, punctuation, and leading zeroes are preserved.
Only one optional `page` parameter is accepted. Unsupported or repeated
parameters return HTTP 400. Blank, invalid, nonpositive, unavailable, and `last`
pages return HTTP 404 with `{"detail":"Invalid page."}`. Page-one links may
omit `page`; every link retains the same workspace path. HEAD applies the same
authentication, authorization, and pagination checks and sends no body.

The view supports GET, HEAD, and OPTIONS. POST, PUT, PATCH, and DELETE return
405 when tested with valid authentication and CSRF; an earlier CSRF failure may
otherwise return 403. Responses from the view are private and non-cacheable.

## Implementation and files

| File | Responsibility |
| --- | --- |
| `backend/apps/catalog/selectors.py` | Explicit organization filter and SKU/ID ordering; lazy results must be consumed inside the matching scope. |
| `backend/apps/catalog/serializers.py` | Seven allowlisted, read-only scalar fields; no organization relation query. |
| `backend/apps/catalog/pagination.py` | Fixed 50-item pages, strict single-parameter validation, stable page errors, no `last` alias. |
| `backend/apps/catalog/views.py` | Existing session/workspace permissions; fresh read scope owns count, retrieval, serialization, and response materialization. |
| `backend/apps/catalog/urls.py` | Catalogue collection route and `catalog` namespace. |
| `backend/apps/organizations/urls.py` | Nested catalogue route; preserves existing workspace routes. |
| `backend/config/urls.py` | Explicit existing `workspaces` namespace for root routing. |
| `backend/apps/catalog/tests/test_read_contracts.py` | 13 selector, scalar serializer, and pagination contracts. |
| `backend/apps/catalog/tests/test_read_api.py` | 22 PostgreSQL HTTP/session/authorization/materialization regressions. |
| `backend/apps/catalog/tests/runtime_rls.py` | Retains 35 policy checks and adds 12 HTTP checks under the actual restricted runtime connection. |
| `scripts/verify_catalog_api.py` | Live loopback-only session verifier; prompts hidden credentials, accepts an empty catalogue, creates no rows, and logs out its session. |
| `scripts/tests/test_verify_catalog_api.py` | Offline confinement, response validation, pagination, and failure-cleanup checks. |
| `docs/AI_Order_Desk_Step_04C4_Read_Only_Catalogue_API.md` | Contract, verification evidence, commands, and next-increment handoff. |

The existing model, applied migration, transaction helper, RLS command guard,
role audits, and demotion race remain unchanged. Explicit application filtering
and independent forced PostgreSQL RLS both enforce tenant isolation. The HTTP
runtime test removes the application filter and checks the count, IDs, and
organization scalars. Serializer failure, connection reuse, and rendering after
scope exit are exercised without permitting late SQL.

## Working-tree boundary and baseline

Starting HEAD: `9a5f2de` (Step 4C.3). Existing unrelated changes included order
models/services/API/migrations, their app/route registration, provisioning edits,
`.gitignore`, `.github/`, `AGENTS.md`, project-state documents, and an ADR.
Those drafts are preserved and are excluded from this commit and its suite.
The local state documents received a current task/checkpoint note and remain
uncommitted because they already contained unrelated content.

Verification uses an isolated worktree at
`C:\Users\HomePC\Desktop\Billion1\order-desk-step4c4`, containing the committed
Step 4C.3 source plus only this increment. Its local untracked Compose override
mounts that backend for `manage`, `dbsetup`, and `rlscheck`, and scripts read-only
at `/verification-project/scripts`. Its committed `.env.example` template is
also mounted for the existing environment-script tests; actual `.env` secrets
are never copied or displayed. The existing PostgreSQL service/volume is reused.
This avoids applying unfinished order migrations or including their draft tests.

The actual preceding normal baseline is **221 tests**, all passing in 38.624s
with no skips. The historical guide's 216 reflected an earlier transaction-test
count. Existing **35 runtime RLS checks** separately passed in 3.757s.

The prepared test database initially had administrator-owned tables/database
and lacked the established migrator schema grants. Ownership was restored only
in `test_orderdesk`; the committed local provisioner restored the existing role
and schema grants. Neither application role received CREATEDB, superuser,
BYPASSRLS, role membership, or runtime schema CREATE. No database was reset,
no volume was deleted, and no main-database catalogue fixtures were inserted.
Existing committed migrations were applied to the prepared test database by the
test runner; this increment introduces no schema migration.

## PowerShell verification

Run from the project root. In a checkout containing only the verified increment,
use the usual `docker compose` commands. With the preserved local drafts, use
the existing isolated worktree and override from this session:

```powershell
Set-Location -LiteralPath 'C:\Users\HomePC\Desktop\Billion1\order-desk'
$verifyCompose = @(
    '--project-directory', (Get-Location).Path,
    '-f', (Join-Path (Get-Location).Path 'compose.yaml'),
    '-f', 'C:\Users\HomePC\Desktop\Billion1\order-desk-step4c4\verification.compose.yaml'
)
docker compose @verifyCompose config --quiet
```

`config --quiet` checks configuration without printing resolved secrets. The
following configuration and migration commands must report no system issues,
no model changes, and no pending migration for the committed increment:

```powershell
docker compose @verifyCompose run --rm manage python manage.py check
docker compose @verifyCompose run --rm manage python manage.py makemigrations --check --dry-run
docker compose @verifyCompose run --rm manage python manage.py migrate --check
```

Run the contract and native API suites sequentially; the test runner uses the
prepared disposable PostgreSQL database and keeps it for the runtime verifier:

```powershell
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_read_contracts --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_read_api --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 2
```

The normal suite should contain **256 tests: 221 preceding tests plus 35 new
read tests**, with no skips. Run the existing four concurrency cases separately
when individual results are needed:

```powershell
docker compose @verifyCompose run --rm manage python manage.py test apps.accounts.tests.test_login_concurrency apps.organizations.tests.test_concurrency apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_waits_for_lock_and_observes_committed_demotion apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_rechecks_membership_after_waiting_for_revocation --settings=config.settings.test --keepdb --noinput -v 2
```

Check backend and verifier-script lint/format, then run the offline script suite:

```powershell
docker compose @verifyCompose run --rm manage ruff check . /verification-project/scripts
docker compose @verifyCompose run --rm manage ruff format --check . /verification-project/scripts/verify_catalog_api.py /verification-project/scripts/tests/test_verify_catalog_api.py
docker compose @verifyCompose run --rm --workdir /verification-project manage python -m unittest discover -s scripts/tests -v
```

The local provisioner rerun must preserve the narrowed catalogue grants. The
runtime command audits actual `orderdesk_app` current/session identities,
forced RLS, policies, and privileges before creating synthetic fixtures only in
`test_orderdesk`. Its separate maintenance-owner alias only manages fixtures:

```powershell
docker compose @verifyCompose run --rm dbsetup
docker compose @verifyCompose run --rm rlscheck
```

Require all **47 runtime checks** passing without skips. Keep tests and the
runtime verifier sequential because they share the dedicated test database.

Check the running API's restricted role, main-database refusal, and health:

```powershell
docker compose up -d --wait --wait-timeout 120 api
docker compose exec -T api python manage.py check_runtime_role
$guardOutput = @(docker compose exec -T api python manage.py verify_catalog_rls 2>&1)
$guardExit = $LASTEXITCODE
if ($guardExit -ne 1 -or (($guardOutput -join "`n") -notlike '*Refusing to populate anything except test_orderdesk.*')) {
    throw 'The main-database guard did not produce its expected refusal.'
}
$live = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/v1/health/live/'
$ready = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/v1/health/ready/'
if ($live.StatusCode -ne 200 -or $ready.StatusCode -ne 200) { throw 'Health check failed.' }
```

The standalone live verifier uses an existing local account/workspace, requests
its credentials interactively, displays status/contract checks without customer
rows, refuses redirects/non-loopback targets, and ends the created session:

```powershell
python scripts/verify_catalog_api.py
# Optionally select an existing accessible workspace explicitly:
python scripts/verify_catalog_api.py --workspace-id <existing-workspace-uuid>
```

For this session's automated live check, a temporary synthetic account and empty
workspace may be created in the main database's control tables with an in-memory
random password; the exact generated identities/login budgets are removed
in `finally`. The script itself never creates fixtures or catalogue records.
All catalogue fixtures remain in the disposable test database. Credentials,
cookies, CSRF tokens, and connection secrets must never be printed or saved.

Finish by reviewing the increment's exact staged files and whitespace:

```powershell
git diff --check
git diff --cached --check
git diff --cached --stat
git status --short
```

Do not stage all local changes. Commit only the files in the implementation table
with `feat: add tenant-scoped read-only catalogue API` after every required gate
passes. Preserve unrelated changes and report the resulting status accurately.

## Actual increment results and Definition of Done

All required checks passed on 2026-10-05 using Python 3.14.8, Django 5.2.17,
DRF 3.18.1, Psycopg 3.3.6, Ruff 0.16.10, and the existing PostgreSQL container.
No dependency or schema definition changed.

| Gate | Observed result |
| --- | --- |
| Preceding normal baseline | 221 tests, 38.624s, OK, no skips. |
| Selector/serializer/pagination contracts | 13 tests, 0.030s, OK. |
| Native catalogue read API | 22 tests, 10.437s, OK; real credential sessions and CSRF. |
| Final full normal PostgreSQL suite | 256 tests, 37.724s, OK, no skips; includes the final forged-cookie and malformed-route assertions. |
| Four existing concurrency tests | 4 tests, 1.032s, OK, no skips. |
| Expanded direct-runtime verifier | 47 tests, 46.757s, OK, no skips; original 35 plus 12 HTTP checks, actual app current/session identities, original demotion race preserved. |
| Provisioner rerun/grant preservation | Committed `dbsetup` passed; subsequent runtime metadata/grant audit and 47 checks passed. |
| Standalone script tests | 18 tests, 0.251s, OK: five existing environment tests plus 13 new verifier tests. |
| Django system check | No issues, zero silenced. |
| Migration drift / pending migrations | `No changes detected`; `migrate --check` exit 0 in the isolated increment checkout. No migration file added or changed. |
| Ruff lint / formatting | Lint passed for backend and all scripts; backend and new verifier files passed format check, 93 files already formatted. |
| Runtime role | Running API reported `Runtime database role is restricted.` |
| Main-database guard | Expected exit 1: `Refusing to populate anything except test_orderdesk.` |
| Live catalogue session verifier | Passed against the actual loopback server as the runtime role, with an empty catalogue; GET/HEAD, 400/403/404/405, rotated CSRF, and logout checked. Temporary control identities removed. |
| Health | Live and ready both HTTP 200, each `{"status":"ok"}`. |
| Source and Git review | Scoped route, authorization, transaction, selector, scalar serializer, pagination, tests, and script independently reviewed; whitespace checks passed. |

Two verification-harness issues were corrected: mixed line endings in the
isolated route copy, and a missing project-root/template mount for standalone
script discovery. Broad formatting also exposed pre-existing parentheses style
in the older session/workspace verifier scripts; they were preserved unchanged,
while backend and this increment's script formatting passed. The live verifier's
bare previous-page link bug was fixed and regression-tested before live proof.

- [x] Only catalogue reads are exposed; creation is deferred.
- [x] All catalogue evaluation and serialization occur inside the matching scope.
- [x] Independent HTTP RLS isolation passes after removing application filtering.
- [x] Normal PostgreSQL, concurrency, runtime, live, and script checks pass.
- [x] No new migrations, dependencies, secrets, main catalogue fixtures, or unrelated draft files enter the commit.
- [x] Existing unrelated working-tree changes remain preserved.

Next increment: Step 4C.5, administrator-only catalogue item creation. Inspect
the preserved uncommitted creation-service/test drafts before adopting them;
they are outside this verified read-only commit and are not proof of creation.
