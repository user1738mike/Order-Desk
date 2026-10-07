# Step 4D.1: Draft order domain

A draft order is a workspace-owned record of an incoming manual request. It may
be empty while intake is in progress. It does not imply a confirmed purchase,
price, reservation, or fulfilment commitment.

## Header and lines

The header owns the organization, initiating user, draft-only status, manual
source, optional customer label and reference, bounded original intake text,
and timestamps. A line owns a positive position, optional requested SKU and
description, optional decimal quantity and unit, optional catalogue reference,
catalogue SKU and description snapshots, and timestamps.

An unresolved quantity is NULL. An unmatched line has no catalogue reference.
These are valid draft states. Original request text and requested line fields
must remain distinct from catalogue snapshots; attachment never rewrites what
the customer requested.

## Access and invariants

Active administrators, reviewers, and viewers of the active workspace may read
drafts. Only active administrators and reviewers may create or update drafts.
The initiating user and organization come from the authenticated, protected
tenant transaction. Future write services must take the organization lock,
refresh membership, then access order and line rows in that order.

PostgreSQL enforces draft/manual state, positive unique line positions per
order, positive finite quantity at most 999999999.999 when present, nonblank
line identification, required nonblank SKU snapshot for catalogue-linked
lines, and matching organization across line, parent, and catalogue item.
Forced RLS limits reads and writes to the active tenant context and role;
restricted runtime grants protect immutable identity, ownership, creator,
and creation time. Runtime DELETE is unavailable.

Snapshots preserve catalogue identity at attachment time. Later catalogue
updates or deactivation do not alter them or hide historical lines. A future
attachment service must check current catalogue eligibility within its write
transaction; a foreign key cannot enforce an item's changing active state.

Future states and transitions, line reassignment, matching, pricing, inventory,
external actions, and APIs require separately reviewed increments.
