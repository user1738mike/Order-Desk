"""Run on the host with: python -m unittest discover -s scripts/tests -v."""

import unittest
from pathlib import Path

from scripts.init_env import SECRET_KEYS, assignments, extend_environment


class EnvironmentUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = (Path(__file__).resolve().parents[2] / ".env.example").read_text(
            encoding="utf-8"
        )

    def test_new_file_generates_distinct_secrets(self) -> None:
        values = assignments(extend_environment(self.template, None))
        self.assertEqual(len({values[key] for key in SECRET_KEYS}), len(SECRET_KEYS))
        for key in SECRET_KEYS:
            self.assertGreaterEqual(len(values[key]), 50)

    def test_upgrade_preserves_original_database_password(self) -> None:
        original = (
            "POSTGRES_DB=orderdesk\nPOSTGRES_USER=orderdesk_dev_admin\n"
            "POSTGRES_PASSWORD=existing-local-password\nPOSTGRES_PORT=5433\n"
        )
        upgraded = extend_environment(self.template, original)
        self.assertEqual(
            assignments(upgraded)["POSTGRES_PASSWORD"], "existing-local-password"
        )
        self.assertEqual(extend_environment(self.template, upgraded), upgraded)

    def test_empty_new_secret_is_filled(self) -> None:
        original = "POSTGRES_PASSWORD=keep-this-value\nDJANGO_SECRET_KEY=\n"
        self.assertTrue(
            assignments(extend_environment(self.template, original))[
                "DJANGO_SECRET_KEY"
            ]
        )

    def test_missing_original_bootstrap_password_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "original POSTGRES_PASSWORD"):
            extend_environment(self.template, "POSTGRES_PASSWORD=\n")

    def test_duplicate_assignments_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate POSTGRES_PASSWORD"):
            extend_environment(
                self.template, "POSTGRES_PASSWORD=a\nPOSTGRES_PASSWORD=b\n"
            )


if __name__ == "__main__":
    unittest.main()
