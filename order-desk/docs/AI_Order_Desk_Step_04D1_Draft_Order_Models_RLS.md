# Step 4D.1: Draft-order models and tenant boundary

## Scope and contract

This increment adds persistence for manual, draft-only order intake. It does
not add a draft HTTP API, matching, AI extraction, pricing, inventory, or
fulfilment. An empty draft is valid. A line may have no catalogue match and
may have NULL quantity; unknown quantities are never changed to one. See
`AI_Order_Desk_Step_04D1_Draft_Order_Design.md` for the domain contract.

The pre-existing `PurchaseOrder` domain and API are unchanged. The new
`DraftOrder` and `DraftOrderLine` are separate records. All synthetic rows
used for verification live in disposable `test_orderdesk`, not the main
`orderdesk` database.

## Changed files and migrations

| File | Responsibility |
| --- | --- |
| `backend/apps/catalog/models.py`, `catalog/migrations/0003_catalogitem_catalog_id_org_unique.py` | Add only the `(id, organization)` unique key needed by the catalogue composite foreign key. |
| `backend/apps/orders/models.py`, `orders/migrations/0006_draftorder_draftorderline_and_more.py` | UUID header and line models, Django relations, validators, timestamps, and database checks. |
| `backend/apps/orders/migrations/0007_draft_order_boundary.py` | PostgreSQL-only role guard, two composite foreign keys, forced RLS, and runtime grants. Raw SQL supplements, but does not replace, Django's ordinary relation and model state. |
| `backend/scripts/bootstrap_database.py` | Reapply restricted draft-table and column grants after general grants on every bootstrap rerun. |
| `backend/apps/health/management/commands/check_runtime_role.py`, `apps/health/tests/test_runtime_role.py` | Reject unsafe draft rights on actual API startup; exercise the new audit in unit tests. |
| `backend/apps/orders/management/commands/verify_order_rls.py`, `apps/orders/tests/runtime_rls.py` | Extend the guarded two-role verifier with draft policy, grant, composite-key, and direct `orderdesk_app` behavior checks. |
| `backend/apps/orders/tests/test_models.py`, `test_constraints.py`, `test_concurrency.py` | Model, raw PostgreSQL, and real-connection race coverage. |
| `backend/apps/catalog/tests/runtime_rls.py` | Keep the original administrator session valid in the Step 4C.9 replay/demotion test; a second login changed its password and invalidated that session. |
| Older order Python files and two root verifier scripts | Mechanical Ruff import/format cleanup needed for the full backend-and-script gate; no intended behavior change. |

`catalog.0003` depends on the previously implemented `catalog.0002` receipt
migration. `orders.0006` follows `orders.0005` and `catalog.0003`; `orders.0007`
adds the PostgreSQL boundary. The local main database had zero purchase orders
and zero catalogue items before applying the reviewed additive plan. It needed
older `orders.0002` through `0005` as prerequisites; all seven planned
migrations applied successfully. No sample order or item was inserted there.

## Database invariants

- Header: UUID, owning organization, protected initiating user, status exactly
  `draft`, source exactly `manual`, optional customer label/reference, optional
  original text of at most 10,000 characters, and timestamps. User deletion is
  protected, so deactivation does not erase historical attribution.
- Line: UUID, organization, parent draft, positive position unique per draft,
  optional requested SKU/description/unit, nullable `Decimal(12,3)` quantity,
  optional catalogue item, independent SKU/description snapshots, and
  timestamps. Nonblank SKU or description, or a referenced item with nonblank
  SKU snapshot, is required. A linked item always requires its SKU snapshot;
  an unlinked line has empty catalogue snapshots.
- PostgreSQL checks enforce `0 < quantity <= 999999999.999` when nonnull;
  numeric NaN fails the upper bound. Raw SQL tests cover zero, negative,
  excessive, and NaN quantities.
- Composite `(order_id, organization_id)` and nullable
  `(catalogue_item_id, organization_id)` foreign keys reject cross-tenant
  references even for a connection that can bypass RLS. Supporting
  `(id, organization_id)` unique keys are present on both parent tables.
- Snapshots do not track later catalogue edits or deactivation. Future
  attachment services must check current item eligibility at attachment time.

## Runtime boundary

