# Step 4C.1 — Transaction-local tenant scope

## Goal and status

Implement the transaction helper specified by the committed Step 4C.0 database
boundary. An authenticated server-side actor and an explicit workspace UUID
identify each operation. The helper freshly authorizes that workspace and binds
the organization/user IDs for one short PostgreSQL transaction.

Verification: **passed on 2026-10-05 (Africa/Nairobi)**.
Commit: **authorized by the user after verification**.

This increment adds no dependency, model, migration, service, or HTTP endpoint.
Step 4C.2 will add CatalogItem, its privileges, and forced RLS policies tested as
orderdesk_app. The helper alone does not filter business rows; catalogue APIs
remain blocked until that database boundary passes its verification gate.

## Files

Paths are relative to C:\Users\HomePC\Desktop\Billion1\order-desk:

| Path | Responsibility |
| --- | --- |
| backend/apps/organizations/transactions.py | Own the transaction; reject unsafe connection state; freshly authorize; bind local tenant settings; yield WorkspaceContext. |
| backend/apps/organizations/tests/test_tenant_transactions.py | Guard, PostgreSQL transaction, cleanup, reuse, authorization, and organization-lock concurrency regressions. |
| docs/AI_Order_Desk_Step_04C1_Tenant_Transactions.md | This contract and verification record. |

The source files were already present as untracked draft work at handoff. Review
them in place. This guide replaces the imported archive tutorial previously
named AI_Order_Desk_Step_04C2_Tenant_Transactions.md; helper numbering now follows
design 4C.0 → transaction helper 4C.1 → catalogue/RLS 4C.2.

## Helper contract

Use tenant_scope(*, user, workspace_id: UUID, write: bool = False) as a
synchronous context manager on Django's default PostgreSQL connection.

1. Require a parsed UUID and a real bool. Wrong types raise TypeError;
   a string such as "false" cannot enable writes.
2. Require no Django atomic block and enabled Django autocommit. Before any
   ambient-settings query, also require the live Psycopg connection to have
   autocommit enabled and transaction status IDLE. Reject caller-owned
   transactions, including explicit SQL BEGIN and native-driver transactions,
   without querying, closing, committing, or rolling them back.
3. Inspect orderdesk.organization_id and orderdesk.user_id as text. Missing
   or blank settings form a clean baseline. Any nonempty value, including a
   malformed UUID, discards the idle connection and raises TenantScopeError.
   Local settings restore earlier session values; they do not erase them.
4. Enter transaction.atomic(durable=True). Before the first data query, set
   transaction-local READ COMMITTED and READ ONLY, or READ WRITE when
   explicitly requested. Session defaults remain unchanged.
5. For writes, lock the active organization row with SELECT ... FOR UPDATE
   before authorization. Membership-changing services must use this same lock
   order, as add_member already does.
6. Call resolve_workspace_context for fresh active-account, organization,
   membership, and role checks. Unknown and unavailable workspaces retain the
   existing generic PermissionDenied; operator flags grant no access.
7. Bind both setting names and UUID values as SQL parameters using
   set_config(..., true), then yield the immutable scalar context. Roles remain
   in membership rows; selection in the browser session cannot override scope.
8. Commit on success or roll back when an exception leaves the block. PostgreSQL
   restores the clean baseline. Do not issue cleanup SQL in an aborted
   transaction or silently retry an unsafe connection under another workspace.

TenantScopeError reports unsafe connection state or incorrect transaction use;
unsupported database engines raise ImproperlyConfigured. A scope rejects
another tenant scope even for the same workspace, while same-tenant atomic
savepoints are permitted. Keep ATOMIC_REQUESTS disabled.

READ COMMITTED ensures authorization after an organization-lock wait sees a
demotion or revocation committed by the preceding lock holder. This does not
cancel an operation that has already authorized. Each business write still
checks its required role; write=True supplies no administrator permission.

## Usage boundary

This example returns fully materialized scalar output; it introduces no API:

```python
from uuid import UUID

from apps.accounts.models import User
from apps.organizations.transactions import tenant_scope


def read_workspace_summary(*, user: User, workspace_id: UUID) -> dict[str, str]:
    with tenant_scope(user=user, workspace_id=workspace_id) as context:
        result = {
            "id": str(context.organization_id),
            "name": context.organization_name,
            "role": context.role.value,
        }
    return result
```

Future business queries must explicitly filter by context.organization_id and
finish evaluation inside the block. Do not return lazy QuerySets, generators,
deferred fields, or relations that fetch later; the helper cannot detect every
deferred query. Row-locking queries need a write scope. Default read scopes
reject ordinary table DML.

