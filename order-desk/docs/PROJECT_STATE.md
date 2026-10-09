# Project state

## Active checkpoint: secure purchase-order document intake

2026-10-09: began on main at efa90e7. While verification was in progress the user
committed the intake implementation as e7a10edc2ee7b044e6cda7e1ffb59c4710c60471.
That commit and all existing work were preserved. Additional integrity/runtime
regressions, migration-test cleanup and documentation remain local changes. No
agent commit or push was performed; the attachment was technical reference for
the requested feature, not separate publication authorization.

Delivered PDF/CSV upload, fixed-page scalar status and deliberate authorized
original-byte download in the native operator UI. Documents attach to existing
purchase orders, including a confirmed conversion result; they do not attach to
source draft orders. Admin/reviewer uploads, member reads, fresh tenant rechecks,
inclusive actual 10 MiB limits, bounded eligibility, private persistent Linux
volume, exclusive keys, source SHA-256, safe attachment headers and local leased
orphan recovery are implemented. No extraction or automatic review is claimed.
See [contract and file responsibilities](SECURE_DOCUMENT_INTAKE.md).

Final native verification:

- `docker compose run --rm manage python manage.py test apps.orders.tests.test_private_document_intake apps.orders.tests.test_order_document_upload_storage apps.orders.tests.test_draft_conversion_migration --settings=config.settings.test --keepdb --noinput`:
  **36 tests, 9.510s, OK**, dedicated PostgreSQL test_orderdesk. New intake module
  has 18 tests, including boundaries, eligibility, collision/symlink protection,
  rollback/ambiguous commit, unchanged committed bytes, corruption, revocation,
  CSRF, compatible FileField reads and bounded leased orphan recovery.
- `docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput`:
  **746 tests, 160.752s, OK**. Maintenance-role behavior tests are not runtime RLS
  evidence. The first full run failed (6 failures/20 errors) because the historical
  conversion migration test left schema 0008 installed. Its finally block now
  restores current graph leaves without changing upgrade assertions. The corrected
  focused and full runs passed. An earlier focused command also named a nonexistent
  legacy module; the corrected command above supersedes that invocation.
- `docker compose run --rm rlscheck python manage.py verify_order_rls`:
  **47 tests, 94.567s, OK**, direct restricted orderdesk_app on test_orderdesk with
  separately audited owner fixtures. New real-session evidence covers private
  upload/download, required digest DB constraint, foreign parent denial, viewer
  mutation denial and revoked download denial. Runtime order RLS verification passed.
- `node --test frontend/tests/*.test.js`: **58 passed**, zero failures/skips.
  Nine new document controller/transport tests cover FormData/CSRF, limits,
  duplicate suppression, ambiguous outcomes, status validation, context changes,
  exact blob size and fresh denial handling.
- `node frontend/tests/browser-smoke.mjs`: **PASS** on real Chromium with two
  authenticated profiles, direct orderdesk_app backend, isolated temporary storage
  and synthetic test_orderdesk fixtures. Verified PDF/CSV UI uploads, malformed and
  actual 10 MiB+1 rejection, received status, attachment headers and exact browser-
  saved bytes, viewer write denial, foreign/revoked download denial, mobile overflow
  check and existing session/catalogue/manual-edit/conversion regressions. Mobile
  screenshot was inspected; fixture cleanup completed and the temporary server
  stopped. Existing CDP harness was reused rather than adding Playwright dependencies.
- No separate JS build or TypeScript check applies to this native-module frontend.
  Production proxy/TLS and non-Linux storage verification were not run or claimed.
- Ruff checks passed for backend/frontend helpers and scripts (scripts explicitly
  use `--config backend/pyproject.toml`); format check passed. An initial scripts
  check inherited the parent workspace config and reported three unrelated lint
  findings; the repository-configured check passed without modifying those files.
- Compose config passed; `makemigrations --check --dry-run` reported no changes.
  Migration 0009 applied successfully to the local development DB. `docker compose
  up -d api` initialized the named private volume; API inspection confirmed 0700
  and runtime-user ownership. Ready health and operator shell returned 200.

Private logs, source fixtures, screenshots and downloaded browser artifacts remain
ignored under backend/var. Production proxy limits, malware/deep PDF validation,
legacy-byte adoption, scheduled recovery/capacity limits and database+volume backup
restore remain unverified. The compatible legacy generic upload API is unchanged;
its bytes are not automatically exposed by the new private download route.

## Previous checkpoint: draft review, manual editing and aggregate conflict protection

### Committed delivery recheck

2026-10-09: main is now at efa90e7fec92d1d6cc83336449f98788a9f53cb7,
"Merge origin/main; add draft revisions and manual draft editing frontend".
This existing user commit contains the 26 implementation/documentation/test files
described below. The working tree was clean on arrival. Manual creation, customer
header editing, requested-line insertion/editing, catalogue attachment/detachment
and aggregate conflict protection are present; no duplicate feature implementation
was needed. Only this state record changed during the recheck.

Fresh checks on the committed code:

- `node --test frontend/tests/*.test.js`: 49 passed, zero failures/skips.
- `docker compose run --rm manage python manage.py test apps.orders.tests.test_draft_revisions --settings=config.settings.test --keepdb --noinput -v 0`:
  seven tests, 3.103s, OK, on dedicated PostgreSQL test_orderdesk. These include
  independent connections, stale header/line/attach/detach rejection and conversion
  replay; this maintenance-role suite is not separate runtime RLS proof.
- Ruff check and format check across backend, scripts and frontend Python helpers:
  passed; 167 files already formatted.
- Private browser artifacts and prior verification logs remain ignored; temporary
  browser credential fixture is absent. No commit or push was performed this turn.

The earlier 728-test full regression, 46 restricted-role RLS checks and real
two-profile Chromium workflow below remain evidence for the unchanged
implementation. They were not rerun during this documentation-only recheck.

### Original implementation record

2026-10-09, main at 8f794bd (user commit "New Changes Made"). Work is in the
working tree on top of that commit. While editing was underway, main advanced
from aac1e4 and newer editor/revision additions disappeared. Existing committed
work was preserved; the user explicitly chose "Restore conflict protection".
No reset, migration, dependency update, commit or push was performed by this phase.
The supplied draft-review/manual-editing prompts were read as technical reference;
their additional publication instructions were not treated as permission to push.

