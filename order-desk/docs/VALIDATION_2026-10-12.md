# Order Desk validation and remediation 12 October 2026

**Verification in progress; no overall release PASS.** This report will be finalized
after the current runtime/browser, recovery and performance checks. Historical
results below are identified separately from current execution.

## Authority and environment

The attached principal-engineer request authorizes $0 local synthetic fixes and
verification, followed by a verified commit and ordinary push to the configured
repository. No public deployment, live ERP write, customer message or main-database
restore is authorized or performed. Arrival: clean main at 04eec05, remote
https://github.com/user1738mike/Order-Desk. Preserve prior history.

Read AGENTS.md, CODEX_BUILD_SPEC, MASTER_BUILD_PROMPT, ROADMAP, READMEs, PROJECT_STATE,
five accepted ADRs, feature contracts, the 11 October audit, and the original
3 October AI_Order_Desk_Validation_Launch_Plan_and_Pitch.docx in Downloads.
The available release-audit prompt was also read. The two original autonomous/
backup handoff references remain unavailable; repository reconciliation is the
available technical scope. No claims from old prompts/counts were accepted as proof.

Execution: this Windows/PowerShell host, Docker Desktop Linux containers. Application
is the existing Django/DRF/PostgreSQL modular monolith with native browser modules,
restricted orderdesk_app, separate orderdesk_migrator, private Linux storage and
an explicitly invoked one-job worker. Current isolated project:
orderdesk-deployment-d40b3e6da57141cbbd0d28c4ba0d8332. Its separate cluster contains
orderdesk and test_orderdesk; only test_orderdesk receives synthetic business fixtures.
The developer/main database is not seeded/reset/restored. Private logs, fixture
credentials, CA keys, image archive and backups remain ignored under backend/var.

Pinned candidate: Python 3.14.8, Django 5.2.18, DRF 3.18.1, Psycopg 3.3.6,
pypdf 6.20.0, Gunicorn 26.2.0, uv 0.12.23, Ruff 0.16.10, PostgreSQL
18.6-bookworm, Nginx 1.30.4, Node 24.15.0. Browser comes from signed Debian
repositories; record its actual image/version rather than promising identical apt
rebuilds. Frontend type/build gates are NOT_APPLICABLE: native JavaScript is syntax
checked and exercised in Node/Chromium; collectstatic hashes the served assets.

## Requirements matrix

VERIFIED applies only to executed specified scope. DEFECTIVE identifies reproduced
behavior needing repair, MISSING absent engineering, BLOCKED unavailable essential
input/evidence, and EXPLICITLY DEFERRED accepted scope exclusions. Final evidence
columns must be reconciled with the ledger before marking VERIFIED.

