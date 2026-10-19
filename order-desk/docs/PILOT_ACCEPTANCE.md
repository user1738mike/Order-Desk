# Customer pilot acceptance and measurement

This is an execution protocol for the original launch plan, not a pilot approval.
Use the current dated audit and PROJECT_STATE for implemented scope and evidence.
The local generic CSV profile does not satisfy a named ERP import requirement.
No customer upload, external communication or ERP write is authorized by this file.

## Inputs required before a customer pilot

Record the authorized customer entity, operations owner, reviewer/champion,
ERP administrator, exact ERP edition/version/modules/import job and sandbox
authorization. Obtain the actual file specification and confirm import licensing.
Require authoritative catalogue/customer/ship-to mappings, timestamped customer
prices, currency and price basis, unit/pack conversion rules and their approvers.
Explicitly record unknowns; hold affected orders for manual review rather than
inventing mappings, conversion factors, prices or account identities.

Agree supported source profiles, critical-field definitions, duplicate/revision
semantics, data access rights, retention/deletion, volume limits, support/escalation
owners and recovery/key custody. Illustrative subscription allowances in the
launch plan are commercial hypotheses, not approved enforcement rules. Current
local resource ceilings do not implement monthly order/line quotas.

Before onboarding real data, require reviewed image/advisory disposition, restricted
runtime/RLS proof, fresh and representative upgrade proof, secure administration
and auditable membership changes, general operation history, applicable usage
controls, monitored failures, protected off-site backups and a witnessed isolated
restore. Same-host encrypted synthetic recovery is insufficient disaster recovery.

## Freeze a representative benchmark

The original launch plan calls for three partners sharing one viable ERP workflow,
60 calibration orders and 300 withheld test orders (100 per partner). Obtain
explicit authorization and protect originals/ground truth in private storage.
Include difficult identifiers, leading zeros, unit/pack/pricing discrepancies,
unsupported layouts, revisions and repeat uploads representative of actual work.
Deduplicate related orders/templates when assessing independence. Never tune rules
using the withheld set; version and freeze parsers, rules, catalogue snapshots and
the candidate source/image manifest before evaluation.

Have a customer-authorized reviewer establish independent ground truth for every
critical field: customer account, ship-to, customer PO number, SKU, quantity, unit,
currency and price basis, plus agreed required price fields. Record provenance,
source/catalogue dates, approved rules and expected ERP result. The present local
schema omits several of these fields; mark them unsupported, not correct by
omission. Resolve disagreements before unblinding candidate output.

## Measure raw extraction and final business outcomes separately

For each order record raw exact field correctness, abstentions, unsupported cases,
manual corrections, reviewer decisions, application/conversion/export identifiers,
ERP sandbox import outcome and independently checked resulting ERP order. Preserve
failed imports and all manual/founder rekeying in the record. Score all critical
fields and order-level completeness; do not count only accepted fields or treat
a successful extraction/download as a correct business outcome.

Use paired baseline/candidate tasks of comparable difficulty with trained staff.
Measure the complete handling interval: open, interpret, match, investigate,
correct, review/approve, export/import and confirm/follow up. Include exception
and retry time; record setup, training and catalogue maintenance separately.
Report per-partner sample sizes, distributions and total time, plus denominators
for unsupported/failed/abstained orders. Log assistance and carry-over effects.
The target is at least 50% less complete handling time for each partner, not an
aggregate extraction-only improvement.

Require zero missed critical errors in reviewed pilot exports and confirmed ERP
results. A critical failure suspends the affected path; retain the original and
output, investigate, add regression evidence and rerun the affected benchmark.
Zero errors in 300 independent representative orders supports only about a 99%
one-sided 95% order-correctness lower bound under the plan's assumptions. It does
not establish 99.9%, generalization to other customers, or permanent reliability.
Synthetic fixture success supplies no commercial accuracy/time-saving evidence.

## Operator rehearsal and release decision

First rehearse locally with synthetic tenants using the current verification
runbooks: login/select workspace; validate/import catalogue; privately upload
supported source; run the explicitly authorized restricted worker; inspect source
provenance; deliberately correct/apply; match exact SKUs; edit unresolved values;
inspect readiness; convert; submit/approve; preview/generate/download generic CSV;
independently compare every value; reload/restart; restore to a fresh isolated
target. Include wrong-tenant/viewer/stale-revision/unknown-outcome failures.

Unsupported extraction uses the manual draft entry link. Preserve the source and
record why it is unsupported; enter only verified values, leaving unknowns
unresolved. Drafts over 500 lines remain editable with a `line_limit` blocker;
preserve them and use the customer's authorized manual order process. Do not
silently truncate/split an order, guess a pack factor or retry an uncertain write
with changed data. Reconcile the same receipt/source and inspect current status.

Record separate signed decisions for local functionality, security, operations
and customer pilot acceptance. Include candidate identity, required-gate results,
unverified checks, risk owners, approved deferrals and exact remaining actions.
An absent input or failed required gate keeps its decision blocked. Source control
delivery and a successful local rehearsal do not authorize public launch or live
ERP posting. Published customer outcomes require independently measured evidence
and customer permission.
