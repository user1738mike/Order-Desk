# Local verification

This is the maintained runbook for the actual checkout. Historical step guides
retain their original increment records; old snapshot overlays and commit hashes
are not prerequisites. Run only against local synthetic development data.
The full local audit is private and ignored; publish only the sanitized results
in [project state](PROJECT_STATE.md), not that report or its logs.

## Working directory and pinned environment

Open PowerShell in the application directory containing `compose.yaml`:

```powershell
Set-Location -LiteralPath 'C:\Users\HomePC\Desktop\Billion1\order-desk'
```

For another checkout, substitute its actual application directory. Git may have
the enclosing workspace as its root. Confirm the branch and preserve existing
staged/unstaged/untracked work before any delivery operation:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git status --short
git remote -v
```

The locked stack is Python 3.14.8, Django 5.2.17, DRF 3.18.1, Psycopg 3.3.6,
uv 0.12.23 and Ruff 0.16.10; Compose pins PostgreSQL 18.6-bookworm.
`backend/pyproject.toml`, `backend/uv.lock`, `backend/.python-version` and
`backend/Dockerfile` are authoritative. Keep the existing locks and $0 budget.
Docker builds use `uv sync --locked`; no new dependency resolution is needed.
The existing editor environment is `../.venv`, using the same lock; see
[editor setup](EDITOR_SETUP.md) to provision/resync it. The frontend uses native
browser modules without a build/install step; Node tests and real-browser checks
are documented in [the frontend guide](FIRST_FRONTEND_WORKFLOW.md).

## Initial local setup

These initialization commands are source-validated setup instructions, not
commands repeated by a documentation-only change. Existing installations should
skip provisioning/migration application when consistency checks already pass.
Provisioning changes role grants; schema application changes the database.
Preserve `.env`, existing passwords and the named PostgreSQL data volume.

On this workspace, use the pinned editor Python; on a new installation first
provision the editor environment or use a compatible host Python for the
standard-library-only environment initializer described in the Step 3 guide.

```powershell
& '..\.venv\Scripts\python.exe' scripts/init_env.py
docker compose config --quiet
docker compose build api
docker compose up -d --wait --wait-timeout 120 db
docker compose run --rm dbsetup
docker compose run --rm manage python manage.py migrate --noinput
docker compose up -d --wait --wait-timeout 120 api
```

Check `$LASTEXITCODE` immediately after each native command and stop on an
unexpected nonzero result. Do not continue a failed setup as if it passed.
The initializer extends `.env` without replacing existing credentials. Never
print `.env` or an expanded secret-bearing `docker compose config`; use `--quiet`.
`dbsetup` requires the administrative credentials already defined by Compose.
It provisions separate `orderdesk_app` and `orderdesk_migrator` roles, creates
`test_orderdesk` owned by the migrator if absent, and sets grants in both local
databases. It rejects unexpected ownership rather than replacing the database.
Migrations include their own role/RLS/grant prerequisites; all application
migrations must be present before either full runtime verifier is valid.
The initial native test run below creates/applies test schema using the migrator;
there is no need to drop/reset the test database.

`manage` uses migration credentials; `api` uses runtime credentials.
The `rlscheck` service is a short-lived verifier with the dedicated test database
and a separate maintenance alias for synthetic fixture setup/cleanup. The API
does not receive those verifier owner credentials. Never run `down -v`, drop the
test database, delete untracked work or reset Git as a routine verification step.
`docker compose down` without volume flags preserves the database volume.

## Consistency and normal PostgreSQL tests

From the application directory:

```powershell
docker compose config --quiet
docker compose run --rm manage python manage.py check
docker compose run --rm manage python manage.py makemigrations --check --dry-run
docker compose run --rm manage python manage.py migrate --check
docker compose run --rm manage python manage.py showmigrations accounts organizations catalog orders
docker compose run --rm manage uv pip check --python /opt/venv/bin/python
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0
& '..\.venv\Scripts\python.exe' -m unittest discover -s scripts/tests -v
```

The checks do not apply pending main-database migrations. The native Django
runner uses PostgreSQL, migration/maintenance credentials and fixed
`DATABASES.default.TEST.NAME=test_orderdesk`; `--keepdb --noinput` preserves that
dedicated database between runs. `config.settings.test` keeps PostgreSQL and
sets DEBUG false. Run fixture suites sequentially, including both verifiers.
The full suite includes existing concurrency tests with distinct connections.
Do not hardcode today's test count as an acceptance threshold.

For a focused orders change, substitute `apps.orders` or the affected test
module after `test`; similarly `apps.catalog` and `apps.organizations` select
their suites. The host script tests use temporary/mocked helper scenarios and
do not prove live HTTP behavior or PostgreSQL runtime isolation.
`uv pip check` proves compatibility of the installed image environment, not
that a fresh image has been rebuilt or deployed.

## Restricted-runtime tenant isolation

After a successful native test run has established current test schema:

```powershell
docker compose run --rm rlscheck python manage.py verify_catalog_rls
docker compose run --rm rlscheck python manage.py verify_order_rls
docker compose exec -T api python manage.py check_runtime_role
```

Both verifiers guard PostgreSQL, local DEBUG settings, exact database
`test_orderdesk`, a clean outer connection, and actual `current_user` **and**
`session_user` equal to `orderdesk_app`. They audit restricted role attributes,
grants, forced RLS, policies and tenant constraints before fixture creation.
Leave `rlscheck` on its existing `config.settings.local`; overriding it with
the DEBUG-false native test settings makes the verifier refuse to run.
The default connection tests reads/writes directly as the restricted runtime
role. The separately audited migrator alias creates and cleans synthetic data.
No SQLite, mocked policy checks, owner connections or owner `SET ROLE` tests
replace this evidence. `check_runtime_role` alone is a role sanity gate,
not the full tenant-isolation test.

Verify refusal on the live API's main database without generating fixtures:

```powershell
docker compose exec -T api python manage.py verify_catalog_rls
# Expected LASTEXITCODE: 1; Refusing to populate anything except test_orderdesk.
docker compose exec -T api python manage.py verify_order_rls
# Expected LASTEXITCODE: 1; Refusing to populate anything except test_orderdesk.
```

Require both the expected exit code and the specific refusal message. A different
connection/authentication error is a blocker, not a successful safety check.
These guards run before fixture creation. Never pass a main database override to
`rlscheck` or bypass a refusal. A missing/misconfigured test database must be
resolved through reviewed local provisioning, not by silently testing on main.

## Lint and format

The reliable host invocation uses the **backend working directory**:

```powershell
Push-Location -LiteralPath backend
& '..\..\.venv\Scripts\ruff.exe' check . ../scripts
& '..\..\.venv\Scripts\ruff.exe' format --check . ../scripts
Pop-Location
git diff --check
```

Check each exit code before continuing. This discovers the app's configuration
and anchors `apps/*/migrations` exclusions and test per-file rules correctly.
Running `--config backend/pyproject.toml backend scripts` from the application
root produced 95 diagnostics during the audit by changing path matching;
unconfigured root script lint produced three different-rule warnings. Those
diagnostic commands are not the documented gate. Do not disable useful rules
or reformat generated migrations to compensate. The canonical commands passed
unchanged. The Docker `backend-lint` task checks backend files; the host combined
command additionally checks the six host-script files.

## Local health and verification evidence

With `api` running:

```powershell
docker compose ps
docker compose exec -T api python -c "import urllib.request; paths=['live/','ready/']; [(lambda r: print(p, r.status, r.read().decode()))(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/'+p)) for p in paths]"
```

Both probes must return HTTP 200 and `{"status":"ok"}`. Readiness confirms a
basic database query, not the complete tenant boundary or deployment security.
Optional credential helpers (`scripts/verify_session_auth.py`,
`verify_workspace_selection.py`, `verify_catalog_api.py` and management
`verify_catalog_api`) have their own guarded read/local contracts. Do not invent
credentials, provision main-database fixture users or print business responses
merely to declare these optional workflows verified.

Record date, branch/candidate, exact commands, environment, results, skips and
blockers in project state. Keep normal Django, catalogue runtime, order runtime
and host-script counts separate. Redirect logs only to ignored `backend/var/`
if needed; inspect exit codes and final summaries. Expected synthetic-failure
tracebacks and negative-test HTTP responses are not test failures. PowerShell
can label Docker stderr progress as NativeCommandError in redirected logs;
use the native command exit and test result to judge success.

The 2026-10-08 audit results remain historical evidence: 679 native tests,
115 catalogue runtime checks, 40 order runtime checks and 23 script tests,
all passing without unittest skips. Reproduce the applicable gates when code,
executable configuration or the delivery candidate changes. Do not rerun the
entire suite just because prose changes. Production TLS/serving/proxy/SMTP/
backup/CI checks remain unverified; this runbook is for local development only.