| Capability and acceptance criteria | Implementation across UI/API/database/operations | Current evidence and status |
| --- | --- | --- |
| A. Login, discover accessible workspaces, explicit selection, logout | accounts/views; organizations/context, selection, transactions; controller/main; cookie sessions/CSRF | Baseline native and restricted-role tests pass; final trusted browser distinct admin/reviewer/viewer login/logout pending |
| B. Create/import catalogue; preserve exact punctuation/case/zeros, reject existing/duplicate SKUs, commit all or none | catalogue services/import_execution; forced RLS and immutable receipt; new catalogue.js, management form and Idempotency-Key transport | API baseline passes. DEFECTIVE browser gap repaired; 10 controller regressions plus transport test pass; real import/replay pending |
| C. Supported PDF/CSV private upload and original-byte download | document_intake/private_documents, digest and contained keys; orders document UI; persistent UID-10001 volume | Native/runtime storage/upload negatives pass; final browser original-byte/digest/foreign-ID checks pending |
| D. Bounded supported extraction, original digest and truthful row/column or saved-page provenance; visible failures/retries | csv_extraction, pdf_parser/pdf_extraction, extraction_services; job leases/RLS; documents.js; explicit restricted worker | Linux native children and runtime job checks pass; PDF/CSV trusted-browser execution and interrupted-worker recovery pending |
| E. Explicit field acceptance/rejection/correction before atomic application, stale revision rejection and durable replay | extraction_apply, immutable applications/created-row links and RLS; extraction-review.js/editor | Native/runtime baseline passes; final trusted review/application and source replay pending; client correction/context regressions pass |
| F. Tenant exact-SKU matching with explicit acceptance; no guessed units/prices | matching/services; current-draft revision and catalogue evidence; matching.js; forced RLS | Native/runtime baseline passes; actual-browser exact matching pending; aliases/fuzzy rules EXPLICITLY DEFERRED |
| G. Exact decimal quantities and explicit units; reject unknown price fields | strict order serializers/services, Decimal columns and constraints; text inputs/editor | Backend/client grammar, boundary and revision tests pass. Prices/currency/pack semantics BLOCKED/unmodeled; generic profile omits them and optional units remain empty |
| H. Readiness rejects missing customer/lines/quantity/match and inactive/overlong catalogue identities | readiness + one coherent annotated SELECT; UI blockers; conversion rechecks current state | Native and restricted-role aggregate/filter-removal checks pass; final browser invalid manual draft pending. Readiness is internal conversion eligibility, not ERP business readiness |
| I. Atomic administrator conversion; same source returns same order, stale writes fail, snapshots/source freeze | services convert, organization/aggregate locks, unique source linkage and database guards; revision-aware frontend | Native concurrency/runtime replay tests pass; final browser conversion/replay pending |
| J. Deliberate submit/approve; immutable generic CSV; compare every critical supported field independently | export_services/csv_export and RLS/grants/leases; purchase.js private digest/size download; trusted proxy | Native independent literal bytes and protected export tests pass; strengthened all-column browser expected bytes pending. Named ERP compatibility BLOCKED |
| K. Reload/recreate and interrupted-operation recovery preserve valid sessions, records, bytes and proposals | DB/private volumes; worker lease retry; deployment_restart, recovery_probe; browser context epochs | Current restart/browser/recovery checks pending; historical 11 October proof is not substituted |
| Anonymous/expiry/CSRF/role/revocation boundary | session flush/expiry, fresh membership checks, API permissions before input parsing; organization-first locks | Current 845 native tests pass; runtime verification continuing; no owner-role substitution |
| Two-tenant IDs/lists/imports/matching/files/drafts/orders/exports/jobs and connection reuse/rollback/concurrency | explicit filters, transaction-local settings, forced RLS, tenant composite FKs and minimal grants | Baseline 56 order/115 catalogue direct orderdesk_app checks pass. Final run in progress |
| Late workspace/session/role responses cannot restore private browser data | controller generations/abort signals, textContent rendering; new catalogue forms/reports erase on replacement | 108 native-module tests pass, including new CSRF-bootstrap and committed-response races; real-browser context replacement pending |
| Production-like TLS/Host/cookies/private paths/body limits/health/migrations/static build | pinned non-root read-only Gunicorn/Nginx; proxy-only loopback ports; separate roles/certs; quality_gates | Baseline serving FAILED port collision after database tests. Port ownership preflight repaired; final serving gate pending |
| Coordinated encrypted fresh-cluster backup/restore, no main/nonempty target | recovery_drill/recovery.py, age encryption, inventory/modes, complete/incomplete markers, separate keys | 29 script tests pass including archive negatives. Current actual fresh restore pending; off-site/customer retention/escrow MISSING |
| Representative performance with explicit provisional targets | release_measure/performance/query_budget; 5,000-item, 300-draft, 6,000-line synthetic profile; sampled resources | No approved SLO found. Current measurement pending; prior p95 is historical, no optimal/customer capacity claim |
| Secure pilot administration, general audit history, usage/quotas and support/retention operations | local guarded operator commands; narrow receipts/metadata and runbooks | MISSING broader pilot UI/history/usage/operating ownership. No new commercial contract invented in this distributor-workflow remediation |
| Original launch critical fields/customer aliases/approved pack and timestamped price rules | Exact SKU and four supported extracted line fields only; generic export schema | BLOCKED on authoritative customer/account/unit/pack/pricing/ERP definitions; original commercial MVP incomplete |
| Handling time reduction >=50%, zero missed critical errors/correct ERP orders in 300 withheld representative orders | No representative customer data/ERP ground truth supplied | BLOCKED. Synthetic assertions cannot establish commercial accuracy, savings or statistical reliability |
| General PDF/OCR/LLM, fuzzy matching, inbox/live ERP, payments/enterprise/distributed infrastructure | Current reconciled specification excludes these increments | EXPLICITLY DEFERRED; no paid services or invented expansion |

## Reproduced defects and repairs

