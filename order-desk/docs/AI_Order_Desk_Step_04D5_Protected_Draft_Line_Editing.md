# Step 4D.5: Protected requested draft-line editing

## Contract

Add GET/HEAD and JSON-only PATCH at:
`/api/v1/workspaces/<workspace-uuid>/draft-orders/<order-uuid>/lines/<line-uuid>/`.
Active workspace members may read. Only active administrators/reviewers may
patch. Session authentication, CSRF on PATCH, never-cache responses and fresh
workspace authorization retain the existing draft conventions.

PATCH accepts only `requested_sku`, `requested_description`, `quantity` and
`unit`, with the same field/decimal rules as line creation. Omitted fields
preserve current locked values; explicit empty text clears that field; explicit
null quantity resets it to unresolved. Validate the merged model state, so
clearing the only requested identifier on an unmatched line returns 400.
Catalogue-linked lines retain their reference and stored snapshots; edits do
not attach, detach, refresh or perform matching. All identity, tenant, parent,
position, catalogue and timestamp fields are immutable through this endpoint.

Each successful PATCH returns HTTP 200 in the existing scalar line read shape.
An empty patch or identical normalized values is a successful no-op preserving
`updated_at`; real changes update only supplied changed fields and `updated_at`.
The header's intake, customer fields, timestamps and computed line count remain
unchanged. GET/HEAD have no query parameters; PATCH rejects all query parameters.
PUT/POST/DELETE are unavailable on this detail route. Existing list/create and
header/detail routes keep their behavior. No schema/dependency/grant/policy
changes, deletion, position reordering or catalogue matching are included.

Write order: own `tenant_scope(write=True)`, lock the organization, refresh
writer authorization, lock the explicitly scoped parent, then lock the line
filtered by organization and parent. Only then parse/validate input, apply the
partial changes, validate the merged model, save changed fields and materialize
the response. Missing/foreign parents or lines return 404 after authorization;
viewers and inactive/nonmember requests are denied before parsing. Convert
Django validation errors to field lists/`non_field_errors` only after rollback.
Unexpected database errors propagate after complete rollback.

## Verification plan

Native tests cover partial updates, clearing/null/decimal behavior, merged-state
validation, immutable fields, real/no-op timestamps, CSRF/media/query guards,
foreign/missing/revoked access, existing snapshots and rollback. Use independent
connections to prove disjoint concurrent updates preserve both fields and a
waiting writer observes committed demotion; retain the established opposite
lock-order test. Extend guarded runtime-role HTTP checks for immutable grants,
update/no-op/read and revocation. Run focused tests, full backend regression,
RLS verifier, lint/format/model/migration gates. All synthetic rows stay in
`test_orderdesk`; main checks stay read-only. Record actual results afterward.

## Local verification commands

From the repository root:

```powershell
docker compose run --rm manage python manage.py test apps.orders.tests.test_draft_line_editing apps.orders.tests.test_concurrency --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm rlscheck python manage.py verify_order_rls
docker compose run --rm manage python manage.py makemigrations --check --dry-run
docker compose run --rm manage python manage.py migrate --check
docker compose exec -T api python manage.py check_runtime_role
```

The guarded RLS command authenticates as the restricted application role and
uses its audited maintenance alias only for synthetic test fixtures and cleanup.
Run fixture suites sequentially. Use the pinned host Ruff for backend lint and
format checks, and check both public health probes and `git diff --check`.

## Actual local results: 2026-10-07

- Focused editing/concurrency: 17 tests passed in 5.373s.
- Full backend, including orders/organizations/catalogue: 630 tests passed in
  143.096s.
- Restricted-role order/RLS verifier: 36 tests passed in 33.103s.
- No skips; pinned Ruff lint/format (140 files), model drift, migration state,
  runtime-role audit, both health probes and whitespace checks passed.

Regressions verify partial updates and numeric no-ops, merged identifier
validation, explicit null quantity, historical snapshots on inactive catalogue
items, immutable input rejection, current/removed/nonmember authorization,
scoped parent/line lookup before malformed parsing, CSRF/media/method/query
guards, model-error translation and post-save rollback. Independent connections
prove disjoint field edits retain both committed changes and a waiting editor
observes committed demotion, including an observed organization lock wait.
The established creation/opposite lock-order regressions remain intact.
Real credential sessions verify PATCH/read/revocation under `orderdesk_app`.
No migration, grant or RLS policy change was needed. Synthetic fixtures stayed
in `test_orderdesk`; main database actions were read-only metadata/health checks.

Files changed: order selectors, serializers, services, views and routes; new
`test_draft_line_editing.py`; existing concurrency and guarded runtime-RLS tests;
this contract, `PROJECT_STATE.md` and `MASTER_BUILD_PROMPT.md`. Logs are ignored
under `backend/var/draft_line_editing_{focused,regression,runtime}.log`.
Catalogue attachment and automatic matching remain subsequent work.
