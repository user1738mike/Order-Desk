# Project state

## Active checkpoint 12 October 2026 verified remediation customer release blocked

The user authorized local synthetic verification/remediation and ordinary Git
delivery with $0 extra spending. Arrival clean main at 04eec05; external commit
4351041 recorded earlier work during verification and was preserved. Delivery
branch codex/principal-validation-2026-10-12. No reset/amend/force push, public
deployment, paid service, customer message, live ERP write or main-data restore.

Read the final [validation report](VALIDATION_2026-10-12.md) for the requirements
matrix, exact commands, failures, security leads, provisional measurements and
remaining pilot gates. The original launch-plan DOCX was read; synthetic local
scope is narrower than its pricing/account/pack/ERP/customer-outcome requirements.

Delivered: administrator catalogue browser creation/validation/atomic import and
same-file/key unknown-outcome replay; independent all-column CSV/PDF provenance
and separate-role browser evidence; early port-collision refusal; stopped-project
retirement preserving volumes/logs; healthy-DB-before-browser-fixtures recovery;
tenant-filtered page-only draft line totals/header-only pagination count; measured
four-sync-worker/four-CPU local serving, same 512MiB/protections. No schema or
business-rule change. Prices/currency/pack/account rules remain unmodeled/blocked.

Actual final evidence, all local synthetic PostgreSQL/Linux Docker/PowerShell:

- Native backend: 846 tests/246.529s PASS, including red-then-green pagination
  regression. Direct orderdesk_app: 56 order/103.326s and 115 catalogue/172.108s
  PASS, no owner substitution/skips. Run bc3a927654f348ad8887338017b15c60.
- Node: 108 tests PASS, zero skips; pinned container 1544.595471ms. Host scripts:
  35/0.229s PASS. Maintained-source Ruff/format 213 files, lock/migration/deploy,
  collectstatic, JS syntax and whitespace PASS. Final actual main-target refusal
  checks exit1 with exact test_orderdesk refusal; no fixture writes.
- Real trusted Chromium: separate admin/reviewer/viewer, catalogue create/import/
  dropped-response replay, actual PDF/CSV child/worker/provenance, UI correction/
  application replay, exact matching, conversion replay, cancelled/confirmed
  approval, dropped export response and independently expected saved CSV PASS.
  Four-worker clean serving/restart/UID/role/TLS/private-path/health/volume recovery
  PASS on fd0cb54afaba48b38235456c9e99f35a. No CSP/uncaught JS or overflow failure.
- Fresh encrypted restore PASS 117.789s; four files/220610 raw bytes; backup
  a2912190868d4ff4a384700d1749d88f -> fresh 4051647519594aa0a6724405afb02a09.
  Restored sessions/private bytes/proposals/native RLS and negative guards PASS.
  Same restored dataset exercised on final four-worker image; no customer RTO/RPO.
- Performance same 5000-item/300-draft/6000-line/100-order-line workload, eight
  clients/200 HTTPS reads: final p50 113.406ms, p95 212.235ms, p99 297.327ms,
  59.241 req/s, zero errors; every route p95 <=500ms, SQL 11/10/12 <=25. API
  sampled peak 232.24%/218.1MiB, DB 55.36%/45.41MiB, proxy 52.66%/4.789MiB. Short
  read profile, not customer capacity/write/job/soak proof or optimality claim.
- pip-audit ten locked packages zero known matches. Bandit final zero parse/high,
  six constant migration-SQL medium and 109 low leads, exit 1 retained. Tracked-source
  secret scan one synthetic test password; no history clearance. Grype current DB
  250 package matches, including 5 critical/62 high, unresolved; primary Debian/
  Python triage in report, no fixed high/critical Bookworm versions listed.

Failed attempts retained: initial proxy binding collision; sandbox temp test
permissions; recursive lint entering scanner cache; image-save wrong tag;
Docker network-pool exhaustion before restore; registry DNS before browser build;
standalone stopped-DB fixture ordering; consistency command before DB startup;
two-worker p95 503.964ms and query-only 712.028ms. Repairs/retries do not relabel
failed commands as uninterrupted passes. First 845-test candidate full runner did
PASS; final query source passed native/runtime stages, then explicit browser/
restart stages after failure. Four-worker serving was independently reverified.

Private evidence backend/var/validation-2026-10-12-*. Source manifest 284 files,
canonical SHA256 63cd4250447efb2a34c58ac85c7a3e16003191a57a9045fd13b39d9a8c4002a9.
All verification projects stopped; volumes, keys, backups and logs retained.
Historical synthetic viewing proxy was resumed using its existing older image;
it is not the current candidate preview. No verification continues in the background.

Local functional verdict: supported synthetic profile VERIFIED; original MVP
INCOMPLETE. Local operating proofs/read targets PASS; customer operations/security
INCOMPLETE. Pilot/release BLOCKED on image findings, authoritative critical fields/
price/unit/pack/account/ERP rules and sandbox import, independent representative
historical orders/handling time, secure pilot admin/audit/usage, off-site backup/
retention/key custody and monitoring/support ownership. No overall release PASS.

Exact next engineering action: perform and record stable-image advisory/reachability
triage against the selected critical/high package matches, keeping the stable
locked stack and $0 budget; do not claim clearance or launch. In parallel obtain
authoritative critical-field/rule/ERP sandbox inputs and define the bounded pilot
administration/audit/usage contract before its RLS/browser implementation. Original
general PDF/OCR/LLM/fuzzy/inbox/live ERP/payment/distributed deferrals remain intact.

## Active checkpoint: host browser connectivity repaired