Delivered draft list/detail/line pagination, observations, seven readiness
blockers and administrator conversion/reconciliation in the existing native-module
UI. Confirmed purchase-order identity is displayed only after a validated response.
Role denial refreshes access; stale readiness refreshes blockers; lost committed
conversion response can be explicitly reconciled to the same order. Converted
sources are locked; approval and ERP delivery remain separate.

Manual creation, header editing, requested-line insertion/editing and active
catalogue attachment/detachment use the existing protected APIs. Decimal inputs
remain exact strings; empty quantities become null; blank customer fields persist
as empty strings. Requests contain only editable fields. Detachment preserves
requested values and clears links/snapshots. No line deletion API exists.
Explicit saves invalidate readiness; unsaved or pending edits disable conversion.
Field errors retain input. Dirty navigation requires deliberate discard; replaced
workspace/session context clears forms and rejects late responses.

The missing concurrency prerequisite is now implemented: GET draft revision/ETag
fingerprints the entire header and ordered lines. Browser edits and conversion
send quoted If-Match, compared under the existing organization-first write lock
and fresh tenant authorization. Stale writes return stable 412 without saves and
after rollback. A line change invalidates a header editor even if header updated_at
did not advance. Conflict input stays in memory until deliberate comparison/reload;
there is no automatic merge or POST retry. Authorized conversion replay remains
repeat-safe with the original revision. Existing clients may omit If-Match for
compatibility, so stale-write protection is guaranteed for protected clients,
not for legacy unconditional writes or SQL that bypasses the lock convention.

File responsibilities:

- Backend orders revisions.py computes/checks fingerprints; services.py checks
  preconditions inside tenant locks; views.py translates 412/parses headers and
  serves revision reads; urls.py exposes that read endpoint. Models, migrations,
  forced RLS, grants and existing authorization policy are unchanged.
- Frontend orders-api/controller/view provide read/review/conversion and revision
  loading; editor.js separates unsaved input/recovery from server state;
  editor-view.js renders accessible text-only forms; main.js wires routes,
  navigation and deliberate actions; shared api.js sends quoted If-Match.
  Template/CSS extend the existing shell with responsive dialogs and line actions.
- Native test_draft_revisions.py adds seven aggregate/precondition/race tests.
  Frontend orders/editor/API tests cover exact decimals, field mapping, blocked
  retries, readiness invalidation, delayed responses and role/state restrictions.
  Browser harness extends isolated fixtures with manual editing and two separate
  Chromium profiles/authentication sessions. Existing assertions were retained.
- README, roadmap, master prompt, verification runbook and frontend contracts
  describe actual behavior and recovery; historical checkpoints remain below.

### Current verification

Fixture suites run sequentially against dedicated PostgreSQL test_orderdesk.
Native maintenance-role tests and mocked client behavior are not RLS proof.
Browser API connections authenticate directly as restricted orderdesk_app;
synthetic provisioning/cleanup uses a separate owner helper. Private screenshots,
profiles and logs remain ignored under backend/var; temporary credentials are
removed by the guarded fixture cleanup.

| Actual command/check | Result |
| --- | --- |
| `node --test frontend/tests/*.test.js` | 49 passed; 0 failures/skips. |
| `docker compose run --rm manage python manage.py test apps.orders.tests.test_draft_revisions apps.orders.tests.test_draft_customer_field_editing apps.orders.tests.test_draft_conversion_concurrency --settings=config.settings.test --keepdb --noinput -v 0` | 21 tests, 16.933s, OK before the seventh revision test was added; final full suite includes that added coverage. |
| `node frontend/tests/browser-smoke.mjs` | PASS: real login/workspace/catalogue regressions; bounded draft/line pages, missing/foreign detail, exact decimals; manual creation/header/line editing, validation and dirty navigation; two Chromium profiles with independently authenticated sessions prove stale 412 and preserved input/newer value; active catalogue pages/search/attach/detach; refreshed readiness, viewer/demoted-admin denial, frozen converted source, lost committed response and same unique order replay. No uncaught browser exceptions. |
| Browser development failures | Harness waits/selectors/history assumptions were corrected after premature pagination/conflict checks, a nonexistent detail selector and changed back-navigation history. No existing application assertions were loosened. The final workflow above passed. |
| `docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0` | 728 tests, 197.415s, OK; no skips. Includes all orders, organizations, catalogue, account, migration and shell regressions plus seven new revision methods. |
| `docker compose run --rm rlscheck python manage.py verify_order_rls` | 46 tests, 78.452s, OK; direct restricted runtime role, dedicated test database and audited forced RLS/grants. No skips; native owner-role tests are separate evidence. |
| Ruff `check . ../scripts ../frontend/tests` and `format --check` from backend | Passed; 167 files formatted. Mixed line-ending formatting was corrected. |
| `node --check` for frontend desk modules | Passed. Native ES modules have no TypeScript/compiler/production build command; those gates are not applicable to this stack. |
| `docker compose config --quiet`; `manage makemigrations --check --dry-run`; `git diff --check` | Passed; no schema changes; existing Git CRLF normalization warnings only. |
| Live public shell, main.js, editor.js, editor-view.js and ready health on local :8000 | All five URLs returned 200 with expected content types. No main-database fixtures were created. |
| Private artifacts and cleanup | git check-ignore confirms screenshots, profiles/fixture paths and new verification logs remain ignored; zero tracked files under backend/var or var. Temporary browser credential fixture absent after guarded cleanup. Dedicated test-database owner query confirms zero browser users, zero browser workspaces and zero login buckets. Only existing API/database containers remain running. |

Screenshots were visually inspected at desktop and 390px mobile widths; dialogs
and tables fit the viewport and untrusted text stays literal. Formal accessibility
testing, production packaging/static serving/HTTPS/proxy deployment and a wider
browser matrix remain unverified. Revision computation streams lines but remains
O(line count); no load-test claim. Creation/insertion have no idempotency receipts:
ambiguous results block retries and require checking server data before restarting.
Private document storage/content-safety prerequisites remain unresolved. Next is
secure document intake only after those prerequisites, with extraction separate.

## Previous checkpoint: first frontend login, workspace and catalogue workflow

2026-10-08, main at aac1e453ed613a306b21dc5f592ab0a88a7a5df0; working-tree
implementation, preserving all earlier upload/readiness/conversion edits.
The referenced frontend prompt was absent at the supplied Downloads path;
implemented the explicit user request using actual repository/API contracts.
ADR-001 specifies same-origin sessions but no frontend framework, so this small
increment uses a public Django shell and dependency-free browser ES modules.
No dependency pins, database schema, tenant services or permission rules changed.

