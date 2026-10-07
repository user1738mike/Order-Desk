# Step 4C.3 — First catalogue model and PostgreSQL RLS boundary

## Goal and scope

Create `CatalogItem` and enforce the approved tenant boundary at the database.
Prove the boundary with a real connection authenticated as `orderdesk_app`.
This increment adds schema, policies, model tests, and a local verifier. The
catalogue HTTP API, imports, matching, and frontend follow after verification.

Your attachment confirms **198 PostgreSQL tests passed in 18.247 seconds with
no skips**, including all four concurrency tests. It contains the test log;
migration checks, health, runtime role, and the commit are reported verified
by you rather than shown in this particular attachment.

Allow 30–45 minutes to apply, read, and verify. Use your existing locked Django,
Psycopg, PostgreSQL, and Ruff versions. No new backend dependencies or paid
services are introduced. `rlscheck` is a one-shot local tool container using
the existing backend image, not a new production service.

## 1. Apply the reviewed increment

Download `AI_Order_Desk_Step_04C3_Catalogue_RLS.zip`. The archive includes the
complete changed/new files plus `apply_step4c3.patch`. Apply the patch from the
project root; Git checks context before editing existing files. Do not copy
whole replacement files over your local changes.

```powershell
Set-Location -LiteralPath "C:\Users\HomePC\Desktop\billion1\order-desk" -ErrorAction Stop
$workingTree = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect Git status." }
if ($workingTree.Count -ne 0) { throw "Finish or preserve your existing changes before applying this increment." }

$archivePath = Join-Path $env:USERPROFILE "Downloads\AI_Order_Desk_Step_04C3_Catalogue_RLS.zip"
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) { throw "Download the Step 4C.3 ZIP first." }
$stagePath = Join-Path $env:TEMP ("orderdesk-step4c3-" + [guid]::NewGuid().ToString("N"))
Expand-Archive -LiteralPath $archivePath -DestinationPath $stagePath -ErrorAction Stop
$patchPath = Join-Path $stagePath "apply_step4c3.patch"
git apply --check -- $patchPath
if ($LASTEXITCODE -ne 0) { throw "The patch does not match this checkout; share the error before applying replacements." }
git apply -- $patchPath
if ($LASTEXITCODE -ne 0) { throw "Could not apply the reviewed patch." }
git status --short
git diff --stat
```

`Expand-Archive` creates a temporary staging directory. `git apply --check`
checks that the patch can be applied without changing your files. `git apply`
then creates the catalogue files and updates the three existing files below.
The archive's full source copies are available for reading. The patch itself
does not belong in your repository; the guide does.

### Where every file goes

Paths in this table are relative to
`C:\Users\HomePC\Desktop\billion1\order-desk`.

| File | Change and responsibility |
| --- | --- |
| `backend/apps/catalog/__init__.py` | New Python package marker. |
| `backend/apps/catalog/apps.py` | New `CatalogConfig`, registered as `apps.catalog`. |
| `backend/apps/catalog/models.py` | New distributor-owned stock-code identity and its structural constraints. |
| `backend/apps/catalog/migrations/__init__.py` | New migration package marker. |
| `backend/apps/catalog/migrations/0001_initial.py` | New atomic PostgreSQL-only migration: role checks, table creation, forced RLS, five policies, and restricted grants. Includes a deliberate reverse operation. |
| `backend/apps/catalog/tests/__init__.py` | New test package marker. |
| `backend/apps/catalog/tests/test_models.py` | 12 ordinary model/constraint tests under the maintenance owner. |
| `backend/apps/catalog/tests/test_verifier_guards.py` | Six tests preventing unsafe verifier environments, targets, transactions, and default identities. |
| `backend/apps/catalog/tests/runtime_rls.py` | 35 database-policy checks explicitly run as the actual runtime role. It is intentionally outside normal `test*.py` discovery. |
| `backend/apps/catalog/management/__init__.py` | New management package marker. |
| `backend/apps/catalog/management/commands/__init__.py` | New command package marker. |
| `backend/apps/catalog/management/commands/verify_catalog_rls.py` | New local-only command: audits the target/roles/policies/grants, registers a separate fixture-owner connection, runs the 35 checks, and closes connections. |
| `backend/config/settings/base.py` | Adds just `CatalogConfig` to `INSTALLED_APPS`. |
| `backend/scripts/bootstrap_database.py` | Preserves the catalogue DELETE/TRUNCATE revocation when local provisioning is rerun after the table exists. |
| `compose.yaml` | Adds the local `rlscheck` tool profile. Its default database role is the app; owner credentials are confined to this one-shot verifier. |
| `docs/AI_Order_Desk_Step_04C3_Catalogue_RLS.md` | This guide. |

