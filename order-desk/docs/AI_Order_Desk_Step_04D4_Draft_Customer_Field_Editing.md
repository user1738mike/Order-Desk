# Protected draft customer-field editing

The requested filename retains 04D4; this increment follows verified Step 4D.7
and does not replace the existing 4D.4 draft-line creation contract.

## Contract recorded before implementation

Add JSON PATCH to `/api/v1/workspaces/<workspace>/draft-orders/<draft>/`.
Current active admins/reviewers may edit customer_name (maximum 255 characters)
and customer_reference (maximum 128). Omitted fields remain unchanged; explicit
empty strings persist as empty strings. Preserve original text, including
surrounding whitespace when a nonblank character exists. Whitespace-only values,
including Unicode whitespace, return field-keyed 400 with
`Provide a nonblank value or an empty string.` Reuse creation validators.
Input values must be strings; null, booleans, numbers, arrays and objects are
invalid. Unknown/system fields and an empty object/body return 400 without saves.
Original intake, organization, initiating user, status, source type, identity and
timestamps cannot be supplied. Reject query parameters and non-JSON media.

Own the organization write tenant scope, refresh writer access after its lock,
lock the explicitly scoped draft, then parse and validate input. Apply a partial
update to fresh locked state, full_clean, save changed fields plus updated_at,
and materialize inside the transaction. Identical supplied values are no-ops
preserving updated_at; empty patches are invalid. Return 200 in the existing
detail read shape (including computed line_count and lines_url). Never create,
change or delete lines. Django validation errors keep field keys and map __all__
to non_field_errors only after rollback; unexpected failures propagate after
rollback. Both model validation and post-save failure paths are verified.

Viewers/inactive/removed/nonmembers (including superusers), inactive accounts
and workspaces return 403 without writes, including revocation after request
permission resolution. Missing/foreign draft IDs return 404 before parsing;
malformed URL UUIDs return 404. Session CSRF is required. Detail PUT/DELETE/POST
remain 405. Existing line collection POST remains 201 under Step 4D.4 and its
assertion is retained. POST to a line detail remains 405. The requested line
collection 405 check conflicts with its documented implemented creation feature;
no response to the clarification arrived before implementation, so preserve it.
No other methods/routes, schema, dependencies, grants or RLS policy changes.

DraftOrder only defines status draft, enforced by draftorder_status_draft.
Submitted/converted statuses do not exist; do not invent fixtures or skip tests
to simulate a nonexistent status transition.

## Verification

Copy creation API setUp, session/CSRF helpers and TransactionTestCase conventions,
then add synthetic existing draft/line fixtures. Use subTest for variants. First
run the new focused module against unchanged production and record 405 failures.
Then add the minimum serializer/service/detail PATCH implementation and update
only the obsolete detail PATCH read-method expectation, preserving other checks.
Independent connections test simultaneous complete edits and disjoint partial
edits, with final valid state and no lost updates. Extend guarded runtime checks
for real admin/reviewer credentials and rollback/current authorization.
Run focused tests, full backend suite, verify_order_rls and existing gates.
Keep fixtures in test_orderdesk; main checks remain metadata/health only.

The corrected tests-first run used unchanged production: 14 tests in 5.509s,
58 failed assertions, zero errors, all due to unsupported PATCH returning 405.
After implementation the focused module passed 14 tests in 6.141s. Save/full_clean
variants include field, __all__ and unkeyed validation; save errors are injected
after the real database update to prove rollback rather than only preventing it.
Concurrent HTTP requests verify whole-field pairs and disjoint partial updates.
The old read-method test now supplies a valid customer PATCH and asserts 200 and
saved values while retaining existing counts and all other method expectations.

```powershell
docker compose run --rm manage python manage.py test apps.orders.tests.test_draft_customer_field_editing --settings=config.settings.test --keepdb --noinput
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput
docker compose run --rm rlscheck python manage.py verify_order_rls
```

Ignored logs are in `backend/var/draft_customer_editing_{red,focused,regression,runtime}.log`.
Creation keeps its existing DRF scalar coercion behavior; editing explicitly
requires strings. Historical creation error precedence for active viewers with
invalid creation input remains unchanged. Both are outside this focused change.

## Actual final results: 2026-10-08

| Gate | Actual output |
| --- | --- |
| Tests-first, unchanged production | Ran 14 tests in 5.509s; FAILED (failures=58), zero errors; expected PATCH 405. |
| Requested focused module | Ran 14 tests in 6.141s; OK. |
| Full backend suite | Ran 670 tests in 148.924s; OK. |
| Restricted-role order/RLS verifier | Ran 39 tests in 50.864s; OK; Runtime order RLS verification passed. |
| Ruff lint/format | Passed; 143 backend files formatted. |
| Model/migration/runtime-role/health/whitespace | Passed; no schema or grant changes. |

No skips. Tests cover all applicable requested variants, plus no-op timestamps,
transport/query rejection and post-save materialization rollback. DraftOrder
has only draft status; status-lock testing is inapplicable. The existing line
collection POST 201 assertion is retained, and POST 405 is verified on both draft
and line detail routes. No response arrived to the collection method clarification.
All business fixtures stayed synthetic in test_orderdesk; main checks remained
metadata/health only. Customer editing stays framework-independent in services.

Files changed for this increment: new `test_draft_customer_field_editing.py`,
order serializers/services/views, the obsolete detail PATCH branch of
`test_read_api.py`, a related customer-editing check in guarded `runtime_rls.py`,
this contract and project/master state. Prior local detachment changes are
preserved. Creation scalar coercion/error precedence remain the documented
unchanged behaviors; no additional risks were found in the edited endpoint.
