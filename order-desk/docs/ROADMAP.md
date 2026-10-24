# Roadmap

Active six-improvement request (24 October): [implementation and acceptance
matrix](WORKFLOW_IMPLEMENTATION.md), with actual commands/outcomes in
PROJECT_STATE.md. Upload-first and customer-reference slices are verified within
their documented local scope, including fresh/upgrade, restricted runtime, real
browser and encrypted recovery evidence. Processor preparation is being verified;
complete team queues, controlled units/product aliases, exceptions and handoff
profiles remain required. [Evaluation tooling/protocol](evaluation/README.md) verifies
synthetic arithmetic only; representative customer outcomes remain blocked.

Current security/release review: [24 October audit](AUDIT_2026-10-24.md).
That evidence ledger does not mark the expanded distributor checklist complete.
Missing functionality below remains required; no deferral or risk acceptance was
approved by the audit. Follow its exact continuation checkpoint before resuming
the next capability increment.

## Distributor workflow implementation checklist (23 October 2026)

This is the authoritative checklist for the expanded distributor request.
Evidence and commands belong in PROJECT_STATE.md. Historical verification below
is not proof of this candidate. Status values: VERIFIED, DEFECTIVE, MISSING,
BLOCKED, APPROVED DEFERRED. No deferrals have been approved for this request.

| Requirement | Current assessment and next acceptance gate |
| --- | --- |
| 1 Baseline | VERIFIED: clean main at 890cf55; stack/spec/source inspected; current execution evidence in state ledger. |
| 2 Workflow terminology | MISSING: neutral UI labels agreed below; full correction/handoff state design pending. |
| 3 Upload-first inbox | Implemented: nullable historical order plus constrained immutable incoming source/draft link, request receipts, private inbox/download, duplicate warnings, linked extraction/review/application. Focused native/runtime and browser pass; final fresh gates/evidence in PROJECT_STATE.md. |
| 4 Operational navigation | VERIFIED for scalar searchable order queue/direct source-draft/documents/approval links, URL filters/reload/history and 50-row pages; received date, assignment and draft search remain MISSING. Evidence in state ledger. |
| 5 Workspace UI | DEFECTIVE: existing screens/session cancellation present; six coherent queues and source/draft workspace remain incomplete. |
| 6 Team processing | VERIFIED processor preparation matrix: source/draft/customer preparation with conversion/final approval/reference boundaries preserved, fresh896/66/115 and real browser/production gates. Assignment and reasoned returns/team queues remain MISSING. See PROCESSOR_PERMISSIONS.md. |
| 7 Customer directory | VERIFIED local slice: account/site directory, exact approved aliases, create-only CSV, versioned admin receipts, explicit confirmation and frozen snapshots. Fresh893/64/115, Node130, real Chromium, production/restart and customer recovery pass. Location name/destination edits/history currently API-only; see CUSTOMER_REFERENCE.md/PROJECT_STATE.md for scope, evidence and legacy structural exemption. |
| 8 Units/packs | MISSING: exact quantities and raw units exist; controlled units/product factors require explicit decimal policy. |
| 9 Approved aliases | MISSING: exact SKU suggestions only; customer directory precedes approved mapping model. |
| 10 Duplicate orders | MISSING: conversion/application/export repeat safety exists; customer reference/fingerprint warning and audited resolution pending. |
| 11 Readiness | DEFECTIVE: structural conversion and generic export checks exist; explicit commercial not-checked and selected-profile readiness pending. |
| 12 Corrections/history | MISSING: converted snapshots/receipts protected; general append-only audit, supersession/cancellation/reconciliation pending. |
| 13 Export/handoff | DEFECTIVE: generic-po-csv-v1 implemented; profile boundary and evidence-level handoff records pending. Named profile BLOCKED on real destination specification/accepted fixture. |
| 14 Worker recovery | DEFECTIVE: durable bounded leases/retry exist; inbox visibility and stalled reconciliation need current evidence. |
| 15 Measurements | MISSING: operational backlog/exception definitions and safe denominators pending; active handling time is not collected. |
| 16 Onboarding/pilot | MISSING: existing operator contracts/pilot protocol; bounded guided synthetic onboarding pending. Representative pilot BLOCKED on historical orders/independent expected results. |
| 17 Security/integrity | DEFECTIVE: tenant helper/forced RLS/private storage exist; every new relationship/table requires restricted-role proof. |
| 18 Verification | MISSING: rerun increment-specific PostgreSQL/runtime/browser gates; clean/upgrade migration gates required for schema increments. |
| 19 Delivery | MISSING: verified coherent commits and exact continuation checkpoints required throughout. |

