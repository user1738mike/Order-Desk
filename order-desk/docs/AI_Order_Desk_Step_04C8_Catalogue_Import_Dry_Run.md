# Step 4C.8 — Administrator CSV catalogue dry run

## Contract established before implementation

POST `/api/v1/workspaces/<uuid>/catalog/imports/dry-run/` accepts
`multipart/form-data` with exactly one `file`, no additional form fields, and
no query parameters. Session authentication and standard CSRF apply; send the
rotated `X-CSRFToken`. The active URL workspace is the only tenant selector.
Fresh administrator authorization precedes CSV decoding, row validation, and
catalogue inspection. Reviewers/viewers receive 403 with
`You do not have permission to validate catalogue imports in this workspace.`
Existing generic inaccessible-workspace and authentication responses remain.

The transport installs a narrow upload handler before authentication, because
Django's CSRF check can parse multipart POST data. It bounds actual aggregate
file chunks at 1,048,576 bytes, independently of Content-Length, then closes
in-progress upload files and raises a stable 413. A final bounded read accepts
at most limit + one bytes. Normal upload spool thresholds and request/form
limits remain unchanged; they are not maximum permitted file size settings.
Other Django-managed temporary files follow normal request cleanup.

Decode strict UTF-8, accepting a leading BOM. Require exactly case-sensitive
`sku`, `description`, `is_active` headers in any order. Support standard strict
CSV quotes, commas, escaped quotes, CRLF/LF and multiline descriptions. Header
is logical record 1; every subsequent parsed record increments row_number,
including skipped completely empty `[]` records. A three-empty-column record
is data and invalid for blank SKU. Require at least one nonempty data record;
reject structural/encoding/header/column-count/parser failures with 400 and a
bounded logical location where available. Retain the process's existing CSV
field limit; never mutate process-global parser state per request.

Maximum 1,000 data records; exceeding it rejects the whole file with 400.
Maximum 100 returned errors and 25 ready preview items. Validate every permitted
record even when output is truncated. Uploaded filename/MIME are metadata only;
never use them as a path or evaluate uploaded values as executable formulas.

Reuse creation's pure serializer/field validation: trim SKU edges, preserve
case/punctuation/leading zeroes, preserve description whitespace/newlines, and
use actual model field limits (SKU/description are unbounded TextFields).
CSV is_active accepts exactly `true`, `false`, or blank for creation's true
default. Other values are invalid. Duplicate normalized SKUs invalidate every
occurrence, including the first; equality follows the existing deterministic
PostgreSQL collation without invented case folding. Existing active or inactive
workspace SKUs conflict. A SKU existing only in another workspace is eligible.

Structurally valid CSV returns 200 even with invalid rows. Exact response keys:
`dry_run` true, `mode` create_only, `can_import`, `summary`, `errors`,
`errors_truncated`, `preview`, `preview_truncated`. Summary counts rows_total,
rows_ready, rows_invalid from the complete bounded file. Each error has
row_number, field, stable code and bounded message. Codes include invalid_value,
duplicate_file_sku, existing_workspace_sku. Preview entries contain row_number,
normalized sku, preserved description and bool is_active, ready rows only.

```csv
sku,description,is_active
000-Part-A,"Washer, stainless",true
Part-B,"First line
second line",
```

`can_import` means this advisory snapshot has no validation/conflict errors.
It reserves no SKU and cannot guarantee future execution or physical index fit.
Actual import execution must revalidate authorization, bytes and database state.
This increment has no catalogue writes, reservations, receipts, locks, file
storage, import execution, upserts, dependencies, schema changes, or frontend.

## Security and files

The dry-run service owns the existing READ ONLY tenant transaction. It checks
fresh administrator status before decoding and again before conflict queries.
Explicit organization-filtered equality queries use batches of at most 250
unique normalized SKUs; results and final report materialize inside scope.
There is no per-row relation/uniqueness query or serializer save. Independent
FORCE RLS remains unchanged; test-only missing-filter queries prove isolation.

