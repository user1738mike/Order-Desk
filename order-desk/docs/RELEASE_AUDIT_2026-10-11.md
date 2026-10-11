# Order Desk release audit and remediation

Date: 11 October 2026. **No overall release PASS.** This report distinguishes the
tested local scope from the broader launch product. Local approval/export and
synthetic recovery can be demonstrated; customer pilot release still has missing
product/operating work and external evidence gates.

## Baseline and authority

The user's six audit/remediation requests authorize local investigation, fixes and
verification. Supplied prompt documents are references; embedded publication or
spending instructions do not independently authorize those actions. No commit,
push, public deployment, customer communication, purchase or main-data restore was
performed. Existing dirty work was preserved.

Baseline branch is `main`, HEAD `4648dea4b13f01accef116f6770c1cd61e5201d0`, three
commits ahead of the configured remote at initial inspection. The audited candidate
is the **uncommitted working tree**, including pre-existing local deployment/export
changes. Its reproducible source hash manifest is kept in ignored local evidence;
HEAD alone is not the identity of this candidate. Manifest:
`backend/var/release-source-manifest.json`, 276 implementation/configuration/test
files; canonical manifest SHA-256
`e1aa4a294052ee28d5c0ce4528d82509e0bb59a1ff39fedcaafe094f88808311`.
The inventory excludes private data, caches and documentation; each listed file
has its own hash. Documentation describes the frozen implementation separately.
Subsequent host-browser repair adds a proxy-only bridge in Compose; its Windows
HTTP 200 and trusted proxy smoke proofs are recorded in PROJECT_STATE.md. The
frozen manifest/full gate here precedes that topology change.

Authority was reconciled from `AGENTS.md`, `CODEX_BUILD_SPEC.md`, `ROADMAP.md`,
`PROJECT_STATE.md`, contracts/ADRs, source/migrations and the available original
`AI_Order_Desk_Validation_Launch_Plan_and_Pitch.docx` (3 October). The two older
autonomous/backup handoff files were absent from their supplied Downloads paths on
reinspection; their repository reconciliation is available, but fresh byte-for-byte
comparison with those originals is BLOCKED. The release-audit reference was read.

The launch plan asks for one verified ERP import, aliases, pack and price rules,
customer account/ship-to/currency/price basis, critical-field scoring and measured
handling-time savings. The reconciled local build explicitly supports exact CSV,
narrow text-PDF, human review and one **generic** CSV profile. That narrower contract
is not evidence that the original commercial product is complete. No undocumented
unit, price, customer or ERP rule was invented to close the difference.

All execution occurred on this Windows machine: PowerShell host orchestration,
Linux containers in Docker Desktop, isolated run-owned PostgreSQL clusters and
private volumes. Host: Intel i7-10610U, eight logical processors, 16,875,102,208 bytes
RAM. Docker: Linux x86_64, eight CPUs, 8,179,281,920 bytes RAM. No public system was
scanned. Additional service spending was $0.

Candidate versions: Python 3.14.8, Django **5.2.18**, DRF 3.18.1, psycopg/binary
3.3.6, pypdf 6.20.0, Gunicorn 26.2.0, uv 0.12.23, Ruff 0.16.10, PostgreSQL
18.6-bookworm, Nginx 1.30.4, browser runner Node 24.15.0 and Debian Chromium.
Recovery separately uses PostgreSQL 18.6 clients, Debian Python and the signed
Debian age 1.1.1-1+b3 package. Image OS/advisory clearance is not asserted.

## Requirement to evidence matrix

VERIFIED means the specified tested scope passed. MISSING means engineering is
absent/partial. FAILED records a reproduced failure. BLOCKED means required input
or environment evidence is unavailable. DELIBERATELY DEFERRED identifies the
current build spec's explicit exclusions, rather than quietly marking them done.

