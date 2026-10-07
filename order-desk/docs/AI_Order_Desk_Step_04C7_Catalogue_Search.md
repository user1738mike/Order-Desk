# Step 4C.7 — Tenant-scoped catalogue search and exact SKU lookup

## Contract established before implementation

Build on verified Step 4C.6. Preserve creation, immutable-SKU partial updates,
deactivation/reactivation, and forced RLS. Add read-only literal substring
search/status filtering to the collection, and a separate exact SKU route.
No imports, fuzzy/AI matching, ranking, regex/wildcard language, full-text
search, frontend, extensions, dependencies, migrations, or speculative indexes.

Both paths require an authenticated active session user and active membership
in an active URL workspace. Administrators, reviewers, and viewers retain read
access. Safe GET/HEAD require no CSRF token. Workspace authorization is refreshed
inside the existing read-only tenant transaction before detailed query errors
or catalogue selection. URL workspace is the only tenant selector; forged
headers/cookies/body fields/session preferences cannot override it.

### Collection

`GET /api/v1/workspaces/<workspace-uuid>/catalog/items/`

Accept only `page`, `q`, and `is_active`, each at most once. Unknown/repeated
parameters return field-keyed 400. Reject tenant identity, ordering, page size,
and extra filters. POST/PATCH retain their independent rejection of all query
parameters; adding read filters does not loosen writes.

When supplied, trim `q` and require 1–200 normalized characters. Match it as one
literal case-insensitive substring of SKU OR description using ORM `icontains`.
Keep organization filtering outside and ANDed with the grouped OR. `%`, `_`,
quotes, and backslashes remain literal via Django's parameterized LIKE escaping;
never interpolate input into SQL. PostgreSQL's installed collation determines
comparison behavior; universal Unicode case folding is not promised.

`is_active` accepts exactly lowercase `true` or `false`. Other spellings, blank,
numeric, or repeated values return 400. Omission retains both active/inactive
rows. Omitted `q` retains the original unfiltered behavior.

Apply filters in PostgreSQL before count/pagination. Preserve ordering by SKU,
then UUID, fixed 50-item pages, scalar item serializer, and envelope
`count`, `next`, `previous`, `results`. Count is the filtered tenant result count.
Pagination links preserve the workspace route and supplied accepted parameters.
Existing invalid-page 404 semantics remain. Valid no-match search returns 200
with the exact empty first-page envelope.

```text
GET .../catalog/items/?q=washer
GET .../catalog/items/?is_active=false
GET .../catalog/items/?q=washer&is_active=true&page=2
```

### Exact SKU

`GET /api/v1/workspaces/<workspace-uuid>/catalog/items/by-sku/?sku=PART-001`

Accept exactly one required `sku` and no other parameter. Reject missing,
repeated, empty/whitespace-only, or invalid text with 400. Reuse creation's
surrounding-whitespace normalization, preserving case, punctuation, and leading
zeroes. The model SKU TextField has no `max_length`; do not invent a cap or
confuse the physical insertion-index size boundary with a lookup character cap.

Use organization AND SKU equality under the existing database uniqueness and
collation semantics, without case-insensitive equality. Authorized no-match
returns 404 `{"detail":"Not found."}`. Another workspace's matching SKU never
affects this response. Include inactive matches. Return one seven-field scalar
item object with 200, never a pagination envelope. GET/HEAD/OPTIONS only; no
write handlers. Static `by-sku` routing precedes the UUID PATCH item route.

Lookup follows normalized writes: legacy stored SKUs with edge whitespace are
preserved by PATCH but do not receive alternate lookup normalization. List
reads still expose their actual stored value. Do not rewrite historical rows.

## Transaction, RLS, and performance boundary

Validate queries, select/filter/count/page/lookup, and materialize serializers
inside `tenant_scope` read mode. No lazy results or relation queries escape.
Keep explicit organization filtering plus independent FORCE RLS. Test-only
unfiltered search/exact queries prove database protection under direct
`orderdesk_app`; never add a production bypass switch. Exceptions restore clean
transaction-local identity. Existing write lock/demotion behavior stays intact.

Inspect the actual organization/SKU unique index and query plans on disposable
synthetic rows. Measure database filtering, fetched page size, equality-index
path, and absence of per-item relation queries. Substring predicates may scan
tenant rows; ordinary B-tree indexes do not make every substring search fast.
Do not equate small local plans with production latency guarantees. Document
actual plan/cardinality observations and measured limits without adding indexes.

## Files