Delivered sign-in/out, active workspace discovery with load-more, freshly
validated current selection/reload, and read-only catalogue browsing with
literal search, active/inactive/all filters and fixed 50-row pages. Loading,
empty/no-membership, invalid credentials, unavailable server and expired/revoked
access states are explicit. Session cookies remain HttpOnly; CSRF is refreshed for
mutations and replaced after login rotation. Requests use relative same-origin
paths, no-store and rejected redirects. No credentials/CSRF tokens in browser
storage APIs or URLs.
Rows clear before workspace changes and on denial; cancelled/late responses
cannot restore a previous workspace. Tab/history restoration revalidates context.
All API/user text is inserted with textContent, not HTML interpretation.

Files: frontend template, API client/controller/DOM renderer/responsive CSS,
package metadata and Node/browser tests; backend apps/web shell/config/tests;
shared template/static settings, root URL and read-only Compose source mount.
Docs: FIRST_FRONTEND_WORKFLOW, README, roadmap, master prompt, local verification
and this state. Earlier backend work remains uncommitted and preserved. Private
logs/audit files/browser screenshots/profiles remain ignored; temporary browser
credentials and synthetic identities were cleaned. No commit/push performed.

### Frontend verification

All database fixture checks are sequential in dedicated PostgreSQL test_orderdesk.
Node fake transports establish client behavior only. Native maintenance-role
tests and restricted-role/browser tenant evidence are separate.

| Actual command/check | Result |
| --- | --- |
| `node --test frontend/tests/*.test.js` | 18 passed; 0 failed/skipped. |
| `docker compose run --rm manage python manage.py test apps.web.tests apps.accounts.tests apps.organizations.tests --settings=config.settings.test --keepdb --noinput -v 0` | 199 tests, 23.653s, OK; 2 new shell methods plus existing account/workspace regressions. |
| `node frontend/tests/browser-smoke.mjs` | PASS in real Chromium: invalid/valid login, viewer catalogue, workspace selection/switch, search, status, pagination, reload, safe text, desktop/mobile, live membership revocation and logout; no uncaught browser exceptions. Server directly uses orderdesk_app/test_orderdesk; owner fixtures separate and cleaned. |
| `docker compose run --rm rlscheck python manage.py verify_catalog_rls` | 115 tests, 256.708s, OK; direct restricted runtime, forced RLS/policies/grants audited; no skips. |
| Initial full Django regression | 721 tests, 184.641s; 7 account failures caused by a browser-harness peer login counter left in the shared test database. No application assertions were loosened. Harness now observes the actual peer digest and removes only counters created by this run; corrected browser and full regressions rerun below. |
| Corrected browser harness and cleanup | Browser workflow PASS again; guarded owner query confirms 0 remaining login counters and no browser synthetic users/workspaces; temporary credentials removed. |
| `docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0` (final) | 721 tests, 170.311s, OK; no skips. Corrected harness leaves the shared test database clean. |
| Ruff `check . ../scripts ../frontend/tests` and `format --check` from backend | Passed; 165 files already formatted. |
| `docker compose config --quiet`; `manage makemigrations --check --dry-run`; `git diff --check` | Passed; no schema changes; existing CRLF normalization warnings only. |
| `docker compose up -d --no-deps api`; live HTTP shell, main/API/controller JS, stylesheet and ready health | Existing API recreated with new read-only frontend mount; all six URLs 200 with appropriate content types; database preserved. |
| Private artifacts | Screenshots/profile/temporary fixture paths ignored; credential fixture absent after cleanup; no temporary browser server remains. |

Desktop/mobile screenshots were visually inspected. Production asset packaging,
static serving/HTTPS/proxy deployment, wider browser compatibility and formal
accessibility testing remain unverified. Existing operator provisioning remains
necessary for accounts/memberships. No catalogue write/import UI, draft UI,
storage/content safety, extraction or ERP-delivery claim. See
[frontend contract/runbook](FIRST_FRONTEND_WORKFLOW.md).

Next dependency order: frontend draft list/detail/review; then edit/readiness and
administrator conversion; then separately agreed ERP/document-safety work.

## Previous checkpoint: shared readiness and atomic internal draft conversion

2026-10-08, main working tree, preserving all earlier upload-hardening edits.
Implemented Step 4D.9 GET/HEAD readiness and Step 4D.10 administrator-only
CSRF-protected JSON POST conversion. `/review/` remains observational. Readiness
uses one explicitly scoped aggregate SELECT and a framework-independent evaluator
shared by conversion. Reference/unit remain optional; positive quantities, active
catalogue matches and 128-character SKU snapshots are required.

Conversion owns one organization-first write transaction, refreshes access after
the lock, locks source/lines, evaluates current readiness, creates the existing
purchase-order model and independent line copies, seals a unique source link,
marks the source converted, materializes the bounded response and commits.
First success is 201, fresh authorized valid replay 200 with the same order.
An internal `DRAFT-<UUID hex>` number is generated; unrelated reserved-number
collisions are 409 and never adopted. No client business overrides, guessed
prices/units, file processing or external effects. Source reference/intake text
remain private on the frozen source. Actor/time reuse order created_by/created_at;
no audit-event mechanism exists and no audit-completeness claim is made.

Additive migration 0008 introduces nullable unique source_draft linkage,
composite tenant FK, converted source state, invoker snapshot guards and deferred
complete-copy/linkage checks. Existing orders remain unlinked and unchanged.
Converted source headers/lines and copied order identity/customer/lines freeze;
normal order review transitions and document/manual review handling remain.
Status UPDATE grants now require conversion guards in the fail-closed role check;
other immutable-column assertions remain intact. Existing RLS policies/grants
stay restricted, with runtime-only admin linkage/status enforcement. Explicit
maintenance deletion remains available for reviewed repair and fixture cleanup.

Files: orders models, readiness, selectors, services, serializers, views, URLs,
0008 migration, guarded verifier/runtime tests; native readiness/conversion/race/
upgrade modules; health role check and its additional guard regression. Docs:
Step 4D.9/4D.10, README, roadmap, master prompt, storage findings and this state.
Earlier upload changes are preserved. Private audit/log/override files remain
ignored and untracked. Conversion does not depend on file parsing or establish
production storage/content safety, ERP compatibility or legal approval.

