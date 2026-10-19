# Local production-like serving

This separate local topology serves the existing native frontend through a
collectstatic manifest, Gunicorn and an HTTPS Nginx proxy. It is for synthetic
local data; it does not establish readiness for public hosting. See
[ADR 0004](adr/0004-local-production-serving.md).

Prerequisites: Docker Desktop running Linux containers/Compose v2; the pinned
Python 3.14 interpreter (the existing `../.venv/Scripts/python.exe` is suitable);
outbound image/package access during build, no access needed at application
startup. No ignored audit record or authenticated browser is required. Preserve
the ordinary `.env`, `compose.yaml` project and its volumes.

From the application directory in PowerShell:

```powershell
$Python = '..\.venv\Scripts\python.exe'
$DeploymentRun = & $Python scripts/local_deploy.py init
& $Python scripts/local_deploy.py build --run $DeploymentRun
& $Python scripts/local_deploy.py prepare --run $DeploymentRun
& $Python scripts/local_deploy.py up --run $DeploymentRun
& $Python scripts/local_deploy.py probe --run $DeploymentRun
& $Python scripts/local_deploy.py status --run $DeploymentRun
```

`init` generates new credentials under ignored backend/var/deployment-UUID and
never overwrites the developer environment or prints credentials. On Windows
the directory inherits the checkout's ACL; keep it in your private user profile.
On Linux directory/file modes are 0700/0600. Preserve the run directory to
address the same project; do not create a new one to resume existing data.
`prepare` creates only this run's volumes, local CA/storage, controlled roles,
and both orderdesk/test_orderdesk schemas; migration plans are printed before
application. Its bootstrap marker prevents regranting privileges on a retry.
An already prepared run refuses bootstrap. Migrations are one-shot, not API
replica startup. API/worker get only runtime credentials and public CA.

Only the proxy binds 127.0.0.1:8443 and 127.0.0.1:8080. The canonical origin is
`https://orderdesk.localhost:8443`; use that exact hostname for sessions/CSRF.
The proxy alone joins a separate `browser_edge` bridge so Docker Desktop can
publish those ports. API and database networks remain internal; the proxy has
outbound connectivity through that bridge. Check actual `docker port` output,
not just container health, when diagnosing host-browser connection failures.
The port numbers/origin are intentionally fixed. Stop another run first if these
ports are occupied. HTTP redirects to the fixed HTTPS origin. DB uses verify-full
against its own SAN db; proxy and DB have separate private keys. Certificates
expire after 14 days; initialization refuses an expired/incomplete issuer state.
Do not delete or regenerate certificate volumes as an ordinary restart. Rotation
of an existing run's issuer is a separate reviewed operational step.

The probe validates CA/hostname through a disposable client, rejects default
public trust, and checks forwarding/Host, cookies, CSRF, redirects, body bounds,
manifest assets and denied private paths. It does not install a host root. A host
browser will initially distrust this certificate. Host certificate trust is a
separate explicit operator action; never disable verification or use `curl -k`.
Use the isolated acceptance client for reproducible browser verification.

After native/runtime checks (sequential on test_orderdesk), run the actual browser
and recovery checks:

```powershell
& $Python scripts/local_deploy.py browser --run $DeploymentRun
& $Python scripts/local_deploy.py restart-checks --run $DeploymentRun
```

This explicit acceptance overlay switches API/worker to this isolated instance's
test_orderdesk. It provisions synthetic accounts only there, starts a disposable
Chromium with an isolated NSS trust store, and hands authorized actor/workspace/job
UUIDs to a separate runtime worker. No Docker socket is mounted in the browser.
The browser container alone disables its Chromium process sandbox; it is confined
to the application network with no DB credentials, dropped capabilities,
no-new-privileges/read-only root and bounded writable tmpfs. This does not disable
TLS validation or the application's separate PDF child sandbox. Resolved Chromium
packages/image identity are recorded; apt tooling rebuilds are not bit-identical.
The controlled CSV interruption exits the actual process at the parser entry after
a durable claim, using a short acceptance lease. All DB guards stay enabled;
normal commands retain 120 seconds. Explicit new worker execution must recover
the same job at attempt two, with no duplicate proposal. Restart checks preserve
private bytes/digests and a synthetic secure session, deliberately remove required
storage access and stop only this run's DB, test readiness 503 with live 200, then
restore/recreate and recheck actual runtime identities. Fixtures/session tokens
remain ignored. Do not run native flushes against that evidence afterward.
Run `up` without the acceptance overlay to return to the main isolated orderdesk
schema. It is intentionally not seeded with test accounts. Account/workspace
provisioning for ordinary use remains an explicit local operator step.

