# Step 4C.5 — Administrator-only catalogue item creation

## Scope and contract

Add `POST /api/v1/workspaces/<workspace-uuid>/catalog/items/` to the existing
catalogue collection. Preserve its GET/HEAD behavior, 50-item pagination,
SKU/ID ordering, inactive-item visibility, read serializer, and namespace
`workspaces:catalog:items`. PUT, PATCH, and DELETE remain unsupported.
No dependencies, model changes, migrations, imports, search, matching, order
processing, frontend, updates, deactivation, or hard deletion are introduced.

POST requires a real browser session, valid CSRF, an active account, an active
URL workspace, and an active administrator membership. Missing, inactive, and
inaccessible workspaces retain the generic HTTP 403 workspace denial. An
accessible reviewer/viewer receives HTTP 403:

```json
{"detail":"You do not have permission to create catalogue items in this workspace."}
```

The URL and authenticated session own organization/user identity. Session
workspace preferences and forged headers/cookies cannot replace them. The
server rejects all creation query parameters and unknown/protected body fields,
including `id`, `organization`, `organization_id`, `user_id`, and timestamps.
Authorization is refreshed after obtaining the existing organization row lock,
before parsing the body, validating fields, or checking catalogue conflicts.
The catalogue's small session-authentication subclass delegates the standard
CSRF check to Django's underlying `HttpRequest`. This preserves session, token,
origin, and referer enforcement while avoiding DRF's eager JSON parsing through
its `Request.POST` property. The JSON parser runs inside protected creation.

Input is a JSON object with exactly these allowed fields:

| Field | Contract |
| --- | --- |
| `sku` | Required JSON string; reject empty/whitespace-only values and numeric coercion. Trim surrounding whitespace using the existing model rule; preserve case, punctuation, and leading zeroes. |
| `description` | Optional JSON string, default `""`; preserve its whitespace. |
| `is_active` | Optional JSON boolean, default `true`; reject string/numeric coercion. |

Both text fields are existing PostgreSQL-backed Django `TextField` values
without a model `max_length`. This increment does not invent a 255-character
limit or alter stored SKUs/collation. Model field validation and existing
database constraints remain in effect. Malformed JSON returns 400; unsupported
media types return 415 through the established DRF JSON parser.

PostgreSQL's existing unique B-tree index still has a physical size boundary.
Some long, poorly compressible SKUs cannot fit, even though the text field has
no character limit. That specific native failure returns a safe HTTP 400:

```json
{"sku":["This stock code is too large for the catalogue index."]}
```

Only SQLSTATE `54000` identifying both the existing catalogue table and its
SKU uniqueness constraint receives this translation, after rollback. Other
database errors propagate. Compressible long SKUs and long descriptions remain
accepted; there is no arbitrary character cap.

Example request:

```json
{"sku":"  000Ab/P-1.x  ","description":"Synthetic replacement part","is_active":true}
```

Success returns HTTP 201 with one item object rather than a pagination envelope:

```json
{
  "id":"11111111-1111-4111-8111-111111111111",
  "organization_id":"22222222-2222-4222-8222-222222222222",
  "sku":"000Ab/P-1.x",
  "description":"Synthetic replacement part",
  "is_active":true,
  "created_at":"2026-10-05T20:00:00Z",
  "updated_at":"2026-10-05T20:00:00Z"
}
```

Invalid input returns the existing field-keyed HTTP 400 validation format.
There was no committed catalogue creation conflict contract before this step;
the unwired draft was not an established API. A same-workspace duplicate now
returns HTTP 409 with this stable response:

```json
{"detail":"A catalogue item with this stock code already exists."}
```

An inactive item still reserves its SKU. The same SKU in another organization
remains permitted. The database constraint resolves concurrent duplicates;
only SQLSTATE `23505` with the known `catalog_org_sku_unique` constraint is
translated. Unrelated integrity errors propagate. Responses never include SQL,
constraint names, another workspace's rows, or credential details.

## Transaction and demotion ordering

The creation service owns the existing outer `tenant_scope(..., write=True)`.
It locks the organization first and resolves current authorization afterward.
The protected administrator check precedes a server-side deferred data callback;
the view uses that callback to validate query parameters and parse its request.
This keeps detailed validation behind protected authorization without passing
an HTTP request object into the service or adding a second tenant mechanism.

The explicit creation serializer validates input inside this scope. Model
field validation runs with uniqueness/constraint prechecks disabled so the
database consistently resolves duplicate submissions. The existing database
constraints remain unchanged. Insertion and scalar response materialization
complete before commit. Known conflicts are caught outside the failed scope,
after rollback; serializer failure also rolls back the inserted item.

If demotion obtains the organization lock and commits first, creation waits,
refreshes authorization, and returns 403 without insertion. If creation obtains
the lock first while the actor is an administrator, it may commit before the
waiting demotion. Subsequent requests observe the new role. This reuses the
existing organization-first membership mutation convention; it does not add a
new demotion endpoint. GET and HEAD retain their separate read-only scopes.

