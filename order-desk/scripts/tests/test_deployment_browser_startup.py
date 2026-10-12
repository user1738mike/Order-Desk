"""Browser recovery starts the owned database before guarded fixture creation."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deployment_browser import prepare_browser_services  # noqa: E402


class BrowserStartupTests(unittest.TestCase):
    def test_new_fixtures_require_a_healthy_database_first(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            prepare_browser_services(calls.append, Path(directory))
            self.assertEqual(calls[0][-1], "db")
            self.assertIn("--wait", calls[0])
            self.assertEqual(calls[1], ["run", "--rm", "fixtures"])
            self.assertEqual(calls[2][-2:], ["api", "proxy"])

    def test_existing_fixture_evidence_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "fixture.json").write_text("preserve", encoding="ascii")
            calls = []
            prepare_browser_services(calls.append, run)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][-1], "db")
            self.assertEqual((run / "fixture.json").read_text(), "preserve")

    def test_failed_database_start_does_not_seed_or_start_serving(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []

            def failed(arguments):
                calls.append(arguments)
                raise RuntimeError("database unavailable")

            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                prepare_browser_services(failed, Path(directory))
            self.assertEqual(len(calls), 1)
