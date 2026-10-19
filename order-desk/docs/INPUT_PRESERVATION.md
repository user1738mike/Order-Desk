# Order line input preservation

The legacy direct order-line endpoint is
`POST /api/v1/workspaces/<workspace>/orders/<order>/lines/`. It remains subject to
the existing session, CSRF, current admin/reviewer, tenant and editable-order checks.
Its direct orders are separate from the reviewed draft-conversion export profile.

`line_number`, `sku` and positive `quantity` are required. Quantity supports up to
14 integral and four fractional digits; successful responses use exact decimal
text. Use decimal values when calling services. Missing HTTP quantities are
rejected, with no row created. Unsupported fields such as price are rejected.

An omitted `unit` remains blank/unknown, matching the existing model and draft
behavior. As of 19 October 2026 the serializer and service no longer invent `ea`.
Clients that know the unit must supply it explicitly. Supplied units retain the
existing whitespace normalization and 32-character limit; no case mapping,
catalogue unit, pack factor or price basis is inferred. Existing recorded values
are unchanged; no data migration is required.

An empty unit does not establish business readiness for an ERP. Critical-field,
customer, price, currency and pack rules still require an authoritative contract
and tested integration. Generic CSV compatibility is defined separately and does
not prove a named ERP import. Preserve leading-zero SKU strings in the client;
never parse part identifiers as numbers before sending them.

Regression evidence belongs in the dated audit: omitted units through the real
API, reload and service, explicit units, required quantity, and the trusted
restricted-runtime browser journey. Read limits and existing legacy oversize
history refusals remain documented in the prior release audit; this correction
does not introduce monthly quotas or change those read contracts.
