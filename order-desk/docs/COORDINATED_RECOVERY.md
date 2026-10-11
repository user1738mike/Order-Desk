# Coordinated synthetic backup and recovery

This procedure proves recovery of the local acceptance installation. It deliberately
refuses every database except `test_orderdesk`, and does not back up or restore the
developer's main database. Production/customer backup coverage is still a release
gate. A container restart is a separate, weaker check.

Run from the application directory with Docker available:

```powershell
..\.venv\Scripts\python.exe scripts/recovery_drill.py --source backend\var\deployment-<verified-browser-run>
```

The source must have run identity, preparation, fixture, completed workflow and
secure-session evidence. The script stops its API/proxy, refuses any other running
source writer/tool, and holds that maintenance window through dump/file collection.
Only the source database may remain running. This assumes the trusted local operator
does not launch another writer during the window; it is not a distributed fence.

The one-shot recovery image uses PostgreSQL 18.6 clients, Python from signed Debian
repositories and Debian's pinned `age=1.1.1-1+b3` package. Encryption uses the standard
X25519 recipient and authenticated age payload. No custom cipher, plugins or SSH
identity are used. The helper runs as UID/GID 10001, with no capabilities, a read-only
root and bounded private tmpfs. Plaintext dump/archive exist only in an exclusive
mode-700 temporary directory and disappear with the helper. The additional byte
budget is 128 MiB and file budget 10,000; larger installations require a reviewed
capacity/profile change rather than an unchecked dump.

The encrypted manifest binds the custom-format database dump, every regular private
file's size/hash/permission mode, backup format/database and the application signing
secret required to recover sessions. Links, unsafe members, duplicate names, unlisted
payload and checksum failures are refused. Original sealed file mode 0400 is retained;
restoring it as 0600 breaks private downloads and is covered by the real HTTP drill.
Database role passwords and TLS private keys are not copied: the fresh installation
gets fresh credentials/certificates. The dump preserves database ownership, grants,
policies, functions, constraints, migrations and business rows.

Encrypted payload and sanitized completion evidence go in an ignored `backup-<UUID>`
directory. Identity material goes in a separate ignored `recovery-keys-<UUID>`
directory. The backup helper mounts only `recipient.txt`; only restore receives the
identity file. Key generation has no network or data mounts. These are separate
directories on the same machine, not off-site key custody or disaster recovery.
Windows directories inherit the checkout owner's ACL; deployment to a shared machine
requires explicit ACL review and independent secure key storage.

`INCOMPLETE` is created before collection and removed only after encrypted payload
and completion evidence exist. A partial payload never substitutes for a complete
backup. Completion metadata alone is not authenticity: age decryption and the inner
inventory must also pass. The drill tests incomplete marker, corrupted outer hash,
and ciphertext authentication even when its outer hash has been recomputed.

Restore creates a fresh run-owned PostgreSQL cluster and empty `test_orderdesk`.
It refuses populated schemas, nonempty private storage, prior restore attempts and
incomplete sets before writes. It fully decrypts/authenticates and verifies the
inventory, then marks `restore-started`, restores SQL in one transaction and copies
private bytes. `restore-complete` is written only when those steps finish. A failure
after SQL restoration can leave an incomplete target; preserve it for diagnosis and
use another empty target. There is no claim of atomicity across PostgreSQL and files.

The drill then proves the original session still authenticates, source/export bytes
match independent expected hashes, extraction results survive, and direct unfiltered
queries under `orderdesk_app` expose only the selected tenant. It checks unscoped
denial, two tenants, forced RLS and migrator ownership. A repeated restore must refuse
the nonempty schema; the existing HTTP workflow must still work afterward. All owned
services are stopped in `finally`; volumes, encrypted sets and diagnostic evidence
are retained. No automatic retention deletion or off-site scheduling is implemented.

Current results and failures belong in [the release report](RELEASE_AUDIT_2026-10-11.md)
and [project state](PROJECT_STATE.md). Protect the key and backup together operationally:
loss of the identity prevents recovery; theft of both allows decryption. An operator
must separately decide and test retention, key escrow/rotation, off-site recovery,
customer deletion obligations and a production maintenance/restore procedure.
