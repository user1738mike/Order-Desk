# Step 3 — backend foundation

## Goal and boundary

Initialize the accepted Django modular monolith, commit a real dependency lock,
create the custom user before initial migrations, and expose minimal health
probes. Your existing PostgreSQL volume and bootstrap password are preserved.
Budget: no new paid services. Allow 45–90 minutes to inspect the files, download
the first backend image, and complete verification.

This is one backend foundation step. Organization membership, tenant policies,
purchase orders, login APIs, background workers, and the frontend follow in
separate steps. The user is a global identity compatible with the accepted
shared-database tenancy model; tenant isolation is not implemented yet.

The Docker target in this step uses Django's **development server** and local
settings. Production settings provide security defaults and validation, but
the production server, TLS termination, deployment, backups, and operational
checks still need their own step before a live pilot.

## 1. Apply the incremental patch

Download `AI_Order_Desk_Step_03_Backend.zip`. Its paths start at the project root;
it does not contain an enclosing `order-desk` folder. It contains no `.env`,
database files, Git history, virtual environment, or credentials.

In PowerShell:

```powershell
Set-Location C:\Users\HomePC\Desktop\billion1\order-desk
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\AI_Order_Desk_Step_03_Backend.zip" -DestinationPath . -Force
```

`Set-Location` selects your existing project. `Expand-Archive` adds the backend
files and replaces the included setup templates and README. Adjust only the
ZIP's download location if your browser saved it elsewhere. Do not extract it
into a second `order-desk` folder.

The patch replaces `compose.yaml`, `.env.example`, `scripts/init_env.py`, and
`README.md`. It also includes the Step 2 decisions with their status marked
accepted. The project name remains `orderdesk-local` and the named volume
remains `postgres_data`, so Compose continues using your existing database.

## 2. Understand the files

All paths below are relative to your `order-desk` folder.

### Root setup

| File | Responsibility |
| --- | --- |
| `README.md` | Short project entry point and links to this walkthrough. |
| `compose.yaml` | Runs `db` and `api`; defines the temporary `dbsetup` and `manage` helpers. Only API credentials enter the API container. Both published ports bind to `127.0.0.1`. |
| `.env.example` | Committed variable names and safe defaults; secret fields are empty. |
| `scripts/init_env.py` | Generates missing secrets and atomically updates the private `.env`. Preserves the original PostgreSQL password and existing values; rejects ambiguous duplicate assignments. |
| `scripts/tests/test_init_env.py` | Checks new secret generation, upgrade preservation, repeatability, and invalid configuration. Runs with your Windows Python. |
| `docs/AI_Order_Desk_Step_03_Backend.md` | This walkthrough, including the remaining verification checks. |
| `docs/AI_Order_Desk_Step_02_Backend_and_Tenancy.md` | Accepted backend/tenancy decisions from Step 2; included so the repository keeps its architecture record. |

Your existing Git ignore and line-ending configuration continue to apply.
The generated `.env` remains private and untracked. On Windows, access to it
depends on your project directory's access controls.

### Backend runtime and dependencies

| File | Responsibility |
| --- | --- |
| `backend/pyproject.toml` | Names the project, declares exact direct dependencies and Python compatibility, and configures Ruff. `package = false` means this app runs directly from source rather than being published as a Python package. |
| `backend/uv.lock` | Generated dependency graph, transitive versions, platform markers, download URLs, and package hashes. Commit it; do not edit it by hand. |
| `backend/.python-version` | Selects Python `3.14.8` for this backend. Your host Python can remain `3.13.12`. |
| `backend/Dockerfile` | Builds the pinned Python/uv environment, installs with `uv sync --locked`, and runs as UID/GID `10001`. Dependencies live at `/opt/venv`, so mounting source at `/app` does not hide them. |
| `backend/.dockerignore` | Excludes secrets, environments, caches, and local output from the image build context. |
| `backend/manage.py` | Entry point for checks, migrations, tests, and administrative Django commands. Defaults to local settings. |

Direct pins: Django `5.2.17`, DRF `3.18.1`, Psycopg `3.3.6`, Ruff `0.16.10`,
uv `0.12.23`, and Python `3.14.8`. Existing PostgreSQL remains `18.6-bookworm`.
Image release tags are pinned here; tested image digests and the update process
will be added during deployment work. A lock makes an install repeatable; it
does not replace security updates.

### Configuration

