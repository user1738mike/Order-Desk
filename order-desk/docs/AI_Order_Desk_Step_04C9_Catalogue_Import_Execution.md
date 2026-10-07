# Step 4C.9 — Atomic administrator catalogue imports

## Contract established before implementation

Verified predecessor: Step4C8 commit `42e1b3e`; 448 normal PostgreSQL tests,
100 direct-runtime checks, 23 script tests and all12 concurrency cases passed
without skips. Its bounded pure CSV parser and upload transport remain shared.

POST `/api/v1/workspaces/<uuid>/catalog/imports/` accepts exactly one multipart
`file`, no other form fields or query parameters. Require active session user,
standard CSRF and current active workspace administrator. The URL alone selects
the tenant. Accessible nonadministrators receive 403 with
`You do not have permission to import catalogue items in this workspace.`
Protected authorization precedes key validation, reading bytes, CSV decoding,
receipt inspection and catalogue lookup. Django CSRF can parse multipart earlier;
the inherited actual-byte guard protects that framework path.

Require `Idempotency-Key: <UUID>`; missing/malformed keys return400. Normalize
accepted UUID spellings to the same database UUID. Fingerprint the bounded raw
file bytes with SHA256 and the fixed create-only CSV contract identifier
`catalogue-create-only-csv-v1`. Filename, MIME, session, multipart boundaries and
other transport metadata are excluded. BOM, newline, row-order or other byte
changes represent another request, even when normalized items are equivalent.

Reuse exactly Step4C8's actual1MiB, strict UTF8/BOM CSV, case-sensitive exact
sku/description/is_active headers, 1000 data records, normalization, strict CSV
booleans and existing process field limit. Validate the entire permitted file;
never trust a previous preview. Duplicate normalized SKUs invalidate every
occurrence. Active and inactive existing workspace SKUs conflict; other tenants
can reuse SKUs and keys. Bound error output at100 and item preview at25.

First success returns201, `Idempotency-Replayed: false`, and exactly import_id,
organization_id, mode=create_only, created_count, items, items_truncated.
Items use the seven existing scalar read fields, in original CSV order, with
at most25 entries. Persist this successful payload in the item transaction.
Recursively canonicalize response keys so JSONB storage does not change first
and replay response bytes.

Matching completed workspace/key/fingerprint replay returns200 with
`Idempotency-Replayed: true` and the original stored payload, before CSV parsing
or treating original SKUs as conflicts. Any currently authorized workspace
administrator may replay; preserve the original initiating user. Subsequent
item edits/deactivation do not alter the receipt. Demoted/inactive users cannot
replay. Same workspace/key with different bytes returns409 and changes nothing.
Validation/conflict/database failures roll back the reservation and every item;
a corrected request can reuse a fully rolled-back key.

## Transaction and receipt design

Lock order: existing Organization row lock and fresh authorization first,
then ordinary workspace/key receipt SELECT or savepoint-protected unique
INSERT reservation, then catalogue inserts ordered by normalized SKU. Completed
receipts are immutable; their SELECT FOR UPDATE would invoke the processing-only
UPDATE policy and hide them. Ordinary replay SELECT is safe under the held
organization lock; reservation INSERT and completion UPDATE acquire row locks.
Conflict inspection uses
bounded250-SKU batches. Original CSV row numbering and preview order remain.
One existing write-capable tenant scope owns all SQL, response materialization
and completion. Translate only named known uniqueness errors; unexpected
database failures escape after rollback. Preserve single-create's safe400 for
actual index-size errors. No partial writes, ignore_conflicts, per-row commits,
upserts, unbounded retries, raw-file storage or independent reservations.

CatalogImportReceipt contains UUID identity, protected organization/initiating
user, UUID idempotency key, fingerprint, fixed mode and contract identifier,
processing/completed state, bounded successful JSON payload and creation/
completion timestamps. Organization/key uniqueness is database enforced.
Force RLS restricts runtime reads to active current-tenant administrators and
binds insert tenant/initiator to transaction context. Runtime completion can
update only state, response_payload and completed_at; immutable metadata and
completed rows cannot be changed. Runtime deletion is denied. Bootstrap rerun
restores these restrictions after its general grants. A deferred completion
constraint rejects any processing reservation remaining at commit, including
direct runtime SQL; its owner-bound helper has a fixed search path and no
direct public/runtime execution grant.

The successful JSON payload must be an object and at most8MiB in its database
text representation. This bounds even JSON escaping expansion of a1MiB file;
the application still returns only25 scalar item previews. Immediate constraints
also require the fixed contract/mode, lowercase64-character SHA256, valid state/
timestamp/payload combinations and completion at or after creation.

## Error and retry contract

| Condition | Result |
| --- | --- |
| Missing/malformed Idempotency-Key | 400, `idempotency_key` field error. |
| Upload over1MiB | 413, inherited stable upload error. |
| Multipart/query/encoding/header/structural/record-limit error | 400, inherited error; no durable receipt. |
| Unsupported media | 415 after authorization. |
| Invalid rows or in-file duplicates | 400, detail `The CSV file contains invalid catalogue rows.` plus bounded dry-run-shaped `report`. |
| Existing active/inactive workspace SKU or named native catalogue collision | 409, existing catalogue conflict detail plus bounded `report`; no partial import. |
| Same workspace/key, different fingerprint | 409, detail `This idempotency key has already been used for a different catalogue import.` |
| Known catalogue index-size failure | Existing safe400 `sku` field error. |
| Unexpected database failure | Propagates after complete rollback; never represented as a SKU conflict. |

