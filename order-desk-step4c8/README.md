# AI Order Desk

Django backend for turning distributors' purchase orders into checked ERP-ready
orders. We are building it collaboratively in small, verified steps.

Current step: **Step 3 — backend foundation**. The custom user, locked dependencies,
local PostgreSQL roles, and health endpoints are implemented. Organization
membership, tenant isolation, order processing, and the frontend follow later.

Read [the complete Step 3 walkthrough](docs/AI_Order_Desk_Step_03_Backend.md) for
every file, the Windows PowerShell setup sequence, verification, and pitfalls.
The accepted design is documented in
[the backend and tenancy decision](docs/AI_Order_Desk_Step_02_Backend_and_Tenancy.md).

## Project layout

| Directory/file | Purpose |
| --- | --- |
| backend/config/ | Django settings and application entry points |
| backend/apps/accounts/ | Global users, admin forms, migration, and tests |
| backend/apps/health/ | HTTP probes and runtime database-role verification |
| backend/scripts/ | Local database provisioning and development startup |
| backend/pyproject.toml, backend/uv.lock | Declared and locked Python dependencies |
| frontend/ | Future purchase-order review interface |
| scripts/ | Host-only environment setup and helper tests |
| docs/ | Step-by-step explanations and architecture decisions |
| compose.yaml | Local database, API, and temporary administrative helpers |
| .env.example | Safe configuration template; private .env is ignored |

## Setup and operation

Follow the Step 3 guide in order: extend `.env`, build `api`, start `db`, run
`dbsetup`, migrate with `manage`, then start and verify `api`. Starting all
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
