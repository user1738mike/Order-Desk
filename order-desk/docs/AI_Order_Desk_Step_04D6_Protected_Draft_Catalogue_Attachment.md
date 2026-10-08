# Step 4D.6: Protected manual draft-line catalogue attachment

## Contract

Add one JSON-only POST action to the existing scoped line-detail route:

`/api/v1/workspaces/<workspace-uuid>/draft-orders/<order-uuid>/lines/<line-uuid>/attach/`

Active workspace administrators and reviewers may attach one currently active
catalogue item to an unmatched requested line. Viewers and all other callers
are denied. Session authentication and CSRF apply. The endpoint never performs
automatic matching, catalogue edits, row deletion, position changes, or status
transitions.

The request body accepts only `catalogue_item_id` as a UUID. The selected item
must belong to the URL workspace and have `is_active=True` at the moment the
write transaction checks it. The line must belong to the same workspace and
parent order, and it must not already have a catalogue reference. The line's
requested SKU/description, quantity, unit, position, identity, organization,
order, parent, and creation timestamp remain unchanged. A successful attachment
advances only the line's `updated_at` timestamp.

On success, the line records the current catalogue item ID and snapshots the
current SKU and description. The response is HTTP 200 with the existing scalar
line read shape. The header's original intake text, customer fields, timestamps,
computed line count, and line position remain unchanged. An already attached line
returns stable 409 (including repeat requests for the same item), preserving its
original snapshots and timestamp. Missing, foreign or inactive references return
404; missing/malformed UUID or extra body fields return 400. Query parameters
return 400; non-JSON media returns 415. GET/HEAD/PUT/PATCH/DELETE return 405.

The write order is: enter an organization write tenant scope, lock the
organization, refresh writer membership, lock the scoped parent order, lock the
scoped line, verify the line is unmatched, then parse/validate input. Read and
resolve the supplied catalogue item under
the same organization and active state, validate the immutable attachment
state, save only the catalogue fields and `updated_at`, and materialize the
response inside the transaction. No schema, dependency, grant, RLS, or policy
change is required.

Catalogue updates also take the organization lock, so attachment sees either
the committed old or new active item and takes a consistent snapshot. A waiting
attachment observes committed deactivation or membership demotion. Concurrent
attachments commit one winner; the loser returns conflict without replacing the
winner's snapshots. Model validation errors become stable 400s after rollback;
unexpected exceptions propagate after rollback. Requests preserve null quantity
and original requested text. Later catalogue edits never refresh stored snapshots.

Read the item without a catalogue `SELECT FOR UPDATE`: the existing catalogue
UPDATE RLS policy is administrator-only, whereas attachment allows reviewers.
The shared organization lock serializes supported catalogue mutations; preserve
that policy and all grants. Direct maintenance writes must follow the same lock
discipline if performed concurrently with application requests.

## Verification

Run focused service/API tests first, then the full backend suite and order RLS
verifier. Keep all synthetic catalogue and draft rows in `test_orderdesk`; main
database checks remain read-only. The implementation is complete only after
focused tests, full regression, lint/format, model drift, migration state, run-time
role and whitespace gates all pass.

Focused regressions retain the existing attachment assertions and add scoped
lookup/authorization before malformed input, removed/nonmember denial, explicit
null quantity, line-only timestamp changes, unchanged header/count, historical
snapshot preservation, stable conflict, CSRF/query/method guards, model and
post-save rollback, and response materialization inside the transaction. Three
real PostgreSQL races cover competing attachments, committed deactivation and
committed demotion; waiting cases must observe the organization lock wait.
Guarded runtime-role HTTP checks cover both writer roles, missing/foreign/inactive
items, snapshot writes, repeat conflict, viewer and revoked membership denial.
The verifier cleans up catalogue fixtures only in its own generated workspaces.

Run from the repository root, with fixture suites sequential:

```powershell
docker compose run --rm manage python manage.py test apps.orders.tests.test_draft_line_attachment --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm rlscheck python manage.py verify_order_rls
docker compose run --rm manage python manage.py makemigrations --check --dry-run
docker compose run --rm manage python manage.py migrate --check
docker compose exec -T api python manage.py check_runtime_role
```

Use pinned host Ruff for backend lint/format, check both health probes and run
`git diff --check`. Logs remain ignored under `backend/var/draft_attachment_*.log`.

## Runtime boundary decision

The first real-role run caught a reviewer 404 caused by a catalogue
`select_for_update()` lookup applying the existing admin-only UPDATE policy.
Removed that item row write lock; attachment now reads through member SELECT
RLS while holding the organization lock used by catalogue mutation services.
The corrected real-role suite passed all 37 checks in 52.977s, including actual
reviewer attachment. No policy or grant was widened. The final native regression
run includes the deactivation/demotion lock races against this corrected service.

## Actual final results: 2026-10-08

15 focused tests passed in 4.740s; final full backend regression passed all 645
tests in 190.715s; corrected restricted-role verifier passed all 37 checks in
52.977s. No skips. Pinned Ruff lint/format (141 files), model drift, migration
state, restricted runtime role, both health probes and whitespace checks passed.
The final full suite includes the corrected attachment implementation.
No schema/dependency/grant/policy changes. All fixtures remained synthetic in
`test_orderdesk`; main checks were metadata/health only. Changes remain
uncommitted. Files changed: order services/serializers/views/routes, new
`test_draft_line_attachment.py`, guarded `runtime_rls.py` and state/contract docs.