| File | Responsibility |
| --- | --- |
| `backend/apps/catalog/query_params.py` | Separate strict list/exact query normalization and full-collection duplicate validation. |
| `backend/apps/catalog/selectors.py` | Lazy scoped literal substring/status selection and exact SKU equality selection. |
| `backend/apps/catalog/pagination.py` | Retain 50-item bounds and numeric-page behavior while accepting the list contract. |
| `backend/apps/catalog/views.py` | Read-scope list integration and scalar exact-lookup GET/HEAD. |
| `backend/apps/catalog/urls.py` | Static lookup route with catalogue namespace, preserving UUID PATCH routing. |
| `backend/apps/catalog/tests/test_search_contracts.py` | Query, normalization, literal predicate, and pagination-link contracts. |
| `backend/apps/catalog/tests/test_search_api.py` | Native PostgreSQL sessions/search/filter/lookup/isolation/materialization coverage. |
| `backend/apps/catalog/tests/test_read_contracts.py` | Deliberately update obsolete supported-filter rejection while retaining other protections. |
| `backend/apps/catalog/tests/test_read_api.py` | Deliberately adapt supported list-filter regression expectations. |
| `backend/apps/catalog/tests/runtime_rls.py` | Preserve predecessor checks and extend direct-app/unfiltered read isolation proof. |
| `scripts/verify_catalog_api.py` | Existing read-only session verifier extended for valid filters and available exact matches. |
| `scripts/tests/test_verify_catalog_api.py` | Live verifier origin/link/filter/empty/session cleanup guards. |
| `docs/AI_Order_Desk_Step_04C7_Catalogue_Search.md` | Contract, file responsibilities, actual measurements/gates, Definition of Done. |
| `docs/PROJECT_STATE.md`, `docs/MASTER_BUILD_PROMPT.md`, `docs/ROADMAP.md` | Completion checkpoint, verification scope, and the proposed read-only CSV increment. |

## Windows/Docker verification

Use a checkout containing only the committed foundation plus this increment.
The local isolated checkout and untracked override reuse existing Compose
configuration/volume; no `.env` is copied or displayed and no unrelated order
migration is applied.

During this increment Git HEAD moved to the externally created mixed commit
`7163966` (`Describe what you changed`). That commit includes the search core
and previously unrelated order/provisioning/guidance drafts. Preserve its
history. The verification checkout remains the `490d971` catalogue foundation
plus this increment's code, without adopting those order migrations or broader
drafts. The full normal-suite total below applies to that scoped checkout;
it is not verification of the mixed commit's unrelated order implementation.

```powershell
Set-Location -LiteralPath 'C:\Users\HomePC\Desktop\Billion1\order-desk'
$verifyCompose = @(
    '--project-directory', (Get-Location).Path,
    '-f', (Join-Path (Get-Location).Path 'compose.yaml'),
    '-f', 'C:\Users\HomePC\Desktop\Billion1\order-desk-step4c7\verification.compose.yaml'
)
docker compose @verifyCompose config --quiet
docker compose @verifyCompose run --rm manage python manage.py check
docker compose @verifyCompose run --rm manage python manage.py makemigrations --check --dry-run
docker compose @verifyCompose run --rm manage python manage.py migrate --check
docker compose @verifyCompose run --rm manage ruff check . /verification-project/scripts
docker compose @verifyCompose run --rm manage ruff format --check . /verification-project/scripts/verify_catalog_api.py /verification-project/scripts/tests/test_verify_catalog_api.py
docker compose @verifyCompose run --rm --workdir /verification-project manage python -m unittest discover -s scripts/tests -v
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_search_contracts --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_search_api --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 1
docker compose @verifyCompose run --rm manage python manage.py test apps.catalog.tests.test_update_concurrency apps.catalog.tests.test_create_concurrency apps.accounts.tests.test_login_concurrency apps.organizations.tests.test_concurrency apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_waits_for_lock_and_observes_committed_demotion apps.organizations.tests.test_tenant_transactions.TenantTransactionTests.test_write_scope_rechecks_membership_after_waiting_for_revocation --settings=config.settings.test --keepdb --noinput -v 2
docker compose @verifyCompose run --rm dbsetup
docker compose @verifyCompose run --rm rlscheck
# Optional local, untracked measurement artifact; guarded synthetic fixtures only:
Get-Content -LiteralPath 'C:\Users\HomePC\Desktop\Billion1\order-desk-step4c7\query_plan_probe.py' -Raw -Encoding UTF8 | docker compose @verifyCompose run --rm -T rlscheck python -
```

Native suites and runtime fixtures share test_orderdesk and run sequentially.
Live main-database verification stays read-only and accepts empty catalogues;
when an accessible normalized SKU already exists, exercise its exact lookup
without printing catalogue values. Its created session is always logged out.
The existing temporary empty-workspace/control-user fixture may automate live
reads, with an in-memory credential and exact cleanup; never seed catalogue
items in the main database just to demonstrate lookup.

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

## Actual results and Definition of Done

Committed predecessor `490d971` was verified immediately before this increment:
355 normal PostgreSQL tests (53.615s), 75 direct-runtime checks (93.112s), and
19 script tests (0.707s), with no skips. Its 38 focused update checks and all
12 normal concurrency cases also passed. All nine code files in that commit
matched the isolated source used in verification.

Actual Step 4C.7 results on 2026-10-06:

