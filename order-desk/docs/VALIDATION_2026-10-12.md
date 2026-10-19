# Order Desk validation and remediation 12 October 2026

**Supported synthetic local workflow verified; customer release BLOCKED.**
Implemented catalogue browser management and operational/performance repairs,
then executed affected gates. Image findings and unmet commercial requirements
prevent an overall product/release PASS. Failed attempts remain separate evidence.

## Authority and environment

The attached principal-engineer request authorizes $0 local synthetic fixes and
verification, followed by a verified commit and ordinary push to the configured
repository. No public deployment, live ERP write, customer message or main-database
restore is authorized or performed. Arrival: clean main at 04eec05, remote
https://github.com/user1738mike/Order-Desk. Preserve prior history.

Delivery branch: codex/principal-validation-2026-10-12. External commit 4351041
recorded earlier changes during verification; it was preserved without amend/reset.
Final source inventory: 284 implementation/configuration/test files,
backend/var/validation-2026-10-12-source-manifest.json, canonical SHA-256
63cd4250447efb2a34c58ac85c7a3e16003191a57a9045fd13b39d9a8c4002a9.

Read AGENTS.md, CODEX_BUILD_SPEC, MASTER_BUILD_PROMPT, ROADMAP, READMEs, PROJECT_STATE,
five accepted ADRs, feature contracts, the 11 October audit, and the original
3 October AI_Order_Desk_Validation_Launch_Plan_and_Pitch.docx in Downloads.
The available release-audit prompt was also read. The two original autonomous/
backup handoff references remain unavailable; repository reconciliation is the
available technical scope. No claims from old prompts/counts were accepted as proof.

Execution: this Windows/PowerShell host, Docker Desktop Linux containers. Application
is the existing Django/DRF/PostgreSQL modular monolith with native browser modules,
restricted orderdesk_app, separate orderdesk_migrator, private Linux storage and
an explicitly invoked one-job worker. First isolated gate project:
orderdesk-deployment-d40b3e6da57141cbbd0d28c4ba0d8332. Its separate cluster contains
orderdesk and test_orderdesk; only test_orderdesk receives synthetic business fixtures.
The developer/main database is not seeded/reset/restored. Private logs, fixture
credentials, CA keys, image archive and backups remain ignored under backend/var.

Final selector/native/runtime run: deployment-bc3a927654f348ad8887338017b15c60;
final four-worker installation/browser/restart: deployment-fd0cb54afaba48b38235456c9e99f35a;
fresh restored/measured data: deployment-4051647519594aa0a6724405afb02a09.
Retired only verified stopped synthetic containers/networks to reclaim exhausted
Docker pools; logs, run files, keys, backups and named volumes retained.

Pinned candidate: Python 3.14.8, Django 5.2.18, DRF 3.18.1, Psycopg 3.3.6,
pypdf 6.20.0, Gunicorn 26.2.0, uv 0.12.23, Ruff 0.16.10, PostgreSQL
18.6-bookworm, Nginx 1.30.4, Node 24.15.0. Browser comes from signed Debian
repositories; record its actual image/version rather than promising identical apt
rebuilds. Frontend type/build gates are NOT_APPLICABLE: native JavaScript is syntax
checked and exercised in Node/Chromium; collectstatic hashes the served assets.
Actual browser: Chromium 154.0.8037.92 on Debian 12. Four synchronous API workers,
four local CPU cores/512 MiB; Node 24.15.0. Additional spending $0.

## Requirements matrix

VERIFIED applies only to executed specified scope. DEFECTIVE identifies reproduced
behavior needing repair, MISSING absent engineering, BLOCKED unavailable essential
input/evidence, and EXPLICITLY DEFERRED accepted scope exclusions. Final evidence
columns are reconciled with the ledger; scope qualifications remain essential.