| Requirement and intended behavior | Implementation and meaningful evidence | Status and remaining work |
| --- | --- | --- |
| Modular Django/PostgreSQL architecture; bounded dependencies and setup | `backend/config`, apps, locked `pyproject.toml`/`uv.lock`, Compose; fresh schema, role and lock gates | VERIFIED locally; production environment separate |
| Tenant isolation through application and native forced RLS | `organizations/transactions.py`, catalogue/order boundary migrations; direct `orderdesk_app` unfiltered reads, foreign IDs, grants, tenant references, reused/contaminated connections and revocation races | VERIFIED for tested tables/roles; credential compromise is not simulated as an entire app takeover |
| Session login/logout, CSRF, current roles and workspace context | accounts/organizations APIs and native frontend; real HTTPS cookies/login/logout/reauth, CSRF and negative role tests | VERIFIED; self-service account lifecycle/SSO not delivered |
| Catalogue import and exact lookup | catalog imports/services/receipts; native dry-run/atomic execution/replay/races and restricted catalogue suite | VERIFIED backend; full administrator catalogue/import browser UI is MISSING |
| Private PDF/CSV originals and downloads | intake/storage/upload guards; byte/hash checks, wrong-tenant denial, traversal/link/resource tests and real browser | VERIFIED for supported local storage; legacy adoption/content-scanning operations remain MISSING |
| Supported extraction retains exact fields/provenance | CSV and narrow text-PDF parser/jobs, isolated child limits; native hostile inputs, leases/stale completion, real worker interruption and retry | VERIFIED for these profiles; arbitrary PDF/OCR is DELIBERATELY DEFERRED |
| Staff corrections/accept/reject/apply require deliberate action | extraction review/application receipts/revisions; native concurrency/replay and Chromium provenance/application | VERIFIED supported fields; no automatic approval or inferred quantities |
| Manual path for unsupported source | manual draft header/line editor, catalogue attach/detach and readiness; Chromium uploads unsupported CSV, runs the real worker, sees explicit failure/no partial proposals, follows manual-entry link and saves a non-ready draft | VERIFIED native/client and final real browser fallback; manual line editing is covered by native/client tests |
| Match exact catalogue identifiers without changing strings | matching API/controller, exact SKU and snapshot/revision checks; inactive/revoked/foreign cases | VERIFIED exact SKU; fuzzy/LLM suggestion is DELIBERATELY DEFERRED |
| Customer-specific aliases and approved pack rules | No alias/rule model or agreed customer rules | BLOCKED on approved input semantics; MISSING implementation for the original launch product |
| Customer account, ship-to, currency, price basis and pricing discrepancy checks | Current header/line schema lacks these launch-critical fields | MISSING; customer/ERP definitions and price freshness policy are BLOCKED |
| Readiness and protected internal conversion preserve exact snapshots | readiness/services/revisions, unique source linkage and DB guards; native migrations/races, runtime/browser replay | VERIFIED internal conversion; not evidence of ERP acceptance |
| Staff submit/approve and immutable generic CSV preview/generate/download | export services/constraints and purchase controller; confirmation cancellation, role denial, lost-response reconciliation, checksum/private download | VERIFIED `generic-po-csv-v1`; unsafe cells fail visibly, no silent SKU transformation |
| Exact import required by a named ERP and confirmation of resulting order | Only versioned generic CSV exists | BLOCKED on import specification/licensing/sandbox and successful import; not compatible by assertion |
| Duplicate/revision controls | durable application/import/conversion/export receipts and guarded revisions; replay/mismatched/stale/race tests | VERIFIED specified operations; cross-upload customer duplicate/revision policy remains MISSING |
| Organization administration/onboarding | services and local commands; active membership/fresh permissions tests | PARTIAL/MISSING customer administration UI/API and a complete operator onboarding flow |
| General audit history | reviewer timestamps and immutable receipts cover particular operations | MISSING general tenant-scoped history, membership changes and operator inspection |
| Usage/volume limits | file/parser/result/page/retry limits exist | MISSING order/line monthly quotas, metering and customer-visible plan limits; resource limits are not billing quotas |
| Dependency and application security | vendor advisory review, patched lock, Python/secret scanners, manual boundary review and negative tests | VERIFIED reviewed scope; OS image advisory scan is BLOCKED by registry failures |
| Reproducible quality gates and CI | `quality_gates.py`, native and frontend suites, real role/proxy/browser/restart stages | Local stages verified; final candidate runner result recorded below. Hosted CI is MISSING, not a local-run PASS |
| Local production-like serving | read-only/non-root/capability-free API/proxy, trusted TLS, pinned static manifest, fixed Host/proxy headers and deploy checks | VERIFIED local WSGI topology; public deployment is deliberately outside authorization |
| Coordinated backup and isolated recovery | `recovery_drill.py`, encrypted dump/file inventory, complete/incomplete markers, empty-target/authentication guards, restored session/bytes/jobs and direct RLS | VERIFIED synthetic drill; customer production coverage, off-site custody and automated retention are MISSING |
| Redacted health/operating visibility | readiness/liveness, safe proxy request IDs/status/latency, bounded logs, visible job error codes | VERIFIED narrow checks; queue/capacity dashboard, alert ownership and incident runbooks are MISSING |
| Read latency, throughput and query/resource budgets | explicit eight-client workload below; before/after measurements and sampled Docker resources | VERIFIED provisional measured profile; long soak, writes/jobs saturation and production SLO approval remain MISSING |
| Operator/support/privacy launch materials | per-feature local runbooks and recovery contract | PARTIAL/MISSING pilot onboarding, escalation/support procedure, retention/deletion policy and live release checklist |
| Business proof: ≥50% less full handling time and critical-field correctness | Synthetic data does not contain independent customer ground truth or ERP outcomes | BLOCKED on representative historical orders and pilot measurements |
| Inbox connectors, payments, enterprise identity, distributed services | Explicit exclusions in current continuation specification | DELIBERATELY DEFERRED; no claim of completion |

