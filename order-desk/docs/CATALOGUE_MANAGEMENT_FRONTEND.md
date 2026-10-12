# Administrator catalogue creation and import

12 October 2026. The distributor validation request adds browser management to
the existing protected catalogue APIs. The original read-only frontend contract
remains historical; no backend role, normalization or import behavior changes.

An active administrator opens Manage catalogue to create an active item with
exact SKU/description strings, or choose a nonempty CSV <=1 MiB/1,000 rows with
sku,description,is_active headers. The server trims only existing outer whitespace
rules and preserves case, punctuation and leading zeros. Existing identifiers are
never renamed or overwritten. Reviewers/viewers retain browsing only.

Validation is read-only and renders bounded row errors and the first 25 ready
rows. Choosing another file discards validation. Explicit confirmation executes
all rows through the existing atomic create-only import, which rechecks current
catalogue state. The browser retains one UUID Idempotency-Key with the same File
in memory until the server confirms the receipt. Duplicate clicks are disabled.
An unconfirmed response disables replacement/writes; explicit reconciliation
repeats the identical request. No automatic POST retry occurs.

Creation has no receipt API. An unconfirmed creation requires a read-only exact
SKU lookup and operator comparison before another deliberate submission. A found
item is not proof that this request created it; the UI reports observed state.
SKU uniqueness prevents another item with the same normalized exact SKU.

Workspace/role/session generation replacement aborts requests, clears reports,
files and form inputs, and rejects late responses. Logout remains available even
with an uncertain catalogue outcome. Reload/logout lose the in-memory import key;
inspect the current catalogue before reselecting a file. A fresh import of existing
SKUs is rejected by the server instead of silently duplicating products.

The new module uses textContent for values/errors and has no browser persistence,
remote dependency, new database table or authority from hidden buttons. API CSRF,
fresh permission checks, tenant transactions, RLS and immutable receipts remain
the authorization and repeat-safety boundary. Native JS regressions and the trusted
isolated browser proof are recorded in PROJECT_STATE and the dated validation.
