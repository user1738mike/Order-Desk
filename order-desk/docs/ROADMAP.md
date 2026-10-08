# Roadmap

## Current source of truth

The active repository contains backend work through Step 4D.8. See
[project state](PROJECT_STATE.md) for actual delivery/results and
[local verification](LOCAL_VERIFICATION.md) for repeatable checks.
The 2026-10-08 audit verified the local working tree, including then-uncommitted
work. Historical walkthroughs describe their original increments; their
snapshot overlays, test totals and commit labels are not current setup gates.
Several historical hashes cannot be resolved in this Git history. No replacement
hashes are inferred. Orders migrations 0001 through 0007 are present and were
applied in the audited local environment.

## Capability status

| Status | Scope and evidence |
| --- | --- |
| Implemented and verified locally | Locked Django/PostgreSQL backend, health and role checks; session/CSRF/login limits; workspace discovery/selection/current authorization; transaction-local tenant scopes; catalogue management/search/exact lookup/create/update/deactivation, CSV dry run and atomic create-only execution with durable retry receipts; draft work listed below; separate purchase-order/document-review APIs. Native and restricted-role PostgreSQL checks passed; results are recorded in project state. |
| Implemented, deployment verification missing | Fail-closed production settings and ASGI/WSGI entry points. No production server/TLS/proxy/SMTP/backup evidence. Optional credential HTTP helpers exist but were not all rerun as live operator workflows in the audit. |
| Partial | File capture and manually supplied extraction-review metadata; workspace administration through services/local provisioning; creator/reviewer/timestamp metadata; draft review observations. These do not establish automatic extraction, customer administration UI/API, an append-only audit history or draft finalization. Document storage prerequisites remain open. |
| Planned only | Frontend review workspace (`frontend/.gitkeep` only), PDF/order-CSV/OCR/AI extraction, automatic/fuzzy matching, pricing/unit conversions/inventory rules, ERP export profile, usage tracking, CI and production serving/operations. Catalogue CSV import is already implemented; order-document CSV extraction is separate. |

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
- Separate older purchase-order API: create/read/lines/submit/approve/reject,
  document upload and manual review creation/resolution. It is included in
  current regression and runtime checks, not completed manual-draft conversion.

## Source checkpoints

All paths are relative to the application. Native `test_*.py` modules below run
with the dedicated PostgreSQL test settings. Runtime checks are separate.

| Capability | Source and API boundary | Relevant verification |
| --- | --- | --- |
| Auth | `backend/apps/accounts/{views,backends,login_limits}.py`; `/api/v1/auth/{csrf,login,logout}/`; active session account and CSRF on mutations. | accounts `test_session_api`, `test_login_limits`, `test_login_concurrency`. |
| Workspaces | `backend/apps/organizations/{access,context,selection,permissions,services,selectors,views}.py`; `/api/v1/workspaces/`, `current/`, `<workspace>/context/`; active user/member/organization, no operator bypass. | organizations access/API/selection/context/service/concurrency tests. |
| Tenant transactions | `backend/apps/organizations/transactions.py`, bootstrap and business RLS migrations; fresh URL-selected tenant, read-only reads, organization-first writes. | `test_tenant_transactions`; both direct-runtime verifiers and role checks. |
| Catalogue management | `backend/apps/catalog/{models,services,selectors,views,serializers,query_params}.py`, migrations 0001–0003; workspace `catalog/items/`, `items/by-sku/`, `items/<item>/`; all members read, admins create/PATCH, no delete/SKU rename. | catalogue `test_models`, `test_read_*`, `test_search_*`, `test_create_*`, `test_update_*`; `verify_catalog_rls`. |
| Catalogue CSV import | `backend/apps/catalog/{imports,uploads,import_services,import_execution}.py`; `catalog/imports/dry-run/` and `imports/`; active admin/CSRF, actual-byte limit, atomic create-only receipt/retry contract. | catalogue `test_import_*`, `test_import_receipts`; runtime upload/import/receipt checks. |
| Draft schema and APIs | `backend/apps/orders/{models,services,selectors,serializers,pagination,views,urls}.py`, migrations 0006/0007; workspace `draft-orders/`, `<draft>/`, `lines/`, `lines/<line>/`, explicit `attach/`/`detach/`, `<draft>/review/`; members read, admin/reviewer write, immutable system fields, no finalization. | orders model/constraint/read/concurrency and `test_draft_*` modules; `verify_order_rls`. |
| Purchase-order workflow | Same orders layering, migrations 0001/0002/0005; workspace `orders/`, `<order>/`, `lines/`, `submit/`, `approve/`, `reject/`; member reads, admin/reviewer writes, status locks. | orders `test_models`, `test_services`, `test_constraints`, `test_concurrency`; runtime order checks. |
| Document/manual review | Same orders layering, migrations 0003/0004/0005; order `documents/`, document `reviews/`, review `resolve/`; scoped parent and admin/reviewer mutations. File storage prerequisites are open. | orders service/constraint/concurrency tests and runtime four-table tenant boundary; separate storage finding reproduction. |

## Next dependency order

The reconciliation increment delivers the existing verified work and the current
documentation/runbook; its actual commit/push outcome is recorded in project state.

1. Resolve the [document-storage prerequisites](STORAGE_FINDINGS.md) in a
   focused tested increment before dependent intake/finalization is ready.
2. Define a separate read-only draft readiness contract and tests, then
   implement its validator. Preserve the observational `/review/` contract.
3. Only after required prerequisites: define atomic, repeat-safe
   draft-to-purchase-order conversion, followed by the frontend review workspace
   and an explicitly specified ERP export profile.

Keep the industrial-distributor product scope, mandatory staff exception review
and $0 local-development budget. Do not claim live email ingestion, ERP
compatibility, production deployment or certification without evidence.