| Capability and acceptance criteria | Implementation across UI/API/database/operations | Current evidence and status |
| --- | --- | --- |
| A. Login, discover accessible workspaces, explicit selection, logout | accounts/views; organizations/context, selection, transactions; controller/main; cookie sessions/CSRF | VERIFIED native/restricted-role and trusted browser with separate admin/reviewer/viewer accounts, workspace selection, reload, logout and anonymous denial |
| B. Create/import catalogue; preserve exact punctuation/case/zeros, reject existing/duplicate SKUs, commit all or none | catalogue services/import_execution; forced RLS and immutable receipt; new catalogue.js, management form and Idempotency-Key transport | VERIFIED after repair: 10 controller regressions, multipart-key test, native/runtime checks and real create/dry-run/import/lost-response replay; exact punctuation/case/zeros preserved |
| C. Supported PDF/CSV private upload and original-byte download | document_intake/private_documents, digest and contained keys; orders document UI; persistent UID-10001 volume | VERIFIED supported order-bound intake, independent original PDF/CSV bytes/digests and foreign download denial. Parent created through real browser API; UI opens existing purchase-order IDs |
| D. Bounded supported extraction, original digest and truthful row/column or saved-page provenance; visible failures/retries | csv_extraction, pdf_parser/pdf_extraction, extraction_services; job leases/RLS; documents.js; explicit restricted worker | VERIFIED Linux native child, restricted worker, independent PDF fields/page spans, CSV provenance, actual interruption/lease retry, visible unsupported-CSV failure and manual path |
| E. Explicit field acceptance/rejection/correction before atomic application, stale revision rejection and durable replay | extraction_apply, immutable applications/created-row links and RLS; extraction-review.js/editor | VERIFIED native/runtime conflicts/rejection/atomicity; actual UI description correction, zero lines before explicit apply, dropped committed response and identical replay producing one corrected line |
| F. Tenant exact-SKU matching with explicit acceptance; no guessed units/prices | matching/services; current-draft revision and catalogue evidence; matching.js; forced RLS | VERIFIED tenant exact matching and protected acceptance; missing/ambiguous/inactive/stale cases reject safely. Aliases/fuzzy rules EXPLICITLY DEFERRED |
| G. Exact decimal quantities and explicit units; reject unknown price fields | strict order serializers/services, Decimal columns and constraints; text inputs/editor | VERIFIED exact quantity/unit editing and decimal/revision negatives; actual price PATCH rejected 400. Prices/currency/pack semantics BLOCKED/unmodeled; optional units remain empty and generic export omits prices |
| H. Readiness rejects missing customer/lines/quantity/match and inactive/overlong catalogue identities | readiness + one coherent annotated SELECT; UI blockers; conversion rechecks current state | VERIFIED native/runtime aggregate/filter-removal negatives and real incomplete manual draft. This is internal conversion eligibility, not customer/ERP business readiness |
| I. Atomic administrator conversion; same source returns same order, stale writes fail, snapshots/source freeze | services convert, organization/aggregate locks, unique source linkage and database guards; revision-aware frontend | VERIFIED native concurrency/stale revisions/runtime replay and real conversion/replay returning the same order ID; reviewer/viewer conversion denied |
| J. Deliberate submit/approve; immutable generic CSV; compare every critical supported field independently | export_services/csv_export and RLS/grants/leases; purchase.js private digest/size download; trusted proxy | VERIFIED native literal bytes and protected exports; real cancelled/confirmed approval, dropped export response, same artifact retrieval, digest/size and independently expected all-column saved CSV. Named ERP compatibility BLOCKED |
| K. Reload/recreate and interrupted-operation recovery preserve valid sessions, records, bytes and proposals | DB/private volumes; worker lease retry; deployment_restart, recovery_probe; browser context epochs | VERIFIED current reload/logout, actual worker interruption, storage/DB outages, API/proxy recreation and fresh encrypted restore preserving sessions/source/export/proposals |
| Anonymous/expiry/CSRF/role/revocation boundary | session flush/expiry, fresh membership checks, API permissions before input parsing; organization-first locks | VERIFIED 846 native tests, directly authenticated runtime suites and separate-role browser checks; no owner-role substitution |
| Two-tenant IDs/lists/imports/matching/files/drafts/orders/exports/jobs and connection reuse/rollback/concurrency | explicit filters, transaction-local settings, forced RLS, tenant composite FKs and minimal grants | VERIFIED final 56 order/115 catalogue direct orderdesk_app checks, revocation/races/unfiltered reads/reused and contaminated connections; separately audited maintenance fixtures and restored native RLS proof |
| Late workspace/session/role responses cannot restore private browser data | controller generations/abort signals, textContent rendering; new catalogue forms/reports erase on replacement | VERIFIED 108 native-module tests including new CSRF-bootstrap/committed-response races and real response held across workspace replacement; catalogue values cleared between identities |
| Production-like TLS/Host/cookies/private paths/body limits/health/migrations/static build | pinned non-root read-only Gunicorn/Nginx; proxy-only loopback ports; separate roles/certs; quality_gates | VERIFIED local four-worker WSGI, trusted TLS/Host/cookies/private paths/body bounds/build/clean schema and actual UID/runtime role/wrong DB-host TLS denial. Public hosting and host-browser trust not proved |
| Coordinated encrypted fresh-cluster backup/restore, no main/nonempty target | recovery_drill/recovery.py, age encryption, inventory/modes, complete/incomplete markers, separate keys | VERIFIED 117.789s fresh restore, four files/220610 raw bytes, incomplete/checksum/authenticated-tampering/nonempty guards and restored sessions/bytes/native RLS; same restored data exercised on final serving image. Off-site/customer retention/escrow MISSING |
| Representative performance with explicit provisional targets | release_measure/performance/query_budget; 5,000-item, 300-draft, 6,000-line synthetic profile; sampled resources | VERIFIED provisional read profile after repairs: p95 212.235ms, 59.241 req/s, zero errors; every route <=500ms, 11/10/12 SQL <=25. No approved production SLO, write/job/soak or customer-capacity claim |
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

