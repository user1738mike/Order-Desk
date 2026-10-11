"""Bounded coordinated synthetic recovery; plaintext exists only in tmpfs."""

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

LIMIT = 128 * 1024 * 1024
MAX_FILES = 10000
ROOT = Path("/files")
BACKUP = Path("/backup")
KEYS = Path("/keys")
SCRATCH: Path


def execute(args, **kwargs):
    return subprocess.run(args, check=True, timeout=120, **kwargs)  # noqa: S603


def scalar(statement):
    return execute(
        ["psql", "--no-psqlrc", "--tuples-only", "--no-align", "--command", statement],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def database_guard():
    if os.environ.get("PGDATABASE") != "test_orderdesk":
        raise ValueError("Refusing any database except synthetic test_orderdesk.")
    if scalar("SELECT current_database() || ':' || session_user") != (
        "test_orderdesk:orderdesk_bootstrap"
    ):
        raise ValueError("Unexpected recovery database identity.")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def members(root):
    paths = []
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Recovery refuses links and special files.")
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise ValueError("Recovery refuses multiply linked private files.")
            paths.append(path)
        if len(paths) > MAX_FILES:
            raise ValueError("Recovery file budget exceeded.")
    return sorted(paths)


def backup():
    database_guard()
    if list(BACKUP.iterdir()):
        raise ValueError("Backup destination must be empty.")
    (BACKUP / "INCOMPLETE").touch()
    dump = SCRATCH / "database.dump"
    execute(["pg_dump", "--format=custom", "--file", str(dump)])
    paths = members(ROOT)
    size = dump.stat().st_size + sum(path.stat().st_size for path in paths)
    if size > LIMIT:
        raise ValueError("Recovery byte budget exceeded.")
    inventory = {
        "database.dump": {"size": dump.stat().st_size, "sha256": digest(dump)},
        **{
            f"files/{path.relative_to(ROOT).as_posix()}": {
                "size": path.stat().st_size,
                "sha256": digest(path),
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
            for path in paths
        },
    }
    manifest = {
        "format": "orderdesk-synthetic-backup-v1",
        "database": "test_orderdesk",
        "created_unix": int(time.time()),
        "inventory": inventory,
        "django_secret_key": os.environ["DJANGO_SECRET_KEY"],
    }
    archive = SCRATCH / "payload.tar"
    with tarfile.open(archive, "w") as bundle:
        value = json.dumps(manifest, sort_keys=True).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(value)
        info.mode = 0o600
        bundle.addfile(info, io.BytesIO(value))
        bundle.add(dump, arcname="database.dump", recursive=False)
        for path in paths:
            bundle.add(
                path,
                arcname=f"files/{path.relative_to(ROOT).as_posix()}",
                recursive=False,
            )
    temporary = BACKUP / "payload.age.partial"
    execute(
        [
            "age",
            "--encrypt",
            "--recipients-file",
            str(KEYS / "recipient.txt"),
            "--output",
            str(temporary),
            str(archive),
        ]
    )
    temporary.rename(BACKUP / "payload.age")
    evidence = {
        "sha256": digest(BACKUP / "payload.age"),
        "file_count": len(paths),
        "plaintext_bytes": size,
    }
    (BACKUP / "complete.json").write_text(json.dumps(evidence), encoding="ascii")
    (BACKUP / "INCOMPLETE").unlink()
    print("PASS: coordinated encrypted synthetic backup completed.")


def validate_archive(archive):
    with tarfile.open(archive) as bundle:
        entries = bundle.getmembers()
        names = [entry.name for entry in entries]
        if len(entries) > MAX_FILES + 2 or len(set(names)) != len(names):
            raise ValueError("Duplicate or excessive archive members.")
        for entry in entries:
            name = PurePosixPath(entry.name)
            if (
                not entry.isfile()
                or name.is_absolute()
                or ".." in name.parts
                or "\\" in entry.name
                or name.as_posix() != entry.name
            ):
                raise ValueError("Unsafe archive member.")
        if sum(entry.size for entry in entries) > LIMIT + 4 * 1024 * 1024:
            raise ValueError("Archive byte budget exceeded.")
        manifest_entry = bundle.getmember("manifest.json")
        if manifest_entry.size > 4 * 1024 * 1024:
            raise ValueError("Manifest budget exceeded.")
        manifest = json.load(bundle.extractfile(manifest_entry))
        if (
            manifest["format"] != "orderdesk-synthetic-backup-v1"
            or manifest["database"] != "test_orderdesk"
        ):
            raise ValueError("Unexpected backup format/database.")
        inventory = manifest["inventory"]
        if (
            set(names) != {"manifest.json", *inventory}
            or "database.dump" not in inventory
        ):
            raise ValueError("Incomplete archive inventory.")
        for name, expected in inventory.items():
            if name != "database.dump" and not name.startswith("files/"):
                raise ValueError("Unexpected payload member.")
            if name.startswith("files/") and expected.get("mode") not in {0o400, 0o600}:
                raise ValueError("Unexpected private file permissions.")
            entry = bundle.getmember(name)
            stream = bundle.extractfile(entry)
            if (
                entry.size != expected["size"]
                or hashlib.file_digest(stream, "sha256").hexdigest()
                != expected["sha256"]
            ):
                raise ValueError("Payload checksum mismatch.")
        secret = manifest["django_secret_key"]
        if (
            not isinstance(secret, str)
            or len(secret) < 50
            or "\n" in secret
            or "\r" in secret
        ):
            raise ValueError("Invalid application secret.")
        return manifest


def restore():
    database_guard()
    if (
        scalar(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('r','p','S','v','m','f')"
        )
        != "0"
    ):
        raise ValueError("Restore target schema must be empty.")
    if any(ROOT.iterdir()) or (Path("/run-state") / "restore-started").exists():
        raise ValueError("Restore target files/state must be empty.")
    if (BACKUP / "INCOMPLETE").exists() or not (BACKUP / "complete.json").is_file():
        raise ValueError("Refusing incomplete backup.")
    evidence = json.loads((BACKUP / "complete.json").read_text(encoding="ascii"))
    payload = BACKUP / "payload.age"
    if (
        payload.stat().st_size > LIMIT + 8 * 1024 * 1024
        or digest(payload) != evidence["sha256"]
    ):
        raise ValueError("Encrypted payload checksum mismatch.")
    archive = SCRATCH / "payload.tar"
    # Full decryption completes and authenticates before any application mutation.
    execute(
        [
            "age",
            "--decrypt",
            "--identity",
            str(KEYS / "identity.txt"),
            "--output",
            str(archive),
            str(payload),
        ]
    )
    manifest = validate_archive(archive)
    (Path("/run-state") / "restore-started").touch()
    with tarfile.open(archive) as bundle:
        dump = SCRATCH / "database.dump"
        with dump.open("xb") as output:
            output.write(bundle.extractfile("database.dump").read())
        execute(
            [
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "--dbname",
                "test_orderdesk",
                str(dump),
            ]
        )
        for name in manifest["inventory"]:
            if name == "database.dump":
                continue
            path = ROOT / name.removeprefix("files/")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(bundle.extractfile(name).read())
            os.chown(path, 10001, 10001)
            os.chmod(path, manifest["inventory"][name]["mode"])
        for directory in ROOT.rglob("*"):
            if directory.is_dir():
                os.chown(directory, 10001, 10001)
                os.chmod(directory, 0o700)
    (Path("/run-state") / "restored-secret.txt").write_text(
        manifest["django_secret_key"], encoding="ascii"
    )
    os.chmod(Path("/run-state") / "restored-secret.txt", 0o600)
    (Path("/run-state") / "restore-complete").touch()
    print("PASS: empty synthetic target restored; owners, grants and RLS retained.")


if __name__ == "__main__":
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="orderdesk-recovery-") as directory:
        SCRATCH = Path(directory)
        {"backup": backup, "restore": restore}[sys.argv[1]]()
