"""Owned restart checks; never stop/delete the developer database or volumes."""

import os
import subprocess

from local_deploy import ROOT


def run_restart_checks(prefix, run):
    compose = [*prefix, "-f", "compose.production-acceptance.yaml"]
    environment = {**os.environ, "DEPLOYMENT_RUN": str(run)}

    def execute(arguments):
        subprocess.run([*compose, *arguments], cwd=ROOT, env=environment, check=True)  # noqa: S603

    def health(ready):
        script = (
            "import sys; sys.path.insert(0,'/deployment'); from probe import request; "
            f"assert request('/api/v1/health/ready/')[0]=={ready}; "
            "assert request('/api/v1/health/live/')[0]==200; "
            "print('PASS: dependency readiness and independent liveness.')"
        )
        execute(["run", "--rm", "client", "python", "-c", script])

    execute(["run", "--rm", "client", "python", "/deployment/recovery_probe.py"])
    try:
        execute(
            [
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "import os; os.chmod('/private-documents',0o555)",
            ]
        )
        health(503)
    finally:
        execute(
            [
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "import os; os.chmod('/private-documents',0o700)",
            ]
        )
    health(200)
    try:
        execute(["stop", "db"])
        health(503)
    finally:
        execute(["up", "-d", "--wait", "--wait-timeout", "120", "db"])
    health(200)
    execute(
        [
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "120",
            "api",
            "proxy",
        ]
    )
    execute(["exec", "-T", "api", "python", "/deployment/runtime_identity.py"])
    execute(["run", "--rm", "extract", "python", "/deployment/runtime_identity.py"])
    execute(["run", "--rm", "client", "python", "/deployment/recovery_probe.py"])
    print(
        "PASS: owned DB outage/restart, required storage outage, API/proxy "
        "recreation; all volumes retained."
    )