5. **Measured pagination/capacity defect.** The first workload failed at 503.964ms
   aggregate p95/600.33ms draft-list p95. A native regression reproduced COUNT(*)
   joining/grouping line histories; indexed tenant-filtered correlated totals now
   leave pagination count on headers only and materialize counts without extra
   serializer queries. The new test and all 846 native/171 restricted-role checks
   passed. The query-only rerun still failed at 712.028ms aggregate p95, with API
   peak 188.73% against a two-CPU cap. Its window overlapped a code-scanner invocation;
   it is retained, not used to claim a causal latency improvement. Four sync
   workers/four CPUs then passed the same workload/targets in a reserved timing
   window: p95 212.235ms, draft-list p95 198.012ms. Fresh four-worker browser and
   restart/role/TLS checks passed. No pool, cached authorization or grant change.

6. **Standalone browser recovery ordering.** Registry DNS interrupted the combined
   runner, which correctly stopped its services. Standalone browser retry built
   successfully but attempted fixtures before starting PostgreSQL. Require a
   healthy owned DB before guarded fixtures, preserve existing fixture files,
   then start API/proxy. Three orchestration regressions and actual stopped-DB
   browser retry passed; these host tests do not substitute for native RLS proof.

7. **Retained verification projects exhausted Docker network pools.** First fresh
   restore failed before restoration while creating a network. Captured logs and
   removed only reviewed stopped synthetic containers/networks, retaining all
   data volumes. Added explicit identity-checked `local_deploy.py retire`, refusing
   running projects and log-capture failure, with three host regressions and actual
   completed-run retirement proof. No automatic cleanup/global prune/volume removal.

## Current verification ledger

Exact app-root commands and private evidence; command exit, not incidental
negative-test HTTP logs or PowerShell stderr labels, determines the outcome.