After an uncertain successful response, retry the exact file/key: a committed
receipt returns its stored body, while a rolled-back attempt may reserve again.
There is no automatic deadlock/serialization retry loop in existing services;
this service preserves that behavior. A client retry uses a fresh tenant
transaction, fresh authorization and the same key/file. Changed bytes after a
committed attempt require a new key. Request shape, byte bounds, session, CSRF
and current role apply equally to replay.

## File responsibilities

| File | Purpose |
| --- | --- |
| `backend/apps/catalog/models.py`, `migrations/0002_catalogimportreceipt.py` | Durable receipt, uniqueness/checks, forced RLS, grants and deferred completion. Catalogue item schema is unchanged. |
| `backend/apps/catalog/import_execution.py` | UUID/fingerprint contract, protected atomic reservation/execution/replay, sorted saves and stored scalar result. |
| `backend/apps/catalog/views.py`, `urls.py` | Thin session/CSRF execution endpoint sharing the inherited bounded upload view. |
| `backend/scripts/bootstrap_database.py` | Restore receipt table and column restrictions after general provisioning. |
| `backend/apps/health/management/commands/check_runtime_role.py` | Refuse unsafe runtime receipt rights. |
| `backend/apps/catalog/management/commands/verify_catalog_rls.py` | Audit receipt owner/policies/grants/constraints/trigger before guarded native fixtures. |
| `backend/apps/catalog/tests/test_import_receipts.py` | Native constraints and commit consistency. |
| `backend/apps/catalog/tests/test_import_execution_contracts.py` | Pure key/fingerprint and native service/savepoint/failure contracts. |
| `backend/apps/catalog/tests/test_import_execute_api.py` | Real multipart/session/CSRF, atomic output and replay. |
| `backend/apps/catalog/tests/test_import_concurrency.py` | Independent connection races, observed locks, rollback and both demotion orders. |
| `backend/apps/catalog/tests/runtime_rls.py` | All preceding checks plus direct restricted-role receipt/execution/concurrency proofs and fixture cleanup. |
| This guide and three checkpoint documents | Contract, actual evidence and exact next action. |

## Verification scope

Preserve mixed external history `7163966` and its unverified order/provisioning
drafts. Use the isolated catalogue foundation plus verified increments in
`order-desk-step4c9`. Apply only intended catalogue receipt migration
`catalog.0002_catalogimportreceipt` on main; do not apply order migrations.
All synthetic uploads, items, receipts and concurrency fixtures stay solely
in disposable `test_orderdesk`. Main verification uses metadata and existing
read-only catalogue HTTP checks. Do not copy or print secrets.

Run native fixture suites sequentially. Established PowerShell commands:

```powershell
Set-Location -LiteralPath 'C:\Users\HomePC\Desktop\Billion1\order-desk'
$verifyCompose = @('--project-directory', (Get-Location).Path,
    '-f', (Join-Path (Get-Location).Path 'compose.yaml'),
    '-f', 'C:\Users\HomePC\Desktop\Billion1\order-desk-step4c9\verification.compose.yaml')
docker compose @verifyCompose config --quiet
docker compose @verifyCompose run --rm manage python manage.py check
docker compose @verifyCompose run --rm manage python manage.py makemigrations --check --dry-run
docker compose @verifyCompose run --rm manage python manage.py migrate catalog --plan
docker compose @verifyCompose run --rm manage python manage.py migrate catalog --noinput
docker compose @verifyCompose run --rm manage python manage.py migrate --check
docker compose @verifyCompose run --rm manage ruff check . /verification-project/scripts
docker compose @verifyCompose run --rm manage ruff format --check . /verification-project/scripts/verify_catalog_api.py /verification-project/scripts/tests/test_verify_catalog_api.py
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_import_receipts apps.catalog.tests.test_import_execution_contracts --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_import_execute_api --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_import_concurrency --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 1
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_update_concurrency apps.catalog.tests.test_create_concurrency apps.accounts.tests.test_login_concurrency apps.organizations.tests.test_concurrency apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_waits_for_lock_and_observes_committed_demotion apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_rechecks_membership_after_waiting_for_revocation --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm --workdir /verification-project manage python -m unittest discover -s scripts/tests -v
docker compose @verifyCompose run --rm dbsetup
docker compose @verifyCompose run --rm rlscheck
docker compose exec -T api python manage.py check_runtime_role
docker compose exec -T api python manage.py verify_catalog_rls # expected main refusal, exit1
python scripts/verify_catalog_api.py # existing local account, catalogue reads only
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/health/live/
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/health/ready/
git diff --check
git diff --cached --check
git status --short
```

The Step 4C.9 foundation was verified in the current checkout while completing
Step 4D.1: 569 normal PostgreSQL tests, 115 catalogue direct-runtime tests,
54 concurrency tests, and 23 standalone script tests passed without skips.
Bootstrap, runtime grants, the main-database guard, and the read-only live
catalogue HTTP verifier passed. The live verifier used a temporary synthetic
account in `test_orderdesk`, removed afterward; its existing-SKU success branch
was unavailable on the empty page but is covered by native tests. The detailed
combined evidence and current commands are in
`AI_Order_Desk_Step_04D1_Draft_Order_Models_RLS.md`. The earlier isolated
worktree commands above record the original Step 4C.9 plan; this final
verification used the current checkout and its complete migration chain.