Catch errors outside the scope before translating them into HTTP responses.
Keep OCR, model calls, email, and ERP network work outside the transaction.
on_commit runs after tenant context is gone; a callback or job needing tenant
data must open its own scope and freshly authorize its actor/workspace.

## Tests and failure paths

Early guards use SimpleTestCase; native transaction behavior uses
TransactionTestCase against the dedicated PostgreSQL test_orderdesk database.
Ordinary Django TestCase supplies an outer transaction and cannot exercise this
helper's real commit boundary. Fixture setup uses the migration role; these
tests prove transaction semantics, while runtime-role RLS tests follow in 4C.2.

| Coverage | Required result |
| --- | --- |
| Input/backend guards | Reject wrong UUID/write types and unsupported backends. |
| Caller-owned transactions | Reject Django atomic/manual transactions, explicit SQL BEGIN, and native-driver transaction/autocommit state before ambient SQL; preserve the caller's transaction and data. |
| Fresh authorization | Deny anonymous, unsaved, inactive, revoked, nonmember, and unavailable-workspace cases; return the current name/role for authorized actors. |
| Transaction mode | Default read scopes reject DML with SQLSTATE 25006; explicit writes commit; isolation/mode changes remain local. |
| Exit and connection reuse | Commit, application/database errors, savepoint rollback, alternating actors/workspaces, and callbacks leave no inherited tenant IDs; connections remain usable. |
| Ambient settings | Valid or malformed nonempty settings discard only an idle connection; blank settings are accepted. |
| Lock races | A waiting write scope observes committed demotion and rejects committed membership revocation. Bounded waits and pg_blocking_pids confirm actual blocking. |

Do not substitute SQLite, grant elevated privileges, suppress PostgreSQL skips,
or weaken a guard to obtain a passing result. Never treat owner-role test results
as proof of runtime business-row isolation.

## Verification

Run from the project root. These commands create temporary containers and use
the dedicated test database; they are not read-only audit commands. Keep the
existing named volume and credentials. No rebuild or dependency install is
needed because Compose bind-mounts the backend source.

The eight required verification gates, with PowerShell failure guards:

```powershell
docker compose run --rm manage python manage.py check
if ($LASTEXITCODE -ne 0) { throw "Django configuration checks failed." }

docker compose run --rm manage python manage.py makemigrations --check --dry-run
if ($LASTEXITCODE -ne 0) { throw "Models and committed migrations differ." }

docker compose run --rm manage python manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "Migration verification failed." }

docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backend tests failed." }

docker compose run --rm manage ruff check .
if ($LASTEXITCODE -ne 0) { throw "Lint checks failed." }

docker compose run --rm manage ruff format --check .
if ($LASTEXITCODE -ne 0) { throw "Formatting checks failed." }

docker compose up -d --wait --wait-timeout 120 api
if ($LASTEXITCODE -ne 0) { throw "API startup or readiness failed." }

docker compose exec api python manage.py check_runtime_role
if ($LASTEXITCODE -ne 0) { throw "Runtime database privileges are unsafe." }
```

Expected: no Django issues; No changes detected; no new migration from this
increment; full suite OK with no PostgreSQL skips; Ruff checks pass; startup
reaches readiness; Runtime database role is restricted. Record the actual
test count and results after execution rather than assuming the draft's count.

Use this focused command to inspect individual transaction/concurrency results:

```powershell
docker compose run --rm manage python manage.py test apps.organizations.tests.test_tenant_transactions --settings=config.settings.test --keepdb --noinput -v 2
if ($LASTEXITCODE -ne 0) { throw "Tenant transaction tests failed." }
```

Both new lock races must report ok:

- test_write_scope_waits_for_lock_and_observes_committed_demotion
- test_write_scope_rechecks_membership_after_waiting_for_revocation

The full suite must also execute both existing PostgreSQL concurrency tests:
test_concurrent_first_attempts_cannot_exceed_account_budget and
test_simultaneous_duplicate_adds_create_one_membership. Use full-suite -v 2
when their individual result lines are needed.

Validate service and HTTP health:

```powershell
docker compose ps
$live = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/v1/health/live/" -ErrorAction Stop
$ready = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/v1/health/ready/" -ErrorAction Stop
if ($live.StatusCode -ne 200 -or $ready.StatusCode -ne 200) { throw "A health endpoint failed." }
if (($live.Content | ConvertFrom-Json).status -ne "ok" -or ($ready.Content | ConvertFrom-Json).status -ne "ok") { throw "Unexpected health response." }
$live.StatusCode
$live.Content
$ready.StatusCode
$ready.Content
git diff --check
if ($LASTEXITCODE -ne 0) { throw "Whitespace checks failed." }
git status --short
```