| File | Responsibility |
| --- | --- |
| `backend/config/env.py` | Strict readers for required strings, integers, booleans, and comma-separated lists. Errors name the setting, not its secret value. |
| `backend/config/settings/base.py` | Shared installed apps, middleware, PostgreSQL connection, custom user setting, UTC, password validators, session authentication, authenticated-by-default REST permissions, JSON responses, and logging. |
| `backend/config/settings/local.py` | Explicit development overrides: debug enabled, localhost hosts, HTTP-compatible cookies, and console email. Never use this module for a live pilot. |
| `backend/config/settings/production.py` | Debug disabled, public host allowlist, strong secret validation, Secure cookies, HTTPS redirect, HSTS, and certificate-verified database TLS. Requires `DATABASE_SSLROOTCERT`; proxy HTTPS trust is opt-in. |
| `backend/config/settings/test.py` | PostgreSQL test settings with debug disabled and an in-memory email outbox. Uses the dedicated `test_orderdesk` database. |
| `backend/config/urls.py` | Registers `/admin/` and `/api/v1/health/`. Future API modules plug in here. |
| `backend/config/asgi.py` | ASGI application entry point; defaults to production settings unless explicitly configured otherwise. |
| `backend/config/wsgi.py` | WSGI entry point with the same production default. Local Compose explicitly selects local settings. |

The app reads environment variables rather than loading `.env` itself. Compose
reads the root `.env` and passes only the variables each service needs. This
keeps the same settings mechanism usable in a later deployment.

Production intentionally leaves HSTS subdomain coverage and preload disabled:
those policies require checking every affected host during deployment.
`check --deploy` will flag those two choices. Do not enable proxy-header trust
unless the trusted proxy strips client-supplied forwarded headers. The local
Compose database has no TLS; changing its settings module to production alone
cannot turn it into a production deployment.

### Accounts

| File | Responsibility |
| --- | --- |
| `backend/apps/accounts/apps.py` | Registers the accounts module with Django. Its app label is `accounts`. |
| `backend/apps/accounts/models.py` | Defines `User`: UUID primary key, email login, no username, Django password hashing, and database-enforced case-insensitive email uniqueness. |
| `backend/apps/accounts/managers.py` | Creates normal users and operators, normalizes/validates email, hashes passwords, and rejects invalid superuser flags. A user created without a password has an unusable password. |
| `backend/apps/accounts/forms.py` | Makes Django's creation/change forms work with email instead of username. Creation uses Django password validation. |
| `backend/apps/accounts/admin.py` | Registers the custom user in Django admin with appropriate forms and fields. This is an operator tool, not the customer review interface. |
| `backend/apps/accounts/migrations/0001_initial.py` | Generated schema change for the custom user, related permissions, and email constraint. It is committed and applied before any customer tables. |
| `backend/apps/accounts/tests/test_users.py` | Covers normalization, password hashing, authentication, disabled users, superusers, database uniqueness, and admin forms. |
| `backend/apps/accounts/tests/test_settings.py` | Checks invalid environment values and production security defaults in isolated interpreter processes. |

**Why now:** `AUTH_USER_MODEL = "accounts.User"` must be configured before the
first migrations. Swapping Django's default user after related tables exist
is expensive. UUIDs are identifiers, not an authorization mechanism.

Our email policy is deliberately case-insensitive for the entire address.
The application normalizes it, while the database adds a `Lower(email)` unique
constraint so bulk writes cannot bypass uniqueness. Django's `is_staff` and
`is_superuser` refer to platform operators; future organization roles will use
membership records. `create_user()` hashes passwords, but future registration
services must also call Django's password validators, just as the admin form does.

### Health and database helpers

| File | Responsibility |
| --- | --- |
| `backend/apps/health/apps.py` | Registers the health module. |
| `backend/apps/health/urls.py` | Defines the versioned liveness and readiness routes. |
| `backend/apps/health/views.py` | Public GET probes with minimal JSON and `Cache-Control: no-store`. Liveness does not query the database; readiness queries the user table and returns 503 on database failure. |
| `backend/apps/health/management/commands/check_runtime_role.py` | Queries PostgreSQL role/schema metadata and refuses an API account with elevated privileges, table ownership, or role membership. |
| `backend/apps/health/tests/test_health.py` | Checks public access, database-independent liveness, readiness, HTTP methods, and sanitized failure responses. |
| `backend/apps/health/tests/test_runtime_role.py` | Checks that each prohibited capability independently blocks API startup. These are unit checks; the live PostgreSQL check is below. |
| `backend/scripts/bootstrap_database.py` | One-shot local provisioning of migration/runtime roles, grants, default grants for future tables, and a dedicated test database. Uses safely quoted SQL identifiers/literals and never prints passwords. |
| `backend/scripts/run_dev_server.py` | Verifies the API database role, then replaces itself with Django's development server so stop signals work normally. Refuses production settings. |