## Verification ledger

Private raw evidence is under ignored `backend/var`; it can contain synthetic
session/fixture material and must not be published. Public report values are sanitized.

| Command/gate | Actual environment/result | Evidence |
| --- | --- | --- |
| `scripts/quality_gates.py` initial attempts | Registry TLS failure, then 843-test run FAILED with four bounded-prefetch errors | `release-quality.log`, `release-quality-retry.log` |
| Corrected native suite, forced runtime verifiers and Node tests | 843 native tests PASS (279.722 s), 56 runtime order checks PASS (114.238 s), 115 runtime catalogue checks PASS (210.942 s), 97 Node tests PASS; no reported skips | `release-quality-final.log` |
| Trusted production-like probe | PASS hostname/chain rejection cases, static manifest, headers, cookie/CSRF, private path denial, body bound and redirect | same log |
| Real browser completion | PASS supported intake → review/apply → exact matching → conversion → submit/approve → immutable CSV, viewer denial, real lost response, private-context race, mobile bounds, logout/reauth | `release-browser-complete.log` |
| Dependency/storage outage and recreation | PASS readiness 503/liveness 200 on outage, recoverable DB and storage, persisted session/file/job result, current/session runtime role and DB TLS | `release-restart.log` |
| Final full candidate after added history tests/resource changes | Uninterrupted PASS, exit 0: 845 native tests (326.120 s), 56 order runtime checks (143.914 s), 115 catalogue runtime checks (228.174 s), 97 Node tests (1.626 s), zero reported skips; trusted proxy, Chromium fallback/supported workflows, outage/restart and actual runtime role/TLS proofs all PASS | `release-quality-candidate.log`; isolated run `deployment-b14a8c83d7384d0689f40eaf2ddf5709` |
| `python -m unittest discover -s scripts/tests` | Final 27 tests PASS, exit 0 (0.251 s) | `release-script-tests-final.log` |
| Ruff/backend and scripts/deployment; whitespace | PASS backend 185 files and scripts/deployment 25 files; lock/deploy/migration checks PASS; JS syntax and `git diff --check` PASS | final quality log and host checks |
| pip-audit 2.10.1, full pinned requirement inventory | Exit 0, ten packages queried, zero known advisory matches; no source/secrets sent to advisory service | `release-pip-audit.json` |
| Bandit 1.9.4 | Final Python 3.14 scan: zero parse errors, zero high, six medium and 59 low findings; exit 1 retained/triaged leads. Earlier wrong interpreter could not parse three scripts | `release-bandit-final-tree.json`; earlier scan evidence retained |
| detect-secrets 1.5.0 | Tracked and untracked source scanned; final scan excludes credentials/data/caches. Test/build placeholders are leads, not usable production credentials | `release-secret-scan-final.json` |
| Grype 0.120.1 image scanner | BLOCKED: three registry/TLS download attempts failed; no fresh image/OS advisory result | `release-grype-pull*.log` |
| `scripts/recovery_drill.py --source <acceptance-run>` | PASS all coordinated encrypted recovery and negative guards, 131.324 s, eight files, 223,512 raw dump/file bytes | `release-restore-final-proof.log`, protected backup completion/drill JSON |
| `scripts/release_measure.py --large-fixture --run <restored-run>` | PASS final explicit provisional read/query profile below; original failures preserved | `release-performance*.log`, protected resource samples |

