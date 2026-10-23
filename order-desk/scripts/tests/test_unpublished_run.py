"""Keep isolated audits from publishing ports or altering an existing run."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from ipaddress import IPv4Network
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_deploy  # noqa: E402
import quality_gates  # noqa: E402


class UnpublishedRunTests(unittest.TestCase):
    def test_default_prefix_remains_published_and_no_override_is_inferred(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            prefix = local_deploy.compose_prefix(run, "owned")
            self.assertEqual(prefix[-2:], ["-f", "compose.production-local.yaml"])
            (run / "unpublished").mkdir()
            self.assertEqual(local_deploy.compose_prefix(run, "owned"), prefix)

    def test_explicit_marker_selects_fixed_overlay_for_every_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "unpublished").touch()
            prefix = local_deploy.compose_prefix(run, "owned")
            self.assertEqual(prefix[-2:], ["-f", "compose.unpublished.yaml"])
            self.assertEqual(prefix[3:5], ["owned", "--env-file"])
            self.assertEqual(prefix[-4:-2], ["-f", "compose.production-local.yaml"])

    def test_initializer_records_mode_without_changing_identity_or_credentials(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(local_deploy, "ROOT", Path(directory)),
            patch.object(local_deploy, "PRIVATE", Path(directory)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            run = local_deploy.initialize(unpublished=True)
            self.assertTrue((run / "unpublished").is_file())
            self.assertTrue((run / "run.env").is_file())
            subnets = [
                IPv4Network(line.split("=", 1)[1])
                for line in (run / "run.env").read_text().splitlines()
                if line.startswith("AUDIT_")
            ]
            self.assertEqual(len(subnets), 3)
            self.assertTrue(
                all(
                    s.prefixlen == 28 and s.subnet_of(IPv4Network("198.18.0.0/15"))
                    for s in subnets
                )
            )
            self.assertTrue(
                all(
                    not a.overlaps(b)
                    for i, a in enumerate(subnets)
                    for b in subnets[i + 1 :]
                )
            )
            self.assertEqual(
                json.loads((run / "identity.json").read_text()),
                {"project": f"orderdesk-{run.name}"},
            )

    def test_cannot_convert_existing_quality_run_into_unpublished_mode(self):
        with (
            patch.object(
                sys, "argv", ["quality_gates", "--run", "existing", "--unpublished"]
            ),
            patch.object(quality_gates, "initialize") as initialize,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                quality_gates.main()
            initialize.assert_not_called()

    def test_standalone_helper_rejects_mode_change_after_initialization(self):
        with (
            patch.object(
                sys,
                "argv",
                ["local_deploy", "up", "--run", "existing", "--unpublished"],
            ),
            patch.object(local_deploy, "command") as command,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                local_deploy.main()
            command.assert_not_called()