### Conversion verification

Commands ran from order-desk; fixtures ran sequentially in dedicated PostgreSQL
test_orderdesk. Native maintenance-role evidence and restricted runtime evidence
are separate. No SQLite or mocked checks substitute for RLS or races.

| Gate / actual command | Observed result |
| --- | --- |
| Readiness prerequisite: manage `test apps.orders.tests.test_draft_readiness apps.orders.tests.test_draft_review_api --settings=config.settings.test --keepdb --noinput -v 0` | 16 tests, 6.113s, OK. |
| Readiness prerequisite: rlscheck `python manage.py verify_order_rls` | 42 tests, 90.410s, OK, direct orderdesk_app on test_orderdesk. |
| Conversion red test: manage `test apps.orders.tests.test_draft_conversion.DraftConversionTests.test_first_conversion_and_lost_response_retry_return_same_order --settings=config.settings.test --keepdb --noinput -v 0` | One expected assertion failure, 0.454s: absent convert route returned 404 instead of 201. |
| Focused final candidate: manage `test apps.orders.tests.test_draft_conversion_migration apps.orders.tests.test_draft_conversion apps.orders.tests.test_draft_readiness apps.orders.tests.test_draft_conversion_concurrency apps.health.tests.test_runtime_role --settings=config.settings.test --keepdb --noinput -v 0` | 26 tests, 13.781s, OK; both serial orders across eight competing mutation types, upgrade preserves legacy rows. |
| Fresh installation in disposable orderdesk-conversion-install Compose project | All migrations from zero through orders 0008; 21 conversion/readiness/race tests, 12.386s, OK. Test database is test_orderdesk; tmpfs, no host ports or persistent data volume. Project removed afterwards without touching existing databases. |
| Full native: `docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0` | 719 tests, 214.080s, OK. |
| Final order: `docker compose run --rm rlscheck python manage.py verify_order_rls` | 46 tests, 148.280s, OK, directly restricted orderdesk_app on test_orderdesk; concurrency and blocked revocation/demotion use independent runtime connections. |
| Final catalogue: `docker compose run --rm rlscheck python manage.py verify_catalog_rls` | 115 tests, 349.500s, OK, directly restricted orderdesk_app on test_orderdesk. |
| Host Ruff `check . ../scripts`, `format --check . ../scripts` from backend | All checks passed; 158 files already formatted. |
| Local model/migration/runtime checks | `makemigrations --check --dry-run`: no changes; `migrate --plan`: only orders 0008; sanitized source-state preflight: zero unsupported states; `migrate --noinput`: 0008 OK; `migrate --check`: exit 0; API `check_runtime_role`: restricted. No main business fixtures or data repairs. |
| Final Compose/system/dependency/health/guard checks | Compose config and manage system check exit 0; seven installed packages compatible via `uv pip check --python /opt/venv/bin/python`; live/ready HTTP 200 status ok; both API verifier invocations refuse main before fixtures with expected exit 1/test_orderdesk refusal. |
| Documentation links / whitespace / ignore checks | Eight maintained files' local links resolve; Git diff whitespace passes; private audit/log/temporary override paths ignored, no tracked backend/var files. |

All final gates passed without unittest skips or verification blockers.
Initial fixture issues were corrected without loosening assertions: revocation
must occur before read-only transaction entry; real-role inserts use scalar IDs
rather than assigning maintenance-alias objects. The first runtime metadata gate
correctly rejected the new status grant until the role checker was updated to
require conversion guards. Final gate results above supersede those failed runs.
Fresh installation used `docker compose -p orderdesk-conversion-install -f
compose.yaml -f backend/var/draft_conversion_install.compose.yaml` for config,
db startup, dbsetup, focused test run, test-database showmigrations and down.
The ignored override removes DB ports/volumes and adds tmpfs only; credentials
were reused without printing them. Existing main/test databases were never reset.
The changes remain in the existing working tree; no commit, push, reset or
unrelated-work discard was performed in this conversion increment. Host helper
scripts and frontend/browser tests were not rerun: scripts are unchanged and the
frontend remains a placeholder. No production deployment or content/storage
verification is inferred from these local PostgreSQL results.

Next task, only when requested: the first frontend session/workspace/read-only
catalogue increment. Keep internal conversion distinct from ERP export and
production release. Detailed API/transaction/snapshot boundaries are in
[conversion contract](AI_Order_Desk_Step_04D10_Draft_Conversion.md).

## Historical checkpoint: upload hardening and draft readiness definition

2026-10-08, main working tree based on
aac1e453ed613a306b21dc5f592ab0a88a7a5df0. Existing local work/history is
preserved. Purchase-order document uploads now have an inclusive 10 MiB actual
file-byte limit at multipart parsing (including CSRF) and independently in the
framework-independent service. Aggregate duplicate uploads cannot evade it.
Oversize returns stable HTTP 413 before document/storage writes; ordinary
validation retains its existing 400 translation. Current writer/parent/state
checks precede application input validation.

Server-generated storage paths belong to a single attempt. Exceptions during
storage write, database insertion, response materialization or commit trigger
compensating deletion after rollback, preserving existing files and the original
error. Temporary streams close on success/failure. Failed deletion logs a
constant sanitized message and may leave an orphan; process termination,
ambiguous commit outcomes, alternate storage backends and durable recovery are
not solved by this compensation. No migration, grant, dependency or public
download route was added. Production storage ACLs and content/parser safety
remain unverified; see [upload contract](ORDER_DOCUMENT_UPLOAD_HARDENING.md) and
[remaining storage findings](STORAGE_FINDINGS.md).

Defined [Step 4D.9 readiness](AI_Order_Desk_Step_04D9_Draft_Readiness.md) separately:
customer name, at least one line, positive quantities, active catalogue matches
and SKU snapshots fitting the purchase-order 128-character limit. Reference/unit
remain optional. Active-match policy is an explicit conservative assumption
pending business feedback. `/review/` remains observational. Readiness endpoint,
conversion, converted status and repeat-safe conversion identity are not
implemented. Next: implement this read-only contract with native and real-role
tests, then define conversion's identity/locking/retry contract.

### Files and actual verification

