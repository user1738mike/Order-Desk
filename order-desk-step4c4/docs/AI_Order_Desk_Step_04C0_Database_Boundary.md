# Step 4C.0: Define the database boundary

This increment adds a design record only. The transaction helper is implemented next, then the first protected table and its policies.

## 1. Database context

Each tenant operation will supply two values derived from authenticated, server-validated context:

| PostgreSQL setting | Value |
| --- | --- |
| orderdesk.organization_id | Authorized workspace UUID |
| orderdesk.user_id | Authenticated user UUID |

The helper will open an outer transaction, recheck membership, and set both values using parameterized set_config(..., true). Transaction-local settings revert on commit or rollback.

Its contract will require:

- A clean connection with no existing tenant context or outer transaction.
- Read-only transactions for reads.
- Organization locking before write authorization.
- Fresh membership and role checks.
- Query results fully materialized before leaving the transaction.

Roles remain in membership records; they are not cached in PostgreSQL settings.

## 2. First protected table: CatalogItem

This supports catalogue matching while giving a straightforward isolation boundary.

Initial fields:

- id
- organization_id
- sku
- description
- is_active
- created_at
- updated_at

SKU uniqueness is within an organization: (organization_id, sku). Two distributors can therefore use the same stock code.

| Action | Viewer | Reviewer | Admin |
| --- | --- | --- | --- |
| Read catalogue | Yes | Yes | Yes |
| Create/update/deactivate items | No | No | Yes |
| Physically delete items | No | No | No |

Units, pack conversions, aliases, and customer pricing will follow when catalogue imports are designed against actual customer data.

## 3. RLS policy design

Row-level security is enabled and forced on the catalogue table.

A mandatory restrictive policy requires matching organization context and an active user, membership, and organization. Separate command policies allow reads and administrator writes. PostgreSQL combines restrictive policies with applicable permissive policies using AND.

Both existing rows and proposed inserted/updated rows are checked, preventing an item from being reassigned across workspaces.

The migration role has an explicit maintenance exception. Isolation tests must connect as orderdesk_app, because owner-level tests cannot prove runtime isolation.

Login, sessions, workspace discovery, and their existing control tables retain their current application checks.

## 4. Verification gate

Before exposing catalogue APIs, PostgreSQL tests must prove:

- Missing context exposes no items.
- An unfiltered query under A returns only A's items.
- Cross-workspace reads and writes fail.
- Viewers and reviewers cannot modify catalogue items.
- Revocation and demotion affect subsequent authorized operations.
- Commit, rollback, and connection reuse retain no previous tenant context.
- Runtime DELETE, TRUNCATE, and owner-role switching are denied.

These tests are planned; no new database tests or policies were applied in this increment.