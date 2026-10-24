"""Verify incoming sources and receipts through the existing isolated restore drill."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from local_deploy import ROOT, compose_prefix
from recovery_drill import owned_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--customer", action="store_true")
    arguments = parser.parse_args()
    source, project = owned_run(arguments.source)
    for name in ("fixture.json", "workflow.json", "session.json", "prepared"):
        if not (source / name).is_file():
            parser.error("Use a completed isolated synthetic acceptance run.")
    prefix = compose_prefix(source, project)
    acceptance = [*prefix, "-f", "compose.production-acceptance.yaml"]
    environment = {**os.environ, "DEPLOYMENT_RUN": str(source)}

    def execute(command):
        subprocess.run(command, cwd=ROOT, env=environment, check=True)  # noqa: S603

    mounts = ["-v", f"{ROOT / 'deployment'}:/checks:ro", "-v", f"{source}:/run-state"]
    try:
        execute(
            [*acceptance, "up", "-d", "--wait", "--wait-timeout", "120", "api", "proxy"]
        )
        # Repeating the seed verifies its receipts instead of creating a second
        # source/draft/application after an interrupted fixture command.
        seeders = ["incoming_recovery.py"]
        if arguments.customer:
            seeders.append("customer_recovery.py")
        for seeder in seeders:
            for _ in range(2):
                execute(
                    [
                        *acceptance,
                        "run",
                        "--rm",
                        *mounts,
                        "extract",
                        "python",
                        "/checks/" + seeder,
                    ]
                )
        execute(
            [
                *acceptance,
                "run",
                "--rm",
                *mounts,
                "client",
                "python",
                "/checks/recovery_probe.py",
            ]
        )
        execute([sys.executable, "scripts/recovery_drill.py", "--source", str(source)])
    finally:
        subprocess.run([*prefix, "stop"], cwd=ROOT, env=environment, check=False)  # noqa: S603


if __name__ == "__main__":
    main()
