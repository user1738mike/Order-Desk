# ADR 0003: one bounded generic machine CSV from approved conversion snapshots

Use generic-po-csv-v1 from existing approved converted purchase orders, not live
catalogue values or unreviewed proposals. Preserve exact values and reject unsafe
text under an explicit conservative profile rather than changing machine data for
spreadsheet viewing. This establishes a local schema, not named ERP compatibility.

Small files (500 lines / 2 MiB) use synchronous formatting outside DB locks, with
one durable leased artifact record and database uniqueness/transition guards.
Reuse private storage, OS leases, digest verification and bounded reconciliation;
no queue/broker/dependency or public storage link is added. A crash is recovered
by an explicit request after lease expiry; success is immutable and never rebuilt
under the same identity. Profile changes are distinct versioned work.

The existing approved state is the human approval gate. Preserve conversion
header/line guards and freeze approved converted decision metadata. Fresh active
admin/reviewer permission protects previews, generation and downloads. A viewer's
general read membership is insufficient export permission. Actual verification
and supported Linux/local limitations are recorded in PROJECT_STATE.md.
