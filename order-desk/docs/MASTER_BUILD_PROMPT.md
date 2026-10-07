# Master build prompt

Current verified checkpoint: Step 4D.4 protected requested draft-line creation
is complete locally after Step 4D.3 header creation and its validation repair.
616 full backend tests, 18 focused line/concurrency tests and 35 restricted-role
order/RLS checks passed on 2026-10-07 without skips. Lint/format, model drift,
migration state, runtime role and health gates passed. Read `PROJECT_STATE.md`
and `AI_Order_Desk_Step_04D4_Protected_Draft_Lines.md` before continuing.
Changes remain uncommitted. Next proposed increment: protected editing of
requested draft-line fields, with the update contract documented first;
catalogue attachment/matching remain separate. Historical next-step
instructions below do not supersede this checkpoint.

Historical verified checkpoint: Step4C8 is complete (448 normal tests, 100 runtime
checks, 23 script tests, 53 focused CSV tests and all12 concurrency cases; no
skips and all established gates passed). Commit title is
`feat: add admin-only catalogue import dry run`, committed as `42e1b3e`. Continue directly with the
already-authorized Step4C9 atomic create-only import execution. Historical
checkpoints below do not supersede this current sequence or verify order drafts.

Latest user override (2026-10-06): complete Step4C8 create-only administrator CSV
dry run, verify/document/commit it, then complete explicitly requested Step4C9
atomic create-only execution with durable tenant-scoped idempotency receipts.
Follow both attachments' exact multipart/header/limit/create-only contracts;
the older proposed upsert preview is superseded. Step4C8 writes no catalogue
rows and introduces no schema. Step4C9 permits a focused receipt schema/RLS
addition. Preserve mixed history7163966, use the isolated catalogue foundation,
keep all synthetic catalogue mutations in test_orderdesk, and apply no unrelated
order migrations. Continue without routine confirmation questions.

Latest user task override (2026-10-06): Step 4C.7 catalogue search and exact SKU
lookup is complete and verified, following `490d971`. Actual final results are
395 normal PostgreSQL tests, 86 direct-runtime checks, 23 script tests, and all
12 normal concurrency cases, with every established gate passed. Contract was
documented before code
in AI_Order_Desk_Step_04C7_Catalogue_Search.md. Keep reads scoped/read-only,
literal search bounded, existing equality/normalization and mutation behavior,
strict separate query allowlists, and all unrelated drafts. All synthetic data
stays in test_orderdesk. Next proposed step is 4C.8 CSV validation/dry run with
no catalogue writes; actual execution remains a separate increment.
Preserve external mixed commit `7163966`; catalogue verification used only the
isolated catalogue foundation plus this increment and does not verify its
unrelated order/provisioning drafts. The completion commit's requested title is
`feat: add tenant-scoped catalogue search and SKU lookup`; resolve its hash in
Git. Detailed actual plans, conditional empty-live limitation, commands, and
results are in the Step 4C.7 guide. Step 4C.8 remains proposed, not implemented.

Latest user task override (2026-10-06): complete only Step 4C.6 administrator-only
catalogue updates/deactivation, based on `bdcd551`. SKU is immutable; PATCH only
description/is_active. Preserve idempotent no-op timestamps, fresh protected
authorization and row locking, existing reads/creation/RLS, and all unrelated
drafts. Contract is in AI_Order_Desk_Step_04C6_Catalogue_Updates.md. Re-establish
actual native baselines; use test_orderdesk for all catalogue mutations. Next
proposed increment is Step 4C.7 search/exact SKU, excluding imports/fuzzy/AI/UI.

Current task override (2026-10-06): finish only Step 4C.5 administrator-only
catalogue creation, using committed Step 4C.4 (`3f1c0d3`) as the foundation.
Creation is implemented; its 317-test native normal suite, 13 contract tests,
44 service/API tests, four creation races, four existing races, 19 standalone
script tests, live read checks, system/migration/lint/health/guard checks pass.
The expanded direct-runtime verifier passed all 60 checks without skips as
orderdesk_app after bootstrap. Step 4C.5 is committed as `bdcd551`
(`feat: add admin-only catalogue item creation`), containing exactly 12 reviewed
files. Its code matched the isolated verified source. The index is empty and
unrelated drafts remain preserved. Do not treat those drafts as verified.
Next proposed increment: Step 4C.6 updates/deactivation, excluding hard deletion
and imports. Preserve unrelated local changes and keep catalogue fixtures in
test_orderdesk; main-database verification remains confined to catalogue reads.

Current task override (2026-10-05): finish only Step 4C.4, the tenant-scoped
read-only catalogue endpoint, verify it as `orderdesk_app`, and commit only that
increment. Leave creation for Step 4C.5. Preserve unrelated order/document drafts.
Use actual local results instead of the historical completion claims below.
Step 4C.4 is now verified and committed as `3f1c0d3`: 256 normal PostgreSQL
tests, 47 direct-runtime RLS/HTTP checks, and live verification passed. The next
requested increment is Step 4C.5; do not treat the preserved creation drafts as
already verified.

This repository is being developed in staged increments with local verification after each phase.

Current project status:
- Local PostgreSQL and backend foundation are verified.
- Organizations/workspace membership and authenticated session auth are in place.
- Catalogue RLS and the tenant boundary are verified.
- Purchase-order intake is implemented with scoped ownership, duplicate prevention, review/approval tracking, and a verified workspace-scoped order API layer for distributor workspaces.
- Source-document intake is now captured as a tenant-scoped order-document model and service for uploaded PDFs/CSVs.
- The next useful phase is downstream document review and extraction workflows beyond the current intake domain.

Key constraints from the build brief:
- Keep the app small, self-hosted, and local-first.
- Preserve the existing tenant-boundary design and role checks.
- Favor small, reviewable increments over large rewrites.
- Run focused tests after each change and document the checkpoint.

The detailed prompt was reviewed from the user's local copy at `C:\Users\HomePC\Downloads\MASTER_BUILD_PROMPT.md` and reduced here to an in-repo reference for this repository's working session.
