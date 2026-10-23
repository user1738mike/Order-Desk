# Order Desk

Django/PostgreSQL application for turning supported distributor PDF/CSV documents
into human-reviewed internal orders and private `generic-po-csv-v1` exports.
Named ERP compatibility and customer pilot readiness have not been established.
Internal orders now have a searchable, paginated queue with direct links to source
drafts, private documents and approval/export. Customer/reference/state filters are
preserved in the URL. Documents still require an existing internal order; the
expanded upload-first distributor scope is tracked in the existing roadmap.
See the [current audit](docs/AUDIT_2026-10-19.md) and
[pilot acceptance protocol](docs/PILOT_ACCEPTANCE.md).

Local production-like serving is verified with isolated synthetic projects:
[setup and trust](docs/LOCAL_PRODUCTION.md),
[deployment decision](docs/adr/0004-local-production-serving.md) and
[local automated quality gates](docs/CI_QUALITY_GATES.md).
The development commands below remain unchanged. Actual results and remaining
gates are recorded in [project state](docs/PROJECT_STATE.md).

Supported local workflow includes administrator catalogue creation/import,
private intake, bounded CSV/text-PDF extraction, deliberate field review/application,
exact SKU matching, draft editing/readiness/conversion, explicit approval and
private generic CSV export. Conversion supports at most 500 lines, matching the
order read/export budget; larger drafts stay editable for manual handling. See the
[input preservation contract](docs/INPUT_PRESERVATION.md),
[matching contract](docs/CATALOGUE_MATCHING.md),
[review/application contract](docs/EXTRACTION_REVIEW_APPLY.md),
[text-PDF profile](docs/TEXT_PDF_EXTRACTION.md),
[CSV profile](docs/LOCAL_CSV_EXTRACTION.md) and
[private intake contract](docs/SECURE_DOCUMENT_INTAKE.md).
Open `http://127.0.0.1:8000/` after starting
the API; see the [frontend guide](docs/FIRST_FRONTEND_WORKFLOW.md),
[draft review](docs/DRAFT_REVIEW_FRONTEND.md) and
[manual editing](docs/MANUAL_DRAFT_EDITING_FRONTEND.md).
Draft readiness and atomic internal conversion are also implemented. See the
[upload contract](docs/ORDER_DOCUMENT_UPLOAD_HARDENING.md) and
[readiness contract](docs/AI_Order_Desk_Step_04D9_Draft_Readiness.md) and
[conversion contract](docs/AI_Order_Desk_Step_04D10_Draft_Conversion.md).
The backend includes session authentication, workspaces, PostgreSQL tenant
transactions and forced RLS, catalogue management and CSV imports, manual draft
creation/editing/catalogue attachment/detachment/review, and separate
purchase-order/document-review APIs. Conversion creates an internal draft
purchase order; approval and external ERP delivery remain separate.

This product serves industrial distributors: checked purchase orders, staff
exception review and eventual ERP-ready output. Development remains local with
synthetic data and a $0 budget; no paid dependency or service is required.

Use [project state](docs/PROJECT_STATE.md) for delivery and verification results,
[the roadmap](docs/ROADMAP.md) for capability status, and
[local verification](docs/LOCAL_VERIFICATION.md) for current PowerShell commands.
The frontend includes session login/logout, workspace selection and
catalogue search/filter/pagination, administrator creation and validated atomic
CSV import ([browser contract](docs/CATALOGUE_MANAGEMENT_FRONTEND.md)), draft list/detail/readiness, manual header/line
editing, catalogue attachment/detachment and administrator conversion/replay.
It also includes secure document intake/status/download, extraction proposals,
explicit field decisions/corrections and exact SKU suggestions. Suggestions
do not confirm quantities, units or prices, and do not approve or convert orders.
General PDF/OCR/AI, customer aliases, fuzzy matching, named ERP export,
usage tracking and public production deployment remain future work. Prices,
currency and pack rules are unmodeled; the supported generic CSV omits them.
Live email
ingestion, real ERP compatibility and certification have not been demonstrated.

Read [the Step 3 foundation walkthrough](docs/AI_Order_Desk_Step_03_Backend.md)
for the original foundation files, setup explanation and pitfalls; its increment
test totals are historical. Current commands are in the verification runbook.
The accepted design is documented in
[the backend and tenancy decision](docs/AI_Order_Desk_Step_02_Backend_and_Tenancy.md).

## Project layout

| Directory/file | Purpose |
| --- | --- |
| backend/config/ | Django settings and application entry points |
| backend/apps/accounts/ | Global users, admin forms, migration, and tests |
| backend/apps/organizations/ | Membership, workspace APIs and tenant transactions |
| backend/apps/catalog/ | Catalogue management, CSV import and runtime RLS tests |
| backend/apps/orders/ | Drafts, purchase orders, document review and RLS tests |
| backend/apps/health/ | HTTP probes and runtime database-role verification |
| backend/scripts/ | Local database provisioning and development startup |
| backend/pyproject.toml, backend/uv.lock | Declared and locked Python dependencies |
| backend/apps/web/ | Public product UI shell and shell tests |
| frontend/ | Same-origin session/workspace/catalogue and draft review/editing UI; Node/browser tests |
| scripts/ | Host-only environment setup and helper tests |
| docs/ | Step-by-step explanations and architecture decisions |
| compose.yaml | Local database, API, and temporary administrative helpers |
| .env.example | Safe configuration template; private .env is ignored |

## Setup and operation

Follow the [current setup sequence](docs/LOCAL_VERIFICATION.md#initial-local-setup)
in order: extend `.env`, build `api`, start `db`, run `dbsetup`, migrate with
`manage`, then start and verify `api`. Starting all
services before provisioning the roles and tables will fail readiness.

After initial verification:

```sh
docker compose up -d --wait --wait-timeout 120
docker compose down
```

The second command preserves the named database volume. Do not add `-v` or
`--volumes`. Schema commands use the temporary `manage` service; the API has
restricted database credentials. This Compose file and Django's development
server are for local work only; production serving and deployment are a later
step for this development Compose file. The separate isolated local WSGI/TLS
topology is documented in [LOCAL_PRODUCTION.md](docs/LOCAL_PRODUCTION.md).
Never commit `.env`, virtual environments, customer files, or database data.

The [11 October release audit](docs/RELEASE_AUDIT_2026-10-11.md) compares the
original launch requirements with verified local capabilities and records missing,
failed, blocked and deliberately deferred work. It does not approve a customer
release. [COORDINATED_RECOVERY.md](docs/COORDINATED_RECOVERY.md) documents the
encrypted synthetic restore drill and its production limitations.
