Order Desk
A workspace-based order operations platform being built incrementally for businesses that need reliable catalogue and order workflows.
The long-term goal is to turn incoming customer requests into structured, reviewable orders, with AI-assisted extraction and human approval. The current work establishes the authentication, workspace and database security foundation for that workflow.
Status: Active development. This is not a released or production-certified product. This README is grounded in the shared Step 4C.3 verification record; subsequent increments must be confirmed against the repository before being marked complete.

Project scope
Order Desk is intended to help operators maintain a product catalogue, capture orders, resolve missing or ambiguous details, and track processing. The initial customer segment and supported intake channels remain product decisions to validate.
Established foundation
- Django backend with Django REST Framework.
- PostgreSQL database and Docker Compose development environment.
- Email-based user accounts, session authentication, CSRF protection and shared login attempt limits.
- Organizations, memberships and selected workspace context.
- Catalogue model with organization-scoped SKU uniqueness and nonblank SKU constraints.
- Forced PostgreSQL row-level security for the catalogue: active members can read; administrators can insert and update within their organization.
- Separate migration and application database roles: orderdesk_migrator and orderdesk_app.
- Runtime-role verification, isolated catalogue RLS verification and health endpoints.
Planned capabilities
These are roadmap items, not claims of working functionality:
- Tenant-scoped catalogue APIs and catalogue management screens.
- Structured order capture, validation and review.
- AI-assisted extraction from approved intake sources.
- Human approval before consequential order actions.
- Processing history, operational dashboards and integrations.
- React/Next.js frontend, subject to the approved implementation plan.
Architecture
The backend enforces authentication and workspace permissions. Catalogue access is additionally constrained by PostgreSQL RLS. Database policies depend on server-established user and organization context; a client-supplied organization identifier alone is not authorization.
The API runs with restricted application credentials. Schema migrations use a separate role. The RLS verifier uses the dedicated test_orderdesk database and must refuse to populate the main application database.
Repository layout
Confirmed paths from the shared project records:
backend/
  apps/
    accounts/               User accounts and authentication
    organizations/          Organizations, memberships and workspace context
    catalog/                Catalogue model, migrations and RLS verification
    health/                 Liveness and readiness endpoints
  config/settings/          Django settings
  scripts/                  Database provisioning helpers
  manage.py                 Django management entry point
scripts/                    Local setup helpers
compose.yaml                Local services and verification tools
docs/                       Increment-specific implementation guides
Local development
Prerequisites: Git, Docker Desktop with Linux containers and Docker Compose. Windows development uses the established PowerShell/WSL workflow. Use repository-pinned dependencies rather than installing arbitrary latest versions.
1. Clone the repository and enter its root.
2. Follow the existing foundation guide in docs/ to generate local environment values using scripts/init_env.py, build the images and provision database roles. Preserve existing environment files on an established checkout.
3. Run the following commands one at a time, stopping if any command fails:
docker compose config --quiet
docker compose up -d --wait --wait-timeout 120 db
docker compose run --rm manage python manage.py check
docker compose run --rm manage python manage.py migrate --plan
Review the migration plan, then apply it locally:
docker compose run --rm manage python manage.py migrate --noinput
docker compose run --rm manage python manage.py migrate --check
docker compose up -d --wait --wait-timeout 120 api
docker compose exec api python manage.py check_runtime_role
These commands assume the existing Compose services and database roles have already been provisioned. They are not a replacement for the first-time setup guide.
Health endpoints
- http://127.0.0.1:8000/api/v1/health/live/
- http://127.0.0.1:8000/api/v1/health/ready/
Both are expected to return HTTP 200 and {"status":"ok"} in a healthy local environment.
Verification
Run checks against PostgreSQL; SQLite cannot prove this project's RLS boundary.
docker compose run --rm manage python manage.py check
docker compose run --rm manage python manage.py makemigrations --check --dry-run
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 2
docker compose run --rm manage ruff check .
docker compose run --rm manage ruff format --check .
docker compose run --rm rlscheck
docker compose exec api python manage.py check_runtime_role
The last shared normal-suite record contained 221 passing tests. This is historical evidence, not a fixed future test count. Require all applicable checks to pass without unexplained skips. See docs/AI_Order_Desk_Step_04C3_Catalogue_RLS.md for verifier provisioning, main-database refusal and concurrency checks.
A test suite running as the schema owner does not establish that restricted runtime access is safe. Keep the separate runtime-role proof.
Development principles
- Deliver small increments with explicit acceptance criteria.
- Check both authorized behavior and denied access across workspaces.
- Test revocation, invalid input and concurrency where relevant.
- Keep credentials, customer data and environment files out of Git.
- Preserve lockfiles and committed migrations.
- Keep documentation aligned with actual repository behavior.
See [CONTRIBUTING.md](CONTRIBUTING.md), [ROADMAP.md](ROADMAP.md), and [SECURITY.md](SECURITY.md).
License
No open-source license has been selected. Publication on GitHub does not by itself grant permission to reuse or redistribute this code. Add a license only after the project owner chooses one.
