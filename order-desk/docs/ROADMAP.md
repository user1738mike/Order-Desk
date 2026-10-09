# Roadmap

## Current source of truth

The active repository contains backend work through Step 4D.8 plus protected
purchase-order upload byte limits and compensating rollback cleanup, Step 4D.9
readiness and Step 4D.10 atomic repeat-safe internal conversion. The local
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

| Status | Scope and evidence |
| --- | --- |
| Implemented and verified locally | Locked Django/PostgreSQL backend, health and role checks; session/CSRF/login limits; workspace discovery/selection/current authorization; transaction-local tenant scopes; catalogue management/search/exact lookup/create/update/deactivation, CSV dry run and atomic create-only execution with durable retry receipts; draft work listed below; separate purchase-order/document-review APIs. Native and restricted-role PostgreSQL checks passed; results are recorded in project state. |
| Implemented, deployment verification missing | Fail-closed production settings and ASGI/WSGI entry points. No production server/TLS/proxy/SMTP/backup evidence. Optional credential HTTP helpers exist but were not all rerun as live operator workflows in the audit. |
| Partial | File capture and manually supplied extraction-review metadata; workspace administration through services/local provisioning; creator/reviewer/timestamp metadata. These do not establish automatic extraction, customer administration UI/API, an append-only audit history or external fulfillment. Private production storage and content handling prerequisites remain open; local upload byte limits and rollback cleanup are tested. |
| Implemented and verified locally | First frontend session login/logout, workspace discovery/selection and read-only catalogue search/filter/pagination; native modules and Django shell, same-origin cookies/CSRF. Real Chromium, 18 client tests, 721 native regressions and 115 restricted-role catalogue checks passed; remaining production/browser prerequisites are in project state and the frontend guide. |
| Implemented locally; current verification in project state | Frontend draft list/detail/readiness, administrator conversion/replay, manual creation/header/line editing and catalogue attach/detach; aggregate revision/If-Match checks under the existing tenant write lock. No line deletion. See draft frontend contracts and current results rather than historical test totals. |
| Implemented locally; verification in project state | Private purchase-order PDF/CSV intake, status pages and authorized original-byte download; persistent Linux volume, digest verification, rollback cleanup and leased local orphan recovery. Legacy adoption and production operations remain open. See SECURE_DOCUMENT_INTAKE.md. |
| Planned only | PDF/order-CSV/OCR/AI extraction, automatic/fuzzy matching, pricing/unit conversions/inventory rules, ERP export profile, usage tracking, CI and production serving/operations. Catalogue CSV import is already implemented; order-document CSV extraction is separate. |

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

## Next dependency order

The reconciliation increment delivers the existing verified work and the current
documentation/runbook; its actual commit/push outcome is recorded in project state.

1. Define an extraction result/review contract using immutable private sources;
   decide content scanning requirements before introducing any parser execution.
2. Implement one bounded extraction format with synthetic fixtures and mandatory
   staff review; keep private sources and tenant permissions intact.
3. Define ERP export profiles before dependent automation. Remaining
   [storage prerequisites](STORAGE_FINDINGS.md) and production operations require
   their own verification; internal conversion is not ERP or launch readiness.

Keep the industrial-distributor product scope, mandatory staff exception review
and $0 local-development budget. Do not claim live email ingestion, ERP
compatibility, production deployment or certification without evidence.
