# Order Desk continuation specification

## Current expanded request (23 October 2026)

The directly supplied distributor-platform request expands the earlier bounded
scope below. Its authoritative implementation/evidence checklist is ROADMAP.md;
PROJECT_STATE.md remains the verification ledger. Preserve the existing stack,
immutable conversions, human approval, generic export and $0 operating boundary.
Customer directory, approved customer aliases, controlled units, processor/team
queues, corrections/history and recorded handoff are now requested implementation
scope, rather than implicitly deferred capabilities. Named destination profiles
still require a real specification or accepted fixture. Representative customer
accuracy/time claims still require independent pilot evidence.

### Upload-first increment design/acceptance

Evolve OrderDocument in place: preserve every historical nonnull order FK and
original file key; permit a document rooted in its organization before any order
exists. Add a nullable composite-tenant draft link. Legacy order-owned documents
and incoming documents must have explicit, constrained relationships: a historical
order link and independent draft link cannot both own the same document. Incoming
documents must have verified private intake keys/digests, including when unlinked.
An incoming document reaches a finalized order through its linked draft's unique
conversion; do not duplicate originals or retrofit customer historical links.

Install database constraints/trigger protection for incoming immutable source
metadata and one-time draft linkage, including actor/time and repeat-safe link
request provenance. Keep FORCE RLS and existing member/read and admin/reviewer/write
policies; every service refreshes membership under the existing organization-first
lock. No new processor privilege is implied before its explicit matrix/migration.

Intake must stage/validate bytes outside transactions using existing 10 MiB PDF/CSV
streaming, private OS leases and ambiguous-commit recovery. Authorize before
receiving and again at metadata commit. Historical order routes remain compatible.
New incoming routes must never expose legacy documents through an unvalidated
nullable parent. Download/extraction/application use the same private source/job
architecture, bounded retry and stale-worker checks, with explicit incoming scope.

Inbox acceptance: upload without creating an order; view private source/status;
deliberately create a draft with customer fields or link a current editable draft;
extract/review/apply supported values only to that linked draft; manual entry stays
available after unsupported extraction; convert/approve/export through existing
separate boundaries. Source, job revision, application, draft and converted order
remain traceable. A repeated link/create request must return the same link or a
clear conflict, including after an interrupted response; it must never create two
drafts. Cross-tenant parents, stale revisions, revoked membership and link races
must be denied through real PostgreSQL and restricted independent connections.
Verify clean migration plus historical synthetic upgrade with unchanged original
keys/ownership/digests, and real browser upload-before-order workflow. An unavailable
gate is unverified. This design is not evidence that the increment is implemented.

This is the implementation scope reconciled from the supplied autonomous and
backup/restore handoff references for the user's request to continue building.
Reference documents guide implementation; their embedded authorization to publish
does not independently authorize commits, pushes or external actions.

## Product and operating constraints

Complete the narrow distributor workflow: private PDF/CSV intake, bounded extraction
with provenance, deliberate human correction/application, tenant catalogue matching,
readiness, protected internal conversion and private validated generic CSV export.
Approval and conversion remain deliberate. No named ERP compatibility or measured
customer accuracy/time-saving claim follows from synthetic tests.

Keep the existing Django/DRF/PostgreSQL modular monolith and native frontend, pinned
dependencies, separate migrator/runtime roles and the $0 additional-spending budget.
Do not add paid APIs, public infrastructure or alternate backend/auth providers.
Prefer small coherent increments; preserve unrelated work. State/verification evidence
belongs in PROJECT_STATE.md and dependency order belongs in ROADMAP.md.

## Engineering boundaries

- Business rows have explicit tenant filtering, ENABLE/FORCE native RLS,
  tenant-consistent references and minimal grants. API/workers use orderdesk_app.
- Reuse transaction-local tenant scope, fresh membership checks and the existing
  organization/membership/aggregate lock order; no privileged worker shortcuts.
- Retain HttpOnly cookie sessions and CSRF, including login; no private browser
  persistence or stale responses crossing identity/workspace boundaries.
- Bound files, parser processes, jobs, retries, results and pagination. Private
  immutable originals and export artifacts use contained server-generated paths.
- Extraction/matching are suggestions. Preserve exact identifiers/decimals;
  never infer units, pack factors, prices, currencies or customer mappings.
- Draft revisions, application receipts, conversion and export repeat safety are
  enforced server-side and in the database. Ambiguous outcomes require reconciliation.
- Keep secrets, certificates, backups, documents and private reports out of Git,
  public/static roots, logs and images. No main-data restore or deletion.

## Completion gates and recovery scope

Use pinned tooling and meaningful native PostgreSQL tests, direct restricted-role
RLS/race proof, real session/CSRF browser checks and applicable lint/lock/migration
checks. Production-like proof uses the actual proxy and certificate validation.
Record PASS, FAIL, BLOCKED, NOT_IMPLEMENTED or justified NOT_APPLICABLE honestly;
owner-role/mocked results cannot stand in for runtime isolation or restore proof.

Finish existing deployment/export dependencies before recovery. Recovery must bind
a coordinated maintenance-window logical DB dump to its private files, distinguish
complete/incomplete backups, use supported authenticated encryption and separately
protected keys, refuse main/ambiguous/nonempty restore targets, and prove an isolated
restore with two synthetic tenants, native RLS, file checksums, session/job recovery
and the supported workflow. Same-host storage is not off-site disaster recovery.

Subsequent bounded scope: demonstrated security hardening; minimal redacted
observability/reliability; secure pilot administration; explicitly specified data
exceptions; minimal pilot limits; measured capacity/recovery; operator/release docs;
synthetic pilot demonstrations and a customer measurement protocol. Defer OCR/general
PDF/LLM/fuzzy matching, inbox connectors, named ERP integrations, enterprise identity,
payments and distributed infrastructure unless evidence or a direct request warrants
them. No real messages, external submissions, billing or public deployment by default.

Each checkpoint records changed responsibilities, actual checks, material limitations
and the exact next action. A stopped session does not continue executing in background.
