# Distributor workflow acceptance contract

Request received 24 October 2026. Baseline: main, clean at
469519510d919af0620f1279a613098275b69e22. Docker development API/database healthy;
other running projects and existing databases are preserved. Python 3.14/Django
5.2/PostgreSQL 18 and native JavaScript remain the implementation stack. Historical
audit evidence is context, not verification of changed code.

| Requirement | Current source behavior | Gap / proposed increment | Observable acceptance | Evidence / status |
| --- | --- | --- | --- | --- |
| Upload-first | Evolved OrderDocument, incoming.py/views/urls, migration0015, documents.js and linked extraction/review/application | Incoming-specific fresh recovery evidence remains in operational gate | Upload before order; create/link draft without typing UUID; original bytes/history survive upgrade; retries cannot create two drafts | VERIFIED local scope: focused12 PostgreSQL plus3 upgrade tests, fresh870 native/59 runtime/115 catalogue checks and actual-backend browser PASS. Duplicate bytes/references warn without blocking legitimate repeats. |
| Customer | DraftOrder customer text only | Scoped accounts, approved aliases, destination IDs/sites, inactive validation and immutable snapshots | Ambiguous/inactive accounts blocked; multi-site selection explicit; validated imports | MISSING |
| Product/units | matching.py exact SKU, raw unit and Decimal quantity | Approved customer aliases, provenance and explicit product-specific conversion policy | Leading zeros preserved; collisions, unknown units and precision errors visible | MISSING |
| Exception review | extraction_apply/readiness, separate editor/review screens | Unified source/draft review; server blockers, revisions and reasoned returns | Resolve through relevant fields; stale approvals cannot authorize material edits | DEFECTIVE; structural checks exist, complete workspace absent |
| Usable handoff | csv_export/export_services, generic-po-csv-v1 only | Versioned profiles, field-level preview, evidence-level handoff outcomes | Immutable revision/profile identity; unsafe cells rejected; actual destination accepted fixture/import | Framework MISSING; real customer handoff BLOCKED: no destination contract/accepted fixture found in inspected spec, roadmap and export ADR |
| Operational savings | scripts/evaluate_workflow.py, evaluation protocol and eight-case simulated fixture/report | Collect representative independent ground truth and observed timer/stopwatch records under documented equivalent boundaries | Equivalent manual/app tasks; failures and downstream work counted; independent customer ground truth | VERIFIED instrument arithmetic/reproducibility:8 unit tests; customer benefit BLOCKED. Simulated durations and authored expected outputs are not customer evidence; no target claim. |
| Permissions | admin/reviewer/viewer, fresh tenant_scope and forced RLS | Explicit processor matrix; new data constraints/policies and runtime tests | Revocation/demotion and concurrent protected actions denied | DEFECTIVE for requested scope; existing controls retained |
| Recovery/support | durable extraction/export leases, private staging, isolated recovery tools | Inbox recovery controls; current increment restart/restore proof and short operator runbook | Crash/retry/stale completion, fresh isolated DB/file restore, safe diagnostic guidance | Existing evidence in AUDIT_2026-10-24; changed candidate unverified |
| Verification/delivery | isolated PostgreSQL, restricted verifiers, browser harness, quality scripts | Extend each gate for new relationships/journeys, coherent commits | Fresh/upgrade migrations, tenant tampering, real browser and final checks | MISSING for changed candidate |

No approved deferrals. Dependency order: upload-first source lifecycle; customer
reference data and processor permissions; units/aliases and exceptions; profile and
handoff evidence; timed evaluation; full operational/recovery verification.

Prices, taxes, stock, credit and delivery promises remain **not checked**. Generic
CSV and synthetic contracts never establish ERP acceptance. A download never
establishes handoff acceptance. Targets of 50% handling-time reduction and 99%
critical-field correctness remain unmeasured customer targets.
