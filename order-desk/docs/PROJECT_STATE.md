# Project state

## Editor and terminal diagnostics repaired: 2026-10-07

Before starting the next build increment, inspected the live VS Code Python,
Flake8, Pylint, and Ruff logs. VS Code selected Python 3.13.14 with no Django
or DRF installed. Cumulative logs contained 2,063 Flake8 E501 warnings from
its default 79-column limit, 350 Pylint import errors, 1,154 missing-function
docstring conventions, and Python 3.14 syntax misread by the older interpreter.
These are log totals across repeated checks and historical copies, not a
measurement of the live Problems panel.

Installed workspace-local Python 3.14.8 using pinned uv 0.12.23 and synced the
unchanged backend lock into `Billion1/.venv`. Configured editor import paths,
installed the Ruff extension, and replaced the duplicate Flake8/Pylint editor
checks with the existing project Ruff rules and pinned Ruff 0.16.10. Live logs
confirm the editor selected the new interpreter and launched pinned Ruff.
Historical `order-desk-step*` checkouts, the older root backend draft, and
tool environments are excluded from current editor linting; their source is
preserved. Generated migrations retain the established lint exclusion.

Corrected root workspace tasks: initialization uses the explicit venv Python;
commands run from the active repository; tests use dedicated test settings,
`--keepdb`, and `--noinput`; legacy reset aliases no longer drop databases;
the environment check audits the runtime role without printing passwords;
health requests fail on errors; migration execution depends on a successful
model-drift check. Added a backend lint task with Problems-panel matching.
Changes to task definitions did not execute migrations or resets.

Verification: locked native Ruff lint passed for active backend and scripts;
all 143 checked files passed formatting. All 870 active/historical Python
files parsed under Python 3.14.8. Django system checks passed. Five editor
JSON files and 36 task definitions/dependencies validated, and shell task
commands parsed. No application behavior or locked dependencies changed.
The previous increment's 585-test regression results remain the application
baseline. The live Problems-panel count is not directly available to this
agent; reload VS Code if earlier diagnostics remain cached.

Step 4D.2 was committed externally during this repair as `c00a6ff`; preserve
that history and the editor configuration commit `7993fb9`.

## Active checkpoint: Step 4D.2 verified locally

The bounded read-only draft API is complete in the current checkout: list,
detail, and separate paginated lines under the workspace `draft-orders/`
namespace. All active member roles can read; missing/foreign drafts return
404 after workspace authorization. Headers and lines use scalar allowlists,
fixed 50-row pages, strict query parameters, and deterministic ordering.
Unresolved quantity/matches remain null, decimals remain strings, and stored
catalogue snapshots are preserved. All queries and serialization finish in
the existing read-only transaction-local tenant scope. No draft write route
or migration was added.

Verification on 2026-10-07: 16 focused read contract/API tests, 585 full normal
PostgreSQL tests, and 33 direct-runtime order checks passed without skips.
Ruff lint and format (137 files), Django checks, migration drift/applied-state
checks, restricted runtime role, main-database verifier refusal, and both
health endpoints passed. Real HTTP list/detail/lines and logout passed using
a viewer session against a temporary runtime-role API on `test_orderdesk`.
Its synthetic user/workspace/draft/line and server were removed. The main
database received no synthetic business rows. Details and repeatable native
commands: `AI_Order_Desk_Step_04D2_Read_Only_Order_API.md`.

Changes remain uncommitted; no Git remote is configured. Preserve the existing
MASTER_BUILD_PROMPT edit and historical checkpoints below. Next proposed
increment: a separately specified draft creation API with protected writes;
its request contract and role rules must be documented before implementation.

## Active checkpoint: Step 4D.1 verified locally, Git delivery pending

The Step 4C.9 atomic catalogue import foundation and Step 4D.1 draft-order
models/boundary are present in the current checkout. Step 4C.9 was uncommitted
when Step 4D.1 began, so its implementation was verified as a prerequisite
and its runtime session fixture was repaired. The repository currently has no
Git remote; do not claim a push until one is configured and verified.

Step 4D.1 adds separate manual `DraftOrder`/`DraftOrderLine` models, a supporting
catalogue composite key, two composite tenant foreign keys, forced draft RLS,
column-limited runtime grants, bootstrap preservation, and native tests. There
is no draft-order HTTP API or automatic matching. The local database's zero
existing order/catalogue rows were confirmed before applying the additive
catalogue and order migrations. Synthetic order rows remain only in disposable
`test_orderdesk`.

Actual local verification: 569 normal PostgreSQL tests, 54 concurrency tests,
115 catalogue direct-runtime tests, 31 order direct-runtime tests, and 23
standalone script tests passed without skips. Django checks, model/migration
state, backend/script Ruff gates, bootstrap rerun, runtime role, both main-DB
guard refusals, both health endpoints, and a read-only live catalogue check
against a temporary test-database API passed. The temporary account/workspace
and API were removed. That catalogue was empty, so live existing-SKU success
was unavailable; native tests cover it. Detailed contract and evidence:
`AI_Order_Desk_Step_04D1_Draft_Order_Design.md` and
`AI_Order_Desk_Step_04D1_Draft_Order_Models_RLS.md`.

