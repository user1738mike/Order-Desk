# Step 4D.4: Protected requested draft-line creation

## Contract

Add JSON-only POST to the existing workspace draft lines route:
`/api/v1/workspaces/<workspace-uuid>/draft-orders/<order-uuid>/lines/`.
Active administrators and reviewers may create one requested line; viewers
retain read access. Session authentication and CSRF apply. Workspace access
is refreshed before entering an organization-first protected write scope,
then the scoped parent is locked before input parsing or insertion. Missing
or foreign parents return 404 after workspace/writer authorization.

Accepted fields:

| Field | Contract |
| --- | --- |
| `position` | Required positive integer, maximum PostgreSQL integer 2147483647; unique within the parent draft. |
| `requested_sku` | Optional text, empty by default; preserved without trimming. |
| `requested_description` | Optional text, empty by default; preserved without trimming. |
| `quantity` | Optional finite positive Decimal(12,3), maximum 999999999.999; omitted or null remains unresolved/null. |
| `unit` | Optional text up to 32 characters, empty by default; preserved without trimming. |

At least one requested SKU/description must contain a non-whitespace character.
Unknown/system fields are rejected, including tenant, parent, identity,
catalogue reference/snapshots, timestamps and status. No automatic catalogue
matching, catalogue attachment, line editing, deletion or workflow transition
is part of this increment. No new schema, grant, dependency or policy is needed.

HTTP 201 returns the existing scalar line read serializer shape; quantities
are decimal strings/null, catalogue reference is null and snapshots are empty.
The header's original intake text and timestamps are unchanged; its existing
computed line count reflects the insertion. Existing paginated line GET/HEAD
and header list/detail behavior are preserved. PUT/PATCH/DELETE are unavailable.

Input/query errors return stable field-keyed 400s; repeated/unknown query
parameters are all rejected for POST. Duplicate positions return 409 with
`{"detail":"This draft already has a line at this position."}`. Model
validation errors map to field lists/`non_field_errors` only after rollback.
Only the named native position uniqueness violation is translated to 409;
unexpected database errors propagate after rollback. Every successful response
is materialized before leaving the write scope. No lazy relations escape.

## Implementation and verification plan

Keep transport validation in serializers/views and the write service independent
of DRF. A server-supplied input callback delays parsing/validation until after
fresh writer authorization and the scoped parent lock. The service also
allowlists input fields for direct callers, validates the model and uses the
existing database tenant constraints. Organization-first locking serializes
cooperating requests; a duplicate-position check under that lock returns the
same conflict as the final database uniqueness guard.

Verify field/decimal/null/error contracts, membership revocation/removal,
foreign/missing parents, authorization before parsing, CSRF, unchanged reads,
rollback, and two real service calls racing for the same position. Extend the
guarded runtime-role verifier for forced-RLS HTTP creation/conflict/revocation.
Run focused native tests, full backend regression, lint/format/model drift,
and the order RLS verifier sequentially. Synthetic rows remain only in
`test_orderdesk`; main database checks remain read-only.

## Implementation and actual results

- `serializers.py`: strict creation input, positive finite quantity and position,
  required requested identification; existing read response is reused.
- `services.py`: DRF-independent input callback, fresh writer check,
  organization/parent lock order, direct-caller field allowlist, model validation,
  protected position precheck and named native uniqueness translation.
- `views.py`: protected POST on the existing lines view, JSON/query guards,
  shared model-error translation and draft CSRF authentication on HttpRequest.
  Shared draft dispatch preserves never-cache headers. No route changes needed.
- `test_draft_line_creation.py`: 15 new native service/API tests for fields,
  unresolved/matched-state protection, unchanged headers/reads, permissions,
  authorization before parsing, CSRF/media, conflicts, rollback and concurrent
  service calls. A forced native collision verifies the final DB guard.
- `test_concurrency.py`: existing duplicate and both demotion tests now use
  the real service and retain assertions and observed PostgreSQL lock waits.
- `test_read_api.py`: verifies the newly allowed line POST while retaining
  detail read-only and unsupported-method checks.
- `runtime_rls.py`: credential-authenticated restricted-role line creation,
  duplicate conflict, foreign parent denial, viewer denial and revocation.

| Gate on 2026-10-07 | Actual result |
| --- | --- |
| Focused draft creation/read suites | 38 passed in 11.374s before the additional native collision regression. |
| Final line/service/concurrency suite | 18 passed in 4.818s, including the native collision and both demotion orders. |
| Full backend PostgreSQL suite | 616 passed in 126.157s; no skips. |
| Direct restricted-role order/RLS verifier | 35 passed in 29.916s; no skips; forced RLS, grants and composite keys audited. |
| Ruff lint and format | Passed; 139 backend files formatted. |
| Model drift and applied migration state | Passed; no changes or pending migrations. |
| Runtime role, live/ready probes, Git whitespace | Passed. |

One transport check initially returned 400 for multipart input after Django
CSRF had consumed the form. An explicit media guard now returns 415 after
authorization and parent lookup, with a passing regression. Unexpected native
database errors remain errors after rollback rather than being mislabeled as
position conflicts. Existing header-creation error precedence remains as
documented in Step 4D.3; this line API denies viewers before parsing input.

Run from the repository in PowerShell; fixture suites must remain sequential:

```powershell
docker compose run --rm manage python manage.py test apps.orders.tests.test_draft_line_creation apps.orders.tests.test_concurrency --settings=config.settings.test --keepdb --noinput
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput
docker compose run --rm rlscheck python manage.py verify_order_rls
docker compose run --rm manage ruff check .
docker compose run --rm manage ruff format --check .
docker compose run --rm manage python manage.py makemigrations --check --dry-run
docker compose run --rm manage python manage.py migrate --check
docker compose exec -T api python manage.py check_runtime_role
git diff --check
```

All synthetic writes were confined to `test_orderdesk`, and guarded runtime
fixtures were cleaned up by the verifier. Main-database checks read only
metadata or health endpoints. Changes remain uncommitted. The next proposed
increment is protected editing of requested draft-line fields, with its update
contract documented before code; attachment/matching require separate work.
