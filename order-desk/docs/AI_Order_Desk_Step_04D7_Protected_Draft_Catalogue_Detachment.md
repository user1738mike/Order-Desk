# Step 4D.7: Protected manual draft-line catalogue detachment

## Contract recorded before code

Add JSON-only POST `.../draft-orders/<order>/lines/<line>/detach/`. Accept only
an empty object `{}`; reject unknown/system/catalogue/requested input fields.
Current administrators/reviewers may detach; session authentication, CSRF and
never-cache apply. No query parameters. GET/HEAD/PUT/PATCH/DELETE return 405.
Active viewers and inactive/removed/nonmembers return 403 before parsing.
Scoped parent/line lookup occurs before parsing; missing/foreign rows return 404.
Malformed/nonobject/extra-field input returns 400; non-JSON media returns 415.

Own the write tenant transaction: lock organization, refresh authorization,
lock scoped parent and line, parse/validate, then clear catalogue reference and
both stored snapshots and validate merged model state. The line must retain a
nonblank requested SKU or description. A catalogue-only line returns stable
model-validation 400 with no writes; callers may first edit requested fields.
Services remain independent of DRF; validation translation happens after rollback.
Unexpected failures propagate after rollback, including post-save failures.

Return HTTP 200 with the existing scalar line shape. Preserve every requested
field, unresolved/null quantity, position, identity, parent/tenant, created_at
and all header fields/timestamps/count. Change only catalogue fields and line
updated_at. An already unmatched valid line is a 200 no-op without a save or
timestamp change. No catalogue row is read or modified. Attachment remains an
explicit separate action; no automatic matching, deletion, reordering, schema,
dependency, grants or RLS changes.

## Verification plan

Native tests: roles, snapshots cleared together, header/request preservation,
real/no-op timestamps, catalogue-only identity denial, repair then detach,
unknown fields, tenant/parent lookup, CSRF/media/query/methods, revocation,
materialization and rollback. Independent connections: concurrent detachment
and clearing requested identity permit exactly one change; merged state stays
valid. A waiting detachment must observe committed demotion with an observed
organization lock wait. Guarded runtime-role HTTP tests verify reviewer/admin
update grants, no-op, invalid identity, viewer/revocation and catalogue untouched.
Run focused tests, full backend regression, restricted-role verifier and normal
lint/format/model/migration/runtime-role/health/whitespace gates. Synthetic
fixtures stay in `test_orderdesk`; main database checks remain read-only.

Run fixture suites sequentially from the repository root:

```powershell
docker compose run --rm manage python manage.py test apps.orders.tests.test_draft_line_detachment --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm rlscheck python manage.py verify_order_rls
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm manage python manage.py makemigrations --check --dry-run
docker compose run --rm manage python manage.py migrate --check
docker compose exec -T api python manage.py check_runtime_role
```

Use the pinned host Ruff and both health probes. Ignore local logs in
`backend/var/draft_detachment_{focused,runtime,regression}.log`.

## Actual results: 2026-10-08

- Focused detachment: 11 tests passed in 6.501s.
- Restricted-role order/RLS verifier: 38 tests passed in 52.824s.
- Full backend regression, including orders/organizations/catalogue: 656 tests
  passed in 148.967s.
- No skips; Ruff lint/format (142 files), model drift, migration state, runtime
  role, both health probes and whitespace checks passed.

Independent connections verify the identity-clear/detachment race commits exactly
one change with valid resulting state and that a waiting detachment observes
committed demotion, including a real organization lock wait. Runtime HTTP checks
use credential sessions as orderdesk_app for both writer roles, identity denial,
no-op, viewer/revocation denial and untouched catalogue/header state. Existing
attachment/editing/read/creation and concurrency regressions remain intact.
No schema, dependency, grant or RLS change. All fixtures were synthetic in
test_orderdesk; main checks remained metadata/health only.

Changed order services, serializers, views/routes, new
`test_draft_line_detachment.py`, guarded `runtime_rls.py`, this contract and
project/master state. Detachment changes are locally verified and uncommitted.
Next proposed increment: protected draft customer-field editing with original
intake/system fields preserved; automatic matching and finalization stay separate.