2026-10-11: user requested browser access and reported the URL unreachable.
Container health/probes had passed, but the proxy attached only to an internal
network: configured HostConfig bindings existed while NetworkSettings port mappings
were empty, and Windows TCP 127.0.0.1:8443 returned connection refused. Recreating
the proxy alone reproduced the failure. Added a separate `browser_edge` bridge
joined only by the proxy; API/database networks remain internal and only proxy
ports bind 127.0.0.1. This permits outbound connectivity for the proxy itself.
No app code, credentials, tenant data or database schema changed.

Recreated proxy in the existing synthetic run
`deployment-b14a8c83d7384d0689f40eaf2ddf5709`. Actual `docker port` now reports
127.0.0.1:8080 and :8443. Windows Python connected to 127.0.0.1 with TLS SNI
orderdesk.localhost, verified the public CA and hostname, and received HTTP 200
with the Order Desk shell. Standard Windows DNS lookup for orderdesk.localhost
failed; the host probe deliberately uses the loopback address with canonical SNI.
`scripts/local_deploy.py probe --run backend/var/deployment-b14a8c83d7384d0689f40eaf2ddf5709`
PASS, exit 0; `backend/var/browser-host-port-probe.log`. Services remain running
for user viewing. Browser open was queued in Codex; visual page success is not
claimed. Browser inspection of its internal error page was rejected by browser
URL policy; no internal-page workaround or certificate bypass was attempted.
Host certificate trust has not been installed and requires explicit operator action.

This Compose change follows the frozen release audit; its recorded source manifest
and full test result remain historical evidence, not a full gate for this updated
topology. Next action: confirm host browser access/trust, then resume the secure
tenant administration/audit/usage contract identified in the release report.

## Active checkpoint: release audit and local remediation verified

2026-10-11: audited the dirty working tree on `main` at `4648dea`, preserving
arrival changes. The user's six explicit audit requests govern this work; attached
prompts were reference material, not independent authorization to publish or spend.
See [RELEASE_AUDIT_2026-10-11.md](RELEASE_AUDIT_2026-10-11.md) for the original-plan
comparison, evidence, failures, blockers and explicit deferrals. **No overall
customer release PASS.** The two older Downloads handoff files were absent; the
available original launch-plan DOCX and release-audit reference were read.

Delivered in this checkpoint: Django 5.2.18 security update/lock; bounded legacy
order nested responses with five native API regressions; coordinated encrypted
synthetic PostgreSQL/private-file recovery with guarded fresh targets; application
SQL/read-load/resource measurements; health-checked local WSGI connection reuse
and two API CPUs; browser reload-race repair and actual unsupported-CSV-to-manual
fallback verification. Generic production/ASGI tuning and customer backup are open.

Final commands/results from app-root PowerShell:

- `..\.venv\Scripts\python.exe -u scripts/quality_gates.py`: **PASS, exit 0**, fresh
  `backend/var/deployment-b14a8c83d7384d0689f40eaf2ddf5709`; evidence
  `backend/var/release-quality-candidate.log`. 845 native tests/326.120s,
  56 direct-runtime order checks/143.914s, 115 direct-runtime catalogue
  checks/228.174s, 97 frontend tests/1.626s, no reported skips. Lock/lint/deploy/
  migration checks, trusted HTTPS/CSRF/cookies/private paths, real Chromium,
  worker interruption/retry, review/application/conversion replay, operator
  approval/export/lost-response recovery, unsupported fallback, role/context
  denial, mobile layout and logout/reauth all passed. Storage/DB outage and
  API/proxy recreation preserved session, bytes and extraction result; actual
  UID/runtime DB role and hostname-validating TLS passed.
- `python -m unittest discover -s scripts/tests`: PASS, 27 tests/0.251s,
  `backend/var/release-script-tests-final.log`. Final host Ruff check/format:
  scripts/deployment 25 files, PASS; backend 185 files in final gate, PASS.
  JS syntax and `git diff --check` passed.
- `scripts/recovery_drill.py --source backend/var/deployment-a6449951c07a439d9a15471c66f3111b`:
  PASS, 131.324s; `release-restore-final-proof.log`. Encrypted set
  `backup-65994c05efb94996b2c37f57f27d30f4`, fresh restored target
  `deployment-d8f0c0f369884690a20ed0f8f7c0c730`. Eight private files and
  223,512 raw dump/file bytes; incomplete/tampered/nonempty guards and actual
  restored HTTP/session/download/job/native RLS proofs passed. Interrupted
  restore targets must be discarded; off-site/retention/customer recovery is missing.
- `scripts/release_measure.py --large-fixture --run <restored target above>`:
  final PASS, `release-performance-capacity.log`, eight clients/200 HTTP reads,
  zero errors, p95 210.881ms, 50.488 req/s. Explicit aggregate/each-route
  p95 target <=500ms, throughput >=10/s; SQL budget <=25, measured 10/12.
  Dataset adds two tenants, 5,000 catalogue items, 300 drafts, 6,000 draft lines
  and a 100-line order. Earlier 882.767ms and larger-data 588.250ms failures
  remain recorded; connection reuse and two API CPUs resolved this tested load.
  Short read profile does not establish write/job/soak or customer capacity.
- pip-audit: zero known matches across ten pinned packages, exit 0. Bandit
  final Python 3.14 scan: zero parse errors/high, six medium fixed-migration-SQL
  leads and 59 low findings manually triaged, exit 1 retained. Secret scanner
  source leads are test/build placeholders; no history clearance claimed.
  Grype image scanner BLOCKED after three registry/TLS failures.

All isolated audit projects were stopped with volumes/evidence retained; no
developer/customer/main data was restored. No commit/push/deployment or customer
messages were performed. Private raw logs/fixtures/cookies/keys stay ignored.
Implementation inventory: `backend/var/release-source-manifest.json`, 276 files,
SHA-256 `e1aa4a294052ee28d5c0ce4528d82509e0bb59a1ff39fedcaafe094f88808311`.

