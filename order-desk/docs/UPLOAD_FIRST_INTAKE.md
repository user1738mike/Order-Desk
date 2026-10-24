# Upload-first intake

Implementation contract; current test outcomes belong in PROJECT_STATE.md.

Open **Documents** to receive an incoming PDF or rectangular UTF-8 CSV up to
10 MiB, before creating an order. Search by original name or the linked draft's
customer name/reference; filter sources needing a draft or processing state.
Received time is the source upload time. Identical original bytes show a possible
duplicate warning without rejecting legitimate repeat orders or revisions.

Choose **Create or link draft**. Create an unresolved draft with optional customer
text/reference, or choose an existing editable draft from paginated headers.
This is a one-time association. Linking checks the current aggregate revision;
it cannot edit another customer's draft fields. Customer text remains unconfirmed
until the operator deliberately confirms the account and required delivery site
using the draft's customer card. See CUSTOMER_REFERENCE.md. Do not interpret
filename, text similarity or an email domain as confirmed customer identity.

Use **Review linked draft** for manual entry. Alternatively open CSV/PDF extraction,
queue its bounded local processor and refresh status. Once proposals succeed,
**Review linked draft** in the extraction panel opens the linked target directly.
Select source fields and mappings, inspect their provenance, correct and deliberately
apply. Applied receipts retain source digest, parser/result revision, decisions and
target draft. Saving a source link does not apply proposed values. Applying values
does not match products, convert, approve or generate an export.

Processors, reviewers and administrators can prepare sources/drafts and confirm
customer identities. Permanent reference changes remain administrative; conversion
and final approval retain the separate roles in PROCESSOR_PERMISSIONS.md.

Text-PDF support remains the existing narrow table parser. A scanned PDF, unknown
layout or invalid quantity has a visible failure and a manual draft-entry path.
Other file formats are rejected with a file error: retain them in the distributor's
existing secure manual process; do not rename them to bypass validation. Unknown
units and commercial rules are not validated by this increment. Prices, currency,
tax, availability, credit and delivery promises remain **not checked**.

Original downloads remain private authorized attachments; no public links or file
keys are exposed. Downloading does not establish destination delivery. Existing
order-owned documents are available through **All internal orders** and retain
their IDs, links, files, reviews and original metadata.

## Interrupted operations and support

An upload carries a request UUID shown beside the upload form. After an uncertain
response, **Check list** queries that exact receipt before permitting another
upload. If absent, the original selected file and UUID remain available for retry.
If present, the source is confirmed without creating another row. Reusing a key
for different bytes/name is a conflict. Browser state is held only in memory;
after a reload, inspect the inbox before a new upload. Identical-byte warnings
provide an additional check, not a universal duplicate-order detector.

An uncertain draft link retains its complete request in memory. Use **Reconcile
saved draft-link request** to replay it. The server returns the same link even
after later draft edits; changing the request/key conflicts. After a reload,
refresh the inbox to inspect the permanent source link before another action.
Do not create a replacement draft blindly. A source already linked to a draft
cannot be reparented; corrections continue in that draft while it is editable.

Queued/running/failed job states and bounded retries use the existing extraction
worker. An expired lease can be reclaimed by the authorized local processor;
old claims cannot publish a result. Do not reset jobs or edit database rows as a
routine recovery measure. For unavailable private bytes/storage, preserve the
source/request references and use the existing coordinated DB/file recovery
runbook in COORDINATED_RECOVERY.md. Restore only to a fresh isolated target.
Record safe operation/job IDs for support; they do not grant access. Never include
documents, cookies, passwords or private file paths in public issue reports.

## Data and authorization

Migration 0015 evolves OrderDocument without copying/replacing historical sources.
Historical order ownership remains nonnull. Incoming rows have null order, private
verified source bytes, a unique organization/request receipt and an optional draft.
A composite draft/organization FK prevents foreign-tenant linking. Database checks
enforce source category/link metadata; triggers protect original metadata and
one-time linkage. The existing table's FORCE RLS, grants and role policies remain.
Admin/reviewer can receive/link; active members can read; viewers cannot write.
Every protected service refreshes membership under the organization write lock.
New extraction review/application routes accept only the linked incoming draft.

No additional services or spending. No automatic OCR, customer communication,
ERP submission or public deployment. Customer directory, controlled unit rules,
comprehensive exception review, customer-specific handoff and measured customer
benefit remain separate required increments, tracked in WORKFLOW_IMPLEMENTATION.md.
