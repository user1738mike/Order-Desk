# Order Desk continuation specification

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
