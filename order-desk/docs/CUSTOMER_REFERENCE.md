# Customer reference and deliberate identity confirmation

Customer accounts and delivery locations belong to one workspace. A stable code
and optional destination ID are strings: leading zeros, case and punctuation are
preserved. Display names may repeat. A matching name or email domain never
establishes identity. Destination IDs are operator supplied reference values;
their presence does not prove compatibility with any external system.

Administrators create and maintain accounts/locations and separately approve exact
customer aliases with an approval source/reason. Alias corrections are not learned
from an order. Retiring an approval requires a reason and preserves its original
actor/time/value; an explicit later approval creates a new record. Active alias
collisions with another account's code or approval are rejected. Codes and parent
relationships cannot be edited. Inactivation preserves historical decisions.

The Customers screen supports directory search, account editing, creating and
activating/deactivating delivery locations, alias approval/retirement and CSV
validation/import. Account/location name and destination edits are available via
the versioned API; the location screen currently exposes creation and activation
changes. Reference administration is reserved to administrators. All active members
may read their own workspace's directory and recorded decisions. Reviewer/admin
roles can deliberately confirm an editable draft's customer; conversion retains
the existing administrator-only policy. Processor permissions remain pending.

Select an account from the draft's customer card, select a delivery location when
required, preview current reference values, then confirm. Multiple locations never
select a default implicitly. Confirmation applies the selected canonical customer
name and retains the original requested name/reference in an immutable decision.
Changing the header retires the decision. Material reference edits, inactive
accounts/sites or newly required locations block renewed conversion until a fresh
confirmation. Conversion copies the decision into an immutable order snapshot;
later reference changes do not rewrite it. Decision history is available through
the paginated confirmation/history API.

Incoming-source drafts require a confirmed customer before conversion. Historical
manual drafts retain their previous structural readiness; this exception never
establishes confirmed identity, customer-specific readiness or destination
acceptance. An order without a recorded snapshot says so explicitly.

Reference writes accept UUID Idempotency-Key headers and return durable operation
receipts. Updates also require the exact quoted If-Match revision observed on the
record. Missing/stale versions return428/412. A lost response remains unconfirmed:
look up the exact operation receipt or repeat the same key/payload/version. Do not
create a new operation to guess whether the original committed. The browser keeps
retry payloads in memory and clears private state at session/workspace changes.
Customer confirmations use their body operation_key and replay the exact original
request even if later changes mean that decision is no longer current. Current
status is fetched separately from successful replay evidence.

CSV imports require a nonempty UTF-8 CSV up to1MiB/1,000 records, with exactly:

```csv
code,display_name,destination_id,requires_location,is_active
00042,Synthetic account,000007,true,true
```

Use literal true/false. Validation creates nothing and returns record/field errors.
Execution is atomic and create-only: duplicates, existing codes and active alias
collisions reject the entire file. Imports never overwrite accounts or approve
aliases. The operation receipt binds the original file digest. Replaying a
committed import reports zero newly created records and the original created
count. A downloaded CSV, successful import here or recorded destination ID proves
no external handoff. Prices, stock, currency, tax, credit, delivery promises and
destination acceptance remain explicitly not checked.
