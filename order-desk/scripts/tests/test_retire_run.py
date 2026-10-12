"""Retirement refuses running projects and retains data and diagnostic logs."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_deploy  # noqa: E402


class RetireRunTests(unittest.TestCase):
    def test_running_project_refused_before_logs_or_down(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                local_deploy.subprocess,
                "run",
                return_value=SimpleNamespace(stdout="running-id\n"),
            ) as process,
        ):
            with self.assertRaisesRegex(RuntimeError, "Stop this synthetic project"):
                local_deploy.retire_stopped_run(
                    ["owned-compose"], "owned", Path(directory)
                )
            self.assertEqual(process.call_count, 1)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_stopped_project_saves_logs_and_never_removes_volumes(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                local_deploy.subprocess,
                "run",
                return_value=SimpleNamespace(stdout=""),
            ) as process,
        ):
            local_deploy.retire_stopped_run(["owned-compose"], "owned", Path(directory))
            commands = [call.args[0] for call in process.call_args_list]
            self.assertEqual(commands[-1], ["owned-compose", "down"])
            self.assertNotIn("--volumes", commands[-1])
            self.assertNotIn("-v", commands[-1])
            self.assertTrue((Path(directory) / "retired-services.log").exists())

    def test_log_capture_failure_prevents_retirement(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                local_deploy.subprocess,
                "run",
                side_effect=[
                    SimpleNamespace(stdout=""),
                    RuntimeError("capture failed"),
                ],
            ) as process,
        ):
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                local_deploy.retire_stopped_run(
                    ["owned-compose"], "owned", Path(directory)
                )
            self.assertEqual(process.call_count, 2)
