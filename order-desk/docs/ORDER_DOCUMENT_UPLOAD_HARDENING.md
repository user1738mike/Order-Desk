# Purchase-order document upload hardening

Implemented locally on 2026-10-08. This concerns the existing purchase-order
document endpoint, not draft catalogue attachment or automatic extraction.

## Contract

POST `/api/v1/workspaces/<workspace>/orders/<order>/documents/` accepts exactly
one multipart `file`. Existing session authentication, CSRF, active workspace
membership and admin/reviewer permission apply. The service refreshes access,
locks the scoped parent and checks its editable state before application input
validation. Foreign/missing parents return 404; unauthorized users return 403.
CSRF processing may parse multipart earlier, so the upload guard is installed
before authentication as well as enforced separately by the service.

The maximum is **10 MiB (10,485,760 actual file bytes), inclusive**. A transport
handler counts aggregate file bytes across multipart files, irrespective of
Content-Length or advertised file size. Oversize returns HTTP 413:

```json
{"detail": "The purchase-order document exceeds the 10 MiB upload limit."}
```

The service independently reads at most the bound plus one byte, using a
spillable temporary copy. Oversized direct service input raises a Django
ValidationError subclass, translated into the same 413 by the API; services
remain independent of DRF. Temporary storage closes on success and failure.
The bound covers file bytes, not total multipart framing or arbitrary non-file
fields; existing Django/proxy request controls remain separate. Empty files,
invalid metadata and duplicate files are rejected without document/file writes.
Successful responses retain the existing response shape and HTTP 201.

Stored filenames are generated server UUIDs under the existing date path.
Original filename metadata is retained. The API records the counted file size;
the legacy explicit service `size_bytes` metadata argument remains supported
and cannot bypass the actual-byte bound. No new public media/download route,
content execution, MIME eligibility rule, parser or scanner is introduced.

## Compensating cleanup

The service owns only the new path allocated for its attempt. It saves storage
explicitly before inserting the row, then materializes the response inside the
tenant transaction. An exception during storage write, row save, materialization
or transaction commit attempts deletion of that owned path after rollback.
Existing files are never reused or deleted; a detected name collision fails
before storage writes. Copying an existing FieldFile does not transfer ownership
of the source. Successful uploads keep both their row and stored bytes.

If deletion fails, the original exception is preserved and the constant message
`Source document rollback cleanup failed.` is logged without private filenames,
content or exception details. Such failure can leave an orphan requiring local
operator cleanup. This is compensating cleanup, not a distributed transaction:
process termination, ambiguous database commit outcomes and storage backend
failures need durable recovery before production guarantees can be made.
The tested backend is the configured local FileSystemStorage; other storage
backends require verification of their naming, partial-write and deletion rules.

## Verification

`apps.orders.tests.test_order_document_upload_storage` covers successful storage,
actual-byte boundaries, forged metadata, aggregate/duplicate multipart files,
CSRF parsing and temporary-file closure, current access, insert/commit/storage/
materialization failures, collisions, source-file preservation and cleanup
failure logging. `apps.orders.tests.runtime_rls` additionally exercises real
restricted-role credential sessions, both writers, viewer denial, foreign
parents and membership revocation with temporary private storage.

Run sequentially from the application directory:

```powershell
docker compose run --rm manage python manage.py test apps.orders.tests.test_order_document_upload_storage apps.orders.tests.test_services --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm manage python manage.py test --settings=config.settings.test --keepdb --noinput -v 0
docker compose run --rm rlscheck python manage.py verify_order_rls
docker compose run --rm rlscheck python manage.py verify_catalog_rls
```

Actual results are recorded in [project state](PROJECT_STATE.md). Fixtures use
the dedicated PostgreSQL test database and temporary MEDIA_ROOT. Native owner-
role tests establish application behavior; only the direct restricted-role
verifiers provide runtime RLS evidence. Logs/private audit files remain ignored.
Production ACLs and safe automatic extraction remain separate prerequisites in
[storage findings](STORAGE_FINDINGS.md).

## Private intake extension (2026-10-09)

The legacy contract above remains compatible. New operator uploads use the
explicit PDF/CSV private intake route, immutable source digest and authorized
download described in [SECURE_DOCUMENT_INTAKE.md](SECURE_DOCUMENT_INTAKE.md).
Legacy bytes are not automatically relocated or exposed through that route.