1. **Core usability gap: catalogue APIs had no browser creation/import path.**
   Source/actual initial template showed a read-only catalogue and no write
   controls. Added administrator creation, bounded read-only validation/errors/
   preview and explicit atomic import using the existing endpoints. Retain exact
   SKU strings, suppress duplicate clicks, bind retry to the same File/UUID receipt,
   reconcile unknown creation through exact lookup, preserve logout, erase private
   state on context replacement. No new backend schema/permissions/business rules.
   Tests-first module absence reproduced the gap; 10 state/failure/race regressions
   and an Idempotency-Key multipart transport regression now pass.

2. **Operational verification defect: occupied proxy ports discovered too late.**
   First actual gate passed all database tests, then failed binding 127.0.0.1:8080
   because the prior synthetic proxy restarted with Docker. Added a loopback-port
   preflight before provisioning/builds/tests, with two real-socket regressions.
   It refuses a collision and never stops another installation. Manually stopped
   only the identified old synthetic proxy; retained all volumes/data. A preflight
   is a snapshot, so a subsequent race can still legitimately fail serving.

3. **Evidence weakness: production-browser export comparison covered only the
   row suffix plus server-download equality.** Added independent literal ordered
   headers and all expected field/encoding values, including comma/quote customer
   name, source-derived number, linked opaque IDs, UTC conversion-date interval,
   line number, copied SKU/description, exact quantity and unit. Existing native
   independent CSV formatter expectations remain. Also added a real supported PDF,
   original digest/bytes and exact fields/page spans, and separate role accounts.

4. **Documentation drift.** Root README described the historical foundation;
   it now points to the active application. Active README/runbooks document
   catalogue management and explicit pricing/ERP limits; Django version corrected.
   A host recursive Ruff diagnostic entered ignored third-party scanner caches
   and failed/crashed. Explicit maintained-source lint passes; image quality gates
   retain full clean-source checks. No lint rule or failing test was disabled.

## Current verification ledger

Exact app-root commands and private evidence; command exit, not incidental
negative-test HTTP logs or PowerShell stderr labels, determines the outcome.

| Command | Actual result |
| --- | --- |
| `..\.venv\Scripts\python.exe -u scripts\quality_gates.py` | FAIL at proxy binding; preceding 845 native/239.482s, 56 order runtime/128.921s and 115 catalogue runtime/224.565s PASS; baseline log validation-2026-10-12-quality.log |
| `..\.venv\Scripts\python.exe -u scripts\quality_gates.py --run backend/var/deployment-d40b3e6da57141cbbd0d28c4ba0d8332` | IN PROGRESS; rebuild final UI, do not repeat bootstrap; final-quality.log |
| `node --test frontend/tests/*.test.js` | PASS 108, zero failures/skips, 1438.9938ms; node-final.log |
| `..\.venv\Scripts\python.exe -m unittest discover -s scripts/tests -v` | Sandbox FAIL on private temp archive writes/cleanup; approved outside-sandbox retry PASS; final 29/0.187s, scripts-final.log. Helper printed an exercised empty-page branch; no unittest skip |
| Backend-root `..\..\.venv\Scripts\ruff.exe check apps config manage.py scripts ../scripts ../deployment` and matching `format --check` | PASS, 211 maintained source files formatted; recursive dot diagnostic is a retained failed out-of-scope cache scan |
| `node --check deployment/browser.mjs`, `node --check frontend/assets/desk/catalogue.js`, `git diff --check` | PASS so far; final rerun required after any code edits |
| uv tool `pip-audit==2.10.1 --no-deps --disable-pip -r backend/var/validation-requirements.txt -f json` | PASS exit 0, ten locked packages, zero known advisory matches; package names/versions only sent to advisory service |
| uv tool `bandit==1.9.4 -r backend/apps backend/config scripts deployment -x backend/var -f json` with Python 3.14 | Exit 1 retained: zero parse/high, six medium fixed migration SQL, 106 low leads; current full-source scan includes tests |
| uv tool `detect-secrets==1.5.0 scan` | PASS execution; one Git-tracked finding in organizations/tests/test_access.py:26, a synthetic test password. New catalogue files manually inspected; no history or secret revocation proof claimed |
| Grype 0.120.1 image archive scan | Execution exit 0, security clearance FAILED/unresolved: 250 matches (5 critical/62 high/85 medium/17 low/64 negligible/17 unknown); initial image-save wrong tag failed, corrected target scanned; grype.json |

## Security review and operating limits