Next engineering action: define and implement bounded tenant administration,
general audit history and usage limits with native RLS/concurrency/browser proofs.
Customer pricing/pack/alias/critical-field definitions, a named ERP sandbox/import
proof, representative withheld orders and pilot outcomes are required externally.
Customer recovery custody/retention, hosted CI, monitoring/support/retention and
image advisory clearance remain open. Do not launch on synthetic evidence alone.

## Active checkpoint: operator approval/export verified locally

2026-10-11: continued `main` at `4648dea`, preserving all arrival dirty serving,
health/export/dependency work and private evidence. Added the native-module
purchase-order screen linked from conversion and the Approval & export tab.
It displays current exact copied lines/state, deliberate submit/approve
confirmation, bounded generic CSV preview/blockers/status, explicit generation
and SHA-256/size-verified private Blob download. Context/role replacement cancels
late responses. Ambiguous mutations require a successful status check and another
deliberate action; no automatic write retries or browser persistence were added.
Backend business code/schema/policies and the existing profile remain unchanged.
See OPERATOR_APPROVAL_EXPORT.md for behavior/responsibilities and limitations.

Candidate verification (app-root PowerShell, host Python/Node and fresh isolated
project `orderdesk-deployment-91d2714587224cde996ec9c82b16380a`):

- `node --test frontend/tests/purchase.test.js`: PASS, exit 0, 12 focused tests.
- `node --test frontend/tests/*.test.js`: final PASS, exit 0, 97 tests,
  zero failed/skipped, 647.8509ms; backend/var/purchase-node-final.log.
- Host Ruff check/format backend/frontend and scripts/deployment: PASS, exit 0,
  185 + 17 files. JS syntax and diff whitespace checks passed.
- `..\.venv\Scripts\python.exe scripts/local_deploy.py init`: fresh run identity.
  All following helper commands use `--run
  backend/var/deployment-91d2714587224cde996ec9c82b16380a`.
- Helper `build`, `prepare`: PASS, exit 0, fresh separate roles/databases/private
  volumes and all migrations through orders 0014; no developer DB fixture writes.
- Helper `compose ... -- run --rm manage python manage.py test apps.web.tests
  apps.orders.tests.test_csv_export --settings=config.settings.test --keepdb
  --noinput`: PASS, exit 0, 16 tests, 8.672s, synthetic dedicated PostgreSQL;
  purchase-native.log. Maintenance-role behavior proof is not RLS proof.
- Final source rebuild initially FAIL, exit 1, Docker Hub TLS handshake timeout;
  retry PASS, exit 0; purchase-build-final.log and purchase-build-retry.log.
- Helper `compose ... -- run --rm rlscheck python manage.py verify_order_rls`:
  PASS, exit 0, 56 tests, 126.467s, directly authenticated orderdesk_app with
  separately audited maintenance fixtures; purchase-order-rls.log.

Final gates using the same helper/run:

- `up`, `probe`: PASS, exit 0, isolated API/proxy healthy and actual trusted
  HTTPS chain/hostname, cookie/CSRF/Host/header/static/private-path/body-limit/
  redirect checks; purchase-up.log and purchase-probe.log.
- `browser`: PASS, exit 0 through the real restricted API/worker and trusted
  proxy. Same-user viewer can read its order but has no approval/export controls,
  and an actual forged export POST returns 403. Cancelled submit confirmation
  leaves server state draft; confirmed submit/approve progress the real order.
  A Fetch response-stage interception drops the committed export response (no
  API mock). The UI reports unconfirmed outcome and disables further writes/
  downloads until deliberate refresh retrieves the successful artifact. Explicit
  generation retrieves that same artifact ID. The download control verifies
  digest/size and its actual saved CSV equals independently retrieved private bytes.
  A real detail response held across workspace replacement cannot restore order
  summary/line/preview data. Existing intake, actual worker interruption/lease
  recovery, provenance application, matching and conversion/replay still pass.
  Desktop/mobile overflow checks pass; no uncaught JS/CSP errors. Evidence:
  purchase-browser.log and purchase-browser-final.log. Final rerun also captures
  the full page after the initial screenshot showed only the header.
- `restart-checks`: PASS, exit 0, required storage/DB outages yield ready 503/live
  200, dependencies recover, API/proxy recreation preserves private source/export
  bytes, secure session and extraction result; API/worker are actual UID 10001 /
  session/current role orderdesk_app with validated DB TLS and wrong-hostname
  denial; purchase-restart-checks.log. Screenshot-only harness change afterward
  does not change serving/runtime behavior; this gate was not needlessly repeated.
- Pinned container Node 24.15.0 `node --test` with every explicit
  `/frontend/tests/*.test.js` filename: PASS, exit 0, 97 tests, no failed/skipped,
  1588.920262ms; purchase-container-node.log. Commands use the helper's Compose
  prefix plus `-f compose.production-acceptance.yaml` and DEPLOYMENT_RUN resolved
  to this run. Chromium is 154.0.8037.92 on Debian 12, read from the final image;
  apt rebuilds remain mutable. Final images: serving `09b98cd4ec85`, proxy
  `1c0cf7486940`, browser `bf0042965b46`, initialize `9034b25c01c0`.
- Final JS syntax, Ruff/script/deployment format and diff checks: PASS, exit 0.
  Full-page synthetic purchase.png was inspected: readable exact values/status,
  wrapped identifiers, clear approval/export actions and contained tables.
- `stop` in finally: PASS, exit 0; only the fresh isolated project stopped, volumes
  and private diagnostic evidence retained. No background verification remains.