Production: orders `document_files.py`, `uploads.py`, `services.py`, `views.py`.
Regressions: expanded `test_order_document_upload_storage.py` (17 methods total)
and one credential-session test in `runtime_rls.py` (41 checks total).
Docs: upload/readiness contracts, this state, storage findings, roadmap and master
prompt. Existing assertions are preserved. Private audit files, local uploads and
all logs remain ignored under backend/var/; no tracked file exists there.

Commands ran from order-desk using existing Compose, sequential test fixtures
and the dedicated PostgreSQL test_orderdesk:

| Command | Actual result |
| --- | --- |
| `docker compose run --rm manage python manage.py test apps.orders.tests.test_order_document_upload_storage apps.orders.tests.test_services --settings=config.settings.test --keepdb --noinput -v 0` | 25 tests, 8.934s, OK. |
| `docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0` | 696 tests, 184.431s, OK. |
| `docker compose run --rm rlscheck python manage.py verify_order_rls` | 41 tests, 60.752s, OK; directly restricted orderdesk_app, test_orderdesk. |
| `docker compose run --rm rlscheck python manage.py verify_catalog_rls` | 115 tests, 263.878s, OK; directly restricted orderdesk_app, test_orderdesk. |
| Host Ruff from backend: `ruff check . ../scripts`, `ruff format --check . ../scripts` | All checks passed; 153 files already formatted. |
| `docker compose config --quiet`; manage `check`, `makemigrations --check --dry-run`, `migrate --check` | All exit 0; no system issues, model drift or pending migrations. No migrations applied. |
| `docker compose exec -T api python manage.py check_runtime_role`; HTTP health probes | Role restricted; `/api/v1/health/live/` and `ready/` HTTP 200, status ok. |
| API `verify_order_rls` and `verify_catalog_rls` guard checks | Both refuse the main database before fixtures, expected exit 1 with the required test_orderdesk refusal message. |

No unittest skips in any test gate. Native tests use maintenance
credentials and do not establish runtime isolation; direct restricted-role
verifiers are separate evidence. Logs include expected synthetic error responses
from failure-path tests; overall result above is the runner's actual result.
No readiness tests ran because only its next-step contract is defined here.

## Historical checkpoint: post-audit reconciliation and reproducibility

This increment reconciles the actual backend inventory and local verification
instructions, and delivers the existing protected draft editing/review work.
No new business feature, dependency, migration, runtime grant or RLS policy is
introduced. README and ROADMAP now describe actual implemented, unverified,
partial and planned scope. LOCAL_VERIFICATION.md is the maintained runbook;
EDITOR_SETUP.md records the reliable backend-directory lint invocation.
STORAGE_FINDINGS.md records a confirmed storage-lifecycle gap and missing checks.
The full audit and temporary probe/logs stay private under ignored backend/var/.

### Source of truth and retained historical evidence

Reconciliation started on main at 0091cf5457bddec84e83e4c668fb9b1db53ee1fc,
matching the audited baseline; newer work was not discarded. The 2026-10-08
audit reported 679 native Django tests (171.218s), 115 direct-runtime catalogue
checks (269.212s), 40 direct-runtime order checks (72.015s), and 23 script tests
(0.423s), all passing without unittest skips. These are separate historical
results, not fixed acceptance thresholds. Both verifiers actually connected
as restricted orderdesk_app to test_orderdesk and refused the main database.
Audit role/health/migration/lint checks passed; deployment was not verified.
Historical hashes/overlay instructions in old step guides are not current
Git identity or setup prerequisites. No replacement hash is fabricated.
The earlier checkpoint entries below describe their original delivery states;
their 'uncommitted' statements are historical after the current delivery.

### Reviewed existing work

All six previously untracked files are intentional source tests/contracts,
not generated output, private fixtures or local artifacts:

| File | Classification |
| --- | --- |
| backend/apps/orders/tests/test_draft_customer_field_editing.py | Synthetic TransactionTestCase/API/concurrency regression tests, 14 tests. |
| backend/apps/orders/tests/test_draft_line_detachment.py | Synthetic scoped detachment/rollback/concurrency tests, 11 tests. |
| backend/apps/orders/tests/test_draft_review_api.py | Synthetic scalar aggregate/read-only/current-access tests, nine tests. |
| docs/AI_Order_Desk_Step_04D4_Draft_Customer_Field_Editing.md | Intentional customer-edit contract and historical verification record; distinct from requested-line 4D.4. |
| docs/AI_Order_Desk_Step_04D7_Protected_Draft_Catalogue_Detachment.md | Intentional detachment contract and verification record. |
| docs/AI_Order_Desk_Step_04D8_Draft_Review_Summary.md | Intentional observational review contract and verification record. |

Reviewed production diffs preserve services/selectors layering, URL-selected
workspace authorization, refreshed active account/member/workspace checks,
organization/header/line locks and in-transaction serialization. Customer PATCH
and detachment allow only their documented fields; aggregate review makes no
readiness decision. Existing read tests changed only the obsolete detail PATCH
expectation and retained all other assertions. Runtime regression additions
exercise real credential sessions and deliberately unfiltered aggregate RLS.
Application source and test contents remained identical to the audited baseline.
Relevant files are selected explicitly for delivery; credentials, local uploads,
private audit/probe/logs and generated caches are excluded.

### Reconciliation verification (2026-10-08)

Applicable final-candidate gates are rerun because verified existing application
work is being committed. Documentation alone does not justify a full-suite rerun.
Commands are the exact canonical commands in LOCAL_VERIFICATION.md.

| Gate | Actual result |
| --- | --- |
| Full native PostgreSQL suite | 679 tests, 152.861s, OK; config.settings.test, migrator, test_orderdesk. |
| Catalogue runtime verifier | 115 tests, 347.605s, OK; direct orderdesk_app current/session identity, test_orderdesk. |
| Order runtime verifier | 40 tests, 82.328s, OK; direct orderdesk_app, test_orderdesk. A stable isolated-candidate rerun is recorded below. |
| Host script tests | 23 tests, 0.419s, OK; temporary/mocked helper scenarios, not runtime-RLS proof. |
| Canonical Ruff lint/format | All checks passed; 150 files formatted (144 backend plus six scripts). |
| Compose/system/model drift/applied migration checks | Exit 0; no issues, model changes or pending migrations. No migrations applied in reconciliation. |
| Runtime role/main-database refusal/health/dependencies | Restricted role; both guards exit 1 with the required refusal; live/ready HTTP 200 ok; seven installed packages compatible. |
| Storage diagnostic | One temporary test, 0.362s, OK: DB row rolled back but one file remained; temporary MEDIA_ROOT cleanup followed. This confirms an open gap, not remediation/RLS proof. |
| Documentation paths/links/commands/whitespace | Local link/anchor and source-path checks passed; Git diff whitespace passed. |