There is no new admin registration, route, serializer, billing feature, queue,
or AI provider. The existing auth and workspace endpoints continue unchanged.

## 2. Read the model

Open `backend/apps/catalog/models.py`.

| Field / constraint | Meaning |
| --- | --- |
| UUID `id` | Server-generated item identity. |
| Required `organization` foreign key, `PROTECT` | Distributor ownership; an item prevents its organization being deleted through the ORM. The database FK also prevents an orphan. |
| Text `sku` | Distributor's stock code. Preserve case/punctuation. `clean()` trims edge whitespace. |
| Text `description`, default empty string | Human-readable description. |
| Boolean `is_active`, default true | Deactivate without deleting historical identity. |
| `created_at`, `updated_at` | UTC timestamps using the project's existing timezone settings. |
| Check `catalog_sku_not_blank` | Rejects blank/whitespace stock codes even when model validation is bypassed. |
| Unique `catalog_org_sku_unique` | One code per distributor, including inactive items. The same code can exist in different distributors. |

The Python validator and database check serve different boundaries: validation
gives a useful input error, while the constraint protects direct/bulk writes.
`save()` does not automatically call `full_clean()`. Future input/services must
validate and normalize before saving. The policy verifier deliberately bypasses
application validation to test database protection independently.

Units, packs, manufacturer aliases, pricing, and import limits will be defined
with actual customer data in their feature increment. An inactive SKU remains
reserved; reactivate/update the existing item rather than recycling its identity.
Authorized members can still read inactive items for historical references.
Future matching selectors will separately filter items eligible for new orders.

## 3. Read the atomic migration and policies

Open `backend/apps/catalog/migrations/0001_initial.py`. Keep this historical
definition independent of future live model/service changes.

The migration runs in one transaction:

1. Refuse non-PostgreSQL backends.
2. Require the approved migration role and safe `orderdesk_app` /
   `orderdesk_migrator` attributes. Refuse superuser/bypass/role-membership
   configurations and runtime schema CREATE.
3. Create `public.catalog_catalogitem` with the model constraints.
4. Enable and force RLS, narrow runtime grants, and install these five policies.

| Policy | Composition / command | Role | Rule |
| --- | --- | --- | --- |
| `catalog_tenant_boundary` | Restrictive / ALL | `orderdesk_app` | Existing/proposed organization must match the local UUID, with an active membership in an active organization for an active local user. |
| `catalog_member_read` | Permissive / SELECT | `orderdesk_app` | Grants reads that also satisfy the mandatory boundary. |
| `catalog_admin_insert` | Permissive / INSERT | `orderdesk_app` | Current active membership must be `admin`; the boundary also checks the proposed row. |
| `catalog_admin_update` | Permissive / UPDATE | `orderdesk_app` | Checks the current admin role for old and proposed rows; the boundary prevents changing ownership to another workspace. |
| `catalog_owner_maintenance` | Permissive / ALL | `orderdesk_migrator` | Explicit privileged maintenance/fixture access, with `USING (true)` and `WITH CHECK (true)`. |

Applicable permissive command policies grant an operation; the restrictive
boundary must also pass. `USING` filters existing rows, and `WITH CHECK` rejects
invalid proposed rows. A viewer's update normally affects zero rows rather
than throwing an exception; a forbidden insert or ownership-changing update
raises an error. Future services will enforce their own role/error contracts.

The runtime gets only SELECT, INSERT, and UPDATE table privileges. There is no
runtime DELETE policy, and DELETE/TRUNCATE privileges are absent. RLS does not
protect TRUNCATE, which is why the privilege restriction matters. No policy
targets PUBLIC and no SECURITY DEFINER helper is introduced.

Both IDs come from the verified transaction helper:

```sql
NULLIF(pg_catalog.current_setting('orderdesk.organization_id', true), '')::uuid
NULLIF(pg_catalog.current_setting('orderdesk.user_id', true), '')::uuid
```

Missing/blank settings become NULL and grant no business access. Malformed
UUIDs fail closed. Roles are checked in current membership rows rather than
stored in a setting. The bootstrap patch preserves these table restrictions
after its general local CRUD provisioning is rerun.

The reverse operation revokes runtime access, drops the five policies,
disables RLS, then Django drops the table within the reversal transaction.
Reversing a table-creation migration removes its data. We are not running a
reversal against your main database. Future production rollbacks should normally
use a forward fix; test destructive reversals only against disposable data.

