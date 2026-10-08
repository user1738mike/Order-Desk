# Manual draft editing contract

The browser uses existing protected draft APIs, same-origin sessions and fresh
CSRF tokens. Active administrators and reviewers can create manual drafts and
edit draft headers/lines; viewers can read. Only administrators can convert.
Every mutation revalidates membership, user and workspace inside tenant_scope.
Converted sources are immutable. No line deletion endpoint exists.

| Action | Endpoint suffix under `/api/v1/workspaces/<workspace>/draft-orders/` | Editable data |
| --- | --- | --- |
| Create | POST collection | customer_name, customer_reference, original_intake_text |
| Header | PATCH `<draft>/` | customer_name, customer_reference |
| Insert line | POST `<draft>/lines/` | position, requested_sku, requested_description, quantity, unit |
| Edit line | PATCH `<draft>/lines/<line>/` | requested_sku, requested_description, quantity, unit |
| Attach | POST `<draft>/lines/<line>/attach/` | catalogue_item_id |
| Detach | POST `<draft>/lines/<line>/detach/` | empty object |
| Revision | GET `<draft>/revision/` | id, organization_id, revision; quoted ETag |

Blank customer fields persist as empty strings; whitespace-only input is invalid.
Quantity stays a string throughout editing and transport: positive decimal with
up to nine integer digits and three fractional digits; blank means null. Original
intake is only writable at creation. Identity, source, status, timestamps and
catalogue snapshots are never browser-editable. Detachment retains requested text,
quantity and unit while clearing the catalogue link/snapshots.
Customer name/reference limits are 255/128 characters; creation-only intake is
limited to 10,000. Line position is an insertion-only integer from 1 to
2,147,483,647, unique within the draft. Requested SKU/description are strings with
at least one nonblank value; these draft text fields have no additional API length
limit. Unit is optional, up to 32 characters. Quantity range is 0.001 through
999999999.999. Strings retain case, punctuation and leading/trailing spaces.
Readiness requires a customer name, at least one line, positive quantities and
active catalogue matches with SKU snapshots fitting the 128-character order limit.

Invalid/unknown fields return structured 400 errors; parent/line lookup in a
different tenant returns 404. Role or current membership denial returns 403.
Converted drafts, occupied insertion positions and invalid attachment transitions
return documented 409 conflicts. No override fields or client-supplied tenant IDs
are accepted in mutation bodies.

Attachment searches the active workspace catalogue with fixed 50-row pages and
bounded search text; the server revalidates tenant ownership and active state.
There is no invented auto-match, pricing, tax, upload or extraction workflow.

## Conflict protection

The browser brackets initial detail/panel loading with aggregate revision reads.
Editing/conversion require a matching observed revision and use a quoted If-Match
header. A SHA-256 fingerprint covers the header and every ordered line, including
identities, values, links, snapshots and timestamps. Header updated_at alone is
insufficient because line writes do not update it. All cooperating writes acquire
the existing organization lock, then check the revision before saving. A stale
precondition returns 412 with `{"detail":"draft_revision_conflict"}` after rollback.
Read revisions are observations, not a new snapshot isolation guarantee.

No schema change is needed. Existing API clients may omit If-Match for backwards
compatibility; they do not gain stale-write protection. Their writes still change
the fingerprint and are detected by protected browser writes. Maintenance SQL
must follow the organization lock convention. Catalogue activity is separately
rechecked by attachment/conversion rather than included in this fingerprint.
Authorized conversion replay returns the original order even with the original
stale revision; malformed headers remain invalid.

Explicit saves invalidate cached readiness. Validation errors preserve input;
412/409 preserve it and block resubmission until deliberate comparison/reload.
Navigation asks before discarding dirty values; context/session replacement clears
private inputs. Pending saves suppress duplicate submissions. Ambiguous network
outcomes never automatically retry draft creation or line insertion: neither API
has an idempotency receipt. Operators must inspect server data before restarting.
Conversion has its own verified repeat-safe reconciliation action.

Verification results are recorded in PROJECT_STATE.md. Browser fixture credentials,
logs, profiles and screenshots remain under ignored backend/var and are cleaned or
kept private. No browser-storage persistence of draft inputs or credentials.