| Command | Actual result |
| --- | --- |
| `..\.venv\Scripts\python.exe -u scripts\quality_gates.py` | FAIL at proxy binding; preceding 845 native/239.482s, 56 order runtime/128.921s and 115 catalogue runtime/224.565s PASS; baseline log validation-2026-10-12-quality.log |
| `..\.venv\Scripts\python.exe -u scripts\quality_gates.py --run backend/var/deployment-d40b3e6da57141cbbd0d28c4ba0d8332` | Uninterrupted PASS exit 0 before pagination tuning: 845 native/257.329s, 56 order/167.738s, 115 catalogue/415.732s, 108 Node/4697.875873ms; trusted browser and restart PASS; final-quality.log |
| Same runner `--run backend/var/deployment-bc3a927654f348ad8887338017b15c60` after query fix | Final source native 846/246.529s, order runtime 56/103.326s, catalogue runtime 115/172.108s, lint/format/lock/deploy/migration/TLS probe PASS. Command FAIL at browser-image registry DNS; quality-remediated.log; not relabeled uninterrupted PASS |
| `scripts/local_deploy.py browser --run <bc3a927...>` | Build retry PASS, fixture ordering FAIL while DB stopped; corrected standalone retry actual browser PASS, browser-final.log. No test data reset or mocked API |
| Pinned acceptance container `node --test` with all explicit `/frontend/tests/*.test.js` paths; helper `restart-checks --run <bc3a927...>` | PASS 108/1544.595471ms, zero failed/skipped; node-container-final.log. Actual storage/DB outages, recreation, role/UID/DB TLS and persisted bytes/session/proposals PASS; restart-final.log |
| Helper `build`, `prepare`, `browser`, `restart-checks` then `stop`, each `--run backend/var/deployment-fd0cb54afaba48b38235456c9e99f35a` | Final four-worker clean installation, all schema/role prerequisites, real separate-role browser/source-to-export/context negatives and recovery PASS exit 0; four-worker.log. Backend behavior unchanged from the 846-test source; no needless full native rerun for worker allocation |
| `node --test frontend/tests/*.test.js` | PASS 108, zero failures/skips, 1438.9938ms; node-final.log |
| `..\.venv\Scripts\python.exe -m unittest discover -s scripts/tests -v` | Sandbox FAIL on private temp writes/cleanup; approved retry PASS; final 35/0.229s, scripts-final.log. Helper printed an exercised empty-page branch; no unittest skip |
| Backend-root `..\..\.venv\Scripts\ruff.exe check apps config manage.py scripts ../scripts ../deployment` and matching `format --check` | PASS, 213 maintained source files formatted; recursive dot diagnostic retained as failed out-of-scope cache scan |
| All frontend module `node --check`, deployment browser syntax and `git diff --check` | PASS; native modules require no TypeScript or package build. Serving build executes collectstatic with module/manifest hashes |
| Helper compose `up -d --wait --wait-timeout 120 db`, then manage `makemigrations --check --dry-run`, `migrate --check` on final fd0cb run | PASS no drift/pending migrations; final-consistency-retry.log. Prior consistency command attempted stopped DB and failed; corrected operator ordering, no schema reset |
| Helper compose runtime `api python manage.py verify_catalog_rls` and `verify_order_rls`, with local settings on isolated main orderdesk | Expected exit 1 and exact refusal to populate anything except test_orderdesk, before fixtures; both guards PASS, main-guard logs. Local production DEBUG-false refusal not substituted |
| `scripts/recovery_drill.py --source backend/var/deployment-d40b3e6da57141cbbd0d28c4ba0d8332` | Initial FAIL exhausted address pools before restore; retry PASS exit 0/117.789s. Backup-a2912190868d4ff4a384700d1749d88f, fresh target 405164..., four files/220610 raw bytes; recovery-retry.log |
| `scripts/release_measure.py --large-fixture --run backend/var/deployment-4051647519594aa0a6724405afb02a09` | Initial FAIL 503.964ms, query-only FAIL 712.028ms retained; final four-worker PASS exit 0/212.235ms p95, 59.241 req/s, zero errors; performance-four-worker.log; preserved before/after resource samples |
| uv tool `pip-audit==2.10.1 --no-deps --disable-pip -r backend/var/validation-requirements.txt -f json` | PASS exit 0, ten locked packages, zero known advisory matches; package names/versions only sent to advisory service |
| uv tool `bandit==1.9.4 -r backend/apps backend/config scripts deployment -x backend/var -f json` with Python 3.14 | Final exit 1 retained: zero parse/high, six medium fixed migration SQL, 109 low leads; full-source scan includes tests; bandit-final.json |
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
malware scanning/customer hosting controls, unresolved OS advisories, off-site recovery,
retention/deletion, monitoring/support owners and broader audit/administration
remain gates. No finite test/scan proves the absence of vulnerabilities.

### Current image advisory findings

