# ADR 0005 Coordinated synthetic recovery

Status: implemented locally; execution evidence is recorded in the dated release report.

## Context

Restart probes verify durable volumes but do not recover a lost database/file set.
The next roadmap dependency is coordinated protected backup and isolated restoration,
with a $0 budget, separate runtime/migrator roles and no main-data destructive action.

## Decision

Use a stopped-writer maintenance window, PostgreSQL custom logical dump and a bounded
private-file inventory. Encrypt the entire bound set with Debian-maintained age using
X25519; hold plaintext only in disposable private tmpfs. Separate public recipient
and private identity mounts. Preserve sealed bytes, original permission modes,
application signing secret, ownership, grants and native RLS. Create a fresh isolated
cluster/roles and restore only into an empty `test_orderdesk` schema/file volume.

Distinguish backup completion from restore completion. Verify authentication and
hashes before writes; write a restore-started marker before the database transaction.
Database/file restoration is not atomic. Interrupted targets cannot be reused and
must be preserved for investigation. Verify restored state with the actual HTTPS
session/download/extraction path and direct restricted-role tenant reads.

## Consequences

This gives reproducible local synthetic recovery evidence, not customer production
backup or off-site disaster recovery. The local operator controls the maintenance
window; a distributed fencing mechanism is not introduced. Limits, key escrow,
retention/deletion and customer production restore require their own decisions and
verification. Read [the runbook](../COORDINATED_RECOVERY.md) for commands and guardrails.