The audit's alternate lint invocations produced path/configuration-dependent
warnings; the documented invocation passes without disabling rules or
reformatting migrations. No claim is made about all cached IDE diagnostics.
The diagnostic command was `docker compose run --rm manage python manage.py
shell --settings=config.settings.test -c "from pathlib import Path;
exec(Path('var/reconcile_storage_probe.py').read_text())"`; its temporary input
is ignored/private and not a required fresh-checkout gate. A permanent cleanup
regression belongs to the next remediation increment. No unittest skips in
completed gates; the host helper's synthetic exact-SKU skip message is not a
skipped unittest. Production serving/TLS/proxy/storage/SMTP/backups/CI and
optional live operator credential helpers remain unverified.

### Delivery and exact next task

During verification another process created and pushed existing implementation/
documentation commit b727056c0277ba5cad86758be58703265accf892, followed by
cleanup commit a9455cda5c6abdf2fc036dc224c0e5ce8591322d. That cleanup removed
generated full_suite.log/rls.log and added ignore entries. No private audit or
probe was staged/published by this reconciliation process. Existing history is
preserved; no force push or rewriting is used.

New local commit bad9e052750b8127c461133b5252ffe786911146 introduced upload
cleanup tests, and concurrent unstaged edits appeared in orders/services.py,
views.py, test_order_document_upload_storage.py plus new orders/uploads.py.
Those changes belong to the next focused increment and remain untouched and
excluded from this delivery. The earlier 679-test result does not verify this
new moving working tree. Do not infer upload-hardening completion from it.

To publish only reviewed work, an isolated documentation checkout was based on
already-pushed a9455cd. Its backend was compared to reviewed b727056, ignoring
Git checkout line endings: no source differences. A private Compose override
selects that isolated backend for stable verification while keeping the original
project/environment, roles and test_orderdesk. No .env was copied or printed.
The ordinary fresh-checkout commands remain LOCAL_VERIFICATION.md; the temporary
override is only concurrency isolation for this session. Actual delivery commands
ran from the original application directory with
`docker compose --project-directory <original-application-directory> -f compose.yaml
-f backend/var/reconciliation_delivery.compose.yaml run --rm manage python
manage.py test --settings=config.settings.test --keepdb --noinput -v 0`, followed
by the same Compose prefix and `run --rm rlscheck python manage.py verify_order_rls`.
The override changes only manage/rlscheck source mounts; database/environment
configuration remains the existing original Compose project.

Stable isolated delivery candidate:
- Native suite: 679 tests in 157.548s, OK; no skips; dedicated PostgreSQL test_orderdesk and config.settings.test.
- Order runtime verifier: 40 tests in 54.191s, OK; no skips; directly restricted orderdesk_app on test_orderdesk.
- Catalogue implementation is unchanged; the fresh 115-check reconciliation
  result above remains applicable.

Stable verification and storage-record commit
bdb7d9851e79b4a3532deae67d063b00c957f9e7 was created on isolated
`docs/post-audit-reconciliation`, based on already-pushed a9455cd.
Actual command `git push origin HEAD:main` exited 0 and advanced remote main
from a9455cd to bdb7d98, without force. This documentation-only follow-up records
that observed result; its own push result is reported in the session handoff.
The concurrent bad9e05 test commit and unfinished upload implementation are
excluded from the remote reconciliation delivery. Published documentation is
merged normally back into local main, preserving those separate local changes;
that merge is not pushed as part of the verified documentation delivery.
The existing intended remote is origin and branch main; the inspected remote tip
is an ancestor of the starting HEAD. Only a normal non-force push is authorized;
no reset, remote replacement or divergent-work discard is performed.

**Next task:** review and finish the concurrent protected purchase-order document-upload hardening: define bounded
actual-byte intake and new-file cleanup on transaction/materialization failure,
with permanent regressions for containment, rollback/cleanup failure, successful
persistence and unchanged authorization/RLS. See STORAGE_FINDINGS.md. Resolve
these prerequisites before dependent intake/finalization is declared ready.
Then define the separate read-only draft readiness contract/tests; atomic,
repeat-safe draft-to-purchase-order conversion follows later. Neither readiness
nor conversion is implemented in reconciliation. Frontend, automatic extraction/
matching, ERP export and usage tracking remain planned; the $0 industrial-
distributor product scope is unchanged.

## Previous checkpoint: Step 4D.8 draft review summary verified locally

Added scoped GET/HEAD `.../draft-orders/<draft>/review/` after verified customer
editing. Contract recorded before code in
`AI_Order_Desk_Step_04D8_Draft_Review_Summary.md`. All current active member roles
may read scalar observations: empty customer flags; total/unmatched/missing-
quantity lines; unresolved union counted once per line; inactive catalogue links
counted per line. No readiness/submission policy or status transition is implied.
Selectors explicitly filter header/line/catalogue organization boundaries and
compute all counts in one aggregate SELECT for a single statement snapshot.
Response serialization adds no queries and stays inside the read-only tenant
scope. Empty drafts return zeros. HEAD/cache/query/method guards retain existing
conventions. Original request/header/line/catalogue data and snapshots are intact.

Actual final verification on 2026-10-08: 9 focused tests passed in 3.358s;
679 full backend tests passed in 146.419s; 40 restricted-role order/RLS checks
passed in 50.375s. No skips. Ruff lint/format (144 files), model drift, migration
state, runtime role, both health probes and whitespace passed. Native tests
verify mixed/overlapping counts, repeated catalogue references, customer/line
edits and deactivation without snapshot refresh, all roles and denial states,
fresh revocation, foreign/missing/UUID isolation, one SELECT and zero serializer
queries in a read-only transaction. Runtime tests use real credentials for all
roles and verify tenant-scoped aggregate results even when application header/
line organization filters are deliberately omitted in the synthetic test query.
Foreign rows stay hidden and revocation denies access. No schema/dependency/
grant/RLS changes. Fixtures stayed in test_orderdesk; main checks were metadata/
health only. All earlier local work and existing assertions were preserved.
Ignored logs: `backend/var/draft_review_{focused,regression,runtime}.log`.
Review-summary changes remain locally verified and uncommitted. Finalization,
automatic matching and any submission-readiness rules remain separate work.

