# Roadmap

## Current approved sequence

- Step 4C.3: committed catalogue schema and forced RLS (`9a5f2de`).
- Step 4C.4: read-only catalogue HTTP API; verified and committed as `3f1c0d3`.
- Step 4C.5: administrator-only catalogue item creation; verified and committed as `bdcd551` (317 normal PostgreSQL tests, 60 direct-runtime checks, 19 script tests).
- Step 4C.6: verified/committed as `490d971` (355 normal tests, 75 runtime checks); description/status updates only, SKU immutable.
- Step 4C.7: tenant-scoped catalogue search/exact SKU lookup; complete, verified with 395 scoped normal PostgreSQL tests, 86 direct-runtime checks, 23 script tests and all 12 normal concurrency cases. Completion commit title: `feat: add tenant-scoped catalogue search and SKU lookup`.
- Step 4C.8: committed `42e1b3e`, administrator CSV create-only dry run, no catalogue writes; 448 normal tests, 100 runtime checks, 23 script tests and all 12 concurrency cases passed.
- Step 4C.9: atomic create-only CSV execution and durable tenant-scoped receipts; implemented and verified locally as the Step 4D.1 prerequisite, with Git delivery pending.
- Step 4D.1: local implementation and verification complete for manual draft-order header/lines, composite tenant references, forced RLS, and restricted grants. Git delivery pending; see the Step 4D.1 verification guide.
- Step 4D.2 (proposed): bounded read-only tenant-scoped draft-order list/detail API; preserve unresolved fields and serialize inside transaction-local RLS.
- Existing order/document work: preserved by external mixed commit `7163966`, outside this increment's verification scope; no order migrations applied.

The historical milestone labels below do not establish verification of local drafts.

## Milestone 1: backend foundation
- Complete

## Milestone 2: workspace and session auth
- Complete

## Milestone 3: catalogue tenant boundary
- Complete

## Milestone 4: order intake
- Complete
- Added purchase-order domain model and validation
- Enforced workspace ownership, duplicate prevention, and review/approval state transitions
- Added workspace-scoped order API endpoints for list/create, detail access, lines, and review actions
- Added tenant-scoped source-document capture at the order boundary

## Future milestones
- PDF/CSV intake and extraction review
- Approved order export profile
- Audit trail and usage tracking
- Frontend review workspace
