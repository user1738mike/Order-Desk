# Step 4D.10: Atomic, repeat-safe internal draft conversion

Contract recorded before implementation, 2026-10-08. This creates an internal
purchase order in `draft` state; approval, external ERP delivery and production
deployment are separate. Readiness is the shared Step 4D.9 evaluator, freshly
executed inside conversion, never a client assertion.

## API and repeat behavior

POST `/api/v1/workspaces/<workspace>/draft-orders/<draft>/convert/` accepts only
an empty JSON object, no query parameters or business overrides. Active workspace
administrators only; deny reviewers/viewers and nonmembers, including superusers.
Require session authentication, CSRF and fresh active account/workspace/member
checks after the organization lock. Foreign/missing/malformed draft IDs return
404; unauthorized requests return 403, invalid input 400, other content types
415 and unsupported methods 405. Inaccessible lookup precedes input parsing.

Return a bounded response: `id`, `organization_id`, `source_draft_id`,
`purchase_order_number`, `order_url`. First committed conversion returns 201;
an authorized valid repeat returns 200 with the same identity and representation.
Validate the empty input before replay. Replay precedes readiness: catalogue
deactivation and later order review do not invalidate an already committed result.
No existing optimistic revision mechanism exists; no new ineffective token or
generic Idempotency-Key subsystem is introduced. This guarantees one committed
internal result per source draft, not global exactly-once delivery.

Fresh readiness failures return 409 with `detail: draft_not_ready` and bounded
`blocking_reasons` containing the stable readiness code/count plus `path`:
customer_name, lines, lines.quantity, lines.catalogue_item_id or
lines.catalogue_sku_snapshot. No foreign tenant data or line text is disclosed.
Converted drafts report `draft_already_converted` on readiness. Mutation attempts
on converted drafts return 409 with `detail: draft_already_converted`.

## Linkage and snapshot

Add a nullable OneToOne `PurchaseOrder.source_draft` for legacy compatibility,
with a unique database index and composite `(source_draft_id, organization_id)`
foreign key to the draft. Existing orders remain unlinked; no data is relabeled.
Converted drafts gain status `converted` and remain readable as source records.
The conversion actor/time are the existing purchase-order created_by/created_at;
draft initiating_user/created_at remain original provenance. No audit-event
subsystem exists, so no audit-completeness claim is made.

Allocate a deterministic internal number `DRAFT-<source UUID hex>` (38 characters,
within the existing 64 limit). An existing unrelated order with that reserved
number returns a stable 409 `purchase_order_number_conflict`; never adopt it or
silently rename it. Unique source linkage is the durable retry identity.

Copy customer_name exactly and create independent purchase-order lines with
position -> line_number, stored catalogue_sku_snapshot -> sku,
catalogue_description_snapshot -> description, exact quantity and unit.
Preserve case, punctuation, leading zeros and stored whitespace. Customer
reference and intake text remain on the frozen source; they are not guessed
into the required order number or public document path. No prices, currency,
pack sizes, documents, extraction or network effects are inferred or copied.

The source link and copied purchase-order identity/customer fields and line set
become immutable after linkage, both in services and database triggers. Source
header/lines are frozen after conversion. Existing submit/approve/reject review
transitions and private document/manual review handling remain available; their
metadata is mutable under existing rules. This is an immutable conversion
snapshot, not an assertion that every purchase-order field is immutable.
Correcting converted source/line data would require a separately defined revision
or copy workflow; no reopen operation is introduced, including after rejection.

## Transaction and lock protocol

Use one outer write tenant scope: organization lock -> refreshed membership/role
-> source draft lock -> ordered source lines -> order/line writes -> source link
-> draft converted status -> bounded response materialization -> commit.
Every existing draft/header/line/attachment writer and catalogue eligibility
writer already takes the organization lock. This serializes inserts as well as
updates and deactivation; no lock on existing lines alone is mistaken for phantom
insertion protection. Membership-changing services follow the same organization-
first protocol. Direct administrative SQL must follow that protocol to obtain
the same application-level concurrency guarantees.

Shared readiness executes under these locks before copying. Order lines are
inserted before linkage, then the immutable source link seals the snapshot.
Database guards reject partial linked/converted states at commit, immutable
snapshot changes and nonadministrator linkage/status transitions as runtime role.
Constraints/triggers run with invoker permissions and retain forced RLS.
Exceptions in order/line/link/status creation, materialization or commit roll
back all business rows. Only recognized number uniqueness conflicts are translated;
unrelated integrity errors remain visible. No file or external effects occur.

## Required verification

Native PostgreSQL domain/API tests: ready mapping and exact decimals; each
readiness blocker; administrator-only access, CSRF and fresh revocation; strict
payload/query/UUID behavior; retries/lost response; original source preservation;
all draft mutation routes frozen; order line endpoint frozen; existing order
review flow; failure after order/line/link/status and materialization/commit.
Database tests enforce source uniqueness, tenant composite references, completion
and immutable snapshots. Inspect migration from 0007 and clean installation;
legacy orders/data must survive unchanged.

Independent-connection races synchronize with barriers/events and observed
PostgreSQL lock waits: two conversions, conversion vs header/line insertion/
editing/attachment/deactivation and revocation/demotion, both permitted serial
orders. Restricted-role credential/service/SQL checks establish allowed/denied
conversion, uniqueness, tenant consistency and freeze independent of owner tests.
Run focused/full suites and both guarded verifiers sequentially on test_orderdesk;
retain main-database refusal, lint/format/schema/health checks. Private audit files,
logs, secrets and customer files remain ignored. Actual results go in project state.

## Actual results: 2026-10-08

26 focused tests passed (13.781s), including previous-schema upgrade and both
serial orders across eight mutation types. A disposable clean PostgreSQL project
applied all migrations and passed 21 conversion/readiness/race tests (12.386s).
Full native regression: 719 tests (214.080s), OK. Direct orderdesk_app verifiers:
46 order checks (148.280s) and 115 catalogue checks (349.500s), OK. No skips.
Lint/format/schema/dependency/health/role/refusal/ignore checks passed. Migration
0008 also applied to the existing local app database after a clean source-state
preflight; legacy records were not relabeled or repaired. See PROJECT_STATE.md
for exact commands and initial corrected fixture failures. Changes remain in the
working tree. This verifies internal conversion, not production storage or ERP.
