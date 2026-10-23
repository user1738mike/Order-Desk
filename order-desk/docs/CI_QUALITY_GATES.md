# Reproducible local quality gates, $0 service budget

Run `python scripts/quality_gates.py` (PowerShell:
`..\.venv\Scripts\python.exe scripts/quality_gates.py`). It creates a fresh,
run-owned ignored environment/project, builds frozen serving/quality images,
checks Ruff/format/lock/migration/deployment settings, full native PostgreSQL
tests, both directly authenticated runtime-role verifiers, native JS tests,
validated TLS probes and real isolated Chromium workflow. Required failures stop
the sequence; no SQLite/mocks/owner substitution or silent browser skip. The
dedicated test_orderdesk database belongs to this project's independent Postgres
instance; suites run sequentially before synthetic browser fixtures are created.
Finally it stops only this project; volumes are retained for failure diagnosis.
To resume a prepared run before browser fixtures exist, supply
`--run backend/var/deployment-<UUID>`. Existing identity is checked; bootstrap is
not repeated. Once browser fixtures exist, a full gate run requires a fresh run
so native test flushes cannot erase the acceptance evidence.

For concurrent local installations, use `python scripts/quality_gates.py --unpublished`.
This creates a fresh identity with `compose.unpublished.yaml`, resets proxy host
port publications and allocates three disjoint run-owned /28 benchmark networks
inside 198.18.0.0/15. Internal TLS, CSRF, production settings and browser checks
still apply. Docker rejects overlapping allocations; select a fresh run if one
collides. No existing network, daemon address pool or running project is changed.
The mode is recorded at initialization; `--run` cannot change it. Recovery targets
inherit the source mode. Performance/recovery helpers use the same recorded overlay.
This mode verifies internal serving, not external host-port reachability.

In the default published mode, the runner checks loopback ports 8080 and 8443 and refuses a collision before
creating a run or starting builds/tests. Identify the existing owner; stop only
an authorized synthetic proxy. The runner never stops another installation to
claim its ports. A free-port preflight is a snapshot; a later competing listener
can still make serving fail and must remain a failed gate.

Repeated retained projects can exhaust Docker's default network address pools.
After reviewing an old synthetic run, use `scripts/local_deploy.py retire --run
backend/var/deployment-<UUID>`. This explicit operator action verifies the run's
identity and refuses any running project container, saves service logs privately,
then executes Compose down without volume/image deletion. Data, certificates,
backups, run credentials and evidence remain. Never use global network/system
prune or down --volumes to make a verification pass. A future command can recreate
the retired services/networks using the same run and retained volumes.

Docker/Linux containers, Python 3.14, network access for builds and adequate
local memory/disk are required. See LOCAL_PRODUCTION.md for manual steps and
actual source/image identities/results in PROJECT_STATE.md. Native owner-role
tests establish behavior; only the restricted verifier establishes RLS evidence.
The frontend has no TypeScript/package-build step. collectstatic hashes native
module dependencies; browser/Node tooling is separate from final serving images.
Serving Python/uv/Postgres/Nginx and Python dependencies are pinned. Acceptance
Chromium comes from signed Debian repositories; its resolved package version and
built image identity must be recorded. Browser tooling is reproducible from the
recorded image, but apt repository updates can change a fresh tooling rebuild;
do not claim a bit-identical historical browser build from mutable repositories.

No hosted workflow is activated. This uses existing local hardware, no paid
service, secrets registration or new runner registration. A GitHub hosted job
could consume a private repository allowance or incur overage; it is not a
guaranteed $0 path without confirmed billing policy. A future hosted adapter must
call these same gates, pin action identities and enforce the user's budget before
activation. A self-hosted runner must be dedicated/trusted and never run untrusted
pull-request code with secrets or a privileged Docker socket.

The named CI prompt was unavailable in Downloads when requested; this workflow
implements the explicit local quality-gate request and existing repository
conventions. Actual end-to-end gate execution must be recorded separately from
individual checks. Neither a skipped GitHub job nor an unrun script is CI proof.
Private credentials, CA keys, sources, reports and logs remain ignored. No
automatic commit/push/publication is performed by these gates.

The quality container keeps its root filesystem read-only and its network disabled.
Ruff caching is disabled; uv uses `/tmp/uv-cache` on the existing bounded tmpfs.
This lets the offline lock check acquire its temporary lock without writing to
`/root/.cache` or weakening the container filesystem boundary.
The separate `rlscheck` process uses local settings and exact localhost hosts for
its in-process HTTP clients. API/proxy services retain `orderdesk.localhost` and
the production-like HTTPS policy; verifier settings are not serving configuration.