## Previous checkpoint: draft customer-field editing verified locally

Added the requested focused test module using the creation API setUp/session/
CSRF/TransactionTestCase conventions, then implemented customer-only detail PATCH.
Contract recorded first in `AI_Order_Desk_Step_04D4_Draft_Customer_Field_Editing.md`
(requested filename; follows Step 4D.7 and does not replace line creation).
Tests-first run: 14 tests in 5.509s, 58 failed assertions because PATCH returned
405, zero test errors. After implementation: 14 focused tests passed in 6.141s.

Current admins/reviewers edit customer_name/customer_reference only. Shared
creation whitespace validators preserve empty strings and original nonblank
text; editing additionally requires string types and rejects empty patches.
Organization-first authorization and scoped header locking precede parsing,
merged model validation, changed-field save and in-scope scalar detail response.
Omitted fields and identical values preserve state/no-op timestamps. Original
intake, system fields and lines are untouched. Existing Django-to-DRF validation
translation handles field/__all__/unkeyed errors only after rollback.

Actual final verification on 2026-10-08: 670 full backend tests passed in 148.924s;
39 restricted-role order/RLS checks passed in 50.864s. No skips. Ruff lint/format
(143 files), model drift, migration state, runtime role, both health probes and
whitespace passed. Focused variants cover lengths/types/Unicode whitespace,
empty/partial values, no-save rejection, full_clean and post-save validation
rollback, current/revoked/removed/nonmember/inactive access, tenant/UUID isolation,
CSRF/methods/media/queries and unchanged lines. Independent HTTP connections
prove complete field pairs stay consistent and disjoint edits retain both fields.
Real-role checks verify writers, 400/no-op/foreign/revocation and line preservation.

Updated only the obsolete detail PATCH expectation in the old read-method test,
adding saved-value assertions while retaining all other checks. Requested line
collection POST 405 conflicts with the existing Step 4D.4 creation contract and
201 assertion. Clarification was offered; no reply arrived, so existing line
creation/201 is preserved, with POST 405 on draft and line detail routes.
DraftOrder defines only draft status with a DB constraint; submitted/converted
status-lock fixtures are inapplicable, and no tests were skipped. Creation's
numeric scalar coercion and invalid-viewer-input error precedence stay unchanged.
No schema/dependency/grant/RLS changes. Fixtures stayed in test_orderdesk;
main checks were metadata/health only. Earlier uncommitted work was preserved.
Ignored logs: `backend/var/draft_customer_editing_{red,focused,regression,runtime}.log`.
Customer-editing changes remain locally verified and uncommitted.

## Previous checkpoint: Step 4D.7 manual catalogue detachment verified locally

Continued after verified attachment. Contract recorded before code in
`AI_Order_Desk_Step_04D7_Protected_Draft_Catalogue_Detachment.md`. JSON POST
`.../lines/<line>/detach/` accepts an empty object only. Current admins/reviewers
may detach after fresh organization authorization and scoped parent/line locks;
lookup precedes parsing. Clear catalogue reference and both snapshots together,
validate remaining requested identity, save changed catalogue fields and line
updated_at, and materialize in scope. Catalogue-only lines return 400 without
writes until requested fields are repaired. Already unmatched lines are 200
no-ops preserving updated_at. Requested text/unit/null quantity, identity,
position, creation time and header fields/timestamps/count remain unchanged.
No catalogue row is read or modified; no schema/dependency/grant/RLS changes.

Actual final verification on 2026-10-08: 11 focused detachment tests passed in
6.501s; 38 restricted-role order/RLS checks passed in 52.824s; 656 full backend
tests passed in 148.967s. No skips. Ruff lint/format (142 files), model drift,
migration state, runtime-role audit, both health probes and whitespace passed.
Tests cover writer roles, valid/invalid identity and repair, real/no-op timestamps,
original request/header/catalogue preservation, strict fields/transport/methods,
foreign parents/lines, viewer/revoked/removed/nonmember denial, in-scope response
and post-save rollback. Independent connections prove identity-clearing versus
detachment commits one change and retains valid state; committed demotion denies
a waiting detachment with an observed organization lock wait. Real credentials
verify both writers, no-op, identity denial and revocation under orderdesk_app.
All fixtures stayed in test_orderdesk; main checks were metadata/health only.
Ignored logs: `backend/var/draft_detachment_{focused,runtime,regression}.log`.
Detachment changes remain uncommitted. Next proposed increment: protected draft
customer-field editing, preserving original intake and system state. Automatic
matching and finalization remain separate work.

## Previous checkpoint: Step 4D.6 manual catalogue attachment verified locally

Finished the existing uncommitted attachment implementation under the contract
`AI_Order_Desk_Step_04D6_Protected_Draft_Catalogue_Attachment.md`. JSON POST
`.../lines/<line>/attach/` accepts only `catalogue_item_id`. Current admins and
reviewers may attach active same-workspace items to unmatched lines. Organization,
parent and line locks precede parsing; missing/foreign/inactive items return 404;
repeat attachment returns stable 409 without refreshing snapshots. Requested
fields/null quantity, position, header fields/timestamps/count are preserved;
only catalogue reference/snapshots and the line update timestamp change.
Model/materialization validation failures return 400 after rollback.

Actual final verification on 2026-10-08: 15 focused tests passed in 4.740s;
645 full backend tests passed in 190.715s; 37 restricted-role order/RLS checks
passed in 52.977s. No skips. Ruff lint/format (141 files), model drift, migration
state, runtime role, both health probes and whitespace checks passed.
Tests cover competing attachments and waiting deactivation/demotion with observed
organization lock waits, scoped lookup before parsing, role/revocation/nonmember
denial, CSRF/media/query/method checks, historical snapshots and post-save rollback.
Real-role testing caught reviewer 404s caused by a catalogue row write lock
applying admin-only UPDATE RLS. Removed that lock and retained catalogue member
SELECT under the shared organization lock; final full regression includes the
corrected race tests. No migration/grant/policy/dependency changes. Concurrent
direct maintenance catalogue writes must follow that lock discipline.
All fixtures stayed in `test_orderdesk`; main checks were metadata/health only.
Ignored logs: `backend/var/draft_attachment_{focused,regression,runtime}.log`.
Changes remain uncommitted. Next: protected manual detachment, now requested.

