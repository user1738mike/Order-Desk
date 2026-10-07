# ADR 0001: tenant boundary and workspace membership

## Status
Accepted

## Context
The product is multi-tenant by distributor workspace. Staff members can belong to multiple organizations and must only access the workspace they are authorized for.

## Decision
- Use a single shared database with explicit organization membership checks.
- Keep global identity separate from workspace identity.
- Enforce workspace membership in application logic and install database boundary checks for business tables.

## Consequences
- Simple deployment footprint.
- Clear access model for later order and catalogue features.
- Every new business table must respect the organization scope.
