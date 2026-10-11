"""Archive validation rejects unsafe or incomplete backups before mutation."""

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "recovery", Path(__file__).resolve().parents[2] / "deployment/recovery.py"
)
recovery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = recovery
spec.loader.exec_module(recovery)


class RecoveryArchiveTests(unittest.TestCase):
    def bundle(self, path, *, extra=None, corrupt=False):
        content = b"synthetic logical dump"
        manifest = {
            "format": "orderdesk-synthetic-backup-v1",
            "database": "test_orderdesk",
            "django_secret_key": "synthetic" * 8,
            "inventory": {
                "database.dump": {
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            },
        }
        with tarfile.open(path, "w") as archive:
            for name, value in (
                ("manifest.json", json.dumps(manifest).encode()),
                ("database.dump", b"corrupt" if corrupt else content),
            ):
                entry = tarfile.TarInfo(name)
                entry.size = len(value)
                archive.addfile(entry, io.BytesIO(value))
            if extra is not None:
                archive.addfile(extra)

    def test_valid_inventory_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "payload.tar"
            self.bundle(archive)
            self.assertEqual(
                recovery.validate_archive(archive)["database"], "test_orderdesk"
            )

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "payload.tar"
            self.bundle(archive, corrupt=True)
            with self.assertRaisesRegex(ValueError, "checksum"):
                recovery.validate_archive(archive)

    def test_traversal_links_duplicates_and_unlisted_members_are_rejected(self):
        link = tarfile.TarInfo("files/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        for entry in (
            tarfile.TarInfo("../escape"),
            link,
            tarfile.TarInfo("database.dump"),
            tarfile.TarInfo("files/unlisted"),
        ):
            with (
                self.subTest(name=entry.name),
                tempfile.TemporaryDirectory() as directory,
            ):
                archive = Path(directory) / "payload.tar"
                self.bundle(archive, extra=entry)
                with self.assertRaises(ValueError):
                    recovery.validate_archive(archive)

    def test_main_database_refused_before_connection(self):
        with (
            patch.dict(recovery.os.environ, {"PGDATABASE": "orderdesk"}),
            patch.object(recovery, "scalar") as query,
        ):
            with self.assertRaisesRegex(ValueError, "Refusing"):
                recovery.database_guard()
            query.assert_not_called()