Production responsibilities changed: purchase.js owns validation/controller/render;
main.js owns routing, confirmation and scoped Blob download; orders-api.js parses
purchase routes; template/CSS expose the controls. purchase.test.js adds 12 meaningful
state/failure regressions. deployment/browser.mjs and fixtures.py extend isolated
acceptance, including a guarded synthetic viewer-order fixture. Backend business
logic/schema/RLS are unchanged. Existing arrival changes were preserved; no broad
full native/catalogue rerun was warranted for this frontend-only increment.
Private credentials/logs/images/screenshots stay ignored. No commit/push, customer
data writes, real external delivery or public deployment has been performed.

Exact next task: inventory the current database/private documents/export/job state
and deployment writer boundaries; write one coordinated maintenance-window backup
ADR and implement protected complete/incomplete recovery sets with guarded fresh
isolated restoration. Reuse the pinned stack and separate trusted operator role;
prove main/nonempty/unsafe target refusal, independent expected private checksums,
restored ownership/grants/native RLS and the operator intake-to-export workflow.
Consult the supplied backup/restore reference and existing source; do not treat
restart evidence as restored-data proof. Backup/restore remains NOT_IMPLEMENTED.

## Active checkpoint: local serving verification completed in resumed stages

2026-10-11: resumed `main` at
`4648dea` (three commits ahead of the locally recorded origin/main). Arrival
already contained tracked export/health/dependency changes and untracked serving,
proxy, acceptance and CI tooling. Preserved that work and all ignored private
evidence. No commit, push, reset, main fixture writes or restore was performed.
The supplied handoff documents were technical references for the explicit
continuation request; their embedded publication authorization was not adopted.

Recovered the actual failure from the previous private gate log: the read-only
quality container could not create uv's lock/cache temporary file under
`/root/.cache/uv`. Set only `quality.environment.UV_CACHE_DIR=/tmp/uv-cache`, using
the existing 16 MiB bounded tmpfs and preserving network isolation/read-only root.
Added the reconciled build specification and linked it from AGENTS.md; updated
the existing roadmap and quality runbook rather than creating competing state.

Verification ledger for this continuation (PowerShell from the application root):

| Command / environment | Scope | Result / limitation |
| --- | --- | --- |
| `..\.venv\Scripts\python.exe -m unittest discover -s scripts/tests -v` / host Python 3.14 | Existing offline operator scripts | PASS, exit 0: 23 tests, 0.183s. Optional live exact-SKU inspection printed its existing no-fixture message; no unittest skips. |
| `node --test frontend/tests/*.test.js` / host Node | Existing frontend regression | PASS, exit 0: 85 tests, no failures/skips, 1206.7292ms. |
| `..\.venv\Scripts\ruff.exe check backend frontend` and `format --check backend frontend` / host | Backend/frontend lint and format | PASS, exit 0; 185 files already formatted. |
| `..\.venv\Scripts\ruff.exe check --config backend/pyproject.toml scripts deployment` and corresponding `format --check` / host | Operator/deployment lint and format | PASS, exit 0; 17 files already formatted. |
| `docker compose --project-name orderdesk-deployment-35842149cf884faabb43a72e3af6aa15 --env-file backend/var/deployment-35842149cf884faabb43a72e3af6aa15/run.env -f compose.production-local.yaml run --rm --no-deps quality uv lock --check --offline` / existing isolated quality image | Reproduce repaired cache boundary | PASS, exit 0: 11 packages resolved, 14ms, read-only root/network disabled. |
| `..\.venv\Scripts\python.exe scripts/quality_gates.py --run backend/var/deployment-35842149cf884faabb43a72e3af6aa15` / isolated Docker project | Required sequential candidate gates | First attempt FAIL, exit 1: Docker Hub token connection timeout before image build. Retry passed builds/lint/format/lock, deployment checks and migration drift check; native/runtime/browser/restart result pending below. |
| `git diff --check` / host | Tracked diff whitespace | PASS, exit 0. |

The retry passed all **840 native PostgreSQL tests in 339.802s** (no skips).
Its order-runtime stage then failed **24 of 56** methods because the deployment
hostname was inherited by local verifier clients sending `HTTP_HOST=localhost`.
Corrected only `rlscheck.DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1`; API/proxy hosts
and HTTPS settings remain unchanged. The corrected order verifier passed **56
tests in 136.552s**, directly as orderdesk_app. Catalogue/browser/restart checks
continue separately; the original automated invocation exited 1 and is not
misreported as a successful whole-run invocation. No backend source changed
after the passed native suite, so it is not repeated for this verifier-only fix.

Retry private log: `backend/var/deployment-gates-retry.log`; initial failed attempt:
`backend/var/deployment-gates-resume.log`. Corrected runtime outputs are in
`backend/var/continuation-order-rls.log` and `continuation-catalog-rls.log`.
The exact rerun for each is `..\.venv\Scripts\python.exe scripts/local_deploy.py
compose --run backend/var/deployment-35842149cf884faabb43a72e3af6aa15 -- run --rm
rlscheck python manage.py verify_order_rls` (replace the final command with
`verify_catalog_rls` for catalogue). `compose ... -- up -d --wait --wait-timeout
120 db` restarted this run's database after the failed runner stopped it.
Run identity was checked and no browser
fixture existed before native tests. Tests use this run's separate PostgreSQL
instance, not the developer database. Native tests use migrator credentials;
the subsequent verifiers connect directly as orderdesk_app. Those results must
remain distinct. Cached image IDs observed during the retry: serving
`9582c1d4bba6`, proxy `42af61663e9b`, quality `510226b00787`, initialize
`73c68daa65b3`, PostgreSQL `3725f4e2499e`. Browser build identity/version must
be recorded after acceptance, not inferred from an older image.