Dependency order: operational navigation; upload-first ownership and provenance;
customer directory and processor/assignment permissions; units/aliases/duplicate
review; immutable correction/audit; profile/handoff readiness; measurements and
onboarding; complete restricted-role, migration, concurrency and browser gates.

### Transition contract before the first increment

Incoming customer PO means immutable original customer bytes. Order draft means
editable internal requested data. Conversion freezes that draft and creates an
internal order (database PurchaseOrder remains unchanged). Submission changes
internal draft/rejected to pending_review; explicit authorized approval/rejection
changes pending_review to approved/rejected. Generic export is a private artifact
from an approved converted snapshot. Download proves no destination delivery.
Handoff attempt/confirmed result are currently unmodeled. Existing self-approval
behavior is retained until the team-workflow requirement is inspected in detail.

First increment acceptance: authorized members can search customer/internal number/
source customer reference, filter exact order state, paginate stable 50-row scalar
headers, and follow source-draft/documents/approval links. Search is literal and
bounded; query parameters are strict; private caches clear on identity/workspace/
role/route changes and late responses cannot restore them. Existing order list
payload/approval/export behavior remains backward compatible. No schema change.
Created date is labelled created (received date and assignment are unmodeled).

## Current source of truth

The active repository contains backend work through Step 4D.8 plus protected
purchase-order upload byte limits and compensating rollback cleanup, Step 4D.9
readiness and Step 4D.10 atomic repeat-safe internal conversion. Later local
increments provide durable CSV/text-PDF proposals, explicit field review and
repeat-safe draft application, and current-draft exact SKU suggestions with
protected deliberate acceptance. Their contracts are
[LOCAL_CSV_EXTRACTION.md](LOCAL_CSV_EXTRACTION.md),
[TEXT_PDF_EXTRACTION.md](TEXT_PDF_EXTRACTION.md),
[EXTRACTION_REVIEW_APPLY.md](EXTRACTION_REVIEW_APPLY.md) and
[CATALOGUE_MATCHING.md](CATALOGUE_MATCHING.md). The local
secure purchase-order document intake/status/download contract is in
[SECURE_DOCUMENT_INTAKE.md](SECURE_DOCUMENT_INTAKE.md), alongside the draft editor.
See [project state](PROJECT_STATE.md) for actual delivery/results and
[local verification](LOCAL_VERIFICATION.md) for repeatable checks.
The 2026-10-08 audit verified the local working tree, including then-uncommitted
work. Historical walkthroughs describe their original increments; their
snapshot overlays, test totals and commit labels are not current setup gates.
Several historical hashes cannot be resolved in this Git history. No replacement
hashes are inferred. Orders migrations 0001 through 0007 are present and were
applied in the audited local environment. Conversion adds migration 0008; its
upgrade, clean-install and local application evidence is in project state.

## Capability status

22 October sidebar dashboard: white collapsible desktop rail, indigo active states,
pale background and existing white work panels. Mobile navigation keeps visible
labels. Native frontend/dependencies, routes and business workflows retained;
only a small ephemeral toggle handler added.109 frontend/two shell tests and25
isolated actual-backend Chromium captures passed, including conversion/approval.
Details, failed-attempt correction and scope limits are in PROJECT_STATE.md.

21 October reference-layout update: shared light gray navigation/frame, rounded
order details, desktop readiness sidebar, inset summaries and soft dialogs applied
without copying reference text or changing workflow logic. Frontend tests and
static Chromium responsive checks pass; database-backed browser revalidation
awaits Docker Desktop. Actual evidence is in PROJECT_STATE.md.

19 October audit: [requirements/evidence matrix](AUDIT_2026-10-19.md).
Conversion/readiness now enforce the existing 500-line order/export budget before
copying source lines; oversized drafts stay editable with an actionable manual
handling blocker. Current PostgreSQL/runtime/browser evidence is recorded in project
state. Original pilot fields/rules/ERP/operating gaps remain open.
The original-plan [pilot measurement and acceptance protocol](PILOT_ACCEPTANCE.md)
now records required inputs, independent withheld-order scoring, full handling-time
measurement and separate release decisions. Its existence is not customer evidence.
Production HTTP diagnostics now exclude raw exception/request payloads while
retaining structured failure classification and proxy request correlation. Final
combined verification is recorded in the dated audit; general tenant audit history,
alert ownership and customer operations remain open.
Omitted legacy order-line units now remain blank; explicit units and exact decimals
are preserved. The local database quota is two CPUs / same 512 MiB after measured
one-core saturation; provisional targets and comparative failures remain in the audit.