Earlier runner exits remain failures. Sequentially successful stages do not rewrite
an earlier command into an uninterrupted PASS. Browser attempts exposed a harness
reload race: `Page.reload` returned while the old DOM was still available, so sign-out
was clicked on the old page. The harness now requires a new document and completed
load. The real final logout/reauth assertions were retained, not skipped.

## Findings and remediations

1. **Medium — known Django security advisories in the pinned 5.2.17.** Official
   [5.2.18 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2.18/)
   disclose header-parsing denial of service and other fixes. Header parsing is
   relevant to the HTTP stack; spatial/formset exploitability in this app was not
   demonstrated. Updated pin/hashed lock to 5.2.18; native auth/CSRF/workspace/order
   and browser gates plus pip-audit passed. No claim that a published PoC was run.

2. **Medium — unbounded legacy nested order histories.** The old order selector
   prefetched every line/document/review even when the browser later rejected a large
   response. Added database sliced prefetches with separate attributes and explicit
   serializer failure: 500 lines, 50 documents, 50 reviews per document. Oversized
   responses return 413 without silent truncation or false approval. Native tests
   cover full exact values at the boundary, over-limit detail/list, foreign-parent
   non-disclosure, document and review history. The first implementation regressed
   Django related prefetch filtering; full tests caught it and the correction is
   verified. Maximum-budget histories and very long legacy text still warrant a
   broader response/capacity design; this is not proof of unlimited workload safety.

3. **High operational release gap — no coordinated backup/restore.** Implemented
   the [protected synthetic recovery procedure](COORDINATED_RECOVERY.md). Negative
   tests reject unsafe archives, main DB, incomplete backup, checksum mismatch,
   authenticated ciphertext tampering and nonempty targets. Real recovery exposed
   incorrect restored file mode 0600; inventory now binds and preserves sealed 0400,
   and actual downloads pass. Restricted UID/identity-file ownership and probe import
   setup were corrected without widening capabilities. A supported customer/off-site
   recovery procedure is still missing, so the operating release gate remains open.

4. **Performance defect against a provisional target.** First p95 was 882.767 ms.
   Bounded health-checked WSGI DB connection reuse reduced p95 to 400.022 ms on the
   same restored dataset. Larger data then failed at 588.250 ms with one CPU saturated.
   Allocating two CPU cores to two sync workers produced 210.881 ms p95 on identical
   larger data. This is a measured configuration change, not a change to the target.
   Transaction-local tenant settings, fresh membership checks and contamination
   rejection remain; no external pool, privilege change or cache of authorization
   was introduced. Generic production/ASGI configuration is not tuned by this proof.

Manual review covered session fixation/invalidation and login CSRF, cookie/origin/
Host/proxy trust, server-side role checks, explicit tenant filters plus RLS,
organization-first locks, revisions/receipts, parameterized SQL, text-only frontend
rendering/no private browser persistence, contained immutable file paths, forced
downloads/digests, parser process limits, worker privilege/leases, CSV formula rejection,
safe logs/errors, read-only container roots/ports and recovery key/data boundaries.
These reviewed controls and corresponding native/runtime/browser negatives passed
for their specified scope. A finite review is not a guarantee of no vulnerabilities.

Bandit results are not suppressed to manufacture a clean scan. Its six medium SQL
construction leads are migration-time SQL assembled from fixed internal table/policy
names, not request input. Low findings include fixed no-shell tool invocations,
acceptance assertions that refuse optimized Python, and unused static-build placeholder
credentials. Temporary plaintext initially triggered medium findings; it now uses an
exclusive mode-700 tmpfs directory and restrictive umask. Final Python 3.14 scan:
zero parse errors, zero high, six medium and 59 low leads (65 total), manually
triaged as above; exit 1 records the retained findings. Image/OS and adversarial production network coverage
remain explicitly unverified.

