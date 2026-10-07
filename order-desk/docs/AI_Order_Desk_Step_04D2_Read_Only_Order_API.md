# Step 4D.2: Read-only draft-order API

## Contract

The existing session-authenticated workspace namespace gains three GET/HEAD
routes. They expose only the manual, draft-only records introduced in Step
4D.1. No draft write route, workflow transition, match, or schema change is
part of this increment.

| Route | Query parameters | Result |
| --- | --- | --- |
| `/api/v1/workspaces/<workspace-uuid>/draft-orders/` | Optional single `page` | Fixed 50-item page of draft summaries. |
| `/api/v1/workspaces/<workspace-uuid>/draft-orders/<order-uuid>/` | None | One header and a `lines_url`, no embedded lines. |
| `/api/v1/workspaces/<workspace-uuid>/draft-orders/<order-uuid>/lines/` | Optional single `page` | Fixed 50-item page of that draft's lines. |

List order is `-created_at, -id`; line order is `position, id`. The paginator
returns `count`, `next`, `previous`, and `results`, with the existing
`Invalid page.` 404 contract. Empty lists and empty drafts return a 200 page
with zero results. Repeated or unsupported query parameters return 400.
Page size, ordering, filters, tenant identity, and search are not caller
controlled. Deterministic ordering does not imply that separate page requests
see an unchanged snapshot while rows are changing.

Summary fields are exactly `id`, `organization_id`, `status`, `source_type`,
`customer_name`, `customer_reference`, `initiating_user_id`, `created_at`,
`updated_at`, and `line_count`. List responses omit original intake text and
all lines. Detail adds only `original_intake_text` and `lines_url`. Lines have
exactly `id`, `organization_id`, `order_id`, `position`, `requested_sku`,
`requested_description`, `quantity`, `unit`, `catalogue_item_id`,
`catalogue_sku_snapshot`, `catalogue_description_snapshot`, `created_at`, and
`updated_at`. Quantity is a precision-preserving decimal string or JSON null;
an unmatched catalogue reference remains null. Stored snapshots are never
substituted with live catalogue values.

## Security and transactions

An active session user with active administrator, reviewer, or viewer
membership in the active URL workspace may read. Missing, inactive, and
inaccessible workspaces retain the uniform workspace-access 403 response.
Anonymous or expired sessions retain the established authentication 403.
After workspace authorization, a missing or foreign draft is a 404. The URL
workspace is the only tenant selector; headers, cookies, bodies, and session
preferences cannot override it.

Each view opens a read-only `tenant_scope` and completes authorization refresh,
query validation, scoped selectors, count/annotation, pagination, scalar
serialization, and response-data materialization before leaving it. Draft
selectors filter by organization. Line selectors filter by both organization
and authorized parent order. PostgreSQL forced RLS provides a second tenant
boundary. Detail links use URL reversal and the request's validated host.
GET/HEAD need no CSRF token; OPTIONS remains available; write methods are
unavailable. Runtime grants, isolation level, and RLS policies are unchanged.

## Implementation and verification

Selectors explicitly scope headers and lines and annotate header line counts.
Read serializers expose UUID/scalar fields without loading related models.
The views materialize responses inside `tenant_scope`; draft pagination shares
the established fixed-page number rules with catalogue pagination, while
retaining its own query allowlist. Workspace routing adds a separate draft
namespace and leaves the existing purchase-order routes intact.

`test_read_contracts.py` checks selectors, field allowlists, decimal/null output,
reversed links, and pagination. `test_read_api.py` uses PostgreSQL and
CSRF-enforced sessions for role reads, tenant/missing-parent denials, rejected
write methods, page bounds/counts/order, empty lines, snapshot preservation,
read-only serialization, and rollback/context cleanup. Two additional runtime
checks use real credential sessions as `orderdesk_app` for all reader roles,
foreign-parent denial, unresolved lines, and fresh membership revocation.

Actual verification on 2026-10-07:

| Gate | Result |
| --- | --- |
| Focused draft read contracts/API | 16 passed in 2.869s. |
| Full normal PostgreSQL suite | 585 passed in 100.895s; no skips. Includes existing catalogue and concurrency regressions. |
| Direct-runtime order verifier | 33 passed in 17.699s; no skips. Metadata audit confirms forced RLS and restricted grants. |
| Backend Ruff lint/format | Passed; 137 Python files formatted. |
| Django system, model drift, migration state | Passed; no issues, model changes, or pending migrations. |
| Restricted runtime role | Passed on the local API. |
| Main-database verifier guard | Refused with `Refusing to populate anything except test_orderdesk.` |
| Real HTTP smoke check | Viewer credential login with CSRF; draft list/detail/lines, null quantity, logout and subsequent 403 passed against a temporary test-database API. |
| Local health | Live and ready both returned `{"status":"ok"}`. |
| Git whitespace | Passed. |

The live check populated only `test_orderdesk` using the maintenance role;
HTTP ran as the restricted runtime role. Its synthetic user, membership,
workspace, draft and line were removed in a cleanup block, and its temporary
API and disposable script were removed afterward. No main-database business
fixture, schema change, dependency change, or draft write endpoint was needed.
The first smoke-check attempt mishandled logout's empty 204 body; the helper
was corrected and the complete check then passed.

Repeat the native gates from PowerShell in `order-desk`:

```powershell
docker compose run --rm manage python manage.py test apps.orders.tests.test_read_contracts apps.orders.tests.test_read_api --settings=config.settings.test --keepdb --noinput
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput
docker compose run --rm rlscheck python manage.py verify_order_rls
docker compose run --rm manage ruff check .
docker compose run --rm manage ruff format --check .
docker compose run --rm manage python manage.py check
docker compose run --rm manage python manage.py makemigrations --check --dry-run
docker compose run --rm manage python manage.py migrate --check
docker compose exec -T api python manage.py check_runtime_role
docker compose exec -T api python manage.py verify_order_rls
# Previous command must refuse main database with exit 1.
git diff --check
```

Run test database fixture suites sequentially. Changes remain uncommitted and
there is no configured Git remote. The next proposed increment is a separately
specified protected draft creation API, with its contract documented first.