Next proposed increment: Step 4D.2, a bounded read-only tenant-scoped draft
list/detail API. It must preserve unresolved quantities and matches, use
transaction-local RLS for every serialization query, and add no write route.

## Active checkpoint: Step 4C.9; Step 4C.8 completed

The latest attachments request create-only CSV dry run first, then atomic
execution with durable workspace receipts. Step4C7 is committed as `184910b`;
its 395 normal /86 runtime /23 script baseline and all12 concurrency checks
passed. The current native predecessor search-contract/API baseline passed
40 tests in 7.135s. Git started clean; preserve mixed history `7163966`.

Dry-run contract: multipart file only, admin/session/CSRF, actual file bytes
bounded at1MiB, UTF8/BOM strict CSV with exact sku/description/is_active headers,
1000 data records, errors100/preview25. Create-only duplicates invalidate every
occurrence; existing active/inactive workspace SKUs conflict; other tenants do
not. Use pure creation field rules, read-only scoped conflict batches250, fresh
admin checks before decoding and lookup, and no catalogue mutations. Details
are in AI_Order_Desk_Step_04C8_Catalogue_Import_Dry_Run.md.

Step4C8 is complete: 448 normal PostgreSQL tests (63.732s), 100 direct-runtime
checks (210.025s), 23 script tests (0.651s), 53 focused CSV tests (7.764s),
and all 12 concurrency cases (4.447s) passed without skips. All established
lint/format/system/migration/Compose/bootstrap/grant/role/guard/live-read/health
and whitespace gates passed. Nine code blobs match the isolated tested source.
Committed as `42e1b3e` (`feat: add admin-only catalogue import dry run`). The
current action is the explicitly authorized Step4C9 execution; its protected
atomic receipt/replay contract was documented before code in
AI_Order_Desk_Step_04C9_Catalogue_Import_Execution.md. Schema, service and native
verification are in progress; no Step4C9 pass is claimed before execution.

Use isolated catalogue source
in order-desk-step4c8; synthetic uploads/catalogue rows stay in test_orderdesk.
Main checks stay read-only. Step4C9 later permits only its focused receipt
schema/RLS/grant addition and intended catalogue migrations, no order migrations.

## Completed checkpoint: Step 4C.7

The requested search/exact-SKU increment follows Step 4C.6, now verified and
committed as `490d971`: 355 normal PostgreSQL tests, 75 direct-runtime checks,
19 script tests, all 12 normal concurrency cases, and every established gate
passed. SKU remains immutable through PATCH; no-op timestamps are preserved.

Search contract was documented before implementation in
`AI_Order_Desk_Step_04C7_Catalogue_Search.md`: list page/q/is_active single-value
allowlist, trimmed 1–200-character literal icontains on scoped SKU OR description,
strict lowercase true/false, filtered counts and fixed pages; exact by-sku GET
uses creation normalization and database equality including inactive items.
No dependency/schema/index/policy changes, imports, fuzzy/AI matching, or UI.
Verified in isolated order-desk-step4c7; synthetic catalogue data stays in
test_orderdesk and main verification stays read-only. Actual final results:
395 normal PostgreSQL tests (59.108s), 86 direct-runtime checks (141.039s),
23 script tests (0.790s), 40 focused search checks, all 12 normal concurrency
cases, and every established system/migration/lint/format/security/live/health
gate passed. Normal and runtime suites had no skips. Empty-catalogue live reads
passed with logout; its conditional existing-SKU success check was unavailable,
while native checks verified success. The measured 2,000-row synthetic sample
fetched 50 of 66 matches, serialized without extra SQL, and exact equality used
catalog_org_sku_unique. Timing/plan limits and cleanup evidence are in the guide.

During work an external commit, `7163966` (`Describe what you changed`), recorded
most search source together with earlier order/provisioning/guidance drafts.
Preserve that history. These verification results apply to the catalogue
foundation plus this increment, excluding that mixed commit's unrelated order
code and migrations. The final completion commit has the requested title
`feat: add tenant-scoped catalogue search and SKU lookup`; find its hash in Git.
Its scope is remaining catalogue verification/source and completion documents.

Exact next proposed task: Step 4C.8 administrator-only CSV catalogue validation
and dry run, with no catalogue writes. Actual import execution remains a
separate increment; Step 4C.8 has not been implemented by this checkpoint.

## Active checkpoint: Step 4C.6

Administrator-only PATCH updates/deactivation are implemented and verified.
SKU is immutable in this increment; only description and is_active may change.
The contract was established before implementation in
`AI_Order_Desk_Step_04C6_Catalogue_Updates.md`: protected administrator check
before scoped item lookup/body parsing, locked fresh state, omitted fields
preserved, real changes advance updated_at, successful no-ops preserve it.
No detail GET, PUT, DELETE, schema/dependency change, import, or frontend work.