### Final resumed-stage results

All applicable serving candidate gates passed in the recorded stages. The automated
whole-run invocation itself failed at the verifier host setting; no successful
single uninterrupted `quality_gates.py` invocation is claimed. Subsequent changes
only affect verifier environment, browser harness and documentation, so passed
native/runtime checks remain applicable; production backend/frontend code was not
changed during this continuation.

| Exact entry point / role | Result and private evidence |
| --- | --- |
| `local_deploy.py compose --run <run> -- run --rm rlscheck python manage.py verify_catalog_rls` / direct orderdesk_app with audited migrator fixtures | PASS, exit 0: 115 tests, 246.705s; continuation-catalog-rls.log. |
| `..\.venv\Scripts\python.exe scripts/local_deploy.py up --run backend/var/deployment-35842149cf884faabb43a72e3af6aa15` | PASS, exit 0: isolated DB/API/proxy healthy; continuation-up.log. |
| Same helper/run, `probe` action / CA-validating proxy client | PASS, exit 0: TLS chain/hostname, static manifest, headers/Host, cookies/CSRF, private paths, body limit and HTTP redirect; continuation-probe.log. |
| Same helper/run, `browser` action / Node 24.15.0, Chromium 154.0.8037.92, restricted API/worker | PASS, exit 0: trusted HTTPS/static/CSP, secure session, workspace isolation, private original bytes, actual parser-entry interruption and attempt-two recovery, provenance review/application replay, exact matching, conversion replay, approval and private export replay/download; continuation-browser-final.log. |
| Same helper/run, `restart-checks` action / restricted API/worker and CA-validating client | PASS, exit 0: storage and DB outages produce ready 503/live 200; dependencies recover; API/proxy recreation retains secure session, exact source/export digests and immutable extraction result; UID 10001, actual orderdesk_app session/current role, DB TLS and wrong-hostname rejection; continuation-restart-checks-final.log. |
| Same isolated Compose prefix, `run --rm --no-deps browser node --test` with every sorted `/frontend/tests/*.test.js` filename supplied explicitly | PASS, exit 0: 85 tests, zero failed/skipped, 2450.678093ms; continuation-container-node.log. |
| Same local Compose prefix, `run --rm --no-deps -e DATABASE_NAME=orderdesk rlscheck python manage.py verify_order_rls` and `verify_catalog_rls` | PASS refusal proof: both exit 1 with `Refusing to populate anything except test_orderdesk.` before fixture writes; continuation-guard-*.log. |
| Same helper/run, `stop` action in finally | PASS, exit 0: only run-owned project stopped; all volumes retained; continuation-stop.log. |
| Final host Ruff check/format for scripts/deployment, `node --check deployment/browser.mjs`, `git diff --check` | PASS, exit 0. |

Here `<run>` is `backend/var/deployment-35842149cf884faabb43a72e3af6aa15`, and the
helper is the host Python/script command above. The exact Docker prefix is recorded
in the cache-check ledger entry. Acceptance adds `-f compose.production-acceptance.yaml`
and `DEPLOYMENT_RUN` set to the resolved run directory. Existing quality runner
constructs the explicit frontend test filename list; no shell glob assumption.
Final browser image ID is `584cdc2b1174`; Chromium version was read using that
image's `chromium --version`. Apt tooling rebuilds can resolve a different version.

Two browser/restart harness defects were corrected without relaxing assertions:
the matching button selector now uses the actual `matching-load` ID; recovery
baseline computes SHA-256 from independently known uploaded CSV bytes, verifies
upload length and extraction `source_sha256`, then stores that expectation privately.
The document API intentionally does not expose a sha256 field. Initial private
browser/restart logs preserve the failures; final logs preserve successful reruns.
The application API contract and backend were not modified to fit the harness.

Changed responsibilities this session: `compose.production-local.yaml` holds the
bounded uv cache and verifier-only host fix; `deployment/browser.mjs` holds accurate
UI selectors and independently bound recovery evidence; AGENTS/build spec/roadmap/
quality runbook/state hold continuation constraints and actual verification.
All arrival export/health/dependency/serving work remains local and preserved.
No commit/push was performed. Main data, public hosting, DNS, host trust and
external messages were not touched. No ongoing verification process remains.

Exact next implementation task: add explicit operator submit/approve and generic
CSV export preview/generate/status/download controls using the existing order API
and GENERIC_CSV_EXPORT.md contract, with identity/workspace-scoped state and deliberate
ambiguous-outcome reconciliation; prove them in the real restricted-role browser.
Use a fresh quality-gate project for any later full native run: this retained run
now contains browser evidence and the gate runner correctly refuses to flush it.
Coordinated protected backup/isolated restore follows that workflow dependency;
it remains NOT_IMPLEMENTED. Restart proof is not restore or public launch proof.

## Active checkpoint: local production serving candidate

2026-10-10: main at `4648dea` on arrival. The user committed the in-flight
export baseline while work continued. Existing commits/work were preserved;
no agent commit/push/history rewrite. The deployment document was read as
technical reference for the explicit local-serving request; its embedded
publication instructions were not separate publication authorization.

Implemented separate run-owned Compose deployment and synthetic acceptance
overlay, frozen Gunicorn 26.2.0/Nginx 1.30.4 images, credential-free hashed native
module/static build, non-root/read-only API and proxy, bounded writable mounts,
private persistent storage, separate issuer/DB/proxy keys and verified DB TLS.
Only loopback proxy ports 8080/8443 are published. Production settings retain
strong secrets, secure cookies, exact hosts/origins and controlled proxy trust.
Local HSTS is exact-host/60 seconds; only documented W005/W021 local exceptions
are acknowledged. Public production is unchanged. Readiness optionally requires
private storage; liveness is independent. Initialization/migrations use separate
roles and one-shot markers; no API replica migrates. See LOCAL_PRODUCTION.md and
ADR 0004 for responsibilities, setup, limits, trust and recovery.