Grype image pinned to
anchore/grype@sha256:e4a44ef45d285b829ce6efe2642980329661bd2d18eab5fc539138d4adaebbbe;
read-only image archive, no Docker socket/private data mount. Its DB was valid,
built 2026-10-12T06:45:22Z. It scanned the catalogue serving-tag archive before the
selector/worker-only changes, including
Python stdlib and Debian packages that pip-audit's ten-package inventory omits.
Counts are package matches, not 250 independently demonstrated application exploits.
No critical/high match lists a fixed Bookworm version: 147 matches not-fixed,
101 wont-fix, two fixed leads point only to Python 3.15 prereleases. The locked
Python contract is >=3.14,<3.15; switching to an alpha/RC to reduce a scanner count
is not a verified repair. Preserve the stable stack and unresolved release gate.

Scanned serving identity: sha256:4008f0400ba3daeab582b4d4a580e0f58e4dd6dbdba97f15343b2369f2e80dab.
Image-layer comparison confirmed unchanged base/Python/dependency layers through
the selector fix; only application/assets/tooling layers changed. Worker allocation
adds no dependency/base change. A second full archive scan was not claimed.

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

## Performance and recovery measurements

No approved operational SLO was found. Before measurement retained the 11 October
provisional targets: aggregate and every route p95 <=500ms, >=10 req/s, zero HTTP
errors, <=25 application SQL statements excluding session-authentication queries.
Environment: shared Windows host, Docker Linux x86_64, eight CPUs/8,179,277,824 bytes
RAM. Same restored data and fixed eight-client/200-request closed-loop profile:
5,000 catalogue items, 300 drafts, 6,000 lines in two additional synthetic tenants,
100-line order plus the acceptance tenants/private export. One warm read per route,
40 measured reads each, new certificate-validating TLS connection per request.

| Measurement | Initial two workers | Query fix/two workers | Final four workers |
| --- | ---: | ---: | ---: |
| p50 ms | 201.573 | 333.629 | 113.406 |
| p95 ms | 503.964 | 712.028 | 212.235 |
| p99 ms | 802.017 | 841.058 | 297.327 |
| requests/s | 31.252 | 20.427 | 59.241 |
| errors | 0 | 0 | 0 |
| result | FAIL | FAIL | PASS |

Final per-route p95 ms: catalogue 225.955; drafts 198.012; readiness 163.527;
source order 295.399; private export 188.769. Maximum response 22,078 bytes.
Application SQL: drafts 11, readiness 10, source order 12, including an assertion
that the restricted-runtime pagination COUNT does not read line histories.
Actual final API CPU quota 4,000,000,000 nanoCPUs and four booted worker PIDs were
inspected. Fifteen resource snapshots: API peak 232.24% core CPU/218.1MiB of512MiB;
DB 55.36%/45.41MiB of512MiB; proxy 52.66%/4.789MiB of128MiB. Samples are approximate
observed peaks, not continuous maxima or memory-exhaustion proof. Previous samples
are retained separately. Final timing ran without another verification/scanner
workload; the intermediate overlapping sample is not a causal performance claim.
Short reads do not establish writes/jobs saturation, large-file contention, long
soak or customer capacity. The system is not described as optimal.

Actual fresh restore: 117.789 seconds including key/tool/target setup, encryption,
guard checks, restoration and HTTP/runtime proof; four files and 220,610 raw dump/
file bytes. Not an approved production RTO/RPO. Sources were stopped for collection;
SQL restoration was transactional, file restoration separately marked. Incomplete,
tampered and nonempty targets refused before further writes. Interrupted targets
cannot be reused. Keys/backups share this host, so off-site disaster recovery,
retention/key escrow/customer coverage remain missing. The unchanged restored data
was subsequently exercised on the final four-worker image with valid sessions.

## Verdicts and exact remaining pilot actions

Local functional verdict: VERIFIED for the documented synthetic order-bound
PDF/CSV, review/correction/application, exact matching, conversion/approval and
generic CSV profile, including catalogue browser management. It does not establish
correctness of unmodeled price/account/currency/pack fields or complete the original MVP.
Operational verdict: local serving/restart/restore and provisional read targets
passed; customer operational readiness is INCOMPLETE because image-security,
off-site recovery, retention/quotas/admin/audit/monitoring/support gates remain open.
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