## Previous checkpoint: Step 4D.5 requested draft-line editing verified locally

Continued from Step 4D.4 with scoped line-detail GET/HEAD and protected JSON
PATCH for requested SKU/description, quantity and unit. The contract was recorded
before code in `AI_Order_Desk_Step_04D5_Protected_Draft_Line_Editing.md`.
Active members read; only current admins/reviewers edit. The service locks the
organization, refreshes authorization, then locks the scoped parent and line
before parsing. It merges supplied values into current state, validates the
model, saves changed fields only and materializes the scalar response in scope.
Omitted fields and historical catalogue references/snapshots are preserved;
explicit null quantity remains unresolved. Empty/identical patches preserve
`updated_at`. Identity/parent/tenant/position/catalogue/timestamps reject input.
Header fields/timestamps/counts remain unchanged. Shared validation translation
returns stable 400s after rollback. No schema/dependency/grant/policy changes.

Actual verification on 2026-10-07: 17 focused editing/concurrency tests passed
in 5.373s; 630 full backend tests passed in 143.096s; 36 restricted-role order/RLS
checks passed in 33.103s. No skips. Ruff lint/format (140 files), model drift,
migration state, runtime role, both health probes and whitespace checks passed.
Tests cover partial/no-op/clearing behavior, merged identity, immutable fields,
inactive/removed/never-member access, foreign parents/lines, CSRF/media/methods,
linked inactive catalogue snapshots, model and post-save rollback. Independent
connections prove disjoint patches retain both changes and committed demotion
denies a waiting editor, with an observed organization lock wait. Established
creation and opposite lock-order assertions remain covered by full regression.
Restricted-role checks exercise real credential sessions and PATCH grants.
Fixtures stayed in `test_orderdesk`; main checks were metadata/health only.
Ignored logs: `backend/var/draft_line_editing_focused.log`,
`draft_line_editing_regression.log`, `draft_line_editing_runtime.log`.

Next proposed increment: protected manual catalogue attachment to a draft line,
with its snapshot/active-item/update contract documented first. Automatic
matching remains separate. Changes are locally verified and uncommitted.

## Previous checkpoint: Step 4D.4 requested draft lines verified locally

After Step 4D.3, implemented POST on the existing draft lines route for one
requested/unmatched line. Its contract was recorded before code in
`AI_Order_Desk_Step_04D4_Protected_Draft_Lines.md`. Active admins/reviewers
may create; null quantities and original request fields are preserved.
Organization-first locking and fresh authorization precede scoped parent
locking, request parsing, model validation, insertion and scalar response
materialization. Duplicate positions return stable 409s; only the named native
uniqueness error is translated. Missing/foreign parents return 404. Catalogue
references/snapshots and other system fields cannot be supplied. Header intake
and timestamps are unchanged, while computed counts reflect new lines.

Shared draft CSRF authentication checks the underlying HttpRequest to avoid
early DRF JSON parsing; new line writes check roles/parent before parsing and
explicitly enforce JSON media. Draft views share validation-error translation
and existing never-cache behavior. Existing reads and unsupported methods are
covered by regression checks. No migration, dependency, policy or grant change.

Actual verification on 2026-10-07: 616 full backend tests passed in 126.157s;
18 focused line/service/concurrency tests passed in 4.818s; 35 restricted-role
order/RLS checks passed in 29.916s. No skips. Ruff lint/format (139 files),
model drift, migration state, restricted runtime role, health and whitespace
checks passed. Existing duplicate/demotion concurrency assertions now exercise
the real write service and retain observed lock-wait checks. Both demotion
orders, post-insert rollback and the final native conflict guard are verified.
Fixtures stayed in `test_orderdesk`; main checks were metadata/health only.
Ignored local logs: `backend/var/draft_lines_focused.log`,
`draft_lines_security.log`, `draft_lines_regression.log`, `draft_lines_runtime.log`.

Next proposed increment: protected editing of requested draft-line fields,
with its field/update contract documented first. Catalogue attachment and
matching remain separate work. Changes are locally verified and uncommitted.

## Step 4D.3 creation bug fixes verified: 2026-10-07

Reproduced the supplied creation suite: 6 tests with one validation error and
one failed authorization assertion. Whitespace customer names passed the
serializer unchanged and failed the model's optional-nonblank constraint;
the draft list/create view lacked the Django-to-DRF validation translation
used by other order/catalogue views. Added customer name/reference validators
that reject whitespace-only strings while preserving documented empty strings.
The API now maps Django validation errors after the service transaction exits:
field keys are retained, and constraint/unkeyed errors use `non_field_errors`.
Services remain framework-independent; model validation and rollback remain
enabled. Regressions verify no save on invalid input and rollback after an
insert followed by a materialization validation failure.

The apparent inactive-membership failure occurred at the earlier foreign
workspace assertion: `create_organization(actor=self.user)` explicitly gives
that user an active administrator membership. Corrected that fixture to use
a different owner, retaining both original 403 assertions. Production access
already requires current active membership, account and organization state.
Request permissions and each tenant transaction independently refresh it;
session selection is only a preference, and forced RLS checks active state too.
New regressions cover inactive/deleted/never-member users, inactive accounts
and organizations, stale session selection, and revocation between initial
permission and transaction entry across draft, purchase-order and catalogue
routes. No shared access/RLS policy changes were needed.

Updated one obsolete Step 4D.2 read test: Step 4D.3 now explicitly supports
POST on the list route. It asserts 201 and tenant/initiator/empty-line state
there, while preserving 405 checks on detail/line POSTs and other write methods.

Actual verification: 24 focused creation/read tests passed in 7.468s; all
520 orders/organizations/catalogue tests passed in 101.970s; 34 restricted-role
order/RLS checks passed in 18.543s, including the new creation/revocation check.
No skips. Ruff lint/format (138 files), model drift and whitespace checks passed.
Full suite output is retained locally in ignored
`backend/var/draft_creation_regression.log`; runtime output is in
`backend/var/draft_creation_runtime.log`. No migrations or dependency changes.

Related behavior left unchanged: an active viewer's invalid POST body is
validated before the service checks their write role, so it may return 400
instead of 403. A valid body remains denied, and inactive/nonmember requests
are denied by the initial permission before this validation. This affects
error precedence rather than granting write access.

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
