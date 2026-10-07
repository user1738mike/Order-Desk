# Step 4D.3: Protected draft-order creation API

## Contract

The active workspace namespace gains one JSON-only `POST` route:

`/api/v1/workspaces/<workspace-uuid>/draft-orders/`

The route creates only a manual draft header. It does not create lines, attach
catalogue items, match requests, transition status, or expose a write route for
an existing draft. The caller must be authenticated by the existing session
mechanism and be an active administrator or reviewer in the URL workspace.

Accepted fields are:

- `customer_name`: optional nonblank string, maximum 255 characters.
- `customer_reference`: optional nonblank string, maximum 128 characters.
- `original_intake_text`: optional bounded text, maximum 10,000 characters.

Unknown fields and malformed values return 400. Empty values are valid and
persist as empty strings. The response is HTTP 201 with the created header's
scalar fields and a `lines_url`; the response never embeds lines.

The URL workspace is the only tenant selector. The initiating user, organization,
status, source type, identity, and timestamps come from the authenticated and
freshly authorized tenant transaction. The endpoint is available only to active
administrators and reviewers. Viewers, inactive membership, missing workspaces,
and foreign workspaces receive the established access-denied response.

The existing read-only draft API remains unchanged. POST is the only new method
on the draft-order namespace, and no schema, dependency, RLS, or grant changes
are required.

## Implementation boundary

- Add a write service that enters `tenant_scope(..., write=True)`.
- Refresh workspace membership and authorize administrator/reviewer access before
  creating the header.
- Instantiate a `DraftOrder`, run model validation, save it, and return scalar
  materialized data while the tenant transaction is still active.
- Add a CSRF-enforced session API view with `IsAuthenticated` and
  `HasWorkspaceAccess`.
- Use the existing `DraftOrderDetailSerializer`-compatible response shape without
  loading draft lines.
- Preserve the existing read-only API routes and ordering contracts.

## Verification

Run the focused contract/API tests first, then the full repository suite and
RLS verification. Synthetic header rows remain in `test_orderdesk`; the main
database is never populated. The implementation must not claim success until
these commands complete with zero failures.
