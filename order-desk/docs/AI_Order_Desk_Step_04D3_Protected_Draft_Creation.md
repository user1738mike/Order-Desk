# Step 4D.3: Protected draft-order creation API

## Contract

The active workspace namespace gains one JSON-only `POST` route:

`/api/v1/workspaces/<workspace-uuid>/draft-orders/`

The route creates only a manual draft header. It does not create lines, attach
catalogue items, match requests, transition status, or expose a write route for
an existing draft. The caller must be authenticated by the existing session
mechanism and be an active administrator or reviewer in the URL workspace.

Accepted fields are:

- `customer_name`: optional string, empty or containing a non-whitespace
  character, maximum 255 characters.
- `customer_reference`: optional string, empty or containing a non-whitespace
  character, maximum 128 characters.
- `original_intake_text`: optional bounded text, maximum 10,000 characters.

Unknown fields and malformed values return 400. Empty values are valid and
persist as empty strings. The response is HTTP 201 with the created header's
scalar fields and a `lines_url`; the response never embeds lines.

Whitespace-only customer names/references return field-keyed 400 errors;
omitted or explicitly empty values remain empty strings. Django model
validation errors are translated at the API boundary after the service scope
rolls back. Field errors retain their field keys; constraint (`__all__`) and
unkeyed errors become `non_field_errors`, with a list of messages per key.

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

### Creation validation and authorization repair

The original foreign-workspace fixture used `create_organization` with the
requesting user as its actor. That service creates an active admin membership,
so its expected 403 was incorrect; the assertion failed before the inactive
membership branch ran. The fixture now has a different owner. Both 403
assertions are retained, with independent revocation/removal/nonmember tests.
Production membership/account/workspace checks were already fresh and active;
the regressions also revoke membership between request permission resolution
and entry into the tenant transaction. Catalogue and purchase-order routes
use that same boundary and deny access in these checks.

The serializer and API exception translation were repaired for whitespace
customer values and Django validation failures. Native tests verify no save
on invalid fields/model validation and rollback of a saved draft if subsequent
materialization raises a Django validation error. Runtime-role tests verify
creation and revocation with forced RLS. A historical read test now verifies
the newly supported list POST while keeping detail/lines read-only.

Verification on 2026-10-07:

| Gate | Result |
| --- | --- |
| Creation/read focused tests | 24 passed in 7.468s. |
| Full orders, organizations, catalogue suites | 520 passed in 101.970s; no skips. |
| Restricted-role order/RLS verifier | 34 passed in 18.543s; no skips. |
| Ruff lint/format | Passed; 138 backend files formatted. |
| Model drift and Git whitespace | Passed; no migration changes. |

```powershell
docker compose run --rm manage python manage.py test apps.orders.tests.test_draft_creation_api apps.orders.tests.test_read_api --settings=config.settings.test --keepdb --noinput
docker compose run --rm manage python manage.py test apps.orders apps.organizations apps.catalog --settings=config.settings.test --keepdb --noinput
docker compose run --rm rlscheck python manage.py verify_order_rls
```

Known unchanged error precedence: active viewers with invalid creation input
can receive 400 before the protected service checks write permission. Valid
viewer input is denied with 403, and inactive/nonmember requests are denied
before serializer validation. This repair does not change that ordering.