PostgreSQL forced RLS independently enforces matching organization, active
identity/membership/workspace, and administrator INSERT permission. Runtime
checks connect directly as `orderdesk_app`, with a separate fixture-only
maintenance alias. No role elevation, session-level tenant context, DELETE
grant, policy change, or database reset is used.

## Files

| File | Responsibility |
| --- | --- |
| `backend/apps/catalog/serializers.py` | Explicit strict creation input, preserving the seven-field read serializer. |
| `backend/apps/catalog/services.py` | Protected admin creation, model validation, insert, materialization, and precise domain conflict translation. |
| `backend/apps/catalog/views.py` | POST, standard CSRF on the underlying request, deferred query/body parsing, safe 400/409 translation, and 201 response; unchanged GET/HEAD. |
| `backend/apps/catalog/tests/test_create_contracts.py` | Defaults, strict fields/types, normalization, and actual model length contracts. |
| `backend/apps/catalog/tests/test_create_services.py` | Owned scopes, authorization ordering, native conflicts, rollback, and materialization. |
| `backend/apps/catalog/tests/test_create_api.py` | Native PostgreSQL session/CSRF/HTTP creation and authorization regressions. |
| `backend/apps/catalog/tests/test_create_concurrency.py` | Independent connection duplicate, cross-workspace, and demotion ordering races. |
| `backend/apps/catalog/tests/test_read_api.py` | Preserve read tests; update the supported-method contract for POST. |
| `backend/apps/catalog/tests/runtime_rls.py` | Preserve 47 checks and extend real runtime HTTP creation/isolation/concurrency proof. |
| `scripts/verify_catalog_api.py` | Keep live verification confined to reads; never submit catalogue POST in the main database. |
| `scripts/tests/test_verify_catalog_api.py` | Explicit guard against live catalogue creation requests. |
| `docs/AI_Order_Desk_Step_04C5_Catalogue_Creation.md` | Contract, commands, actual results, and Definition of Done. |

Existing routing, model/migration definitions, tenant helper, bootstrap,
runtime-role audit, main-database guard, and original demotion race are retained.
Unrelated order/provisioning/guidance drafts are preserved. Local checkpoint
documents are updated without staging their pre-existing unrelated content.

## Verification setup and commands

Starting committed predecessor: `3f1c0d3`. Its current PostgreSQL normal baseline
is 256 tests, all passed in 30.667s without skips before creation changes.
The predecessor's 47 direct-runtime RLS/HTTP checks also passed in 29.982s
without skips; system checks and both migration-state checks passed.

Because unrelated order drafts are registered in the primary working tree,
verification uses `C:\Users\HomePC\Desktop\Billion1\order-desk-step4c5`, an
isolated checkout containing the committed predecessor plus this increment.
A local untracked Compose override mounts that backend for `manage`, `dbsetup`,
and `rlscheck`, and its scripts/example template under `/verification-project`.
It reuses the existing PostgreSQL service/volume and secrets configuration
without copying or displaying `.env`. No unfinished order migration is applied.

Use the following PowerShell argument list from the project root for this
session's isolated verification. A checkout containing only the committed
increment can use the ordinary `docker compose` commands instead.

```powershell
Set-Location -LiteralPath 'C:\Users\HomePC\Desktop\Billion1\order-desk'
$verifyCompose = @(
    '--project-directory', (Get-Location).Path,
    '-f', (Join-Path (Get-Location).Path 'compose.yaml'),
    '-f', 'C:\Users\HomePC\Desktop\Billion1\order-desk-step4c5\verification.compose.yaml'
)
docker compose @verifyCompose config --quiet
docker compose @verifyCompose run --rm manage python manage.py check
docker compose @verifyCompose run --rm manage python manage.py makemigrations --check --dry-run
docker compose @verifyCompose run --rm manage python manage.py migrate --check
```

These commands validate configuration without printing secrets, check Django,
and require no model drift or pending migration in the scoped checkout.

Run contracts, services/API, and races sequentially against the prepared
disposable `test_orderdesk` database:

```powershell
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_create_contracts --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_create_services apps.catalog.tests.test_create_api --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_create_concurrency --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 2
```

Require all tests passing without skips. Actual totals are reported from the
final source rather than padded to a historical guide number. Explicitly
preserve and run the four existing concurrency tests:

```powershell
docker compose @verifyCompose run --rm manage python manage.py test apps.accounts.tests.test_login_concurrency apps.organizations.tests.test_concurrency apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_waits_for_lock_and_observes_committed_demotion apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_rechecks_membership_after_waiting_for_revocation --settings=config.settings.test --keepdb --noinput -v 2
```

Check lint/format and offline script guards without modifying dependencies:

```powershell
docker compose @verifyCompose run --rm manage ruff check . /verification-project/scripts
docker compose @verifyCompose run --rm manage ruff format --check . /verification-project/scripts/verify_catalog_api.py /verification-project/scripts/tests/test_verify_catalog_api.py
docker compose @verifyCompose run --rm --workdir /verification-project manage python -m unittest discover -s scripts/tests -v
```

Rerun the committed provisioner, then prove restricted grants and RLS/HTTP
behavior as the real app role. Keep it sequential with the Django suite because
the fixture database is shared:

```powershell
docker compose @verifyCompose run --rm dbsetup
docker compose @verifyCompose run --rm rlscheck
```

The runtime command audits actual current/session identities, table ownership,
forced RLS, five policies, and grants before fixture creation. Owner credentials
are confined to its separate fixture connection; operations under test run as
the restricted app. Record the actual expanded test total and require no skips.

Check the running API's restrictions, expected main-database refusal, and health:

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
if (($live.Content | ConvertFrom-Json).status -ne 'ok' -or ($ready.Content | ConvertFrom-Json).status -ne 'ok') { throw 'Health response failed.' }
python scripts/verify_catalog_api.py
git diff --check
git diff --cached --check
git status --short
```

The live script prompts for an existing local account's hidden credentials,
accepts an empty catalogue, refuses redirects/non-loopback origins, displays
only status/contract checks, and logs out its session. All main-database catalogue
requests remain reads or checks of unsupported update/delete methods.
Do not create/delete a main-database item for verification. An automated local
run may use the established temporary account/empty-workspace control fixture
with a random in-memory password and exact cleanup; it still never POSTs items.
Synthetic catalogue creation and races run only in `test_orderdesk`.

## Actual results and Definition of Done

Executed locally on 2026-10-06 against PostgreSQL 18.6, using Python 3.14.8,
Django 5.2.17, DRF 3.18.1, Psycopg 3.3.6, and Ruff 0.16.10:

| Gate | Actual result |
| --- | --- |
| Creation contract tests | 13 passed in 0.034s. |
| Native service/API tests | 44 passed in 11.024s (17 service, 27 API). |
| Creation concurrency | 4 passed in 1.305s, using distinct PostgreSQL connections. |
| Full normal PostgreSQL suite | 317 passed in 46.011s; no skips. |
| Explicit existing concurrency rerun | 4 passed in 0.858s. |
| Standalone script suite | 19 passed in 0.707s. |
| Direct-runtime RLS/HTTP verifier | 60 passed in 77.149s as `orderdesk_app`; no skips; original 47 cases preserved. |
| Django system check | No issues. |
| Migration-state checks | No model changes; no pending scoped migrations. |
| Ruff lint and formatting | All checks passed; 98 backend/changed script files already formatted. |
| Bootstrap rerun | Completed successfully; subsequent runtime audit confirmed owner, FORCE RLS, five policies, and preserved restricted grants. |
| Main-database guard | Expected refusal before fixtures, exit 1. |
| Live runtime-role check | Restricted role verified. |
| Live catalogue read verifier | Passed through real login/session/CSRF; empty catalogue accepted; no catalogue POST. |
| Health | Both endpoints HTTP 200 with `status: ok`. |
| Whitespace/source review | Passed; only the 12 files listed above belong in this increment's commit. |

The normal suite grew from 256 to 317 by adding 61 checks. Its total already
includes the focused creation suites and concurrency cases; the standalone
script and direct-runtime totals are separate. Native fixture creation stayed
in `test_orderdesk`. Temporary live control identities were removed, and no
main-database catalogue rows were created or deleted.

Same-workspace simultaneous POSTs produced one 201, one 409, and one item.
Cross-workspace simultaneous POSTs both returned 201. Both organization-lock
orderings passed: committed demotion first denies creation; creation first may
commit, then demotion prevents the next creation. Native checks also exercised
PostgreSQL's real unique-index size failure, safe field-keyed 400, no partial
item, clean tenant context, and successful subsequent creation.

Focused execution found and corrected two concrete integration issues: DRF's
non-object error needed its normal dictionary-shaped serializer handling, and
CSRF on the DRF request eagerly parsed JSON before protected authorization.
The corrected focused suites and full regression passed. A real PostgreSQL
high-entropy SKU probe established the physical index-size boundary and drove
the narrow safe 400 handling, rather than an invented model maximum length.

Completion requires strict input, protected fresh admin authorization, precise
409 conflicts, independent native duplicate/demotion races, rollback/context
cleanup, unchanged reads, runtime app-role proof, no schema/dependency changes,
all established gates, and a reviewed scoped commit:
`feat: add admin-only catalogue item creation`.

All verification gates are satisfied. There is no unresolved execution blocker.
The pre-existing guidance/checkpoint, order, provisioning, and mixed catalogue
draft files remain outside this increment. The final staged source is compared
with the isolated source that passed the checks before committing.

Next proposed increment: Step 4C.6, administrator-only catalogue updates and
deactivation. Hard deletion and imports remain outside that scope.