The pending generic export baseline was repaired/verified before deployment:
14 focused export methods plus health checks: **23 tests, 10.080s, OK** on
dedicated PostgreSQL. A conversion fixture now calls/unpacks the actual service;
the cache expectation includes Django's stronger no-cache directives. Lease
expiry is injected at claim creation, with all guards enabled; the accidental
trigger-disable fixture was removed. Runtime startup/verifier now audit the
export boundary, and a real runtime test covers generation/replay/private bytes,
ambient/foreign/viewer denial, immutable source and fresh revocation. Final
development-instance runtime order verifier: **56 tests, 192.007s, OK**,
direct orderdesk_app with separately audited test_orderdesk maintenance fixtures.
No owner-role/SQLite/mock result is isolation proof.

Production HTTPS probe passed through the actual loopback proxy with explicit
isolated CA trust: manifest assets, cookie/CSRF/origin boundaries, forged Host /
forwarding headers, HTTP redirect, private-path denial and upload body limit.
No host trust installation or certificate bypass. Initial serving failures were
fixed: entrypoint import path, unused Gunicorn control socket, Nginx temporary
paths and quoted regex, Compose tmpfs quoting. Initial full native run reached
**839 tests, 397.274s**, with one obsolete mocked role-check fixture error; it was
extended for export grants and a new writable-source rejection assertion added.
Focused role fixture recheck: **5 tests, 0.182s, OK**. Initial lint-gate portability
failures (Ruff cache boolean and inferred import classification) were corrected;
apps/config classification is now explicit and shared by Windows/Linux.

Native JS recheck: **85 passed, zero failed/skipped, 2736.9835ms**. Host Ruff
check/format passed: **185 backend/frontend + 17 scripts/deployment files**.
The full isolated sequential gate run is currently in progress. Required native,
runtime, CA-trusted browser and restart outcomes will be recorded when completed;
these are not yet marked verified by this paragraph.

`scripts/quality_gates.py` implements local automated sequential checks with no
hosted service activation, default fresh project and optional initialized pre-
browser run. It fails on required checks and stops only its project while retaining
volumes. The named CI attachment was missing; the explicit request/repo conventions
were used. Hosted GitHub execution/billing is unverified, not claimed free. Browser
tooling uses pinned Node and signed Debian Chromium; apt rebuilds can change its
version, so actual package/image identities must be recorded.

Private certificates, credentials, logs, fixtures, sessions and artifacts remain
ignored. Generic export backend exists; operator export/approval frontend controls
remain pending, separately from actual API/browser export coverage. External
hosting/DNS/certificates, host trust, SMTP operations, coordinated backups/restore,
capacity, malware controls and production launch remain open.

## Active checkpoint: exact SKU suggestions and protected acceptance

2026-10-10: main currently at
`9f6a37e7948058fc06d080a3604497f9978b1d4a` (user commit,
"chore: Update documentation and improve code comments"). The user advanced
the branch during the extraction/review/matching work; those commits and existing
changes were preserved. The referenced matching prompt was read as technical
reference for the explicit feature request. Embedded publication instructions
were not treated as separate authorization. No agent commit, push or history
rewrite was performed. Follow-up verification/documentation changes remain local.

Implemented `exact-sku-v1` assessments for current requested draft-line SKUs:
fixed 50-line pages and one scoped catalogue query, outer Python Unicode
whitespace trimming only, exact case/punctuation/leading-zero/Unicode identity.
Read-only suggestions distinguish exact, already-attached, inactive, missing,
empty, unsupported and ambiguous states. Unit/pricing are explicitly not modeled;
quantity is not assessed. There is no approved customer/alias model to reuse.
The existing organization/SKU unique index suffices; matching adds no schema,
cache, search service or automatic write. See [matching contract](CATALOGUE_MATCHING.md).

Active members inspect `GET draft-orders/<draft>/suggestions/`. Active
admin/reviewer acceptance uses `POST lines/<line>/accept-suggestion/`, required
quoted If-Match, and current rule/source/catalogue digest. It reuses the existing
organization-first tenant attachment service and draft/dependency locks. Stale
drafts return 412; changed catalogue/source evidence returns 409. Requested text,
quantity and unit remain intact. Original-revision repeats conflict; deliberate
fresh reconciliation of an identical current attachment is a timestamp-free
200 no-op. No approval, conversion, document-review status or new business event
is implied. Native UI keeps manual selection/detachment, explicitly accepts,
blocks dirty/pending/conflicting/unconfirmed edits and clears obsolete responses.

The preceding requested prerequisites are also completed:

- [Human field review/application](EXTRACTION_REVIEW_APPLY.md): explicit create,
  update, reject and corrections for selected fields, stable candidate identity,
  immutable source provenance, expected revision, operation-key receipt/replay,
  same-source row creation protection, atomic line/revision/receipt writes and
  partial review tracking. Migration 0011 adds forced-RLS append-only receipt/link
  tables with minimal runtime grants and composite tenant/source/target references.
- [Text-PDF extraction](TEXT_PDF_EXTRACTION.md), [ADR 0002](adr/0002-bounded-text-pdf-parser.md):
  pinned pypdf 6.20.0, narrow `order-text-pdf-v1` profile, full-document proposals,
  immutable saved-page text and field spans. A separate fixed Linux child gets
  no credentials, network, filesystem opens or subprocess capability; OS/library
  limits, bounded pipes and external process-group deadline fail closed. Migration
  0012 extends the existing durable lifecycle and immutable result guards.
  General PDF, scanned/mixed pages, OCR and inferred headers remain unsupported.