## 4. Understand the two-role verifier

Normal Django tests run with the migration role. They verify constraints,
authorization logic, and transaction lifetimes; that role's maintenance policy
cannot prove runtime row filtering.

`docker compose run --rm rlscheck` instead starts a short-lived process with:

| Connection | Identity / database | Purpose |
| --- | --- | --- |
| Django `default` | `orderdesk_app` / `test_orderdesk` | All row-isolation assertions, unfiltered ORM queries, writes, and the real `tenant_scope` helper. |
| `catalog_rls_owner` | `orderdesk_migrator` / `test_orderdesk` | Create, change, and remove synthetic fixtures only. |

The command refuses non-development settings, a non-PostgreSQL backend, an
existing transaction, or any database except `test_orderdesk`. It checks the
actual server database and both current/session users, not just the configured
name. It refuses owner impersonation as the default connection, unsafe runtime
attributes, wrong table ownership, missing ENABLE/FORCE RLS, unexpected policies,
or unexpected privileges before creating fixtures.

Owner credentials are read only in this local tool process. They are absent
from the normal API environment. No role membership or SET ROLE shortcut is
used to obtain runtime proof. The owner connection is registered separately,
audited, then removed afterward.

Each case creates random-UUID fixtures with synthetic `example.test` accounts
and stock codes. Cleanup is registered before setup; partial fixture creation
rolls back. Cleanup deletes only those generated organization/user IDs in FK
order, including after assertion failures. It never truncates the test database.
Run tests and the verifier sequentially because they share `test_orderdesk`.

The 35 checks cover missing/blank/malformed context, deliberate unfiltered reads,
cross-tenant IDs/inserts/ownership changes/bulk writes, admin vs viewer/reviewer
permissions, inactive items, account/membership/organization deactivation,
fresh role demotion, real connection reuse after commit/rollback, read-only
enforcement, forbidden DELETE/TRUNCATE/owner impersonation/policy changes,
and an actual organization-lock race ending in a denied catalogue update.

The race proves blocking with `pg_blocking_pids`; timeouts bound a broken test.
The owner transaction releases its lock before the worker is joined. Attempts
that unexpectedly succeed raise inside the transaction so forbidden test DDL
and writes are rolled back rather than left behind.

The verifier fails on a failed check, a skipped check, or an empty/incomplete
suite. The test-only helper that forges GUC values bypasses application checks
on purpose; do not copy it into application services.

### Security boundary to keep in mind

This first policy protects catalogue rows. User, Organization, Membership,
sessions, and login budgets retain the existing application checks. Settings
are server-controlled context, not a cryptographic customer identity; arbitrary
SQL or stolen runtime credentials can forge them and access global control
tables. Keep parameter binding, application authorization, and credential
protection. Continue using the organization lock for membership-changing writes.
Revocation does not instantly cancel a statement already in flight.

Future foreign keys between two tenant business tables need matching organization
ownership enforced by a composite FK or equivalent constraint; a UUID FK alone
is insufficient because integrity checks look through RLS. This first entity
references only the global Organization table.

## 5. Apply the schema and run the normal suite

Run from the project root. The source is bind-mounted; no image rebuild or new
package installation is required. Keep the two approved database role names.

```powershell
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose configuration is invalid." }
docker compose up -d --wait --wait-timeout 120 db
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL is not healthy." }

docker compose run --rm manage python manage.py check
if ($LASTEXITCODE -ne 0) { throw "Django checks failed." }
docker compose run --rm manage python manage.py makemigrations --check --dry-run
if ($LASTEXITCODE -ne 0) { throw "Models and committed migration state differ." }
docker compose run --rm manage python manage.py migrate --plan
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the migration plan." }
```

The plan should contain just `catalog.0001_initial` for this unchanged baseline:
the PostgreSQL check, role guard, model creation, and RLS/grants SQL. Inspect it
before executing the next block.

```powershell
docker compose run --rm manage python manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "The catalogue migration failed; stop and share the error." }
docker compose run --rm manage python manage.py migrate --check
if ($LASTEXITCODE -ne 0) { throw "A migration remains pending." }
docker compose run --rm manage python manage.py showmigrations catalog
if ($LASTEXITCODE -ne 0) { throw "Could not inspect catalogue migration state." }

docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 2
if ($LASTEXITCODE -ne 0) { throw "The normal PostgreSQL suite failed." }
docker compose run --rm manage ruff check .
if ($LASTEXITCODE -ne 0) { throw "Lint checks failed." }
docker compose run --rm manage ruff format --check .
if ($LASTEXITCODE -ne 0) { throw "Formatting checks failed." }
```