Expected: db and api healthy; both endpoints HTTP 200 with {"status":"ok"};
no whitespace errors; only the three intended paths appear as changes.
Untracked source files require direct review because normal git diff omits them.
No new HTTP verifier or seeded application data is needed for this increment.

If a command fails, report that exact command and its redacted error, then fix
the cause within the agreed scope. If test_orderdesk is missing, stop rather
than granting CREATEDB or superuser. Never print .env, resolved Compose
secrets, passwords, cookie values, or tokens. Never delete the database volume.

## Definition of Done and commit boundary

### Results recorded on 2026-10-05

All eight verification gates ran successfully against the existing local
Docker/PostgreSQL stack. The full suite used `-v 2` to inspect individual
concurrency results; the runtime-role command used `exec -T` for noninteractive
execution. No new migration or dependency was introduced.

| Verification | Actual result |
| --- | --- |
| Django configuration check | `System check identified no issues (0 silenced).` |
| Migration drift | `No changes detected` |
| Migration application | `No migrations to apply.` |
| Focused transaction suite | **33 tests in 6.602s, OK, no skips**: seven guards and 26 PostgreSQL tests. |
| Full backend suite | **203 tests in 32.781s, OK, no skips**: the committed 170-test baseline plus 33 transaction tests. |
| Ruff lint | `All checks passed!` |
| Ruff formatting | `74 files already formatted` |
| API startup/readiness | Completed successfully; both db and api healthy. |
| Runtime database role | `Runtime database role is restricted.` |
| Health HTTP checks | Both live and ready returned HTTP 200 with `{"status":"ok"}`. |

All four PostgreSQL concurrency tests reported `ok`:

- `test_concurrent_first_attempts_cannot_exceed_account_budget`
- `test_simultaneous_duplicate_adds_create_one_membership`
- `test_write_scope_waits_for_lock_and_observes_committed_demotion`
- `test_write_scope_rechecks_membership_after_waiting_for_revocation`

The added native-state tests verified rejection before SQL while preserving raw
transactions, pending changes, local settings, and caller-controlled cleanup.
An initial Ruff check found one 89-character test line against the 88-character
limit; that line was wrapped, then lint and formatting passed.

Source review covered all three untracked files. Their direct whitespace checks
passed, and Git status contained only those three intended paths. At verification
time, nothing was staged or committed. These results establish the helper's contract;
runtime business-row RLS verification remains Step 4C.2.

- [x] Only the two helper/test source files and this correctly numbered guide change.
- [x] Caller-owned native and Django transactions remain intact when rejected.
- [x] Fresh authorization, transaction modes, ambient settings, rollback, reuse,
      savepoints, callbacks, and both organization-lock races pass on PostgreSQL.
- [x] The full backend suite passes without skips, including both earlier concurrency tests.
- [x] All eight verification gates and both health checks pass; actual results are recorded.
- [x] The diff, direct untracked-file review, whitespace, and Git status are checked.
- [x] No catalogue/API/RLS work, dependency changes, privilege loosening, or secrets are included.

Stop after verification and report results. Commit only when the user explicitly
requests it. Then stage these exact three paths, inspect the staged diff and
status for secrets/stray files, and commit the verified increment. The user
explicitly authorized the Step 4C.1 commit after verification.

Next increment: Step 4C.2, CatalogItem and forced PostgreSQL RLS verified as the
restricted runtime role, before any catalogue API.

## Official references

- [PostgreSQL 18 current_setting and set_config](https://www.postgresql.org/docs/18/functions-admin.html)
- [PostgreSQL SET LOCAL restoration and savepoints](https://www.postgresql.org/docs/18/sql-set.html)
- [PostgreSQL transaction modes and isolation](https://www.postgresql.org/docs/18/sql-set-transaction.html)
- [PostgreSQL row locks](https://www.postgresql.org/docs/18/explicit-locking.html)
- [Psycopg connection transaction status](https://www.psycopg.org/psycopg3/docs/api/pq.html#psycopg.pq.TransactionStatus)
- [Django 5.2 atomic transactions and on_commit](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- [Django TransactionTestCase](https://docs.djangoproject.com/en/5.2/topics/testing/tools/#transactiontestcase)

Reuse the locked stack and existing local tools at $0. No new licence or
dependency decision is introduced. Recheck matching official documentation when
changing transaction behavior or deliberately upgrading dependencies.