12 October validation adds administrator catalogue creation/validated atomic
CSV-import browser controls using the existing APIs. See
[CATALOGUE_MANAGEMENT_FRONTEND.md](CATALOGUE_MANAGEMENT_FRONTEND.md) and the current
PROJECT_STATE checkpoint for actual verification rather than historical counts.

| Status | Scope and evidence |
| --- | --- |
| Implemented and verified locally | Locked Django/PostgreSQL backend, health and role checks; session/CSRF/login limits; workspace discovery/selection/current authorization; transaction-local tenant scopes; catalogue management/search/exact lookup/create/update/deactivation, CSV dry run and atomic create-only execution with durable retry receipts; draft work listed below; separate purchase-order/document-review APIs. Native and restricted-role PostgreSQL checks passed; results are recorded in project state. |
| Verified local WSGI topology | Fail-closed settings, isolated Gunicorn/Nginx serving, certificate-validating HTTPS probes and local quality gates. Current results belong in project state and RELEASE_AUDIT_2026-10-11.md. Public hosting, SMTP and customer production recovery remain open; ASGI serving is not proven by these WSGI checks. |
| Partial | Workspace administration through services/local provisioning; creator/reviewer/timestamp metadata and narrowly scoped immutable application receipts. Customer administration UI/API, a general audit history, unattended document ingestion and external fulfillment are open. Production storage/content handling prerequisites remain open; local upload byte limits and rollback cleanup are tested. |
| Implemented and verified locally | First frontend session login/logout, workspace discovery/selection and read-only catalogue search/filter/pagination; native modules and Django shell, same-origin cookies/CSRF. Current native/client/restricted-role/Chromium results are in project state; deployment prerequisites remain open. |
| Implemented locally; current verification in project state | Frontend draft list/detail/readiness, administrator conversion/replay, manual creation/header/line editing and catalogue attach/detach; aggregate revision/If-Match checks under the existing tenant write lock. No line deletion. See draft frontend contracts and current results rather than historical test totals. |
| Implemented locally; verification in project state | Private purchase-order PDF/CSV intake, status pages and authorized original-byte download; persistent Linux volume, digest verification, rollback cleanup and leased local orphan recovery. Legacy adoption and production operations remain open. See SECURE_DOCUMENT_INTAKE.md. |
| Planned only | General PDF/OCR/AI and additional CSV formats, customer aliases, fuzzy matching, pricing/unit conversions/inventory rules, named ERP compatibility, usage tracking, hosted CI and public production operations. |
| Verified synthetic scope only | Coordinated encrypted PostgreSQL/private-file backup and guarded fresh-cluster restore, including restored sessions, private bytes and native RLS. Customer production backup, off-site custody, retention and key escrow remain missing. See COORDINATED_RECOVERY.md. |
| Implemented and verified locally | Protected approved converted-order generic-po-csv-v1 preview/generation/private download with bounded immutable snapshots, lease/replay and RLS contracts. Explicit submit/approve/export controls passed trusted real-browser confirmation, lost-response reconciliation, private byte download and context-race checks; see OPERATOR_APPROVAL_EXPORT.md and actual results in project state. |
| Implemented locally; verification in project state | Durable order-csv-v1 and narrow order-text-pdf-v1 proposals with original digest, raw/exact values and row/column or saved-page provenance; job leases, explicit bounded retry, visible failures, restricted one-job processor and isolated PDF child. No automatic business writes. |
| Implemented locally; verification in project state | Explicit field acceptance/rejection/corrections and repeat-safe application to an editable same-workspace draft; immutable receipts/creation links, revision conflicts and atomic rollback. No automatic approval, catalogue attachment or conversion. |
| Implemented locally; verification in project state | Bounded read-only exact-sku-v1 suggestions from current draft lines; active members inspect, active admin/reviewer deliberately accept through protected attachment/revision checks. No alias model exists; units/prices are unchecked. |

## Implemented backend increments

- Foundation and 4A/4B: global identity, organizations/memberships, authenticated
  workspace discovery, session login/logout/CSRF and workspace preference/context.
