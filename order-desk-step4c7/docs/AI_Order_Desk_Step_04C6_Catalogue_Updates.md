# Step 4C.6 — Administrator-only catalogue updates and deactivation

## Contract established before implementation

Add only `PATCH /api/v1/workspaces/<workspace-uuid>/catalog/items/<item-uuid>/`
under namespace `workspaces:catalog:item`. Existing collection GET/HEAD/POST,
pagination, ordering, inactive-item visibility, creation defaults and conflicts
remain unchanged. The detail route supports PATCH and framework OPTIONS only;
GET, HEAD, POST, PUT, and DELETE are unsupported. No detail reads, SKU renaming,
hard deletion, imports, bulk mutations, matching, frontend, dependencies,
migrations, or grant/policy changes belong to this increment.

PATCH requires the existing active session user, valid CSRF, active URL
workspace, and active administrator membership. The catalogue-local standard
session/CSRF implementation is reused. Missing/inactive/inaccessible workspaces
retain their established generic 403. Accessible reviewers/viewers receive 403:

```json
{"detail":"You do not have permission to update catalogue items in this workspace."}
```

The service owns `tenant_scope(..., write=True)`, acquiring the organization
lock first and refreshing authorization. It checks administrator permission
before any catalogue lookup or detailed body/query validation. It then loads
the current item with both URL item UUID and authorized organization, using
`SELECT FOR UPDATE`. A missing or foreign item returns HTTP 404:

```json
{"detail":"Not found."}
```

No unrestricted item lookup discovers its organization. Missing-item handling
precedes body validation; malformed UUIDs retain the router's existing 404.
Session workspace selection, headers, cookies, and client fields never replace
URL workspace or authenticated actor identity.

Accept a nonempty JSON object with either or both fields:

| Field | Contract |
| --- | --- |
| `description` | Genuine JSON string; blank allowed, null rejected, whitespace preserved. Existing TextField has no `max_length`; no arbitrary cap is introduced. |
| `is_active` | Genuine JSON boolean; strings/numbers/null rejected. False deactivates; true reactivates. |

Omitted fields remain stored as they were, without creation defaults. Reject
empty objects, non-objects, unknown fields, and protected fields including
`sku`, `id`, `organization`, `organization_id`, `user_id`, `created_at`, and
`updated_at`. Reject all query parameters. Validation uses existing field-keyed
400 errors (`non_field_errors` for invalid objects/empty input). Malformed JSON
returns 400; unsupported media returns 415 after protected authorization/lookup.

Example requests:

```json
{"description":"Updated catalogue description"}
```

```json
{"is_active":false}
```

```json
{"description":"Available again","is_active":true}
```

Return HTTP 200 using the existing scalar read serializer:

```json
{
  "id":"11111111-1111-4111-8111-111111111111",
  "organization_id":"22222222-2222-4222-8222-222222222222",
  "sku":"000Ab/P-1.x",
  "description":"Available again",
  "is_active":true,
  "created_at":"2026-10-06T08:00:00Z",
  "updated_at":"2026-10-06T09:00:00Z"
}
```

Real changes save only changed mutable fields plus the model's auto-updated
timestamp. Valid requests supplying already stored values skip saving and
return the existing representation, preserving `updated_at`. Repeated
deactivation/reactivation is idempotent. Preserve ID, organization, stored SKU
(including legacy edge whitespace), and creation timestamp. Validate mutable
model fields without invoking creation-oriented SKU normalization.

Deactivation preserves the row and its reserved SKU. Inactive items continue
appearing in catalogue reads. The existing POST duplicate 409 and narrowly
translated native unique-index-size 400 remain unchanged. Unexpected update
database failures propagate; they are never disguised as validation errors.

## Locking, concurrency, and RLS

Use the established organization-first lock order, fresh administrator check,
then organization-filtered item row lock. Parse and validate only afterward.
Insertion of a new tenant mechanism or nesting caller-owned transactions is
unnecessary and forbidden by the existing helper. Save and scalar response
materialization occur before scope exit; failures roll back before response
translation, restoring clean transaction-local context.

