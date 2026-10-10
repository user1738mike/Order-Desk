# Exact catalogue suggestions: exact-sku-v1

This read-only assessment uses current draft-line requested SKU, never an
unreviewed extraction proposal. It supports no customer aliases: no verified
customer/approved-alias model exists in this checkout.

| Rule/state | Meaning |
| --- | --- |
| exact | One active item has exactly equal SKU after outer whitespace trim. |
| already_attached | That active exact item is already attached with current snapshots. |
| inactive | The exact same-workspace identity exists but is inactive. |
| no_match | No equal SKU exists in this workspace. |
| empty_sku | There is no nonblank requested SKU to assess. |
| unsupported_sku | Requested SKU exceeds the 4096-character assessment bound. |
| ambiguous | More than one equal eligible identity exists; never choose the first. The current unique organization/SKU constraint prevents this normally. |

Case, punctuation, leading zeros and Unicode codepoints remain significant.
Outer whitespace follows Python Unicode `str.strip`, including NEL and the
separator controls; BOM is retained as part of the identity. The browser validates
the same rule rather than using JavaScript's different `trim` character set.
The 4096-character bounds count Unicode codepoints, including astral characters.
Substring/casefold/fuzzy matching, pack conversion and inferred customer data
are unsupported. Unit/pricing data is not modeled in catalogue items and is
explicitly unchecked; quantity is not assessed. Existing readiness policy still
checks actual lines/quantity/catalogue attachments and active states.

`GET /api/v1/workspaces/<workspace>/draft-orders/<draft>/suggestions/?page=1`
returns 50 stable position/UUID-ordered lines, aggregate draft revision,
`rule_version`, and each line's source code, normalized code, state, candidate
identity/SKU/description/active state/revision and attachment condition. Candidate
descriptions/source codes are limited to 4096 characters with truncation flags.
Attached lines whose source or catalogue snapshot changed are explicitly marked;
an old attachment is not fresh match evidence. Unknown/repeated parameters fail
400, invalid pagination fails under existing conventions and foreign/malformed
identities return 404. All active members may inspect; assessments make no writes.
One bounded catalogue query serves the page. Existing organization/SKU unique
index is sufficient; no new schema/index/cache is added.

`POST .../lines/<line>/accept-suggestion/` requires quoted `If-Match` and:

```json
{
  "catalogue_item_id": "<candidate UUID>",
  "rule_version": "exact-sku-v1",
  "source_sku": "<assessed normalized SKU>",
  "catalogue_revision": "<64-character catalogue digest>"
}
```

It reuses the protected attachment service: fresh active admin/reviewer access,
organization-first write lock, editable draft and aggregate revision, scoped
line, current exact source code and current active catalogue record/revision.
Cooperating catalogue/membership writers take the same organization lock.
Source/catalogue dependency mismatch is 409, stale draft 412 and unauthorized
write 403. A successful response is the existing scalar line shape. Only catalogue
identity/SKU/description snapshots change; requested values, quantities and units
remain intact. Explicit manual picker and detach/reattach remain available.

Repeat with the original pre-edit revision returns 412 after a successful
attachment. Reconcile through fresh GET, without silently replacing the revision.
A current-revision repeat against the identical current attachment is a no-op
200; no lines/events/timestamps are duplicated. A changed existing attachment
must be deliberately detached rather than silently overwritten. This narrowly
reuses attachment snapshots and does not claim a general historical audit trail.

Read scopes remain read-only and lock-free; a draft revision checked before and
after assessment detects cooperating draft edits during loading. Catalogue
evidence can change after the response; acceptance revalidates its digest. The
browser scopes responses by session/workspace/draft/revision/page, aborts obsolete
loads, renders text safely and requires explicit acceptance. On an unconfirmed
write it blocks further acceptance until a deliberate reload confirms actual
server state. It never approves or converts the draft.

Actual PostgreSQL, restricted runtime, concurrency, native frontend and Chromium
verification is recorded in PROJECT_STATE.md. Aliases, generalized extraction,
fuzzy/LLM matching, pricing, pack/unit rules and ERP export remain separate work.