| Command | Purpose / expected result |
| --- | --- |
| `config --quiet` | Validates Compose without printing resolved secrets. |
| `up ... db` | Reuses your existing database volume and waits for health. |
| `check` | No Django configuration issues. |
| `makemigrations --check --dry-run` | `No changes detected`; the model and committed migration match. |
| `migrate --plan` | Shows the one new catalogue migration without applying it. |
| `migrate --noinput` | Applies the new boundary to your main development database as the migration owner. Creates no catalogue fixtures there. |
| `migrate --check`, `showmigrations` | Exit zero and `[X] 0001_initial`. |
| `test ... --keepdb` | Applies the same migration to the prepared test database, then runs **216 tests**, `OK`, no skips, with the unchanged baseline. This is 198 earlier tests plus 12 model and six verifier-guard tests. |
| Ruff | All lint checks pass; no files require formatting. |

The four existing concurrency tests from Step 4C.2 must still report `ok`.
The 35 runtime RLS cases are deliberately a separate command, not part of
this owner-role test count.

## 6. Run the actual runtime-role proof

First rerun the patched local provisioner once. This verifies that its broad
existing grant setup still leaves DELETE/TRUNCATE revoked on the new table in
both databases. It reuses existing local credentials and does not reset data.

```powershell
docker compose run --rm dbsetup
if ($LASTEXITCODE -ne 0) { throw "Local permission provisioning failed." }
docker compose run --rm rlscheck
if ($LASTEXITCODE -ne 0) { throw "Runtime RLS verification failed; do not expose a catalogue API." }
```

Expected output includes:

```text
Runtime database role is restricted.
Catalogue metadata verified: owner, forced RLS, 5 policies, grants.
...
test_demotion_that_wins_org_lock_denies_runtime_catalogue_update ... ok
...
Ran 35 tests ...
OK
Runtime catalogue RLS verification passed.
```

Require **all 35 checks passing, no skips**. This confirms table ownership,
policy composition, effective privileges, actual row filtering/write checks,
and the lock/demotion behavior as `orderdesk_app`. If it fails, keep the
boundary closed and share the complete failing check/error, without secrets.
Do not add BYPASSRLS, superuser, role membership, PUBLIC access, or a global
permissive policy to make it pass. Do not run this suite under `manage` with
the owner as its default connection.

## 7. Check the API, main-database refusal, and health

```powershell
docker compose up -d --wait --wait-timeout 120 api
if ($LASTEXITCODE -ne 0) { throw "API startup or readiness failed." }
docker compose exec api python manage.py check_runtime_role
if ($LASTEXITCODE -ne 0) { throw "API database privileges are unsafe." }
docker compose ps

$guardOutput = @(docker compose exec api python manage.py verify_catalog_rls 2>&1)
$guardExit = $LASTEXITCODE
$guardOutput | ForEach-Object { "$_" }
if ($guardExit -ne 1 -or (($guardOutput -join "`n") -notlike "*Refusing to populate anything except test_orderdesk.*")) {
    throw "The main-database guard did not produce its expected refusal."
}