The committed predecessor is `bdcd551`. Re-establish its actual PostgreSQL
baseline and verify only that foundation plus this increment in the isolated
`order-desk-step4c6` checkout. All synthetic catalogue mutations remain in
test_orderdesk; main-database checks remain catalogue reads. Preserve unrelated
order/provisioning/guidance drafts. Actual results: 355 normal PostgreSQL tests,
75 direct-runtime checks, 19 script tests, 38 focused update cases, and all 12
normal concurrency cases passed. System, migration, lint/format, bootstrap,
grant/role/guard, live read, health and whitespace gates passed. Committed as
`490d971` (`feat: add admin-only catalogue updates and deactivation`); all nine
code blobs matched the isolated verification source. Exact next action was
the user's requested Step 4C.7, now active above.

## Active checkpoint: Step 4C.5

Administrator-only catalogue creation is implemented and fully verified,
following committed Step 4C.4 (`3f1c0d3`). The approved POST contract is JSON-only input (`sku`,
optional `description`, optional `is_active`), protected administrator checks
before validation, HTTP 201 scalar output, and HTTP 409 for the known
workspace/SKU uniqueness violation. The actual unique-index size failure has
a safe field-keyed 400; no arbitrary model text cap or schema change was added.
Standard CSRF on the underlying HttpRequest preserves authorization before
DRF JSON parsing. Insertion and scalar output complete inside the owned write
scope using the existing organization-first locking/demotion convention.

Actual results on 2026-10-06: 317 normal PostgreSQL tests, 60 direct-runtime
RLS/HTTP checks, 19 standalone script tests, all four new creation races, and
all four original races passed without skips. System, migration, lint/format,
bootstrap/grant, role, main-database guard, health, and live read gates passed.
Detailed commands/results: `AI_Order_Desk_Step_04C5_Catalogue_Creation.md`.

Verify only the committed catalogue foundation plus this increment in the
isolated `order-desk-step4c5` checkout; preserve unrelated order/document,
provisioning, and guidance drafts. All synthetic catalogue creation belongs in
`test_orderdesk`. Main-database live verification remains limited to reads.

Step 4C.5 is committed as `bdcd551` (`feat: add admin-only catalogue item creation`).
All 11 committed code files exactly matched the isolated verified source;
the twelfth file is this increment's contract and verification guide. Final
Git status contains only preserved unrelated drafts and local checkpoint files,
with an empty index. No new dependency or migration is included.

Exact next action: Step 4C.6 administrator-only updates/deactivation, following
the next explicit increment request. Hard deletion and
imports remain outside that next increment. No unrelated order draft is verified
or authorized by these results.

## Active checkpoint: Step 4C.4

The latest request scopes this increment to the read-only catalogue API. Step
4C.3 is committed as `9a5f2de`. Its actual normal PostgreSQL baseline is 221
tests, all passing on 2026-10-05 after restoring the dedicated test database's
established ownership and grants. Catalogue creation remains Step 4C.5.

The read API and its verification are complete: 13 contract tests, 22 native
API tests, the final 256-test normal PostgreSQL suite, all four concurrency
cases, 47 direct-runtime RLS/HTTP checks, 18 standalone script tests, and live
session/health/role/migration/lint gates passed. Existing uncommitted
order/source-document changes are preserved and excluded from this increment;
the older completion claims below are not verification evidence for those drafts.
No order migrations or test catalogue rows in the main database are authorized
by this increment. An isolated checkout verifies only Step 4C.3 plus Step 4C.4.

Step 4C.4 is committed as `3f1c0d3` (`feat: add tenant-scoped read-only catalogue API`).
Exact next action: Step 4C.5 administrator-only catalogue creation in the user's
next increment; preserve and review unrelated drafts before adopting them. Detailed
commands and evidence are in `AI_Order_Desk_Step_04C4_Read_Only_Catalogue_API.md`.

## Current checkpoint

- Django backend foundation verified and in use.
- Local PostgreSQL and restricted database roles are configured.
- Workspace membership model, access checks, and session auth are implemented.
- Catalogue tenant boundary and row-level security checks are in place.
- Purchase-order intake is implemented with workspace ownership checks, duplicate-prevention rules, review-state transitions, and approval tracking.
- The workspace-scoped order API layer is implemented and verified for list/create, detail access, line creation, and review/approval actions.
- Source-document intake is now supported as a tenant-scoped order document model and service, with file metadata captured and tied to the owning workspace and order.
- The project is now ready to move to the next useful domain increment beyond intake: document review and extraction workflows that turn uploaded source documents into structured review data while preserving the current tenant boundaries.

## Current working assumptions

- Each distributor workspace owns its own purchase-order data and uploaded documents.
- Membership and workspace access remain the authorization boundary.
- Review and approval are tenant-scoped actions performed by active workspace members with reviewer/admin access.
- Order document intake remains tied to a valid workspace order and revalidates ownership on each write.

## Exact next action

Move to the next narrow increment beyond intake: source-document review and extraction workflows such as document validation, OCR/extraction review metadata, and a tenant-scoped review record for uploaded PDFs/CSVs.
