"""Measure the already verified synthetic deployment, then stop only that run."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from threading import Event, Thread

from local_deploy import ROOT
from recovery_drill import owned_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--large-fixture", action="store_true")
    args = parser.parse_args()
    run, project = owned_run(args.run)
    if not (run / "session.json").exists():
        parser.error("Complete real browser acceptance first.")
    environment = {**os.environ, "DEPLOYMENT_RUN": str(run)}
    prefix = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(run / "run.env"),
        "-f",
        "compose.production-local.yaml",
        "-f",
        "compose.production-acceptance.yaml",
    ]

    def execute(args, **kwargs):
        return subprocess.run(  # noqa: S603 -- fixed operations, owned project.
            [*prefix, *args], cwd=ROOT, env=environment, check=True, **kwargs
        )

    try:
        execute(["up", "-d", "--wait", "--wait-timeout", "120", "api", "proxy"])
        if args.large_fixture and not (run / "performance-fixture.json").exists():
            execute(
                [
                    "run",
                    "--rm",
                    "fixtures",
                    "python",
                    "manage.py",
                    "shell",
                    "-c",
                    "exec(open('/checks/performance_fixtures.py').read())",
                ]
            )
        ids = execute(
            ["ps", "--quiet", "api", "proxy", "db"], capture_output=True, text=True
        ).stdout.splitlines()
        done = Event()
        snapshots = []

        def sample():
            while not done.is_set():
                output = subprocess.run(  # noqa: S603 -- owned container IDs.
                    ["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],  # noqa: S607
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=True,
                )
                snapshots.extend(
                    json.loads(line) for line in output.stdout.splitlines()
                )
                done.wait(1)

        sampling = Thread(target=sample, daemon=True)
        sampling.start()
        failures = []
        for service, script in (
            ("client", "performance.py"),
            ("extract", "query_budget.py"),
        ):
            result = subprocess.run(  # noqa: S603 -- fixed checks, owned project.
                [
                    *prefix,
                    "run",
                    "--rm",
                    "-v",
                    f"{ROOT / 'deployment'}:/checks:ro",
                    "-v",
                    f"{run}:/run-state:ro",
                    "-e",
                    "PYTHONPATH=/checks:/app",
                    service,
                    "python",
                    f"/checks/{script}",
                ],
                cwd=ROOT,
                env=environment,
                check=False,
            )
            if result.returncode:
                failures.append(script)
        done.set()
        sampling.join(timeout=16)
        (run / "resource-samples.json").write_text(
            json.dumps(snapshots), encoding="ascii"
        )
        print(f"Resource snapshots recorded: {len(snapshots)}")
        if failures:
            raise RuntimeError(f"Performance checks failed: {', '.join(failures)}")
    finally:
        if "done" in locals():
            done.set()
            sampling.join(timeout=16)
        subprocess.run([*prefix, "stop"], cwd=ROOT, env=environment, check=False)  # noqa: S603


if __name__ == "__main__":
    main()