## Performance and recovery interpretation

No approved operational SLO was found. Before testing, set provisional limits:
p95 aggregate and **each endpoint** ≤500 ms, ≥10 requests/s, zero HTTP errors, and
≤25 instrumented application SQL statements for representative detail/readiness reads.
HTTP profile: eight closed-loop clients, 200 requests (40 each catalogue/draft list,
readiness, order detail, private export), new correctly validated TLS connection per
request, one warm request per endpoint. Query instrumentation uses the real runtime
role but force-authenticated request factory; session-authentication queries are
explicitly excluded. This is a short read burst, not long-term saturation or queue proof.

| Configuration/workload | p50 / p95 / p99 ms | Throughput | Errors / result |
| --- | --- | --- | --- |
| Browser fixture, fresh DB connection per request, API 1 CPU | 419.761 / 882.767 / 1063.436 | 15.850/s | 0; FAILED latency |
| Same restored fixture, health-checked 60-second connection reuse, API 1 CPU | 212.803 / 400.022 / 452.805 | 33.644/s | 0; PASS small profile |
| Larger data, connection reuse, API 1 CPU | 348.989 / 588.250 / 673.686 | 21.351/s | 0; FAILED latency |
| Same larger data, API 2 CPUs/two sync workers | 151.765 / 210.881 / 224.975 | 50.488/s | 0; PASS final profile |

Larger fixtures add two tenants, 5,000 catalogue items, 300 drafts, 6,000 draft lines
and a 100-line purchase order; the original recovered fixtures remain. Each request
is tenant scoped, including the original export in a different authorized workspace.
Largest measured HTTP response was 22,078 bytes. Endpoint p95s ranged from 173.160 to
219.997 ms. Application statement counts: readiness 10, 100-line detail 12 (under 25).
List/readiness aggregate and prefetch paths were inspected; no per-line N+1 appeared
in these measured paths. This does not validate maximum nested document histories.

Five Docker samples per service during/following the final workload showed API
≤146.2 MiB/512 MiB and ≤145.40% CPU (two-core quota), DB ≤69.86 MiB/512 MiB and
≤48.55% CPU, proxy ≤17.14 MiB/128 MiB and ≤28.75% CPU. Sampling does not establish an
absolute memory/CPU peak. Write/job throughput, long soak, larger catalogues and mixed
upload/download contention remain MISSING measurements; do not infer a customer capacity.

Recovery's 131.324 seconds includes tool/target setup, encryption, guard checks,
restore and HTTP/runtime proofs. It is not an approved production RTO. Raw source
data was 223,512 bytes/eight private files, so extrapolation to larger installations
would be unjustified. The source stayed stopped during collection; database SQL was
restored transactionally, file writes separately. An interrupted restore target is
marked incomplete and cannot be reused. Backup/key directories share this host;
no off-site loss simulation, retention schedule, production RPO or key escrow is verified.

## Release decision and next work

**Local functional readiness:** verified for the supported synthetic exact-intake/
human-review/internal-conversion/generic-export scope. Full original MVP remains incomplete.

**Security review:** patched dependency and reviewed/tested boundaries; provisional
local acceptance only. Image OS scan is BLOCKED; no certification or blanket clearance.

**Operational readiness:** synthetic restart and coordinated recovery verified.
Customer production backup, off-site custody, quotas, admin/history, monitoring/alert
ownership, retention/deletion and deployment/onboarding operations are MISSING.

**Live-pilot readiness:** **BLOCKED / do not launch yet.** The original plan requires
one actual ERP sandbox import and confirmation, agreed critical fields/rules,
representative withheld orders and customer outcomes. Synthetic correctness cannot
demonstrate 50% less total handling time or 99% approved critical-field accuracy.
The launch plan is stricter: zero missed critical errors and correct ERP results in
300 representative withheld orders, with independence/confidence limitations.

Next engineering work is a bounded secure pilot administration/audit/usage increment,
with its contract, native RLS/grants, concurrency negatives and actual browser evidence.
In parallel, obtain an authorized ERP specification/sandbox and critical-field/rule
definitions, and restore the two unavailable original handoff references for traceability.
Rerun a current image/OS scanner when registry access is reliable. Customer recruitment,
messages, purchases, production restore and public deployment require separate authorization.