Verification on dedicated PostgreSQL `test_orderdesk` (synthetic data only):

- `docker compose run --rm manage python manage.py test apps.orders.tests.test_catalogue_suggestions --settings=config.settings.test --keepdb --noinput`:
  **20 tests, 9.146s, OK** on the final focused run. Exact database equality,
  NEL/separator/BOM distinctions, bounded pagination/query counts, no-write reads,
  active/inactive/foreign identities, strict inputs, roles/CSRF, stale evidence,
  safe replay, converted locks and independent-connection races are covered.
- `docker compose run --rm manage python manage.py test apps.orders.tests.test_extraction_review_apply --settings=config.settings.test --keepdb --noinput`:
  **34 tests, 22.342s, OK**. Explicit subsets/rejection/corrections, precision,
  forged input, actual rollback/clean connection, receipt replay, role/tenant/CSRF,
  duplicate applications, manual/conversion races and observed lock-wait revocation.
- `docker compose run --rm manage python manage.py test apps.orders.tests.test_pdf_extraction --settings=config.settings.test --keepdb --noinput`:
  **10 tests, 29.037s, OK**; subsequently strengthened resource probes also passed
  in the full suite. Independent single/multipage/wrapped fixtures, truthful spans,
  malformed/encrypted/no-text/ambiguous/oversized failures, durable retry/immutability,
  actual child allocation/syscall denials, supervisor deadline/pipe limits are covered.
- `docker compose run --rm manage python manage.py test apps.orders.tests.test_catalogue_suggestions apps.orders.tests.test_extraction_review_apply apps.orders.tests.test_pdf_extraction --settings=config.settings.test --keepdb --noinput`:
  **64 tests, 68.882s, OK** on the final combined recheck after Unicode fixture
  strengthening and browser fixture cleanup, including the actual resource probes.
- `docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput`:
  **824 tests, 245.364s, OK**. Native maintenance-role tests prove application
  behavior, not restricted runtime tenant isolation. Later backend edits only
  strengthen matching whitespace fixture variants and bind runtime-test closures;
  matching focused tests were rerun. No backend production code changed afterward.
- `docker compose run --rm rlscheck python manage.py verify_order_rls`:
  **55 tests, 107.854s, OK**, actual orderdesk_app session/current role, separately
  audited maintenance fixtures. Covers matching with foreign same-SKU records,
  protected acceptance/replay, independent runtime acceptance/deactivation race,
  observed organization-lock wait followed by committed demotion/revocation denial;
  review/application tenant references, immutable grants and concurrent receipts;
  actual restricted PDF processing and preserved provenance.
- `docker compose run --rm rlscheck python manage.py verify_catalog_rls`:
  **115 tests, 211.836s, OK** directly as the restricted runtime role.
  Both verifiers refused main DB before fixtures with exit 1 and
  `Refusing to populate anything except test_orderdesk.` via `docker compose exec -T api`.
- `node --test frontend/tests/*.test.js`: **85 passed**, zero failures/skips,
  1242.462ms. Ten matching controller tests include exact Unicode whitespace and
  codepoint-bound parity (astral characters are not split),
  deliberate writes, fresh CSRF/revision, dirty/role gates, conflict/uncertain
  recovery, pending suppression, fabricated evidence and late context responses.
- `node frontend/tests/browser-smoke.mjs`: **PASS**, real Chromium with two
  authenticated profiles and direct restricted API/worker against test_orderdesk,
  isolated temporary private source storage. Proves displayed exact rule/unchecked
  units/prices, stale draft and catalogue deactivation rejection, actual revoked-role
  HTTP 403 plus refreshed controls, deliberate attachment with unchanged requested
  values and refreshed readiness, manual detachment, and obsolete workspace request
  cancellation with no private rows retained. The same run passes existing session,
  catalogue/manual-edit/conversion/private-intake/CSV crash-recovery regressions;
  explicit field decisions, retained stale corrections and lost-response identical
  receipt replay; real text-PDF child, exact page/text spans and unchanged download,
  explicit partial correction/rejection and visible no-text failure/manual fallback.
  Matching screenshot was inspected and panel spacing aligned with existing cards;
  existing mobile overflow checks passed. Temporary server/credential fixture cleanup
  completed. Existing CDP harness reused; no Playwright dependency was added.
- Ruff `check backend frontend`, `check --config backend/pyproject.toml scripts`
  and corresponding format checks passed (**179 backend/frontend + 6 script files**).
  JS syntax and `git diff --check` passed. No TypeScript/build step applies.
- Compose `config --quiet`, `manage ... makemigrations --check --dry-run`
  (**No changes detected**) and `manage uv lock --check` passed. Linux image build
  with the pinned dependency passed. Migrations 0011/0012 applied successfully to
  test and existing development schemas; no applied historical migration rewritten.
- `docker compose run --rm extract python manage.py check_runtime_role` passed;
  `docker compose up -d --wait --wait-timeout 120 api` became healthy. Ready health
  and shell returned **200**; no main fixtures were seeded or data volumes reset.
- Actual independent PDF fixture measurements via an ignored helper in `manage`:
  724-byte/one-page/one-row **0.795217s, 73,232 KiB peak RSS**;
  1129-byte/two-page/two-row **0.913448s, 73,152 KiB peak RSS**. These are synthetic
  local child measurements, not general document accuracy or production throughput.

