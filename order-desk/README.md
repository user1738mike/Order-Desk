# AI Order Desk

Django backend for turning distributors' purchase orders into checked ERP-ready
orders. We are building it collaboratively in small, verified steps.

Current checkpoint: **Secure purchase-order document upload, status and authorized
download**, alongside draft review, manual editing and conversion. See the
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
The frontend includes session login/logout, workspace selection and read-only
catalogue search/filter/pagination, draft list/detail/readiness, manual header/line
editing, catalogue attachment/detachment and administrator conversion/replay.
Automatic extraction/matching, secure document intake UI, ERP export,
usage tracking and production deployment remain future work. Live email
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
step. Never commit `.env`, virtual environments, customer files, or database data.