Independent-field updates apply only submitted fields to freshly loaded state,
preserving both changes. Same-field edits use serialized last-write-wins: the
request acquiring the protected locks later reads the committed current state
and applies its submitted value. Row locking prevents unsafe interleaving; it
does not detect stale browser forms. No optimistic version/conditional request
protocol is added.

Demotion first: creation/update waits on the organization lock, refreshes the
committed role, and denies the mutation. Mutation first: an authorized update
may finish before waiting demotion; the next request sees its new role. This
reuses existing membership mutation ordering rather than adding an endpoint.

The established restrictive tenant boundary and administrator UPDATE policy
already enforce both USING and WITH CHECK under forced RLS. Runtime verified
operations authenticate directly as `orderdesk_app`; the separate maintenance
alias prepares/asserts/cleans synthetic fixtures only in `test_orderdesk`.
No role elevation, session-level tenant identity, DELETE grant, policy changes,
or main-database catalogue writes are needed. No existing transactional audit
hook was found in committed catalogue code; no audit subsystem is introduced.

## Files

| File | Responsibility |
| --- | --- |
| `backend/apps/catalog/serializers.py` | Explicit strict nonempty partial-update input; read/creation contracts retained. |
| `backend/apps/catalog/services.py` | Owned protected update scope, fresh row lock, minimal changes, no-op timestamps, materialization. |
| `backend/apps/catalog/views.py` | PATCH-only detail handler using existing session/CSRF and safe validation/not-found responses. |
| `backend/apps/catalog/urls.py` | Workspace-scoped UUID item route with existing namespace conventions. |
| `backend/apps/catalog/tests/test_update_contracts.py` | Mutable fields, omitted-field behavior, strict types, immutable/unknown rejection. |
| `backend/apps/catalog/tests/test_update_services.py` | Native locking/authorization order, timestamps, unchanged identity, rollback/scope cleanup. |
| `backend/apps/catalog/tests/test_update_api.py` | Real session/CSRF PostgreSQL PATCH integration and collection regressions. |
| `backend/apps/catalog/tests/test_update_concurrency.py` | Independent connection partial edits, same-field ordering, and both demotion races. |
| `backend/apps/catalog/tests/runtime_rls.py` | Preserve 60 checks and extend direct-runtime HTTP/SQL update and isolation proof. |
| `docs/AI_Order_Desk_Step_04C6_Catalogue_Updates.md` | Contract, actual evidence, commands, Definition of Done. |

Unrelated order, provisioning, guidance, and mixed catalogue drafts remain
preserved. Local checkpoint documents are updated without staging their
pre-existing unrelated contents. Verify committed Step 4C.5 plus this increment
in the isolated `order-desk-step4c6` checkout so no draft order migration runs.

## PowerShell verification commands

The local untracked override mounts the scoped backend for helper containers
and scripts/example template for script checks; it reuses existing Compose
configuration/volume without copying or displaying `.env`.

```powershell
Set-Location -LiteralPath 'C:\Users\HomePC\Desktop\Billion1\order-desk'
$verifyCompose = @(
    '--project-directory', (Get-Location).Path,
    '-f', (Join-Path (Get-Location).Path 'compose.yaml'),
    '-f', 'C:\Users\HomePC\Desktop\Billion1\order-desk-step4c6\verification.compose.yaml'
)
docker compose @verifyCompose config --quiet
docker compose @verifyCompose run --rm manage python manage.py check
docker compose @verifyCompose run --rm manage python manage.py makemigrations --check --dry-run
docker compose @verifyCompose run --rm manage python manage.py migrate --check
docker compose @verifyCompose run --rm manage ruff check . /verification-project/scripts
docker compose @verifyCompose run --rm manage ruff format --check . /verification-project/scripts/verify_catalog_api.py /verification-project/scripts/tests/test_verify_catalog_api.py
docker compose @verifyCompose run --rm --workdir /verification-project manage python -m unittest discover -s scripts/tests -v
```

Native suites share the prepared disposable database, so run them sequentially:

```powershell
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_update_contracts --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_update_services apps.catalog.tests.test_update_api --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_update_concurrency --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 1
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_create_concurrency apps.accounts.tests.test_login_concurrency apps.organizations.tests.test_concurrency apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_waits_for_lock_and_observes_committed_demotion apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_rechecks_membership_after_waiting_for_revocation --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm dbsetup
docker compose @verifyCompose run --rm rlscheck
```