- 4C.0/4C.1: tenant boundary design and outermost transaction helper.
- 4C.3 through 4C.9: forced catalogue RLS, reads, administrator creation/updates,
  literal search/exact SKU, bounded CSV dry run and atomic create-only imports.
- **4D.1 exists:** manual draft header/line models, unresolved values,
  composite tenant references, forced RLS and restricted mutable-column grants.
- **4D.2 exists:** bounded scoped draft list/detail/lines GET/HEAD APIs.
- 4D.3: protected manual draft header creation and validation repair.
- 4D.4: protected requested draft line creation.
- 4D.5: requested draft line read/edit.
- 4D.6/4D.7: explicit manual catalogue attachment/detachment with snapshots.
- Customer-only header PATCH: its requested guide uses the 4D.4 filename but
  follows 4D.7 chronologically; it does not replace requested-line creation.
- 4D.8: read-only draft review observations; no readiness/status decision.
- 4D.9: read-only shared draft readiness policy and bounded blocker counts.
- 4D.10: administrator-only atomic internal conversion with unique tenant source
  linkage, converted source freeze, copied line snapshots and authorized replay.
- Separate older purchase-order API: create/read/lines/submit/approve/reject,
  document upload and manual review creation/resolution. It is included in
  current regression and runtime checks, not completed manual-draft conversion.

## Source checkpoints

All paths are relative to the application. Native `test_*.py` modules below run
with the dedicated PostgreSQL test settings. Runtime checks are separate.

| Capability | Source and API boundary | Relevant verification |
| --- | --- | --- |
| Auth | `backend/apps/accounts/{views,backends,login_limits}.py`; `/api/v1/auth/{csrf,login,logout}/`; active session account and CSRF on mutations. | accounts `test_session_api`, `test_login_limits`, `test_login_concurrency`. |
| First frontend | `frontend/templates/`, `frontend/assets/desk/`, `backend/apps/web/`; public GET/HEAD `/` shell, protected existing auth/workspace/catalogue APIs above; no authority from client state. | `apps.web.tests`, frontend API/controller tests and real-browser restricted-runtime harness; see `FIRST_FRONTEND_WORKFLOW.md`. |
| Workspaces | `backend/apps/organizations/{access,context,selection,permissions,services,selectors,views}.py`; `/api/v1/workspaces/`, `current/`, `<workspace>/context/`; active user/member/organization, no operator bypass. | organizations access/API/selection/context/service/concurrency tests. |
| Tenant transactions | `backend/apps/organizations/transactions.py`, bootstrap and business RLS migrations; fresh URL-selected tenant, read-only reads, organization-first writes. | `test_tenant_transactions`; both direct-runtime verifiers and role checks. |
| Catalogue management | `backend/apps/catalog/{models,services,selectors,views,serializers,query_params}.py`, migrations 0001–0003; workspace `catalog/items/`, `items/by-sku/`, `items/<item>/`; all members read, admins create/PATCH, no delete/SKU rename. | catalogue `test_models`, `test_read_*`, `test_search_*`, `test_create_*`, `test_update_*`; `verify_catalog_rls`. |
| Catalogue CSV import | `backend/apps/catalog/{imports,uploads,import_services,import_execution}.py`; `catalog/imports/dry-run/` and `imports/`; active admin/CSRF, actual-byte limit, atomic create-only receipt/retry contract. | catalogue `test_import_*`, `test_import_receipts`; runtime upload/import/receipt checks. |
| Draft schema and APIs | `backend/apps/orders/{models,services,selectors,serializers,pagination,views,urls}.py`, migrations 0006/0007; workspace `draft-orders/`, `<draft>/`, `lines/`, `lines/<line>/`, explicit `attach/`/`detach/`, `<draft>/review/`; members read, admin/reviewer write, immutable system fields, no finalization. | orders model/constraint/read/concurrency and `test_draft_*` modules; `verify_order_rls`. |
| Purchase-order workflow | Same orders layering, migrations 0001/0002/0005; workspace `orders/`, `<order>/`, `lines/`, `submit/`, `approve/`, `reject/`; member reads, admin/reviewer writes, status locks. | orders `test_models`, `test_services`, `test_constraints`, `test_concurrency`; runtime order checks. |
| Draft readiness | `backend/apps/orders/{readiness,selectors,serializers,views,urls}.py`; GET/HEAD `draft-orders/<draft>/readiness/`; active members, read-only scope, one statement snapshot, no writes. | `test_draft_readiness`; real-session and deliberately unfiltered aggregate runtime checks. |
| Draft conversion | Existing orders models/services/API plus migration 0008; POST `draft-orders/<draft>/convert/`; active administrator/CSRF, unique tenant source link, fresh readiness, converted source/copy freeze, first 201/replay 200. | `test_draft_conversion`, `test_draft_conversion_concurrency`, `test_draft_conversion_migration`; direct-runtime races, access, completion, uniqueness and snapshot constraints. |
| Draft frontend and edit preconditions | `frontend/assets/desk/{orders-api,orders-controller,orders-view,editor,editor-view,main}.js`, template/CSS; `backend/apps/orders/revisions.py`, services/views/URLs; GET revision and optional quoted If-Match on existing edits/new conversion. Browser always supplies revision; existing role/tenant/lifecycle rules retained. | Frontend orders/editor/API tests, real restricted-runtime Chromium harness with separate authenticated sessions, native `test_draft_revisions`; existing conversion races and runtime verifier. |
| Document/manual review | Same orders layering, migrations 0003/0004/0005; order `documents/`, document `reviews/`, review `resolve/`; scoped parent and admin/reviewer mutations. File storage prerequisites are open. | orders service/constraint/concurrency tests and runtime four-table tenant boundary; separate storage finding reproduction. |
| Extraction and field application | `backend/apps/orders/{csv_extraction,pdf_extraction,pdf_parser,extraction_services,extraction_apply}.py`, migrations 0010-0012; order document `extraction/`, `retry/`, `review/`, `apply/`; fresh active member reads, admin/reviewer mutations, explicit target/revision/operation key. Restricted worker and memory-only PDF child are separate from web requests. | `test_csv_extraction`, `test_pdf_extraction`, `test_extraction_review_apply`; immutable receipt/tenant/race runtime checks; native review controller tests and real Chromium. |
| Exact SKU suggestions | `backend/apps/orders/matching.py`, selectors/services/serializers/views/URLs; GET draft `suggestions/`, POST line `accept-suggestion/`; fresh active members read, admin/reviewer accept, required quoted If-Match plus current source/catalogue digest under organization-first lock. No new schema. | `test_catalogue_suggestions`; restricted same-SKU tenant isolation, catalogue deactivation and observed revocation races; `frontend/assets/desk/matching.js`, controller tests and real Chromium. |