The empty `__init__.py` files in `config/`, `config/settings/`, `apps/`, each app,
their tests, `accounts/migrations/`, and `health/management/commands/` mark Python
packages and allow Django to discover modules. They intentionally contain no
startup logic.

HTTP contracts:

| Request | Success | Failure |
| --- | --- | --- |
| `GET /api/v1/health/live/` | `200 {"status":"ok"}` | Process/network failures are observed by the caller. |
| `GET /api/v1/health/ready/` | `200 {"status":"ok"}` | `503 {"status":"unavailable"}` when the database/schema is unavailable. |

HEAD and OPTIONS are supported. Writes are not supported. Health endpoints are
the explicit exception to the API's authenticated-by-default permission policy.
Readiness needs migrations and SELECT access; it does not require an existing
user. It is not a substitute for a production deployment check or restore drill.

## 3. Initialize private settings

Run each command from the project root. The guard after a native command stops
the sequence if it fails; Windows PowerShell does not do that automatically.

```powershell
python .\scripts\init_env.py
if ($LASTEXITCODE -ne 0) { throw "Environment setup failed." }
git check-ignore .env
if ($LASTEXITCODE -ne 0) { throw ".env must be ignored by Git." }
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose configuration is invalid." }
```

The helper keeps your existing `POSTGRES_PASSWORD` and generates distinct
migration/runtime passwords and a Django secret. Git should print `.env`.
Compose validation should produce no output. Use `--quiet` so resolved secrets
are not printed. Do not delete `.env` to resolve an existing-database problem:
the original password still belongs to the persistent volume.

## 4. Build, provision, and migrate

```powershell
docker compose build api
if ($LASTEXITCODE -ne 0) { throw "Backend image build failed." }
docker compose up -d --wait --wait-timeout 120 db
if ($LASTEXITCODE -ne 0) { throw "Database startup failed." }
docker compose run --rm dbsetup
if ($LASTEXITCODE -ne 0) { throw "Database role provisioning failed." }
docker compose run --rm manage python manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "Migrations failed." }
docker compose up -d --wait --wait-timeout 120 api
if ($LASTEXITCODE -ne 0) { throw "API startup or readiness failed." }
```

| Command | What happens and why |
| --- | --- |
| `build api` | Builds one reusable backend image. `uv sync --locked` installs the committed dependency graph and fails on a stale lock. Host Python is not used for the backend. |
| `up ... db` | Starts/waits for PostgreSQL using the original named volume. Starting just `db` avoids launching the API before roles and tables exist. |
| `run --rm dbsetup` | Temporarily uses the bootstrap administrator to create/reconcile roles and grants, then removes the helper container. Re-running it is safe with the same configuration. |
| `run --rm manage ... migrate` | Applies committed migrations as `orderdesk_migrator`, which owns the resulting tables. `--noinput` prevents unattended prompts. |
| `up ... api` | Starts the non-root API using `orderdesk_app`. The startup privilege check must pass and the readiness probe must become healthy. |

The migration role can create schema objects but cannot create databases,
create roles, act as superuser, or bypass RLS. The API role has table DML and
sequence access; it cannot own/create tables or administer the database. The
bootstrap superuser is not passed to the API. Future RLS policies will restrict
tenant business rows; these grants alone do not implement tenant isolation.

The provisioning helper creates `test_orderdesk`, owned by the migration role.
Tests use `--keepdb` so the migration role does not need CREATEDB privileges.
The helper only handles this local `orderdesk` installation; production database
provisioning will be a separate, reviewable deployment task.

## 5. Verify the backend

```powershell
docker compose ps
docker compose exec api python --version
docker compose exec api python manage.py check
if ($LASTEXITCODE -ne 0) { throw "Django system checks failed." }
docker compose exec api python manage.py check_runtime_role
if ($LASTEXITCODE -ne 0) { throw "The runtime database role is unsafe." }
docker compose run --rm manage python manage.py makemigrations --check --dry-run
if ($LASTEXITCODE -ne 0) { throw "Committed migrations do not match the models." }
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 2
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backend tests failed." }
python -m unittest discover -s scripts/tests -v
if ($LASTEXITCODE -ne 0) { throw "Environment helper tests failed." }
docker compose exec api ruff check .
if ($LASTEXITCODE -ne 0) { throw "Lint checks failed." }
docker compose exec api ruff format --check .
if ($LASTEXITCODE -ne 0) { throw "Formatting checks failed." }
docker compose exec api uv lock --check
if ($LASTEXITCODE -ne 0) { throw "Dependency lock is stale." }
```