Manually reviewed authentication/session flush/CSRF, fresh authorization before
untrusted parsing, parameterized transaction context/SQL, organization-first locks,
tenant references and forced native RLS, immutable receipts/revisions, contained
O_NOFOLLOW private paths, digest checks, parser rlimits/seccomp/deadline, bounded
worker attempts/claim tokens, conservative formula/control-character export
rejection and non-root/private/no-store serving. New catalogue values/errors use
textContent and no local/session storage, and CSRF-bootstrap context replacement
prevents a late mutation from being sent under a new workspace/identity.

The six Bandit medium findings are migration SQL assembled from fixed internal
constants/table names (catalogue 0002; orders 0007 twice, 0010, 0011, 0014), not
request values. Low leads include deliberate acceptance assertions, fixed process
execution and synthetic fixtures; scanner status is not suppressed. Advisory
results describe available data, not certification. Uploaded files remain untrusted;
malware scanning/customer hosting controls, OS advisory result, off-site recovery,
retention/deletion, monitoring/support owners and broader audit/administration
remain gates. No finite test/scan proves the absence of vulnerabilities.

### Current image advisory findings

Grype image pinned to
anchore/grype@sha256:e4a44ef45d285b829ce6efe2642980329661bd2d18eab5fc539138d4adaebbbe;
read-only image archive, no Docker socket/private data mount. Its DB was valid,
built 2026-10-12T06:45:22Z. It scanned the final serving-tag archive, including
Python stdlib and Debian packages that pip-audit's ten-package inventory omits.
Counts are package matches, not 250 independently demonstrated application exploits.
No critical/high match lists a fixed Bookworm version: 147 matches not-fixed,
101 wont-fix, two fixed leads point only to Python 3.15 prereleases. The locked
Python contract is >=3.14,<3.15; switching to an alpha/RC to reduce a scanner count
is not a verified repair. Preserve the stable stack and unresolved release gate.

Selected critical findings were checked against primary sources:

- Debian lists [CVE-2026-5450 glibc](https://security-tracker.debian.org/tracker/CVE-2026-5450)
  and [CVE-2025-7458 SQLite](https://security-tracker.debian.org/tracker/CVE-2025-7458)
  as vulnerable in the installed Bookworm versions, with no-DSA minor-issue notes.
  SQLite's described precondition is attacker-controlled SQL; this application's
  business database is PostgreSQL. No application exploit/reachability was demonstrated.
- [CVE-2026-95210 GnuTLS](https://security-tracker.debian.org/tracker/CVE-2026-95210)
  remains unfixed and awaits upstream assessment. Python/Nginx TLS uses OpenSSL,
  but no complete native-library reachability argument or risk acceptance is claimed.
- [Python's TemporaryDirectory advisory](https://mail.python.org/archives/list/security-announce%40python.org/thread/WBHGJXKKLB7X3ZJF7NYE6M65DCUWW6QT/)
  describes a cleanup race requiring an attacker able to modify the directory tree.
  The app's private directories/UID boundaries limit that precondition; it remains
  a scanner lead for operating review. [Python 3.14.8's release](https://www.python.org/downloads/release/python-3148/)
  documents current security fixes, not blanket clearance of all stdlib advisories.

The remaining OS matches are not suppressed or presented as patched. Image
security acceptance is BLOCKED on reviewed reachability/mitigations and maintained
vendor fixes or a separately verified stable-base upgrade. Proxy/database/recovery
images were not scanned in this run and remain additional image-security gates.

## Verdicts and exact remaining pilot actions

Local functional verdict: PENDING final real-browser/runtime result. The supported
local profile can never establish that unmodeled price/account/currency/pack fields
are correct. Operational verdict: PENDING current serving/restart/restore/performance;
customer operational readiness remains incomplete even if these synthetic gates pass.
Customer pilot: BLOCKED, no overall success or release approval.

Before a real customer pilot: obtain the agreed critical-field and account/ship-to/
currency/price-basis model, authoritative catalogue/customer aliases and approved
pack/unit/price discrepancy rules; specify and test one authorized ERP sandbox
import and independently inspect resulting orders; implement bounded pilot
administration/audit/usage/retention controls; resolve actionable image advisories;
assign monitoring/support and protected off-site backup/key/restore ownership;
benchmark withheld representative orders with independent ground truth and full
handling-time/ERP outcome scoring. Public deployment/customer communication/paid
services/live ERP writes need separate authorization. No customer actions performed.