| File | Responsibility |
| --- | --- |
| `backend/apps/catalog/imports.py` | Bounded pure CSV parsing/creation validation, normalized duplicates, full-file bounded report. |
| `backend/apps/catalog/import_services.py` | Fresh admin read scope, bounded tenant conflicts, materialized report. |
| `backend/apps/catalog/uploads.py` | Pre-CSRF byte guard, multipart shape, bounded read and upload cleanup. |
| `backend/apps/catalog/selectors.py` | Lazy scoped batch equality lookup. |
| `backend/apps/catalog/views.py`, `urls.py` | Session/CSRF multipart POST endpoint. |
| `backend/apps/catalog/tests/test_import_contracts.py` | Pure parsing, validation, duplicates, bounds and reporting. |
| `backend/apps/catalog/tests/test_import_dry_run_api.py` | Native sessions/upload/scope/no-mutation integration. |
| `backend/apps/catalog/tests/runtime_rls.py` | Direct restricted-runtime HTTP/RLS/read-only/cleanup proof. |
| This guide and three checkpoint documents | Contract, actual results, next approved execution increment. |

## Verification scope and commands

Preserve the externally committed order/provisioning drafts in `7163966`.
Use the isolated `order-desk-step4c8` checkout of catalogue foundation `490d971`
plus the verified catalogue code from `184910b` and this increment. No unrelated
order migrations are applied. Reuse existing Compose project/volume/secrets
without copying or printing `.env`; synthetic catalogue data stays exclusively
in `test_orderdesk`. Main verification remains catalogue reads and metadata.

```powershell
Set-Location -LiteralPath 'C:\Users\HomePC\Desktop\Billion1\order-desk'
$verifyCompose = @('--project-directory', (Get-Location).Path,
    '-f', (Join-Path (Get-Location).Path 'compose.yaml'),
    '-f', 'C:\Users\HomePC\Desktop\Billion1\order-desk-step4c8\verification.compose.yaml')
docker compose @verifyCompose config --quiet
docker compose @verifyCompose run --rm manage python manage.py check
docker compose @verifyCompose run --rm manage python manage.py makemigrations --check --dry-run
docker compose @verifyCompose run --rm manage python manage.py migrate --check
docker compose @verifyCompose run --rm manage ruff check . /verification-project/scripts
docker compose @verifyCompose run --rm manage ruff format --check . /verification-project/scripts/verify_catalog_api.py /verification-project/scripts/tests/test_verify_catalog_api.py
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_import_contracts apps.catalog.tests.test_import_dry_run_api --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 1
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_update_concurrency apps.catalog.tests.test_create_concurrency apps.accounts.tests.test_login_concurrency apps.organizations.tests.test_concurrency apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_waits_for_lock_and_observes_committed_demotion apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_rechecks_membership_after_waiting_for_revocation --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm --workdir /verification-project manage python -m unittest discover -s scripts/tests -v
docker compose @verifyCompose run --rm dbsetup
docker compose @verifyCompose run --rm rlscheck
docker compose exec -T api python manage.py check_runtime_role
docker compose exec -T api python manage.py verify_catalog_rls # expected refusal exit 1 on main
python scripts/verify_catalog_api.py # existing local account; never uploads/imports
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/health/live/
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/health/ready/
git diff --check
git diff --cached --check
git status --short
```

Native fixture suites run sequentially. Established baseline: verified Step4C7
395 normal tests, 86 runtime checks, 23 script checks and all12 concurrency cases.
Actual final results: 448 normal PostgreSQL tests (63.732s), 100 direct-runtime
checks (210.025s), 23 script checks (0.651s), 53 focused CSV contract/API tests
(7.764s), and all 12 established concurrency cases (4.447s) passed without
skips. Lint and formatting (110 files), system and migration checks, Compose
validation, bootstrap rerun, restricted runtime role and catalogue grants,
main-database refusal guard, whitespace and both health endpoints passed.
Live empty-catalogue reads passed and logged out; the conditional existing-SKU
success case was unavailable there and is covered by native tests. No CSV was
executed against the main database. All nine changed code blobs matched the
isolated tested source.

Definition of Done completed: bounded strict CSV/multipart contract, full-file report,
admin-before-CSV validation, unchanged catalogue rows/timestamps, independent
runtime isolation, clean context/files on failures, all established gates,
and scoped commit `feat: add admin-only catalogue import dry run`.

Next explicitly requested increment: Step4C9 atomic create-only execution with
durable tenant-scoped receipts, current protected authorization and safe replay.