Expected: `db` and `api` are healthy, Python prints `3.14.8`, Django identifies
no issues, the runtime check prints `Runtime database role is restricted.`,
the migration check says `No changes detected`, **25 Django tests** pass, and
**five host helper tests** pass. Ruff and the lock check must succeed.

The test runner may print a readiness warning and a 503 while checking the
failure path. That is expected when the suite ends in `OK`. Tests use
`test_orderdesk`, not your application database.

Confirm the real PostgreSQL role flags and user-table ownership:

```powershell
docker compose exec db psql -U orderdesk_dev_admin -d orderdesk -v ON_ERROR_STOP=1 -c "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname IN ('orderdesk_app', 'orderdesk_migrator'); SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = 'accounts_user';"
if ($LASTEXITCODE -ne 0) { throw "Database permissions verification failed." }
```

Both rows must show `f` for all four privilege flags. The `accounts_user` table
must be owned by `orderdesk_migrator`.

Now check the actual HTTP responses:

```powershell
$live = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/v1/health/live/"
$ready = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/v1/health/ready/"
if ($live.StatusCode -ne 200 -or $ready.StatusCode -ne 200) { throw "A health probe failed." }
if (($live.Content | ConvertFrom-Json).status -ne "ok" -or ($ready.Content | ConvertFrom-Json).status -ne "ok") { throw "Unexpected health response." }
$live.StatusCode
$live.Content
$ready.StatusCode
$ready.Content
```

`Invoke-WebRequest` makes real requests from Windows; `ConvertFrom-Json` checks
the response bodies. Both should report `200` and `{"status":"ok"}`. Substitute
your chosen port if you changed `API_PORT`.

Do not run `migrate` inside `api`: its deliberately restricted role cannot
perform schema changes. Do not run tests without `--keepdb` in this setup.
Do not run `docker compose down -v`; that deletes the named database volume.

### Checks performed while preparing this patch

The actual `uv.lock` was resolved and installed with uv `0.12.23` on Python
`3.14.8`. Ruff linting/formatting, Django system checks, migration consistency,
25 Django tests, and five environment helper tests pass. Application tests
used a temporary SQLite verification harness outside the delivered project
because Docker and an unprivileged PostgreSQL server are unavailable in this
environment. The delivered settings remain PostgreSQL-only. The commands above
are the required PostgreSQL 18.6, permissions, image-build, and HTTP verification
on your machine; those results have not been assumed.

## 6. Review and commit after verification

```powershell
git status --short
git add README.md compose.yaml .env.example scripts backend docs/AI_Order_Desk_Step_03_Backend.md
git diff --cached --stat
git commit -m "feat: initialize Django backend foundation"
if ($LASTEXITCODE -ne 0) { throw "Commit failed." }
```

`status` shows the local changes. `add` stages the source and templates, including
the lock and migration. `diff --cached --stat` lists staged files for review:
`.env`, `.venv`, and caches must not appear. `commit` creates local history; it
does not publish the project or deploy anything.

For later sessions, `docker compose up -d --wait --wait-timeout 120` starts both
regular services; `docker compose down` stops them while keeping the volume.
Source is bind-mounted for local development. Rebuild `api` after dependency
or Dockerfile changes. Privileged helpers have a `tools` profile and stay off
until explicitly invoked.

Optional after verification: `docker compose run --rm manage python manage.py
createsuperuser` creates a local platform operator interactively. Use a unique
password. This is not needed for either health endpoint or the next tenancy
step, and an operator is not a distributor workspace administrator.

## Tools and alternatives