The API uses four synchronous workers, 30-second request timeout and 15-second
graceful timeout; 512 MiB/four CPUs, UID 10001, read-only root, bounded private tmpfs.
This local allocation is measured against the provisional eight-client workload;
it is not a customer capacity promise. Results and earlier failures are in the
12 October validation report.
Nginx UID 101 has no private document mount. Private data is UID-10001-only and
outside public paths. Proxy replaces forwarding headers and supplies fixed Host;
do not publish an application port or enable proxy trust in another topology.
CSP disallows inline scripts/eval; shell/API/file responses are private/no-store.
Hashed asset filenames are built into both immutable images; original asset
names have short public caching. Local HSTS lasts 60 seconds on this hostname,
without sibling/preload policy; public production retains its existing policy.
The local module explicitly acknowledges deployment checks security.W005
(includeSubDomains) and security.W021 (preload): sibling hostnames and public
preload are outside this exact local-host policy. These two checks alone are
silenced locally and documented; every other deployment warning fails startup.
The public production module remains unsilenced.

Operate an explicit authorized extraction job; there is no privileged global
scan or unattended worker added by deployment:

```powershell
& $Python scripts/local_deploy.py compose --run $DeploymentRun -- run --rm extract python manage.py check_runtime_role
& $Python scripts/local_deploy.py compose --run $DeploymentRun -- run --rm extract python manage.py process_document_extraction --workspace <workspace-uuid> --actor <active-user-uuid> --job <job-uuid>
& $Python scripts/local_deploy.py compose --run $DeploymentRun -- run --rm manage python manage.py check --deploy --fail-level WARNING
& $Python scripts/local_deploy.py compose --run $DeploymentRun -- run --rm rlscheck python manage.py verify_order_rls
& $Python scripts/local_deploy.py compose --run $DeploymentRun -- run --rm rlscheck python manage.py verify_catalog_rls
```

RLS helpers connect directly as orderdesk_app to **test_orderdesk** with separate
audited migrator fixtures. Never treat native owner-role tests as isolation proof.
Run native/runtime/browser suites sequentially against that database. Do not run
fixture tools on orderdesk. Runtime jobs keep existing lease/retry/parser bounds.

```powershell
& $Python scripts/local_deploy.py compose --run $DeploymentRun -- restart api proxy
& $Python scripts/local_deploy.py probe --run $DeploymentRun
& $Python scripts/local_deploy.py compose --run $DeploymentRun -- logs --tail 50 api proxy
& $Python scripts/local_deploy.py stop --run $DeploymentRun
```

Stop/restart/recreate preserve named database/private/certificate volumes. No
volume-deletion shortcut is provided. Logs contain safe process/job identifiers
and proxy request IDs/status/timing, without query strings/bodies/cookies. Do not
print expanded Compose config, environment files or inspect environment secrets.
For upgrades, build the reviewed compatible candidate, explicitly run manage
migrate --plan then migrate before recreating API/proxy; never rerun bootstrap.

Production and local-production Django HTTP error logs use structured JSON with
UTC time, severity, response status, HTTP method, registered route name, exception
type and a validated proxy request ID. Raw exception messages/traceback text,
request bodies, cookies, query strings and arbitrary headers are omitted. Correlate
the request ID with the proxy's safe status/latency log and the operator-visible
failure. This retains failure visibility without copying database row details into
central logs. It does not supply alert ownership or a general business audit trail.
Development-only traceback logging is for the documented synthetic environment.
Returning to an older image does not reverse schema changes. Preserve existing
data and only use a schema-compatible image. Coordinated backup/restore and
durable external storage recovery remain the next separate operational task.

Verification results, including blockers, are in PROJECT_STATE.md. A healthy
container or one HTTPS page alone does not prove the full workflow. External
DNS/certificate issuance, host trust, capacity, alerting, coordinated backup,
malware scanning and launch obligations are unverified. Local $0 execution does
not promise free public production capacity. Pending export UI/runtime gates
and CI work must be recorded separately from this deployment increment.