$live = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/v1/health/live/" -ErrorAction Stop
$ready = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/v1/health/ready/" -ErrorAction Stop
if ($live.StatusCode -ne 200 -or $ready.StatusCode -ne 200) { throw "A health endpoint failed." }
if (($live.Content | ConvertFrom-Json).status -ne "ok") { throw "Unexpected liveness body." }
if (($ready.Content | ConvertFrom-Json).status -ne "ok") { throw "Unexpected readiness body." }
$live.StatusCode
$live.Content
$ready.StatusCode
$ready.Content
```

`up ... api` loads the mounted source and waits for readiness. The API's runtime
role check must remain restricted. Both services should be healthy.
The verifier invocation inside the normal API container must exit 1 with the
specific main-database refusal; another error is not a successful guard check.
No fixture connection or population is attempted on that path. Both health
responses must be HTTP 200 with `{"status":"ok"}`.

### Checks completed while preparing this increment

- Ruff lint and formatting pass.
- Django checks pass; migration state has no drift.
- Compose YAML parses, with the owner credentials confined to `rlscheck`.
- Migration forward/reverse SQL and the role-guard PL/pgSQL body parse against
  PostgreSQL 18.6's grammar.
- A private SQLite model/guard regression run collected 216 tests:
  **191 passed, 25 PostgreSQL-dependent tests skipped**. For that scratch-only
  check, the PostgreSQL catalogue migration was omitted; it verifies model and
  guard logic only. That harness/parser is not a backend dependency or deliverable.

No PostgreSQL server or Docker runtime is available here. Neither the new
migration's native execution nor the 35 runtime RLS checks have been executed
in this preparation environment. The two Docker test commands above are the
required verification gate; syntax parsing and owner/model tests cannot replace
runtime-role proof.

## 8. Review, commit, and stop

After all native checks pass:

```powershell
git add -- backend/apps/catalog backend/config/settings/base.py backend/scripts/bootstrap_database.py compose.yaml docs/AI_Order_Desk_Step_04C3_Catalogue_RLS.md
if ($LASTEXITCODE -ne 0) { throw "Could not stage the catalogue boundary." }
git diff --cached --stat
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "The staged patch contains whitespace errors." }
git diff --cached -- backend/apps/catalog/models.py backend/apps/catalog/migrations/0001_initial.py compose.yaml
git commit -m "feat: add catalogue model and PostgreSQL tenant RLS"
if ($LASTEXITCODE -ne 0) { throw "Could not commit the verified boundary." }
git status --short
```

Inspect the staged model, migration, and credential separation before committing.
The final working tree should be clean. Stop here; the first read-only catalogue
API follows after runtime verification.

## Tools and common pitfalls

| Existing tool | Fit / maturity | License / deployment | Alternative |
| --- | --- | --- | --- |
| PostgreSQL 18 native RLS | Established database row checks and policy composition. | Permissive PostgreSQL License; existing local container; managed hosting optional later. | Per-tenant databases, with more operational work. |
| Django ORM, migrations, tests, commands | Established framework APIs keep schema state and verification explicit. | BSD-3-Clause; self-hosted backend. | SQLAlchemy/Alembic, which would change the accepted stack. |
| Psycopg 3 | Existing maintained driver binds ORM values and context parameters. | LGPL-3.0-only; preserve notices/review redistribution obligations for customer-hosted packages. | Psycopg 2 after compatibility review. |
| Python unittest and Ruff | Existing test runner and fast code-quality checks; no new test dependency. | Python Software Foundation License / MIT; local/container execution. | pytest-django plus separate formatting tooling, adding configuration. |

Common mistakes are testing RLS as an owner, trusting an empty response without
checking grants/policy metadata, omitting the proposed-row check, forgetting
that permissive policies combine with OR, exposing a business route before the
runtime checks pass, or using a session GUC in application code. Keep the
approved scope helper, fresh membership, and explicit organization filters in
future business services. The owner policy is an intentional maintenance
exception, never a normal request path.

### Definition of Done

- [ ] Only this catalogue boundary, verifier, and three supporting existing-file edits are applied.
- [ ] The main database shows `catalog.0001_initial` applied; Django checks and migration drift checks pass.
- [ ] All 216 normal PostgreSQL tests pass, no skips, including the four earlier concurrency tests.
- [ ] The patched bootstrap rerun succeeds and preserves catalogue restrictions.
- [ ] The actual runtime verifier passes all 35 checks, no skips, including its lock/demotion race.
- [ ] The verifier refuses the main database with the expected message.
- [ ] Lint/formatting pass; the API role remains restricted; both health responses are HTTP 200 / `{"status":"ok"}`.
- [ ] The staged change is reviewed and committed; Git status is clean.

Send this exact next prompt after verification:

> Step 4C.3 verified and committed. Here are my migration output, 216-test PostgreSQL summary, four existing concurrency results, runtime RLS verifier output including its demotion race, main-database guard refusal, runtime-role check, health responses, and Git status: [paste output]. Start Step 4C.4: the first read-only, tenant-scoped catalogue API, one small step at a time.

## Official references

- [PostgreSQL 18 row security, owners, integrity checks, and policy races](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)
- [PostgreSQL CREATE POLICY: composition, USING, WITH CHECK](https://www.postgresql.org/docs/18/sql-createpolicy.html)
- [PostgreSQL privilege and role inquiry functions](https://www.postgresql.org/docs/18/functions-info.html)
- [Django 5.2 migration operations and RunSQL](https://docs.djangoproject.com/en/5.2/ref/migration-operations/)
- [Django model validation and full_clean](https://docs.djangoproject.com/en/5.2/ref/models/instances/#validating-objects)

Verify future schema/security changes against the matching official docs.
Dependency upgrades remain a separate reviewed increment.