The runtime verifier refuses skipped/missing cases and audits direct identities,
role flags, catalogue ownership, FORCE RLS, five policies, and restricted grants
before fixtures. Its owner alias remains confined to test fixture control.

```powershell
docker compose up -d --wait --wait-timeout 120 api
docker compose exec -T api python manage.py check_runtime_role
$guardOutput = @(docker compose exec -T api python manage.py verify_catalog_rls 2>&1)
if ($LASTEXITCODE -ne 1 -or (($guardOutput -join "`n") -notlike '*Refusing to populate anything except test_orderdesk.*')) { throw 'Main database guard failed.' }
foreach ($endpoint in @('live', 'ready')) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/v1/health/$endpoint/"
    if ($response.StatusCode -ne 200 -or ($response.Content | ConvertFrom-Json).status -ne 'ok') { throw 'Health failed.' }
}
python scripts/verify_catalog_api.py
git diff --check
git diff --cached --check
git status --short
```

The existing live script checks catalogue reads and unsupported collection
methods only, with real login/CSRF/logout. Never mutate main-database catalogue
items for verification. The established temporary empty-workspace/control-user
fixture may automate live reads with an in-memory credential and exact cleanup.
No synthetic catalogue row is created, updated, deactivated, or deleted there.

## Actual results and Definition of Done

Executed locally on 2026-10-06 with Python 3.14.8, Django 5.2.17, DRF 3.18.1,
Psycopg 3.3.6, and the existing PostgreSQL 18.6/Ruff stack:

| Gate | Actual result |
| --- | --- |
| Committed predecessor normal baseline | 317 passed in 44.553s, no skips. |
| Committed predecessor runtime baseline | 60 passed in 69.209s, no skips. |
| Focused update checks | 38 passed in 8.291s: 8 contracts, 7 services, 19 API, 4 races. |
| Full normal PostgreSQL suite | 355 passed in 53.615s, no skips. |
| Final affected checks plus every existing concurrency case | 46 passed in 14.230s; includes all 12 normal concurrency cases. |
| Standalone scripts | 19 passed in 0.707s. |
| Expanded direct-runtime verifier | 75 passed in 93.112s as orderdesk_app, no skips; all 60 predecessor checks preserved. |
| System/migration checks | No issues, no model changes, no pending scoped migrations. |
| Lint/formatting | Backend/script lint passes after scoped test fixes; 102 files already formatted. |
| Bootstrap | Completed successfully; runtime audit confirmed owner/FORCE RLS/five policies/restricted grants before fixtures. |
| Main-database guard and live runtime role | Expected guard refusal exit 1; restricted runtime role confirmed. |
| Live reads and health | Real session/CSRF/logout read verifier passed; both endpoints 200 and status ok. |
| Source/whitespace review | Scoped review passed; final staged-source comparison remains before commit. |

All synthetic catalogue mutations stayed in test_orderdesk. Live verification
created only the established temporary empty-workspace/control-user fixture,
removed it exactly, and never wrote catalogue rows in the main database.

Independent connection tests proved both partial edits survive, deterministic
same-field last-write-wins, and both update/demotion lock orderings. Native
runtime checks also exercised the missing-application-filter UPDATE, rejected
organization reassignment, scalar materialization, and SQLSTATE 22012 rollback
on a reused runtime PID. An initial runtime test incorrectly expected logout
200; the established endpoint returns 204, and that assertion was corrected;
the complete 75-check native rerun passed. No execution blocker remains.

Completion requires the specified strict immutable-SKU PATCH contract, active
administrator/session/CSRF checks, organization-filtered locked lookup, minimal
field updates, no-op timestamp preservation, independent-connection concurrency,
both demotion orderings, rollback/context cleanup, forced runtime RLS proof,
unchanged reads/creation, all 15 established gates, and a reviewed scoped commit:
`feat: add admin-only catalogue updates and deactivation`.

Next proposed increment: Step 4C.7 tenant-scoped catalogue search and exact SKU
lookup. Imports, fuzzy matching, AI matching, and frontend remain outside it.
