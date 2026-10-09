# Human review and repeat-safe CSV application

This increment applies explicit decisions from one completed `order-csv-v1` job
to one existing editable draft in the same workspace. Documents belong to
purchase orders; the target draft is selected separately. Nothing is selected,
matched, linked to catalogue items, converted or approved automatically.

## Contract

`GET /api/v1/workspaces/<workspace>/orders/<order>/documents/<document>/extraction/review/?draft_id=<draft>&page=1`
returns the current successful job, a digest of its immutable result, the target
draft and its aggregate revision, and 50 candidates per page. Candidate UUIDs
derive from job identity and the source record's physical start row. Each field
retains exact value, raw cell, start/end row, column name and column index.
Current draft lines use the existing paginated lines endpoint.

`POST` to the sibling `extraction/apply/` requires JSON:

```json
{
  "job_id": "<job UUID>",
  "draft_id": "<draft UUID>",
  "result_revision": "<64 hex characters>",
  "expected_draft_revision": "<64 hex characters>",
  "operation_key": "<UUID>",
  "mappings": [{
    "candidate_id": "<candidate UUID>",
    "action": "create",
    "position": 1,
    "fields": ["sku", "quantity"],
    "corrections": {"quantity": "1.234"}
  }]
}
```

There are at most 50 mappings per request. `update` requires an explicit existing
`line_id` instead of position. `reject` records the named fields without target
or corrections. Duplicate candidates/target lines, missing fields, unsupported
keys, empty selections and forged provenance are rejected. Corrections must be
bounded strings and apply only to selected fields. SKU maps to requested SKU,
description to requested description, quantity and unit to their draft fields.
The supported CSV profile has no customer-header proposals; header editing
continues through the existing manual editor. No header values are inferred.

Draft quantities retain the existing positive 9 integer / 3 fractional digit
limit. Wider CSV proposals require an explicit correction; they are never
rounded. All selected lines are validated before any draft write. Unselected
fields, manual lines and existing catalogue attachments remain intact.

## Authorization, consistency and replay

Active admins/reviewers may apply; active viewers may inspect. Every request and
replay revalidates user, membership and workspace. One outer tenant write scope
locks the organization before checking access, then the draft, source document
and job. Same-workspace source/target references are resolved before returning
a receipt. New application requires the successful current parser/source result,
an editable draft and the exact aggregate revision; stale revisions return 412,
locked/source conflicts 409, invalid decisions 400 and foreign resources 404.

An append-only application receipt is unique by workspace and operation UUID.
It binds the normalized request (sorted mappings/fields, exact corrections),
job/source/result identity, actor, timestamp, targets and immutable source
provenance to the committed response. Identical repeats return that original
response with 200, including its historical revision; the first commit returns
201. Reusing the key with another payload returns 409. A second key cannot
recreate the same source row in the same draft, even after subsequent manual
edits. Explicit updates to named existing lines remain separate reviewed edits.
Business changes, revision advancement, receipts and row links commit together.

Both new tables use forced PostgreSQL RLS and only SELECT/INSERT runtime grants,
active-member reads and admin/reviewer inserts. Composite foreign keys preserve
organization, job, draft and target-line identity. These records are narrowly
scoped application provenance, not a general audit history.

## Review and readiness

Accepted and rejected fields are recorded individually. Omitted fields remain
unreviewed; partial decisions never mark the entire result/document accepted.
Review completion is the union of explicit field decisions for this job/target.
Reject-only decisions do not change draft timestamps/revision. Failed extraction
has no usable partial proposals. Existing draft readiness still checks actual
customer/line/quantity/catalogue values; extraction review does not approve or
unlock conversion. Unreviewed proposals are not draft values and do not create
additional blockers. Newly created unmatched lines retain catalogue blockers.

The browser shows current values, raw provenance, selected fields/corrections
and an explicit preview. It retains unsaved decisions on validation/conflict,
and requires deliberate comparison/reload after conflict. An unconfirmed POST
freezes its operation key and exact payload for safe retry; another payload is
blocked until the outcome is confirmed. Successful or replayed applications
reload actual draft/review/readiness state, rather than displaying a historical
receipt as current state. Workspace changes discard late responses.

## Verification

Actual native PostgreSQL, restricted-role RLS, deterministic race, controller
and Chromium evidence is recorded in PROJECT_STATE.md after execution. Private
fixtures, source bytes, browser profiles and logs remain ignored. This increment
does not add PDF/OCR/AI extraction, aliases, fuzzy matching, pricing, unit
conversion, exports or bulk document-to-draft application.
