# Step 4D.9: Draft readiness contract

Defined on 2026-10-08 and implemented as the conversion prerequisite. The existing
`/review/` endpoint continues returning observations without readiness policy.
Actual verification is recorded in PROJECT_STATE.md. Step 4D.10 adds a separate
conversion endpoint and converted source status.

## Policy

Use the conservative initial policy: every line requires an active same-workspace
catalogue match. Unconverted draft editing still permits incomplete and unmatched
lines. The initial policy question had no reply; this conservative rule is now
the explicit conversion prerequisite and can be changed only with its contract
and shared evaluator/tests.

A draft is ready to convert only when all these conditions hold:

- Customer name contains a non-whitespace character.
- At least one draft line exists.
- Every line has a positive quantity. Existing model constraints reject zero,
  negative and non-finite quantities; null remains allowed during drafting.
- Every line references an active catalogue item in the same workspace.
- Each attached line's stored catalogue SKU snapshot fits the purchase-order
  SKU field (maximum 128 characters). Conversion must use the stored snapshot,
  preserving the explicit attachment decision rather than silently refreshing it.

Customer reference and unit remain optional. Draft quantities (12 digits,
three decimal places) fit purchase-order quantities (18 digits, four decimals);
customer name and unit limits already agree. Catalogue/requested SKUs are text
fields, so the 128-character conversion boundary needs an explicit readiness
check. Draft reference must not be silently treated as a purchase-order number:
the latter is required, unique per workspace and limited to 64 characters.
Its allocation/retry policy belongs to the separate conversion contract.

Step 4D.10 adds `converted`; such sources return a first blocking reason
`draft_already_converted` with count 1. No submitted source state exists. The
converted source and its lines are frozen by that conversion contract.
Readiness does not imply ERP compatibility,
pricing, inventory availability or permission to perform a write.

## API and permission boundary

GET/HEAD `/api/v1/workspaces/<workspace>/draft-orders/<draft>/readiness/`.
All active admin/reviewer/viewer members may read. Require an active account,
workspace and membership refreshed at request and tenant entry; no superuser
bypass or cached-session authorization. Use the existing read-only tenant scope,
explicit header/line/catalogue tenant predicates and restricted PostgreSQL RLS.
Inactive/removed/never members and anonymous users return 403. Foreign/missing
drafts and malformed UUID paths return 404. Reject all query parameters with
400, and unsupported mutations with 405 under valid authentication/CSRF.
GET/HEAD requires no mutation CSRF token. Responses are never cached.

HTTP 200 has a bounded scalar/count shape, regardless of the number of lines:

```json
{
  "id": "<draft UUID>",
  "organization_id": "<workspace UUID>",
  "ready_to_convert": false,
  "line_count": 0,
  "blocking_reasons": [
    {"code": "customer_name_missing", "count": 1},
    {"code": "lines_missing", "count": 1}
  ]
}
```

Include only nonzero reasons in this fixed order:

| Code | Count |
| --- | --- |
| draft_already_converted | 1 when conversion has sealed this source. |
| customer_name_missing | 1 when the header name has no non-whitespace character. |
| lines_missing | 1 when no line exists. |
| quantity_missing | Number of lines with null quantity. |
| catalogue_unmatched | Number of lines with no catalogue reference. |
| catalogue_inactive | Number of attached lines whose same-workspace item is inactive. |
| catalogue_sku_too_long | Number of attached lines with SKU snapshots longer than 128 characters. |

Counts are per line, including repeated references. One line can contribute to
several different reasons. `ready_to_convert` is true exactly when the reasons
array is empty. No customer text, line arrays, requested text or catalogue
descriptions appear in this response. No writes, snapshot refresh, timestamp
changes, attachments, matching or status transitions occur.

Compute header flags and all counts in one aggregate SELECT so every decision
uses one PostgreSQL statement snapshot; materialize inside the read-only scope
with zero serializer queries. The result is an observation, not a reservation:
later edits or catalogue deactivation can change it immediately. Conversion
revalidates these same rules under its write locks; Step 4D.10 defines atomic,
repeat-safe source identity handling independently. A previous successful GET
must never authorize or bypass conversion validation.

## Verification

The focused module follows draft-review TransactionTestCase/fixture patterns;
credential-session checks extend the existing guarded runtime verifier. Cover empty,
complete and mixed drafts; overlapping reasons and repeated catalogue links;
optional reference/unit; quantity null and valid decimal values; catalogue
deactivation without snapshot mutation; SKU boundaries 128/129 and long catalogue
SKUs; edits immediately reflected. Assert exact bounded shape/order/counts,
one aggregate SELECT, zero serializer queries, unchanged rows/timestamps and
unchanged existing `/review/` behavior.

Exercise all roles, inactive account/workspace/membership, removal, never-member
superuser and revocation at tenant entry. Check foreign/missing/malformed IDs,
strict query/method handling, HEAD and cache headers. Restricted-role tests must
use real credentials in test_orderdesk, including synthetic aggregate queries
that omit application tenant filters to establish independent RLS protection.
Do not use SQLite, mocks or owner-role tests as runtime-isolation proof.

Run the focused readiness suite, full native suite and guarded order verifier
sequentially, plus the normal lint/format/model/migration gates. No schema/grant/
dependency change is expected. Atomic conversion races, durable retry identity
and partial-write rollback tests belong to its later separate increment.
