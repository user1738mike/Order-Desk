"""Host orchestrator: isolated CA-trusted browser and explicit scoped worker."""

import json
import os
import subprocess
import time
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]


def prepare_browser_services(execute, run):
    # Standalone retry follows a runner that stops its project in finally.
    # Fixture containers do not implicitly start db; require it healthy first.
    execute(["up", "-d", "--wait", "--wait-timeout", "120", "db"])
    if not (run / "fixture.json").exists():
        execute(["run", "--rm", "fixtures"])
    execute(["up", "-d", "--wait", "--wait-timeout", "120", "api", "proxy"])


def run_browser(prefix, run):
    environment = {**os.environ, "DEPLOYMENT_RUN": str(run)}
    compose = [*prefix, "-f", "compose.production-acceptance.yaml"]

    def execute(arguments):
        subprocess.run([*compose, *arguments], cwd=ROOT, env=environment, check=True)  # noqa: S603

    execute(["build", "browser"])
    prepare_browser_services(execute, run)
    fixture = json.loads((run / "fixture.json").read_text(encoding="utf-8"))
    process = subprocess.Popen(  # noqa: S603 -- fixed Compose command, owned path.
        [*compose, "run", "--rm", "browser"], cwd=ROOT, env=environment
    )
    jobs = set()
    try:
        deadline = time.monotonic() + 300
        while process.poll() is None:
            if time.monotonic() > deadline:
                raise RuntimeError("Production browser exceeded its bounded deadline.")
            request = run / "worker-request.json"
            if request.exists():
                try:
                    values = json.loads(request.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    time.sleep(0.1)
                    continue
                if (
                    set(values) != {"actor", "workspace", "job", "mode", "request_id"}
                    or values["actor"] != fixture["user"]
                    or values["workspace"] != fixture["a"]
                ):
                    raise RuntimeError("Invalid synthetic worker request.")
                job = str(UUID(values["job"]))
                request_id = str(UUID(values["request_id"]))
                if values["mode"] not in {"normal", "interrupt"}:
                    raise RuntimeError("Invalid worker mode.")
                if request_id not in jobs:
                    if values["mode"] == "interrupt":
                        interrupted = subprocess.run(  # noqa: S603 -- guarded UUIDs, fixed entrypoint.
                            [
                                *compose,
                                "run",
                                "--rm",
                                "extract",
                                "python",
                                "/deployment/interruption_worker.py",
                                "--workspace",
                                fixture["a"],
                                "--actor",
                                fixture["user"],
                                "--job",
                                job,
                            ],
                            cwd=ROOT,
                            env=environment,
                            check=False,
                        )
                        if interrupted.returncode != 73:
                            raise RuntimeError(
                                "Actual worker interruption was not observed."
                            )
                    else:
                        execute(
                            [
                                "run",
                                "--rm",
                                "extract",
                                "python",
                                "manage.py",
                                "process_document_extraction",
                                "--workspace",
                                fixture["a"],
                                "--actor",
                                fixture["user"],
                                "--job",
                                job,
                            ]
                        )
                    jobs.add(request_id)
                    (run / "worker-result.json").write_text(
                        json.dumps({"job": job, "request_id": request_id, "code": 0}),
                        encoding="ascii",
                    )
            time.sleep(0.2)
        if process.returncode:
            raise RuntimeError("Production browser acceptance failed.")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
    print(
        "Production browser finished; isolated synthetic data preserved "
        "for restart checks."
    )