## Next dependency order

### Reconciled continuation, 2026-10-11

The export backend and local production/quality tooling exist in the current
working tree. Local serving was verified in resumed native/runtime/proxy/browser/
restart stages after the cache/verifier/harness fixes. The original uninterrupted
runner failed; its exit is not rewritten. Preserve the pre-existing dirty files.

1. Local serving stage verification completed; current commands/results are in
   PROJECT_STATE.md. Public hosting/launch is outside this local proof.
2. Operator approval/export controls completed and verified locally, including
   ambiguous outcome reconciliation and late-response context clearing.
3. Coordinated encrypted synthetic backup/restore is implemented and verified,
   including native restored-data RLS and private-byte/workflow recovery proof.
   Extend its contract to customer production custody, retention and recovery
   ownership before claiming operational readiness.
4. Continue the bounded hardening, reliability, pilot administration, specified
   exceptions/limits, capacity, release and pilot measurement scope in
   [CODEX_BUILD_SPEC.md](CODEX_BUILD_SPEC.md).

The original export sequence below remains historical context for that contract;
the reconciled order above governs continuation. Recovery has its own fresh-cluster
drill evidence; container restart checks alone do not prove backup/restore.

The reconciliation increment delivers the existing verified work and the current
documentation/runbook; its actual commit/push outcome is recorded in project state.

1. Define one versioned generic CSV export contract: eligible converted purchase
   orders, immutable approved source fields, exact decimal/SKU semantics, and
   separate machine-import versus spreadsheet-safe viewing behavior.
2. Implement a bounded repeat-safe private export artifact and authorized download
   with native PostgreSQL, runtime-role, storage/rollback and race checks.
3. Add explicit operator generation/status/download and real-browser verification.
   Named ERP compatibility needs an actual specification and import test. Remaining
   [storage prerequisites](STORAGE_FINDINGS.md) and production operations require
   their own verification; internal conversion is not ERP or launch readiness.

Keep the industrial-distributor product scope, mandatory staff exception review
and $0 local-development budget. Do not claim live email ingestion, ERP
compatibility, production deployment or certification without evidence.
