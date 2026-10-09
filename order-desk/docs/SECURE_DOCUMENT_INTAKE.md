# Secure document intake

This local increment attaches original sources to an existing **purchase order**,
not a draft-order source. A confirmed conversion links to that purchase order's
Documents screen. Operators can also open a known purchase-order UUID. It reuses
OrderDocument and its existing received/pending_review/rejected lifecycle; upload
does not approve, extract, match, submit or export an order.

## Contract and authorization

- GET/POST `/api/v1/workspaces/<workspace>/orders/<order>/documents/intake/`:
  fixed 50-item metadata pages; POST accepts exactly one multipart `file`.
- GET `/api/v1/workspaces/<workspace>/orders/<order>/documents/<document>/download/`:
  authorized attachment of the original private bytes.
- Active members can read. Active administrators/reviewers can upload to an active
  draft/rejected purchase order. Fresh user, workspace and membership checks occur
  at request entry and in tenant transactions. Foreign parents/documents are 404.
  Anonymous/revoked access is denied; session mutations require CSRF.

Empty or unsupported files return field-keyed 400. Actual file bytes are bounded
to an inclusive 10 MiB, including multipart parsing during CSRF and direct service
streaming regardless of supplied size. Oversize returns 413. PDF eligibility checks
the version signature and final EOF marker; it is **not** deep PDF validation or
malware scanning. CSV must be rectangular UTF-8 (optional BOM), 2–128 columns,
at most 10,000 rows, 4,096 characters per cell and 65,536 per physical line.
Client MIME is ignored. The bytes are preserved, never executed or previewed.

## Private storage and transactions

The supported storage runtime is Linux containers. Compose mounts the persistent
`document_data` volume at `/private-documents`; its one-shot `documentstorage`
service initializes the root for UID 10001 with mode 0700. The root must be outside
static and legacy media roots. Every directory component is opened without following
symlinks; generated exclusive UUID filenames cannot overwrite another source.
Names supplied by users are sanitized display metadata only. Files are sealed 0400,
fsynced, and have their SHA-256 recorded in metadata (migration 0009). Downloads
verify regular-file ownership, single link, size, permissions and digest, then send
attachment/no-store/nosniff headers. Missing/corrupt storage fails safely with 503.
No private path or public URL is returned.

Preflight and final metadata writes are short tenant transactions. Slow receive,
validation, digest verification and download streaming occur outside database locks.
Finalization reacquires the existing organization-first lock and revalidates access
and order state. Ordinary pre-commit failure deletes staged bytes. Once commit is
attempted, acknowledgement failure retains bytes: a 503 means the outcome is
unconfirmed. Check the status list before a deliberate retry. There is no automatic
POST retry or server upload idempotency claim.

An OS file lease spans staging and commit; process death releases it. Local orphan
recovery requires DEBUG, the direct orderdesk_migrator maintenance identity and
orderdesk/test_orderdesk. Run:

```powershell
docker compose run --rm manage python manage.py reconcile_private_documents
```

Each invocation inspects at most 1,000 entries and removes at most 100 unreferenced
UUID files older than 24 hours. Leased, recent, referenced and unrelated files are
preserved. `--offset` (0–100000) bounds continuation; restart at zero after a complete
pass because deletions change directory positions. Never run cleanup under a tenant
role whose metadata visibility is incomplete. Production recovery scheduling,
capacity quotas and backup/restore of both database and volume are not verified.

## Operator behavior and compatibility

The Documents screen clears private data/file selection across workspace/session
changes and rejects late responses. Upload shows an indeterminate progress state;
duplicate submission is disabled. Validation errors preserve the selection; ambiguous
results require an explicit status refresh before retry. Download requires a deliberate
click and creates a temporary object URL, then revokes it. Revocation denies the next
request; it cannot recall bytes already downloaded or stop an already authorized stream.

The legacy generic `/documents/` endpoint remains compatible with its existing
tests and arbitrary-file contract. Its files remain in MEDIA_ROOT; they are not
automatically adopted, hashed or downloadable through this new route. Their status
rows show no private download URL. Legacy migration and deeper content scanning
are separate work. No OCR, AI, pricing, ERP or automatic review is introduced.

Verification commands and actual results are recorded in PROJECT_STATE.md. Native
maintenance-role tests establish behavior, not runtime RLS; the separate restricted
order-role verifier and real browser server provide that evidence. Production
proxy/TLS/storage deployment is outside this local result.

## Source responsibilities

| Files | Responsibility |
| --- | --- |
| `backend/apps/orders/private_documents.py`, `document_storage.py` | Bounded private staging, eligibility, leases, immutable opens and compatible FileField reads. |
| `document_intake.py`, `selectors.py` | Framework-independent finalization and scoped metadata reads. |
| `models.py`, migration `0009_private_document_digest.py` | Persist source digest and enforce its presence for private keys; existing forced RLS/grants remain in force. |
| `views.py`, `serializers.py`, `urls.py` | Explicit intake/status/download endpoints, scalar responses and safe error/attachment handling. |
| `management/commands/reconcile_private_documents.py` | Bounded local orphan recovery with complete metadata visibility and leases. |
| `config/settings/base.py`, `compose.yaml` | Storage adapter, dedicated persistent root and runtime permissions. |
| `frontend/assets/desk/{api,orders-api,documents,main}.js`, `frontend/templates/workspace.html` | Shared FormData/binary transport, routing and operator controls. |
| `test_private_document_intake.py`, `runtime_rls.py`, `frontend/tests/{documents.test.js,browser-smoke.mjs,browser_fixture.py}` | Native storage/rollback regressions, restricted-role evidence and isolated real browser flow. |
| `test_draft_conversion_migration.py` | Restore current schema after historical upgrade assertions, so later tests include the digest column. |
