"""Synthetic/partial evidence cannot become customer savings claims."""

import copy
import json
import unittest
from pathlib import Path

from scripts.evaluate_workflow import evaluate


def sample():
    row = {
        "case_id": "one",
        "timing_method": "observed_stopwatch",
        "observer": "observer-a",
        "session_reference": "local-record-one",
        "queue_wait_seconds": "10",
        "elapsed_seconds": "610",
        "post_export_seconds": "20",
        "completed": True,
        "corrections": 1,
        "review_returns": 0,
        "exceptions": 1,
        "destination_outcome": "unknown",
        "extraction_outcome": "succeeded",
        "actual": {"sku": "00042", "quantity": "1.25"},
    }
    return {
        "schema": "orderdesk-evaluation-v1",
        "dataset_kind": "synthetic",
        "independently_reviewed": False,
        "cases": [
            {
                "id": "one",
                "supported": True,
                "line_count": 1,
                "first_arm": "manual",
                "categories": ["fractional"],
                "expected": {
                    "sku": {"kind": "text", "value": "00042"},
                    "quantity": {"kind": "decimal", "value": "1.250"},
                },
            }
        ],
        "observations": [
            {**row, "arm": "manual", "active_seconds": "600"},
            {**row, "arm": "orderdesk", "active_seconds": "300"},
        ],
        "eligible_monthly_order_volume": {
            "value": "120",
            "basis": "assumed",
            "reference": "synthetic example",
        },
    }


class EvaluationTests(unittest.TestCase):
    def test_checked_in_synthetic_report_is_reproducible_and_not_customer_evidence(
        self,
    ):
        folder = Path(__file__).resolve().parents[2] / "docs" / "evaluation"
        source = json.loads((folder / "synthetic-observations.json").read_text())
        expected = json.loads((folder / "synthetic-report.json").read_text())
        report = evaluate(source)
        self.assertEqual(report, expected)
        self.assertEqual(report["cases"], 8)
        self.assertEqual(report["supported_documents"], 7)
        self.assertEqual(
            sum(row["errors"] for row in report["critical_fields"].values()), 1
        )
        self.assertEqual(report["processing_decisions"]["processing.mode"]["scored"], 8)
        self.assertEqual(report["timing_methods"], {"synthetic_simulation": 16})
        self.assertIsNone(report["monthly_capacity_hours"])

    def test_exact_identifiers_decimal_equality_and_additive_capacity(self):
        report = evaluate(sample())
        self.assertEqual(report["critical_correctness_percent"], "100")
        self.assertEqual(report["cohort_active_time_reduction_percent"], "50.0")
        self.assertEqual(report["monthly_capacity_hours"], "10")
        self.assertEqual(report["paired_minutes_saved"]["median"], "5")
        self.assertEqual(report["destination_rejection_denominator"], 0)
        self.assertIsNone(report["targets"]["customer_targets_met"])
        self.assertIn("BLOCKED", report["customer_benefit_verdict"])

    def test_missing_app_observation_counts_errors_and_blocks_capacity(self):
        data = sample()
        data["observations"].pop()
        report = evaluate(data)
        self.assertEqual(report["critical_correctness_percent"], "0")
        self.assertEqual(report["critical_fields"]["sku"], {"scored": 1, "errors": 1})
        self.assertFalse(report["complete_cohort_comparison"])
        self.assertIsNone(report["monthly_capacity_hours"])

    def test_leading_zero_identifier_not_numerically_coerced(self):
        data = sample()
        data["observations"][1]["actual"]["sku"] = "42"
        self.assertEqual(evaluate(data)["critical_fields"]["sku"]["errors"], 1)

    def test_failed_task_time_retained_but_savings_not_claimed(self):
        data = sample()
        data["observations"][1]["completed"] = False
        report = evaluate(data)
        self.assertEqual(
            report["active_seconds_including_failed_observations"]["orderdesk"]["n"], 1
        )
        self.assertIsNone(report["cohort_active_time_reduction_percent"])
        self.assertIsNone(report["monthly_capacity_hours"])
        self.assertEqual(len(report["savings_exclusions"]), 1)

    def test_invalid_measurements_do_not_become_zero_or_elapsed_as_active(self):
        for field, value in (
            ("active_seconds", "NaN"),
            ("active_seconds", "-1"),
            ("active_seconds", 10),
            ("timing_method", "tab_open"),
            ("post_export_seconds", "301"),
            ("elapsed_seconds", "20"),
            ("observer", ""),
            ("session_reference", ""),
            ("destination_outcome", "downloaded"),
        ):
            with self.subTest(field=field):
                data = sample()
                data["observations"][1][field] = value
                with self.assertRaises(ValueError):
                    evaluate(data)

    def test_duplicate_observations_and_untyped_ground_truth_refused(self):
        data = sample()
        data["observations"].append(copy.deepcopy(data["observations"][0]))
        with self.assertRaises(ValueError):
            evaluate(data)
        data = sample()
        data["cases"][0]["expected"]["sku"]["value"] = 42
        with self.assertRaises(ValueError):
            evaluate(data)

    def test_customer_data_cannot_use_simulated_timing(self):
        data = sample()
        data["dataset_kind"] = "customer"
        data["observations"][1]["timing_method"] = "synthetic_simulation"
        with self.assertRaises(ValueError):
            evaluate(data)


if __name__ == "__main__":
    unittest.main()
