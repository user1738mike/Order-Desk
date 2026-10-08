# Step 4D.8: Read-only draft review summary

## Contract recorded before code

Add GET/HEAD `/api/v1/workspaces/<workspace>/draft-orders/<draft>/review/`.
All current active members (admin/reviewer/viewer) may read. Use existing session
authentication, fresh workspace authorization, a read-only tenant transaction
and never-cache responses. Reject every query parameter (400). Unsupported write
methods return 405 with valid CSRF; missing/foreign draft IDs return 404 and
inactive/removed/nonmembers, inactive users/workspaces and anonymous requests
return 403. Malformed URL UUIDs return 404.

HTTP 200 returns only these scalar fields:

- id and organization_id identify the scoped draft.
- customer_name_empty and customer_reference_empty observe empty customer fields.
- line_count counts all lines belonging to the parent and workspace.
- unmatched_line_count counts lines with no catalogue reference.
- missing_quantity_line_count counts null quantities.
- unresolved_line_count counts the union of unmatched and missing-quantity lines,
  once per line even when both apply.
- inactive_catalogue_line_count counts attached lines whose same-workspace item
  is currently inactive; stored snapshots remain untouched.

These observations are not submission/readiness policy: customer reference and
unit remain optional, inactive links retain valid historical snapshots, and
there is no ready_to_submit flag or status transition. Return zero counts for
empty drafts. No line arrays, request text, catalogue descriptions or new PII.
Counts are per line, not per distinct item. Compute header flags and all counts
from one aggregate SELECT so each response uses one PostgreSQL statement snapshot.
Explicitly filter header, line and catalogue organization boundaries as well as
RLS. Materialize scalar output inside the tenant scope, with no lazy queries from
serialization. The response remains bounded regardless of line count.

No matching, attachment/detachment, header/line/catalogue writes, timestamps,
creation/edit routes, schema, dependencies, grants or RLS changes. Preserve all
previous verified behavior and uncommitted local work.

## Verification

Native PostgreSQL tests cover empty/mixed/complete drafts, overlapping counts,
repeated catalogue references, catalogue deactivation, edits reflected without
snapshot refresh, all roles/current access, tenant/UUID isolation, strict queries,
methods/HEAD/cache and unchanged business rows. Assert the selector uses one
SELECT and scalar serialization zero queries inside a read-only tenant scope.
Guarded runtime tests use real credential sessions as orderdesk_app and prove
RLS still scopes aggregates when application header/line filters are omitted in
a synthetic test query, plus revocation denial.
Run focused tests, full backend suite and verify_order_rls sequentially; run
normal lint/format/model/migration/runtime-role/health/whitespace gates. Keep all
synthetic rows in test_orderdesk; main checks remain metadata/health only.

Run fixture suites sequentially from the repository root:

```powershell
docker compose run --rm manage python manage.py test apps.orders.tests.test_draft_review_api --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm rlscheck python manage.py verify_order_rls
docker compose run --rm manage python manage.py makemigrations --check --dry-run
docker compose run --rm manage python manage.py migrate --check
docker compose exec -T api python manage.py check_runtime_role
```

Use pinned host Ruff lint/format, both health probes and `git diff --check`.
Ignored local logs: `backend/var/draft_review_{focused,regression,runtime}.log`.

## Actual results: 2026-10-08

- Focused review API: 9 tests passed in 3.358s.
- Full backend regression: 679 tests passed in 146.419s.
- Restricted-role order/RLS verifier: 40 tests passed in 50.375s.
- No skips. Ruff lint/format (144 files), model drift, migration state, runtime
  role, both health probes and whitespace checks passed.

Native tests assert overlap/repeated-item counts, empty customer flags, current
edits/deactivation without snapshot refresh, unchanged business rows, all roles,
current/revoked/removed/operator/inactive access, foreign/missing/malformed UUIDs,
strict queries/methods/HEAD/cache and one SELECT/zero serializer queries inside
a read-only scope. Real-role credential tests verify all member roles, inactive
links, overlapping unresolved counts and foreign isolation both with normal
filters and a synthetic aggregate that deliberately omits application tenant
predicates. Revocation denies access. No grants or policies were widened.

Files changed: order selectors/serializers/views/routes, new
`test_draft_review_api.py`, related guarded `runtime_rls.py` and this/project/
master documentation. No schema or dependency changes; prior local work stays
intact. All fixtures remained synthetic in test_orderdesk and main checks stayed
metadata/health only. Review changes remain uncommitted. A summary is an
observation at its statement snapshot; later edits require a fresh GET. No
conversion/submission decision should be inferred from these counts.