| Tool | Fit and maturity | License | Local / managed choice | Viable alternative |
| --- | --- | --- | --- | --- |
| Django 5.2 LTS | Mature framework with ORM, migrations, sessions, forms, and admin; actively supported LTS line. | BSD-3-Clause | Local/self-hosted application; can later run on a managed app host. | FastAPI with SQLAlchemy/Alembic, which requires assembling more identity/admin behavior. |
| Django REST Framework | Mature, actively maintained Django API toolkit; supplies sessions, permissions, requests, and JSON responses. | BSD-3-Clause | Runs inside the application; no separate managed service is needed. | Django Ninja. |
| Psycopg 3 | Established, actively maintained PostgreSQL driver; modern Django compatibility and binary wheels simplify Windows/Linux setup. | LGPL-3.0-only | Bundled driver works with self-hosted or managed PostgreSQL. | Psycopg's C build linked against a separately maintained system libpq. |
| uv | Actively maintained package/environment tooling; produces a cross-platform lock with hashes and fast clean installs. | MIT OR Apache-2.0 | Local build tool; no managed account required. | Poetry. |
| Ruff | Actively maintained Python linter/formatter with broad adoption; one tool covers style, import order, and selected correctness/security rules. | MIT | Local CLI now; same command can run in CI later. | Black plus Flake8 and isort. |
| Django test runner / unittest | Mature framework and standard-library test tooling; checks behavior without extra test infrastructure. | Django BSD-3-Clause / Python PSF | Local tests now; CI runner later. | pytest plus pytest-django. |

There are no AGPL or BSL dependencies among these direct choices. Psycopg's
LGPL license needs its redistribution notices/obligations considered when
shipping images; using the driver does not impose an AGPL-style network source
disclosure rule. Keep dependency license notices with redistributed builds.
Self-hosted development requires no paid service. Managed hosting and licensed
third-party ERP connectors will be evaluated separately, within your cost constraint.

## Common pitfalls

- **API started too early:** run `dbsetup` and migrations first. Readiness checks
  the actual user table, so a healthy PostgreSQL process alone is insufficient.
- **Image missing:** run `docker compose build api` before either helper. All
  backend services intentionally share that image.
- **Password mismatch with existing volume:** restore the original bootstrap
  value. Editing initialization variables does not rotate existing PostgreSQL
  credentials. The helper preserves that value during this upgrade.
- **Migration-role mismatch:** use the `manage` helper for schema changes. The
  API startup check catches privileges that would undermine later RLS.
- **Test-database creation error:** provision once and use `--keepdb`. Do not
  solve this by granting CREATEDB or superuser to the API.
- **Import errors from host Python:** run backend commands in containers. This
  backend deliberately requires Python 3.14; the host only runs stdlib helpers.
- **Stale lock:** change pins deliberately, run `uv lock` with the pinned uv
  version, inspect the diff, rebuild, and reverify. Do not delete the lock or
  use unlocked package installation as a workaround.
- **Startup failure:** inspect `docker compose logs --tail 60 api` and the failed
  command. Share the error with secrets removed; do not share `.env` or full
  resolved Compose configuration.

## Definition of Done — stop here

- [ ] Patch is in the existing project and the PostgreSQL volume is preserved.
- [ ] Environment upgrade preserves existing values; `.env` remains ignored.
- [ ] Backend image builds using the committed dependency lock.
- [ ] Database setup and migrations succeed; the user table has the migration owner.
- [ ] API runs as a restricted database role and passes its live role check.
- [ ] Both containers are healthy and both HTTP probes return 200 with status `ok`.
- [ ] All 25 PostgreSQL backend tests and five host helper tests pass.
- [ ] Django checks, migration consistency, lint, formatting, and lock checks pass.
- [ ] The verified changes are committed locally.

If a command fails, stop and share that command and its redacted error. Otherwise
send this exact next prompt, filling in the requested output:

> Step 3 verified. Here are my docker compose ps output, PostgreSQL permissions
> output, test summaries, and both health responses: __. Start Step 4:
> organizations, memberships, and tenant isolation, one small step at a time.

## Official references to verify when upgrading

- Django supported versions: https://www.djangoproject.com/download/
- Custom user model timing: https://docs.djangoproject.com/en/5.2/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project
- Django deployment checklist: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- Django PostgreSQL requirements: https://docs.djangoproject.com/en/5.2/ref/databases/#postgresql-notes
- DRF authentication: https://www.django-rest-framework.org/api-guide/authentication/
- uv lock/sync: https://docs.astral.sh/uv/concepts/projects/sync/
- uv Docker integration: https://docs.astral.sh/uv/guides/integration/docker/
- Ruff settings: https://docs.astral.sh/ruff/configuration/
- Psycopg installation: https://www.psycopg.org/psycopg3/docs/basic/install.html
- PostgreSQL privileges: https://www.postgresql.org/docs/current/sql-grant.html
- PostgreSQL default privileges: https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html
- PostgreSQL RLS: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
