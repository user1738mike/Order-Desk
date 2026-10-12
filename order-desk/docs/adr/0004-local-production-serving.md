# ADR 0004: isolated local production serving

Accepted for local synthetic use, 2026-10-10. External launch is not authorized.

Use a separate, explicitly named Compose project. PostgreSQL 18.6, the existing
migrator/bootstrap and restricted orderdesk_app identities remain authoritative.
Run bootstrap and migrations as operator one-shot steps, never in API startup.
Do not run bootstrap again on an installed schema: it resets broad grants before
migrations restore the boundary. Existing development Compose is unchanged.

Gunicorn 26.2.0 (MIT, Python >=3.12) serves synchronous Django WSGI; the app has
no asynchronous requirement. Nginx stable serves collectstatic output and proxies
the native frontend shell and API. There is no frontend package/build tool.
Manifest hashing is the production asset build. Official sources:
[Gunicorn installation](https://gunicorn.org/install/),
[release/package](https://pypi.org/project/gunicorn/26.2.0/),
[Nginx BSD license/releases](https://nginx.org/),
[forwarding](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[PostgreSQL TLS](https://www.postgresql.org/docs/18/ssl-tcp.html).

Only Nginx publishes 127.0.0.1:8443 (TLS) and 127.0.0.1:8080 (fixed redirect).
Separate internal proxy/app and app/database networks prevent the database from
being reachable by the proxy. The API and worker publish no ports. Proxy rejects
unknown Host, replaces forwarding headers and supplies a fixed canonical Host.
The API trusts forwarded HTTPS only in this topology. /static is public;
/media, /private-documents, /intake and /exports are denied. Unknown API routes
reach Django and never fall back to a shell. API/shell responses are no-store.

The locally generated CA and keys live in private named volumes. API/worker get
only the public CA; DB/proxy each get only their own key/certificate. DB TLS uses
verify-full with SAN db. HTTPS uses orderdesk.localhost. Isolated clients trust
the CA explicitly; no host root installation or certificate bypass. Host trust
is a separate operator choice. Local HSTS is 60 seconds, exact hostname only,
without includeSubDomains/preload. Public production keeps its existing policy.

API/worker UID 10001, proxy UID 101, read-only root filesystems, dropped
capabilities and no-new-privileges; bounded tmpfs and private UID-10001 volume.
One-shot certificate/storage initialization is privileged only to set ownership.
On the measured 8-CPU/8-GiB Docker host start with two sync API workers, 512 MiB,
one CPU, 30-second request / 15-second graceful deadline. Extraction runs as an
explicit tenant/actor/job worker, one job per command, 512 MiB, one CPU; existing
parser OS bounds remain. No privileged global queue discovery or speculative daemon.

Database, private files and certificates persist across recreation. Stop does not
remove volumes. Rollback an image only if compatible with applied schema; never
infer migration rollback from image rollback. Preserve source and lease state,
restart an explicit authorized job after expiry under its existing attempt bound.
Coordinated backups/restore, public certificates/DNS, real host trust, monitoring,
capacity measurement, malware controls and external hosting remain separate work.

Required verification is recorded in LOCAL_PRODUCTION.md and PROJECT_STATE.md.

12 October measured local update: four synchronous workers/four API CPUs with
the same 512 MiB and protections. The unchanged eight-client synthetic workload
failed its provisional p95 target with two workers; final p95 212.235ms passed.
See VALIDATION_2026-10-12.md for query remediation, prior failures and actual
four-worker browser/restart/role/TLS proof. This is not a production capacity SLO.
An image build, health probe or owner test alone is insufficient evidence.
