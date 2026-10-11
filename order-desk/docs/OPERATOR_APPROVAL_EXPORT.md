# Operator approval and generic CSV export

The conversion result links to **Review approval and CSV export**. The workspace
**Approval & export** tab also accepts a purchase-order UUID. These routes identify
purchase orders, not source drafts. Viewers can inspect current order detail;
active administrators/reviewers can use the existing protected review/export APIs.
All permissions remain server-enforced. This increment changes no schema or backend
business rules, profiles, tenant policies or approval authority.

The screen shows current order identity/customer/state and copied line values,
keeping exact quantities and SKUs as strings. It supports at most 500 lines, the
existing generic CSV profile limit. Submit and approve are separate buttons with
deliberate confirmation against displayed order/customer identity. Cancelled
confirmation sends no mutation. Approval is not export or external delivery.
Operators must resolve unit/pack/pricing exceptions outside unsupported automation.

Administrators/reviewers see generic-po-csv-v1 eligibility and bounded blockers,
50-row preview pages, explicit truncation markers, and durable artifact state,
attempt count, lease expiry and safe error code. Running live leases and exhausted
failures disable generation; expired claims can be deliberately reclaimed within
the existing three-attempt bound. Successful generation can explicitly retrieve
the same server-bound artifact. Profile rules are in GENERIC_CSV_EXPORT.md.

Each unsafe request refreshes CSRF and checks its context again before POST.
Pending actions suppress duplicate clicks. An ambiguous transport/5xx/malformed
success outcome blocks further writes and downloads until a successful current
status check. Status checks never automatically retry writes. If status still
permits an action, the operator must deliberately choose it again. Existing
server locking, state guards, immutable snapshots and unique export bindings
provide authoritative concurrency/repeat safety; UI gating supplies no authority.

Downloads are separately deliberate, use same-origin authenticated no-store fetch,
and validate size and SHA-256 against the current successful artifact before
creating a short-lived Blob URL. Links are constructed/validated against exact
workspace/order/artifact identities. URLs are revoked; private order/export state
is not persisted in browser storage. No named ERP compatibility, arbitrary
spreadsheet-opening safety or downstream submission is claimed.

Session/workspace/order/role changes abort outstanding requests and clear state.
Late detail/preview/mutation/download/digest responses cannot repopulate another
context. Denial refreshes workspace access and clears export controls. The module
`frontend/assets/desk/purchase.js` owns response validation, state and rendering;
`main.js` owns routing, confirmation and deliberate Blob download. The template
provides semantic forms/tables and live messages; existing CSS handles scrolling.

Focused state/failure tests are in frontend/tests/purchase.test.js. Actual native,
restricted HTTPS browser, loss/reconciliation and byte-download evidence is recorded
in PROJECT_STATE.md, separately from earlier backend/RLS evidence.
