"""Zero-service-cost sequential gates, always on a new run-owned installation."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from deployment_browser import run_browser
from deployment_restart import run_restart_checks
from local_deploy import PRIVATE, ROOT, command, initialize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    arguments = parser.parse_args()
    run = arguments.run.resolve() if arguments.run else initialize()
    if run.parent != PRIVATE.resolve() or not run.name.startswith("deployment-"):
        parser.error("Use an initialized run in this checkout's ignored backend/var.")
    project = f"orderdesk-{run.name}"
    if json.loads((run / "identity.json").read_text(encoding="ascii")) != {
        "project": project
    }:
        parser.error("Unexpected run identity.")
    if (run / "fixture.json").exists():
        parser.error("Browser fixtures already exist; use a fresh quality-gate run.")
    prefix = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(run / "run.env"),
        "-f",
        "compose.production-local.yaml",
    ]
    helper = [sys.executable, "scripts/local_deploy.py", "--run", str(run)]
    try:
        command([*helper, "build"])
        command([*prefix, "build", "quality"])
        for arguments in (
            ["ruff", "check", "/app", "/frontend"],
            ["ruff", "format", "--check", "/app", "/frontend"],
            [
                "ruff",
                "check",
                "--config",
                "/app/pyproject.toml",
                "/scripts",
                "/deployment",
            ],
            [
                "ruff",
                "format",
                "--check",
                "--config",
                "/app/pyproject.toml",
                "/scripts",
                "/deployment",
            ],
            ["uv", "lock", "--check", "--offline"],
        ):
            command([*prefix, "run", "--rm", "quality", *arguments])
        if not (run / "prepared").exists():
            command([*helper, "prepare"])
        else:
            command([*prefix, "up", "-d", "--wait", "--wait-timeout", "120", "db"])
        command(
            [
                *prefix,
                "run",
                "--rm",
                "manage",
                "python",
                "manage.py",
                "check",
                "--deploy",
                "--fail-level",
                "WARNING",
            ]
        )
        command(
            [
                *prefix,
                "run",
                "--rm",
                "manage",
                "python",
                "manage.py",
                "makemigrations",
                "--check",
                "--dry-run",
            ]
        )
        command(
            [
                *prefix,
                "run",
                "--rm",
                "manage",
                "python",
                "manage.py",
                "test",
                "--settings=config.settings.test",
                "--keepdb",
                "--noinput",
            ]
        )
        for verifier in ("verify_order_rls", "verify_catalog_rls"):
            command(
                [*prefix, "run", "--rm", "rlscheck", "python", "manage.py", verifier]
            )
        command([*helper, "up"])
        command([*helper, "probe"])
        environment = {**os.environ, "DEPLOYMENT_RUN": str(run)}
        acceptance = [*prefix, "-f", "compose.production-acceptance.yaml"]
        subprocess.run(  # noqa: S603 -- fixed Compose command and owned identity.
            [*acceptance, "build", "browser"], cwd=ROOT, env=environment, check=True
        )
        tests = [
            f"/frontend/tests/{path.name}"
            for path in sorted((ROOT / "frontend/tests").glob("*.test.js"))
        ]
        if not tests:
            raise RuntimeError("No frontend tests found.")
        subprocess.run(  # noqa: S603 -- only committed test filenames.
            [*acceptance, "run", "--rm", "browser", "node", "--test", *tests],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        run_browser(prefix, run)
        run_restart_checks(prefix, run)
        print("PASS: required local quality gates; no paid runner/service requested.")
    finally:
        # Retain run-owned volumes/logs for diagnosis; stop only this project.
        subprocess.run([*prefix, "stop"], cwd=ROOT, check=False)  # noqa: S603


if __name__ == "__main__":
    main()
