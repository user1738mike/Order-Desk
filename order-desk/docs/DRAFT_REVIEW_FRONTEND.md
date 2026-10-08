# Draft list, review, readiness and internal conversion UI

This increment implements the user's draft-screen request. The attached prompt
is reference material; its additional commit/push workflow is not authorization
to publish this preexisting uncommitted working tree. Existing native-module UI,
session/CSRF client and Chromium harness are extended rather than replaced.

| Screen/action | API under `/api/v1/workspaces/<workspace>/` | Contract |
| --- | --- | --- |
| Draft list | GET `draft-orders/?page=<n>` | All active member roles; 50 rows, newest-created first; only page supported. Customer/reference, manual source, status, line count and timestamps. |
| Header | GET `draft-orders/<draft>/` | Active members; explicit tenant/UUID, 404 for foreign/missing drafts; customer fields, intake text, manual source, initiating-user ID, timestamps; no embedded lines. |
| Lines | GET `draft-orders/<draft>/lines/?page=<n>` | 50 rows ordered by position/id. Requested text, exact decimal quantity strings/null, unit, catalogue ID and stored snapshots. No prices, currency or document provenance. |
| Review observations | GET `draft-orders/<draft>/review/` | Header-empty flags and bounded unresolved/unmatched/missing-quantity/inactive counts; observational, no review mutation or approval. |
| Readiness | GET `draft-orders/<draft>/readiness/` | Ready boolean and seven stable code/count blockers; point-in-time, no revision token, warnings or approval state. |
| Convert/reconcile | POST `draft-orders/<draft>/convert/`, JSON `{}` | Active administrator + CSRF; fresh readiness under transaction locks. 201 first committed result, 200 authorized replay, same unique source-linked order. No revision/idempotency headers or overrides. |

Root shell hash routes are `#/workspaces/<workspace>/catalogue/`,
`#/workspaces/<workspace>/draft-orders/` and
`#/workspaces/<workspace>/draft-orders/<draft>/`. Reload/direct links and browser
back/forward revalidate the URL-selected workspace through existing session
selection APIs; an unauthenticated deep link is retained until login. Malformed
routes and inaccessible/missing drafts get explicit errors. Page changes use
bounded server requests, not bulk loading. No new backend routes are needed.

Detail, lines, observations and readiness are separate HTTP snapshots. Header
updated_at is shown as a timestamp, not an aggregate revision or optimistic lock.
Refresh replaces assessments without polling. Conversion always checks current
server state even after the screen reported ready. Blockers link to header/lines;
reference/unit remain optional. No warning, price, extraction-confidence,
document, download, approval-history or ERP information is fabricated.

Conversion requires deliberate confirmation with supported customer/line details.
It creates an internal purchase order, without approval, email or ERP delivery.
Confirmed results show the returned number/identifier and refreshed source state;
there is no existing order-detail UI to navigate to. Current purchase-order review
state is not inferred from a replay. Converted sources can retrieve their result
through the authorized replay action. Lost response/5xx/malformed success is
unconfirmed, never optimistic success; explicit reconciliation repeats the
documented safe request and may create the order if no result previously committed.
No automatic POST retries. Conflict blockers are displayed and current panels
refetched; role/action denial is distinguished from expired sessions or lost
workspace access. Workspace/session/draft changes discard obsolete responses.

Actual checks, limitations and file responsibilities are recorded in project state.
Production hosting, browser matrix and formal accessibility testing remain open.
