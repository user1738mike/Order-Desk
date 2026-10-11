"""Encrypted backup and fresh isolated restore of the synthetic acceptance run."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

from local_deploy import PRIVATE, ROOT, initialize


def owned_run(path):
    run = path.resolve()
    if run.parent != PRIVATE.resolve() or not run.name.startswith("deployment-"):
        raise ValueError("Use a run-owned ignored deployment path.")
    UUID(run.name.removeprefix("deployment-"))
    project = f"orderdesk-{run.name}"
    if json.loads((run / "identity.json").read_text(encoding="ascii")) != {
        "project": project
    }:
        raise ValueError("Unexpected deployment identity.")
    return run, project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    source, source_project = owned_run(args.source)
    for name in ("fixture.json", "workflow.json", "session.json", "prepared"):
        if not (source / name).is_file():
            parser.error("Source must be a completed synthetic browser acceptance run.")
    destination = PRIVATE / f"backup-{uuid4().hex}"
    keys = PRIVATE / f"recovery-keys-{uuid4().hex}"
    destination.mkdir()
    keys.mkdir()
    target = initialize()
    target, target_project = owned_run(target)
    environment = {
        **os.environ,
        "RECOVERY_BACKUP": str(destination),
        "RECOVERY_KEYS": str(keys),
        "RECOVERY_RUN": str(target),
    }

    def prefix(run, project, recovery=False, acceptance=False):
        command = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(run / "run.env"),
            "-f",
            "compose.production-local.yaml",
        ]
        if recovery:
            command += ["-f", "compose.recovery.yaml"]
        if acceptance:
            command += ["-f", "compose.production-acceptance.yaml"]
        return command

    def execute(command, **kwargs):
        return subprocess.run(command, cwd=ROOT, env=environment, check=True, **kwargs)  # noqa: S603

    start = time.monotonic()
    try:
        execute([*prefix(source, source_project), "stop", "api", "proxy"])
        running = execute(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project={source_project}",
                "--format",
                '{{.Label "com.docker.compose.service"}}',
            ],
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if any(service != "db" for service in running):
            raise RuntimeError(
                "Stop every source writer/tool before coordinated backup."
            )
        execute([*prefix(source, source_project), "up", "-d", "--wait", "db"])
        recovery = prefix(source, source_project, recovery=True)
        execute([*recovery, "build", "recovery"])
        # Key material is mounted separately; this container has no network/data.
        execute(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "10001:10001",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--mount",
                f"type=bind,source={keys},target=/keys",
                "--entrypoint",
                "age-keygen",
                "orderdesk-recovery:1",
                "--output",
                "/keys/identity.txt",
            ],
            stderr=subprocess.DEVNULL,
        )
        public = execute(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "10001:10001",
                "--network",
                "none",
                "--read-only",
                "--mount",
                f"type=bind,source={keys},target=/keys,readonly",
                "--entrypoint",
                "age-keygen",
                "orderdesk-recovery:1",
                "-y",
                "/keys/identity.txt",
            ],
            capture_output=True,
            text=True,
        ).stdout
        (keys / "recipient.txt").write_text(public, encoding="ascii")
        execute([*recovery, "run", "--rm", "recovery", "backup"])
        execute(
            [sys.executable, "scripts/local_deploy.py", "build", "--run", str(target)]
        )
        target_prefix = prefix(target, target_project)
        execute([*target_prefix, "up", "-d", "--wait", "db"])
        execute([*target_prefix, "run", "--rm", "dbsetup"])
        target_recovery = prefix(target, target_project, recovery=True)

        # Each failure must occur before restore-started or target writes.
        def expect_refusal(message):
            result = subprocess.run(  # noqa: S603 -- fixed owned restore command.
                [*target_recovery, "run", "--rm", "recovery-restore", "restore"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
            )
            if result.returncode == 0 or message not in result.stderr:
                raise RuntimeError(
                    "Recovery negative guard did not refuse: "
                    + result.stderr[-1500:].decode("utf-8", errors="replace")
                )
            if (target / "restore-started").exists():
                raise RuntimeError("Rejected backup began mutating its target.")

        (destination / "INCOMPLETE").touch()
        try:
            expect_refusal(b"Refusing incomplete backup")
        finally:
            (destination / "INCOMPLETE").unlink()
        encrypted = destination / "payload.age"
        evidence_path = destination / "complete.json"
        original = encrypted.read_bytes()
        original_evidence = evidence_path.read_bytes()
        try:
            damaged = original[:-1] + bytes([original[-1] ^ 1])
            encrypted.write_bytes(damaged)
            expect_refusal(b"Encrypted payload checksum mismatch")
            import hashlib

            modified = json.loads(original_evidence)
            modified["sha256"] = hashlib.sha256(damaged).hexdigest()
            evidence_path.write_text(json.dumps(modified), encoding="ascii")
            expect_refusal(b"failed to decrypt and authenticate payload chunk")
        finally:
            encrypted.write_bytes(original)
            evidence_path.write_bytes(original_evidence)
        execute([*target_recovery, "run", "--rm", "recovery-restore", "restore"])
        restored_secret = (target / "restored-secret.txt").read_text(encoding="ascii")
        env_file = target / "run.env"
        entries = env_file.read_text(encoding="ascii").splitlines()
        env_file.write_text(
            "\n".join(
                f"DJANGO_SECRET_KEY={restored_secret}"
                if line.startswith("DJANGO_SECRET_KEY=")
                else line
                for line in entries
            )
            + "\n",
            encoding="ascii",
        )
        (target / "restored-secret.txt").unlink()
        for name in ("fixture.json", "workflow.json", "session.json"):
            shutil.copyfile(source / name, target / name)
        environment["DEPLOYMENT_RUN"] = str(target)
        acceptance = prefix(target, target_project, acceptance=True)
        execute(
            [*acceptance, "up", "-d", "--wait", "--wait-timeout", "120", "api", "proxy"]
        )
        execute(
            [
                *acceptance,
                "run",
                "--rm",
                "client",
                "python",
                "/deployment/recovery_probe.py",
            ]
        )
        execute(
            [
                *acceptance,
                "run",
                "--rm",
                "-v",
                f"{target}:/run-state:ro",
                "-v",
                f"{ROOT / 'deployment'}:/checks:ro",
                "extract",
                "python",
                "/checks/restored_boundary.py",
            ]
        )
        # A second restore must refuse the nonempty schema before mutation.
        refused = subprocess.run(  # noqa: S603 -- fixed command, owned target.
            [*target_recovery, "run", "--rm", "recovery-restore", "restore"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
        )
        if (
            refused.returncode == 0
            or b"Restore target schema must be empty" not in refused.stderr
        ):
            raise RuntimeError("Nonempty restore guard did not refuse.")
        execute(
            [
                *acceptance,
                "run",
                "--rm",
                "client",
                "python",
                "/deployment/recovery_probe.py",
            ]
        )
        elapsed = time.monotonic() - start
        (destination / "drill.json").write_text(
            json.dumps(
                {"target": target.name, "seconds": round(elapsed, 3), "result": "PASS"}
            ),
            encoding="ascii",
        )
        print(
            "PASS: encrypted coordinated restore, runtime boundary, "
            "secure-session/private-byte recovery and nonempty-target refusal; "
            f"{elapsed:.3f}s."
        )
        print(f"Evidence: {destination.relative_to(ROOT)}")
    finally:
        for run, project in ((source, source_project), (target, target_project)):
            subprocess.run(  # noqa: S603 -- fixed stop command, owned project.
                [*prefix(run, project), "stop"], cwd=ROOT, env=environment, check=False
            )


if __name__ == "__main__":
    main()
