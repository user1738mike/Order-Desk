# Durable local CSV extraction

This increment produces immutable **proposals**, not purchase-order lines,
catalogue matches, approval or ERP output. It uses verified private CSV documents
already attached to a purchase order. PDF/OCR/AI and legacy-file adoption are
unsupported. The referenced Downloads prompt was absent at implementation time;
the explicit user request and repository conventions define this local contract.

## CSV v1 contract

Parser `order-csv-v1` accepts exact, unique, case-sensitive headers `sku` and
`quantity`, with optional `description` and `unit` in any order. Unknown/duplicate
headers fail. Input inherits the private intake's inclusive 10 MiB, UTF-8/BOM and
rectangular CSV eligibility. Extraction is further limited to 500 data records and
2 MiB serialized proposals. Every cell is at most 4096 characters; interpreted
SKU is nonblank/max128 and unit max32. Description is preserved. Other values
trim only outer whitespace; case and leading zeroes remain intact.

Quantity is a positive ASCII decimal string with at most 14 integer digits and
four decimal places. No floating point, exponent, currency symbol, thousands
separator, rounding or unit conversion is used. Formula-looking text is inert;
it is never evaluated, rendered as HTML or exported to a spreadsheet here.

Each field stores `value`, `raw`, header `column`, one-based `column_index`, and
the record's starting/ending physical source lines (`row`, `end_row`). Multiline
records therefore retain their physical line range. The job records the original
source SHA-256, parser version and requesting/processing identities. Any invalid
record fails the entire job; partial results are never published. Staff must review
proposals separately before any future application to orders.

## Durable jobs and tenant boundary

Migration 0010 creates DocumentExtractionJob with a composite tenant document FK,
ENABLE/FORCE RLS, active-member read and active admin/reviewer write policies,
restricted SELECT/INSERT/UPDATE grants and no runtime DELETE/DDL privileges.
Database constraints bound attempts, result size/state and leases; an invoker
trigger protects source identity, valid transitions and completed result immutability.
Owner credentials are confined to migrations and dedicated-test fixtures.

Jobs are unique per document/source digest/parser version. Enqueue is repeat-safe:
one queued job, not duplicate work. Status moves queued → running → succeeded/failed.
Failure requires an explicit retry, at most three total attempts. A claim has a random
token and a two-minute lease. A live lease cannot be claimed twice. Expired running
jobs can be reclaimed by a fresh authorized processor; obsolete tokens cannot
publish. After the third interrupted attempt, the next authorized invocation marks
the job failed with `attempts_exhausted`.

Claim and publication use short organization-first tenant write transactions.
Byte integrity verification and parsing run outside database transactions. Publication
rechecks actor membership/role, source identity, lease/token and editable order state.
A revoked actor cannot publish or use owner credentials to record an error; its
running lease remains visible to other authorized readers and expires for recovery.
Unanticipated process errors likewise leave a durable lease. Database commit-response
loss is reconciled from stored status rather than by blindly repeating work.

The job result is one bounded JSON value committed atomically. It is intentionally
not a second copy of the order or an automatic document review. Existing document
received/review status, order lines and conversion records remain unchanged.

## APIs and operator workflow

Under `/api/v1/workspaces/<workspace>/orders/<order>/documents/<document>/`:

| Endpoint | Behavior |
| --- | --- |
| GET `extraction/?page=1` | Member read; nullable job plus fixed 50-record proposal pages. No storage paths or claim token. |
| POST `extraction/` with `{}` | Admin/reviewer and CSRF; 202 for newly queued identity, 200 for authorized repeat. |
| POST `extraction/retry/` with `{}` | Admin/reviewer and CSRF; 202 for failed job with attempts remaining, otherwise field-keyed 400. |

Malformed/foreign identifiers return 404; revoked/anonymous or insufficient role
is denied. Unknown input/query fields are 400. Intake metadata provides an
`extraction_url` only for private CSV. The Documents screen shows queue/processing,
expired lease, exact proposals/provenance and safe failure codes/row numbers.
Refresh is explicit; no automatic POST retry or optimistic success. Workspace/session
replacement clears proposals and rejects late responses. Downloads retain exact bytes.

The local processor is deliberately a one-job command, not an in-process web task
or added broker. Operators start it using active admin/reviewer identity:

```powershell
docker compose run --rm extract python manage.py process_csv_extraction --workspace <workspace-uuid> --actor <user-uuid> --job <job-uuid>
```

The extract helper uses direct orderdesk_app credentials and the same private volume;
the command verifies the actual session role before processing. Supply IDs from the
existing local workspace/user and queued job; never substitute the maintenance role.
Repeat an invocation after a crash once its lease expires. Failed jobs must first
be retried explicitly in the UI/API. No unattended scheduler/daemon is installed.

Visible failure codes include unsupported_headers, invalid_csv/row/sku/quantity/unit,
empty_result, row_limit, result_limit, source_unavailable, source_changed, order_locked
and attempts_exhausted. Errors never include source contents, private paths or exception
text. A storage failure does not forge an empty successful extraction.

## Verification and limitations

See PROJECT_STATE.md for actual native, migration, frontend, restricted-role and
real-browser results. Maintenance-role tests and parser mocks are not RLS proof.
The browser uses the real restricted worker in another process, deliberately exits
after claim, observes the durable expired lease and resumes from a new invocation.
Its short injected lease simulates expiry without waiting two minutes; the actual
process death and PostgreSQL persistence are real.

PDF parsing, confidence scores, autonomous matching, review acceptance/application,
ERP export, daemon scheduling, global worker capacity/rate limits and production
deployment remain separate increments. Backups must cover job metadata and private
source volume; extraction cannot recover missing original bytes.

Implementation: `csv_extraction.py` parses proposals; `extraction_services.py` owns
transitions; models/migration 0010 enforce persistence/boundaries; selectors,
serializers/views/URLs expose scoped status/actions. `process_csv_extraction.py`
and Compose extract run one restricted job. Existing document UI modules/template
render proposals using text nodes. Native/controller/runtime/browser tests cover
their respective behavior and evidence boundaries. No dependencies were added.