| Gate | Observed result |
| --- | --- |
| Focused query contracts and native search/lookup API | 40 tests, 5.418s, PASS. |
| Full scoped normal PostgreSQL suite | 395 tests, 59.108s, PASS, no skips. Earlier run also passed in 68.662s; reran after correcting the preference test to use `SELECTED_WORKSPACE_KEY`. |
| All established normal concurrency cases | 12 tests, 4.030s, PASS, no skips; four update, four create, and four authentication/workspace races. |
| Direct runtime RLS/HTTP suite | 86 checks, 141.039s, PASS, no skips; all 75 predecessor methods preserved and 11 new search/lookup checks. |
| Standalone script tests | 23 tests, 0.790s, PASS. |
| Django system / migration drift / pending foundation migrations | No system issues, no model changes, migration check exit 0. No order migrations applied. |
| Ruff / formatting / Compose configuration | Backend and scripts PASS; 105 backend and changed-script files already formatted; Compose config PASS. |
| Bootstrap rerun / boundary metadata | PASS; direct runtime owner/FORCE RLS/five policies/grants audit PASS. Separate main metadata audit confirmed ownership, forced RLS, SELECT/INSERT/UPDATE only and denied DELETE/TRUNCATE/REFERENCES/TRIGGER/MAINTAIN after bootstrap. |
| Main database guard / runtime role | Expected refusal exit 1 (`Refusing to populate anything except test_orderdesk.`); main runtime role restricted. |
| Extended live HTTP verifier | PASS with an empty accessible catalogue, real login/rotated CSRF/logout 204, valid search/status requests, strict query failures, exact absence/HEAD and cache checks. No catalogue rows created. Temporary control identities removed exactly. |
| Live exact-success availability | No normalized existing SKU in the inspected empty page; conditional success check explicitly skipped. Native API/runtime tests exercise success including inactive/overlapping SKUs; offline guard tests verify encoded existing-SKU GET/HEAD. |
| Health | Both live and ready returned HTTP 200 with `status: ok`. |
| Whitespace / reviewed scope | PASS; final catalogue code compared to the isolated verified source before commit. |

The live script prints query names with redacted values on success/failure,
validates retained filters before following pagination links, and creates no
catalogue fixtures or mutation requests. Its POSTs are authentication only.

### Measured database plans

The untracked local probe ran directly as `orderdesk_app` in a read-only
`test_orderdesk` tenant scope after all native suites. Its separate restricted
maintenance alias added 1,000 synthetic catalogue rows per organization with
overlapping SKUs, plus the existing three fixture rows. It analyzed test-table
statistics, executed real bound selectors and `EXPLAIN ANALYZE BUFFERS`, and
verified removal of its exact catalogue/workspace/membership/user fixture IDs.
No planner settings, indexes, policies, grants, or production data changed.

Observed database: PostgreSQL 18.6, UTF8, libc `en_US.utf8`; SKU uses the default
deterministic collation. Native comparison tests use the database's own UPPER/
LIKE result instead of Python case folding. Existing indexes were exactly the
UUID primary key, organization foreign-key B-tree, and unique
`catalog_org_sku_unique (organization_id, sku)` B-tree.

For `q=needle&is_active=true`, PostgreSQL counted 66 tenant matches and fetched
50 rows. Count plus page used two SQL queries (10.548ms wall time in this one
local observation); scalar page serialization issued zero additional queries.
The page plan used the organization bitmap index/heap scan over 1,002 tenant
rows, rejected 936 by filtering, sorted the 66 matches, and applied LIMIT 50.
Measured page execution was 1.189ms; its row estimate was 1 versus 66 actual.

The exact inactive `PLAN-00042` lookup returned the authorized organization's
item with one fetch query and zero serialization queries. Its LIMIT/ordering
plan used `catalog_org_sku_unique`, returned one catalogue row, and measured
0.099ms execution. RLS membership checks remained present in both plans.

These are single warm-cache measurements (zero shared blocks read), on a small
synthetic local sample, excluding HTTP latency. They demonstrate database-side
filtering, bounded row fetching, independent policy evaluation, and the existing
equality index path. They do not establish production throughput. Substring
filtering still inspected tenant rows and the estimate understated selectivity.
Before tuning larger catalogues, repeat with realistic tenant sizes, match
selectivity, and concurrency; measure count and page independently. No scaling
blocker was demonstrated by this sample and no speculative index was added.

Definition of Done: strict separate read query contracts, literal grouped
tenant search, exact normalized case-preserving SKU equality, filtered count
and fixed pagination, retained links/status behavior, read-scope materialization,
independent runtime RLS proof, unchanged mutation/concurrency behavior, measured
plan observations, all established gates, no dependencies/schema/grant changes,
and a reviewed scoped commit. All execution gates above passed; the final
completion commit uses the requested title:
`feat: add tenant-scoped catalogue search and SKU lookup`.

The externally committed search core remains in `7163966`. The completion
commit contains the remaining runtime/API-test/verifier changes and this guide
plus the three checkpoint files; it does not restage or rewrite unrelated order
work. Resolve its hash from `git log -1 --format=%H` after committing.

Next proposed increment: Step 4C.8 administrator-only CSV catalogue import
validation and dry run, reporting proposed changes without writing catalogue
rows. Actual import execution belongs to a separate verified increment.
