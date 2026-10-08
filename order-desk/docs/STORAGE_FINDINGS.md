# Document-upload storage prerequisites

Sanitized post-audit findings, 2026-10-08. These concern the older purchase-order
document endpoint, not draft attachment (which links catalogue rows).
No application remediation is included in the documentation/reproducibility
increment. Existing passing suites do not close these gaps. Concurrent local
upload-hardening edits and tests appeared after reconciliation began; they are
preserved but excluded from this documentation delivery and not declared ready.
The findings below describe the audited/published backend before those edits.

## Affected implementation

- `backend/apps/orders/services.py:create_order_document`: fresh writer
  authorization, scoped order lookup/lock, model validation, FileField save and
  response materialization inside the tenant transaction.
- `backend/apps/orders/models.py:OrderDocument.file`: local FileField path
  `orders/source_documents/%Y/%m/%d/`; file metadata and workspace parent.
- `backend/apps/orders/views.py:OrderDocumentListCreateView` and
  `serializers.py:OrderDocumentCreateSerializer`: generic multipart upload.
- `backend/config/settings/base.py`: local `MEDIA_ROOT=BASE_DIR/var/uploads`.
- Existing tests: `apps.orders.tests.test_services`, `test_constraints`,
  `test_concurrency`, and guarded `runtime_rls`; catalogue's actual-byte bounded
  upload transport in `apps/catalog/uploads.py` is a useful existing reference.

## Classification and evidence

| Finding | Evidence and scope | Smallest focused remediation / missing checks |
| --- | --- | --- |
| Storage rollback leaves an orphan | Reproduced after a successful file save followed by a synthetic materialization ValidationError: the DB document row rolled back, one stored file remained, and the connection left its atomic block. One temporary test passed in 0.362s using `test_orderdesk`, migrator credentials and temporary MEDIA_ROOT. This demonstrates a storage lifecycle gap; it is not runtime-RLS evidence. | Own the new stored file lifecycle and compensate failures after save, including commit failures. Delete only the file created by that attempt; never a pre-existing file. Test validation/materialization/save/commit failure, cleanup failure handling, success persistence and no unrelated-file deletion. |
| File bytes have no dedicated endpoint bound | Inspected generic FileField serializer/service; no order-document actual-byte upload handler comparable to catalogue imports. Size metadata is not a stream limit. No oversized-file attack was performed in this increment. | Define a bounded document upload contract and guard actual aggregate bytes, including multipart parsing during CSRF, absent/forged Content-Length and streaming/temp-file cleanup. Test rejection before document/storage writes and current authorization; do not rely on Django's memory-to-disk threshold as a total size cap. |
| Confidential storage/retrieval is not deployed or verified | Local uploads are ignored, there is no authenticated document-download route, and root URLs do not mount public media serving. Row-level tenant isolation passed separately. A shared date directory is not itself proof of leakage, and DB RLS does not enforce filesystem permissions. | Keep files outside a public web root; document private deployment ACL/storage access and any future scoped download contract. Test foreign/anonymous/revoked download denial before introducing retrieval; verify production storage access independently. |
| Content eligibility and parser safety are undefined | Generic upload accepts supplied metadata; no MIME/content validation, malware scan or parser pipeline is present. No malicious file was executed. | Define accepted formats and safe handling before automatic intake; validate content independently of client MIME/name and prohibit execution/public rendering. Determine whether scanning is needed for the eventual handling model without adding paid dependencies speculatively. |

The private reproduction lives only under ignored `backend/var/`; it dynamically
adds one temporary test to the existing TransactionTestCase and uses the existing
setUp's temporary storage cleanup. It is not added to the normal suite or Git.
The reproduction intentionally asserts the current faulty storage behavior to
confirm the finding. It must be replaced by a permanent regression asserting
cleanup when remediation is implemented.

## Release/dependency boundary

No authorization bypass, filesystem escape or cross-tenant download was
demonstrated in this increment. Existing application checks and real-role
PostgreSQL checks remain valid for their tested row/endpoint scope. The confirmed
orphan behavior is still a data lifecycle gap; containment and confidentiality
require separate evidence. Do not declare dependent document intake or
finalization ready while these prerequisites are open. Production deployment,
TLS, storage ACLs, backup/restore and real customer files remain unverified.

**Exact next task:** define and implement protected purchase-order document upload
hardening in one focused tested increment: actual-byte containment and new-file
cleanup on transaction/materialization failure, preserving authorization/RLS and
existing contracts. Record unresolved private-storage/content handling decisions
before any dependent intake/finalization release. Then define the separate
read-only draft readiness contract; atomic conversion follows later.
