"""Run-owned local deployment; credentials never enter command arguments/logs."""

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "backend" / "var"


def command(arguments):
    subprocess.run(arguments, cwd=ROOT, check=True)  # noqa: S603


def initialize():
    run = PRIVATE / f"deployment-{uuid4().hex}"
    # Windows inherits the checkout owner's ACL, as scripts/init_env.py does.
    # Python 3.14 mode=700 would bind the directory to a sandbox helper identity.
    run.mkdir(parents=True, mode=0o700 if os.name != "nt" else 0o777)
    with (run / "run.env").open("x", encoding="ascii", newline="\n") as stream:
        stream.write(f"DEPLOYMENT_ID={run.name}\n")
        for key in (
            "POSTGRES_PASSWORD",
            "DATABASE_APP_PASSWORD",
            "DATABASE_MIGRATION_PASSWORD",
            "DJANGO_SECRET_KEY",
        ):
            stream.write(f"{key}={secrets.token_urlsafe(64)}\n")
    os.chmod(run / "run.env", 0o600)
    (run / "identity.json").write_text(
        json.dumps({"project": f"orderdesk-{run.name}"}), encoding="ascii"
    )
    print(run.relative_to(ROOT))
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "init",
            "build",
            "prepare",
            "up",
            "probe",
            "stop",
            "status",
            "compose",
            "browser",
            "restart-checks",
        ),
    )
    parser.add_argument("--run", type=Path)
    args, arguments = parser.parse_known_args()
    if args.action != "compose" and arguments:
        parser.error("Unexpected command arguments.")
    if args.action == "init":
        initialize()
        return
    if args.run is None:
        parser.error("Specify the run path printed by init.")
    run = args.run.resolve()
    if run.parent != PRIVATE.resolve() or not run.name.startswith("deployment-"):
        parser.error("The run must be inside this checkout's ignored backend/var.")
    identity = json.loads((run / "identity.json").read_text(encoding="ascii"))
    if identity != {"project": f"orderdesk-{run.name}"}:
        parser.error("Unexpected deployment identity.")
    prefix = [
        "docker",
        "compose",
        "--project-name",
        identity["project"],
        "--env-file",
        str(run / "run.env"),
        "-f",
        "compose.production-local.yaml",
    ]
    command([*prefix, "config", "--quiet"])
    if args.action == "build":
        command([*prefix, "build", "api", "proxy", "initialize"])
    elif args.action == "prepare":
        marker = run / "prepared"
        if marker.exists():
            parser.error(
                "Already prepared. Use explicit manage migrate for upgrades; "
                "do not reset grants."
            )
        command([*prefix, "up", "-d", "--wait", "--wait-timeout", "120", "db"])
        bootstrap_marker = run / "bootstrapped"
        if not bootstrap_marker.exists():
            command([*prefix, "run", "--rm", "dbsetup"])
            bootstrap_marker.touch()
        for database in ("orderdesk", "test_orderdesk"):
            command(
                [
                    *prefix,
                    "run",
                    "--rm",
                    "-e",
                    f"DATABASE_NAME={database}",
                    "manage",
                    "python",
                    "manage.py",
                    "migrate",
                    "--plan",
                ]
            )
            command(
                [
                    *prefix,
                    "run",
                    "--rm",
                    "-e",
                    f"DATABASE_NAME={database}",
                    "manage",
                    "python",
                    "manage.py",
                    "migrate",
                    "--noinput",
                ]
            )
        marker.touch()
    elif args.action == "up":
        if not (run / "prepared").exists():
            parser.error("Run prepare before application startup.")
        command(
            [*prefix, "up", "-d", "--wait", "--wait-timeout", "120", "api", "proxy"]
        )
    elif args.action == "probe":
        command([*prefix, "run", "--rm", "client"])
    elif args.action == "stop":
        command([*prefix, "stop"])
    elif args.action == "status":
        command([*prefix, "ps"])
    elif args.action == "browser":
        from deployment_browser import run_browser

        run_browser(prefix, run)
    elif args.action == "restart-checks":
        from deployment_restart import run_restart_checks

        run_restart_checks(prefix, run)
    else:
        arguments = arguments[1:] if arguments[:1] == ["--"] else arguments
        # Do not provide an accidental secret-expanding diagnostic shortcut.
        if not arguments or arguments[0] not in {
            "run",
            "exec",
            "restart",
            "stop",
            "start",
            "up",
            "ps",
            "images",
            "logs",
        }:
            parser.error("Use a documented run/exec/restart/status operation.")
        command([*prefix, *arguments])


if __name__ == "__main__":
    main()
