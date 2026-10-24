# Workflow evaluation protocol and instrumentation

This folder's eight cases and sixteen timed-arm records are **fabricated**.
They test the evaluator, not extraction coverage, customer accuracy, ERP
compatibility or staff productivity. Expected outputs were authored with the
fixture generator, not independently reviewed. No customer target is established.

Use `scripts/evaluate_workflow.py input.json new-report.json` from the repository
root. It uses only the Python standard library, preserves exact text identifiers,
compares decimal quantities with Decimal and refuses to overwrite an existing
report. Keep real observations, source documents and report files in ignored
private storage, not this tracked example directory. The input schema is
`orderdesk-evaluation-v1`; synthetic-observations.json shows every field.

Reproduce the instrument check:

```powershell
python docs/evaluation/generate_synthetic_fixture.py
python scripts/evaluate_workflow.py docs/evaluation/synthetic-observations.json backend/var/new-synthetic-evaluation.json
python -m unittest scripts.tests.test_evaluate_workflow -v
```

Use a fresh report filename each time. Compare the resulting JSON with
synthetic-report.json. JSON content is deterministic; the report has no generated
timestamp. Eight evaluator regressions cover exact IDs/decimals, missing/failed
cases, invalid timing evidence, duplicate observations, and simulated timing
rejection for customer datasets.

## Collection method

Select the full case cohort before processing. Include supported and unsupported
sources, multiple lines, customer/product ambiguity, multiple delivery locations,
explicit unit conversions, duplicates, revisions, invalid/incomplete inputs and
failures. Sample real incoming proportions; do not select only successful parses.
Record composition and inclusion/exclusion reasons. Keep independently reviewed
expected critical outputs separate from the implementation and hold them back
from the processor until scoring. An independent distributor reviewer must approve
critical fields and units, reference data date and expected manual fallback.
An `independently_reviewed` flag is an attestation, not proof of independence.

Define equivalent manual and Order Desk task boundaries: first active handling
through source interpretation, customer/product/unit resolution, corrections,
review, usable handoff and all downstream retyping or rejection work. Record
practice separately. Alternate/counterbalance which arm runs first, record the
operator, observer and prior experience, and avoid scoring remembered answers
as independent work. The example records four cases per first arm, without
claiming that this removes learning bias.

Start/stop an explicit timer for **active** work, or have an observer record
stopwatch intervals with a private session reference. Pause for queue waiting and
unattended extraction; resume for correction, review and downstream work. Preserve
the original interval notes so totals can be audited. Do not derive active time
from an open tab, login lifetime or elapsed interval. Record all failure work;
`completed=false` means an equivalent full task has not been observed.

## Metrics, denominators and limits

| Metric | Definition / denominator |
| --- | --- |
| Active handling | Sum of explicit work intervals per arm/case, in seconds, including post-export work; all observed failures remain in the distribution. |
| Queue waiting | Explicit measured queue intervals for observed Order Desk cases; kept separate from active time. |
| Total elapsed | Receipt/task start through completion/failure observation, including unattended waits; never a substitute for active time. |
| Format coverage | Declared supported documents / all selected documents; capability classification is distinct from observed extraction success. |
| Extraction success | Observed succeeded jobs / all selected documents, including unsupported, failed and missing observations in the denominator. |
| Corrections | Deliberate manual field changes; record order and line counts separately. Report raw counts, corrections / observed orders and corrections / observed lines. The simple evaluator does not deduplicate repeated field changes. |
| Critical correctness | Correct approved expected critical fields / all selected expected critical fields. Missing output/observation and invalid decimal are errors; identifiers retain leading zeros. Manual fallback/processing decisions are separately scored and cannot inflate critical-field correctness. |
| Exceptions / review returns | Explicit counts on observed Order Desk tasks; include reasons in private observer notes. Missing observations are visible through observation/case counts. |
| Rejection | Rejected / resolved reported-or-confirmed destination outcomes. Unknown/not-attempted cases remain separate; acceptance evidence levels are counted separately. Reported acceptance is never independent confirmation. |
| Extra downstream work | Explicit post-export active seconds, already included in total active handling; do not add it twice. |
| Savings | Manual minus Order Desk active minutes for completed equivalent pairs. Every excluded pair is listed. No cohort reduction or monthly capacity is calculated unless the entire selected cohort has completed paired observations. |

Distributions show sample size, median, min, max and linearly interpolated P90.
For additive monthly capacity use the arithmetic mean of paired minutes saved:

`eligible monthly volume × mean measured minutes saved per order ÷ 60`.

Volume must identify measured versus assumed basis and its evidence reference.
Negative savings means additional work. Treat labor value as capacity, not cash
savings; no wages, prices or lost-sales value are fabricated or added. Financial
outcomes require separately measured expenditure changes. Timing resolution,
observer effects, task complexity, operator experience and small sample size limit
inference. This instrument does not produce confidence intervals or establish a
causal rollout effect.

## Current result and readiness

The synthetic fixture includes seven declared supported formats and one unsupported
scanned PDF, two multi-line examples, ambiguous customer/sites, unit conversion,
duplicate/revised requests and an invalid incomplete task. One unit answer is
deliberately wrong to exercise field-level error scoring. One task is deliberately
incomplete, so full-cohort savings and monthly capacity remain null. Durations are
simulations, not measured staff observations. Targets of 50% less handling time
and 99% correctness remain **customer evaluation targets**, with no met/not-met
customer verdict from this data. The script never automatically approves a pilot.

Customer evidence remains BLOCKED: supply a representative source cohort,
approved critical-field definition, independent ground truth/reference data,
equivalent observed work records including failed/manual/downstream work, actual
destination rejection evidence and measured eligible monthly volume. Separately
approve the operational/security and customer-specific handoff gates in the main
implementation matrix. Instrument arithmetic passing does not clear those gates.