Both draft tables have enabled and forced RLS. A restrictive tenant policy
requires matching transaction-local organization and user settings plus active
membership, user, and workspace. A permissive read policy allows active
members in any of the three roles. Insert and update policies allow only
active administrators/reviewers. Header INSERT additionally binds
`initiating_user_id` to the current user; line writes require a draft parent
in the same organization. Existing rows and proposed rows are checked.
Owner maintenance remains limited to `orderdesk_migrator`.

`orderdesk_app` receives SELECT and INSERT on both tables and UPDATE only on
mutable customer/header fields or line content/position/catalogue attachment
fields plus `updated_at`. It has no runtime DELETE, TRUNCATE, REFERENCES,
TRIGGER, or MAINTAIN grant. Identity, organization, parent, initiator, status,
source, and creation time are not runtime-updateable. The bootstrap helper
restores this exact grant shape after its broad provisioning step. The API
role audit and direct-runtime verifier check these rights after bootstrap.

Future write services must use `tenant_scope(write=True)`, acquire the
organization lock first, refresh active administrator/reviewer membership,
then touch draft/line rows. If demotion commits first, the write is denied;
if the protected write takes the lock first, it finishes before demotion.
This step exercises that lock order directly without exposing a draft-write
endpoint. Scope settings are transaction-local and clear on commit/rollback.

## Verification commands

From PowerShell in this repository:

```powershell
$compose = @('--project-directory', (Get-Location).Path,
  '-f', (Join-Path (Get-Location).Path 'compose.yaml'))
docker compose @compose run --rm manage python manage.py check
docker compose @compose run --rm manage python manage.py makemigrations --check --dry-run
docker compose @compose run --rm manage python manage.py migrate --check
docker compose @compose run --rm manage ruff check .
docker compose @compose run --rm manage ruff format --check .
docker compose @compose run --rm manage python manage.py test apps.orders.tests.test_models apps.orders.tests.test_constraints --settings=config.settings.test --keepdb --noinput
docker compose @compose run --rm manage python manage.py test apps.orders.tests.test_concurrency --settings=config.settings.test --keepdb --noinput
docker compose @compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput
docker compose @compose run --rm dbsetup
docker compose @compose run --rm rlscheck python manage.py verify_catalog_rls
docker compose @compose run --rm rlscheck python manage.py verify_order_rls
docker compose @compose run --rm api python manage.py check_runtime_role
docker compose @compose exec -T api python manage.py verify_order_rls
# The preceding command must refuse the main database, exiting nonzero.
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/health/live/
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/health/ready/
git diff --check
```

Use the locked image with read-only mounts to lint/format/test root `scripts`.
The existing `scripts/verify_catalog_api.py` needs an authenticated existing
account or a temporary account in `test_orderdesk`; never create verification
orders or catalogue items in the main database. The verifier logs out its
session. Both RLS verifiers explicitly refuse the main database.

## Actual verification

| Gate | Result |
| --- | --- |
| Django check, model drift, applied migrations | Passed; no issues, no drift, no pending migrations. |
| Focused draft model/constraint tests | 16 passed on PostgreSQL. |
| New draft concurrency tests | 3 passed; duplicate position commits once and both demotion lock orders hold. |
| Full normal PostgreSQL suite | 569 passed, no skips. |
| All concurrency modules | 54 passed. |
| Existing catalogue direct-runtime verifier | 115 passed, no skips, after repairing its invalidated-session fixture. |
| Order direct-runtime verifier | 31 passed, no skips, including draft checks as `orderdesk_app`. |
| Standalone script tests | 23 passed. |
| Backend and script Ruff lint/format | Passed; 140 Python files formatted. |
| Bootstrap rerun and runtime role | Passed; restricted draft grants survived. |
| Main-database verifier guards | Both returned `Refusing to populate anything except test_orderdesk.` |
| Live catalogue HTTP verifier | Passed against a temporary API and synthetic account in `test_orderdesk`; fixture and server removed. Exact existing-SKU success was unavailable because the catalogue page was empty; native checks cover it. |
| Live and ready endpoints | Both returned `{"status":"ok"}` on the local API. |

Definition of Done: draft-only persistence and snapshots, native quantity and
tenant constraints, forced RLS, restricted runtime grants after bootstrap,
role/demotion/rollback verification, no draft HTTP writes, no production
fixtures, and clean system/migration/lint/test/security gates. The next
increment is a bounded, read-only, tenant-scoped draft-order API.
