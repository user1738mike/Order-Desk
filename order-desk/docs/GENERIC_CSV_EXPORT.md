# generic-po-csv-v1

Machine-import CSV from an active, approved, source-linked converted purchase
order only. Conversion is not approval: use existing submit then approve actions.
Export does not approve, deliver or mark an order imported. Admins/reviewers may
preview/generate/download; active membership/account/workspace is rechecked for
each action. Viewers retain normal order reads but have no export permission.
No named ERP compatibility or arbitrary spreadsheet opening safety is claimed.

## Profile and immutable source

UTF-8 without BOM; comma delimiter; RFC-style doubled double quotes and minimal
quoting; CRLF records, final CRLF; one row per line in line-number/UUID order.
Optional text is an empty cell; required text cannot be blank. Quantities are
positive exact ASCII decimals, 14 integer/4 fractional digits, emitted with four
fractional digits without rounding. Date is the immutable order-created UTC date,
YYYY-MM-DD. No volatile generation time is included. Maximum 500 lines, 4096
codepoints per description, 2 MiB file. Preview is 50 rows/page with descriptions
truncated to 256 codepoints and explicit flags. No line is silently skipped.

| Ordered column | Immutable source / validation |
| --- | --- |
| profile | literal generic-po-csv-v1 |
| order_id | purchase-order UUID |
| source_draft_id | frozen source UUID, required |
| order_number | stored purchase_order_number, nonblank, max64 |
| order_date | order.created_at UTC date |
| customer_name | stored customer_name, nonblank, max255 |
| line_number | positive unique integer |
| sku | copied line.sku, nonblank, max128; exact case/zeros/punctuation |
| description | copied line.description, optional, max4096; multiline permitted |
| quantity | copied quantity, positive, 14/4 exact decimal |
| unit | copied unit, optional, max32; never inferred |

Prices, currency, tax, accounts and pack data are not modeled and are omitted.
Live catalogue/draft data never replaces copied values. Existing conversion
guards freeze headers/lines; this increment additionally freezes the approval
decision metadata of an approved converted order. Active-state changes still
affect new export/download eligibility. Corrections need a separate revision.

Text is never apostrophe-prefixed or otherwise rewritten. The conservative v1
profile rejects control/format/surrogate characters (except CR/LF inside a
description), and formula-triggering =,+,-,@ after leading Unicode whitespace
and quote characters on any logical text line. Legitimate values outside this
profile are unsupported, not corrupted. Numeric quantity follows its own positive
decimal grammar. CSV quoting is not a formula defense. Preview uses escaped text
nodes; this increment adds no spreadsheet/XLSX representation.

Stable blockers include not_converted, not_approved, inactive_order, no_lines,
line_limit, required, text_limit, unsafe_formula, unsupported_control,
invalid_quantity and output_limit, each with path and optional line identity.
At most 100 blockers are returned, with total count. Invalid generation is 400
and produces no artifact or partial download.

## APIs, repeat safety and storage

Under /api/v1/workspaces/<workspace>/orders/<order>/:

- GET exports/?profile=generic-po-csv-v1&page=1: bounded validation preview,
  source revision and nullable scalar artifact status. No business write.
- POST exports/ with {"profile":"generic-po-csv-v1"}: authenticated JSON/CSRF,
  first success 201, completed replay 200, live/reclaimed work pending 202.
  Unknown/repeated parameters, unsupported versions and forged fields are 400.
- GET exports/<artifact>/download/: deliberate fresh authorized attachment;
  foreign/malformed identities 404, insufficient access 403, unfinished 409,
  missing/corrupt sealed bytes 503. No public keys or paths are exposed.

One durable record is unique by organization/order/immutable JSON snapshot hash/
profile. Hash is SHA-256 of PostgreSQL's canonical JSONB text. Snapshot and identity
are immutable; successful metadata is immutable. Forced RLS, minimal column grants,
composite order/tenant FK and invoker source/transition guards protect the record.
One synchronous bounded formatter runs outside DB locks. Short organization-first
transactions capture and claim, then reauthorize and validate token/source before
publication. A live two-minute lease returns 202; explicit repeat after expiry
reclaims with a new token, at most three attempts. Failed storage/publication work
requires deliberate Generate/retry; stale attempts cannot publish over newer work.
Unsupported profile versions require their own future contract/code/migration.

Server-generated exports/<random UUID hex> keys share the established contained
Linux private root, exclusive creation, OS file lease, sealed 0400 bytes, fsync,
recorded length/SHA-256 and verified streaming. Formatting is bounded before staging.
Metadata is not downloadable until success commits. Ordinary pre-commit failure
cleans its staging file; uncertain commit retains it for status reconciliation.
Process death leaves a durable lease and sealed/partial orphan, never a download.
The existing bounded 24-hour local orphan reconciler now recognizes successful
export references and active file leases as well as documents. It never replaces
missing successful bytes or changes historical payloads. Backup metadata and bytes.

Downloads authorize/materialize metadata, then verify/open and stream outside the
tenant transaction. Revocation blocks new requests; an already-authorized stream
may finish. Use attachment, text/csv; charset=utf-8, nosniff and private/no-store.
Creator/completion metadata records generation; no general audit or downstream
delivery event is fabricated. Timeout is unconfirmed: refresh status/repeat the
same server binding, never invent progress or automatically open a download.

Actual PostgreSQL/RLS/race/recovery/browser and resource results are recorded in
PROJECT_STATE.md. Synthetic example and independently authored expected bytes
are tested by round-trip CSV parsing. Production serving/operations remain open.
