"""Recovery wrapper must refuse ambiguous source paths before Docker actions."""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_incoming_recovery as driver  # noqa: E402


class IncomingRecoveryGuardTests(unittest.TestCase):
    def test_non_owned_source_is_refused_before_subprocess(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(driver.subprocess, "run") as run,
        ):
            with patch.object(sys, "argv", ["verify", "--source", folder]):
                with self.assertRaises(ValueError):
                    driver.main()
            run.assert_not_called()

    def test_missing_acceptance_receipts_refused_before_startup(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(driver.subprocess, "run") as run,
        ):
            with patch.object(
                driver, "owned_run", return_value=(Path(folder), "owned")
            ):
                with patch.object(sys, "argv", ["verify", "--source", folder]):
                    with self.assertRaises(SystemExit) as error:
                        driver.main()
                self.assertEqual(error.exception.code, 2)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