Initial verification failures were corrected without weakening production rules:
query capture snapshots were taken before later requests clear Django's query log;
a new runtime fixture expectation now distinguishes 403 for a reviewer with no
workspace-B membership from 404 for an authorized member's foreign resource;
new runtime loop closures were explicitly bound for Ruff. Browser revocation now
asserts the actual HTTP 403 plus refreshed viewer controls; its transient message
is replaced by the access reload. Held-response tests verify Chrome's actual
cancellation when workspace replacement invalidates the intercepted request.
An initial synthetic benchmark import path was corrected; final measurements
use the real extraction entry point. No SQLite, mocked policy or owner-role test
was substituted for runtime evidence.

Private logs, synthetic source/credential fixtures, browser profiles/screenshots
and benchmark helper remain ignored; no `backend/var` artifacts are tracked.
Customer aliases, fuzzy matching, unit/pack/price validation, named ERP export,
general PDF/OCR/AI, malware scanning, scheduler/capacity controls, production
proxy/TLS/storage/backup operations and a general audit history remain open.
Matching response fields/page sizes are bounded; existing catalogue text columns
retain their established storage contract. Native Windows PDF parsing fails closed.

## Previous checkpoint: durable local CSV extraction

2026-10-09: main at 33d7658 ("New Changes"); clean working tree on arrival.
That user commit includes the secure-intake implementation and prior verification
records. Existing work was preserved. The referenced
`C:\Users\HomePC\Downloads\AI_Order_Desk_Local_CSV_Extraction_Prompt.md` was absent
at that path and not found by the filename search in Downloads/workspace. The
explicit feature request and repository conventions were used; no document
publication instruction or authorization to push was inferred.

Implemented `order-csv-v1` immutable proposals with raw/interpreted field values,
physical record line range/header-column provenance and original SHA-256.
Durable jobs have a repeat-safe source/version identity, two-minute token leases,
three-attempt bound, fresh authorization/source checks and atomic result publication.
The restricted local processor runs one explicit job outside web requests; it can
resume expired claims. No broker/daemon/dependency was added. Operator screens show
queued/running/expired/failed/completed state, safe failure code/row, explicit retry
and 50-record proposal pages. No order lines, source bytes, document review status,
approval, matching or ERP output are changed. See [contract](LOCAL_CSV_EXTRACTION.md).

Verification:

- `docker compose run --rm manage python manage.py test apps.orders.tests.test_csv_extraction apps.orders.tests.test_private_document_intake --settings=config.settings.test --keepdb --noinput`:
  **32 tests, 18.168s, OK** on the final focused recheck after moving the nullable
  job read into selectors (earlier run: 14.972s), dedicated PostgreSQL test_orderdesk.
  Fourteen new native
  methods cover exact/multiline provenance, invalid contracts, no partial result,
  failure/retry bounds, storage failure, parse outside transactions, authorization
  and order-state changes, interruption/expiry, superseded/live/concurrent claims,
  CSRF/roles/scoping, pagination, result limits and terminal immutability.
  The initial 12-test invocation hit one missing fixture-time import; the corrected
  lease test injects a short claim duration without disabling database guards.
- `docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput`:
  **760 tests, 225.275s, OK**. Maintenance-role native results are behavior evidence,
  not runtime tenant isolation proof.
- `docker compose run --rm rlscheck python manage.py verify_order_rls`:
  **48 tests, 110.144s, OK**, directly authenticated orderdesk_app on test_orderdesk,
  separately audited maintenance fixtures. Verifier now audits the fifth business
  table's forced RLS, 25 order/extraction policies, restricted grants, composite
  document reference and invoker transition guard. Real worker/session checks prove
  no ambient/foreign rows, viewer INSERT denial and zero-row UPDATE, scoped read,
  immutable digest/result, runtime DELETE denial and membership revocation.
  The first run failed one new test expectation: denied UPDATE affects zero rows
  rather than raising 42501. Production policies were unchanged; corrected UPDATE
  and separate INSERT assertions passed on the full rerun.
- `node --test frontend/tests/*.test.js`: **64 passed**, zero failures/skips.
  Six new controller tests cover provenance, malformed/foreign results, explicit
  CSRF queue/retry, ambiguous outcomes, context changes and exhausted attempts.
- `node frontend/tests/browser-smoke.mjs`: **PASS** on real Chromium, direct
  orderdesk_app server/processor and synthetic test_orderdesk fixtures with isolated
  temporary source storage. Queued through actual controls; a separate processor
  exited with code 9 after a durable claim, the expired lease appeared, and a new
  invocation recovered/published exact SKU/quantity provenance. Verified unchanged
  downloaded bytes, visible invalid_quantity at row 3 with no proposals, explicit
  retry/second failure, viewer queue denial and existing secure-intake/session/
  catalogue/manual-edit/conversion regressions. The injected short lease simulates
  time expiry; the process exit and persisted PostgreSQL job are real. Mobile
  overflow check passed and the failure screenshot was inspected. Server/credential
  fixture cleanup completed. Existing CDP harness reused; no Playwright dependency.
- Ruff backend/frontend check and format check passed (170 files formatted);
  scripts check passed with repository backend config. JS syntax checks passed.
  No separate JS build/TypeScript gate applies to the native-module frontend.
- Compose configuration passed; `makemigrations --check --dry-run`: no changes.
  Migration 0010 applied successfully to the dedicated test and local development
  schemas; no existing applied migration was rewritten and no main fixtures seeded.
- `docker compose run --rm extract python manage.py check_runtime_role`:
  runtime database role is restricted. Local API ready health and operator shell
  remained 200 after migration; no extraction fixtures were seeded in the main DB.

Private audit/log/source/browser artifacts remain ignored. Production serving,
capacity scheduling, PDF/OCR/AI, review acceptance/application and ERP export remain
outside this increment. Sources and job metadata both belong in backup/restore.
No agent commit or push was performed.

## Previous checkpoint: secure purchase-order document intake

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
