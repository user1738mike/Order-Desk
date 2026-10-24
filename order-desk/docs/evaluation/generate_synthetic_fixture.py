"""Deterministic fabricated observations for evaluator verification, never a pilot."""

import json
from pathlib import Path


def main():
    cases, observations = [], []
    scenarios = [
        ("csv-multiline", True, 2, ["csv", "multi-line"], "complete"),
        ("text-pdf", True, 2, ["text-pdf", "fractional"], "complete"),
        (
            "ambiguous-account",
            True,
            1,
            ["customer-ambiguity", "delivery-sites"],
            "manual",
        ),
        ("case-conversion", True, 1, ["product-alias", "unit-conversion"], "complete"),
        ("duplicate-request", True, 1, ["duplicate"], "manual"),
        ("revised-request", True, 1, ["revision"], "complete"),
        ("invalid-quantity", True, 1, ["invalid", "incomplete"], "return"),
        (
            "scanned-pdf",
            False,
            2,
            ["unsupported", "scanned-pdf", "manual-fallback"],
            "manual",
        ),
    ]
    for index, (key, supported, lines, categories, mode) in enumerate(scenarios):
        expected = {
            "processing.mode": {"kind": "text", "value": mode, "critical": False}
        }
        if mode == "complete":
            expected.update(
                {
                    "customer.id": {"kind": "text", "value": "C0001"},
                    "delivery.id": {"kind": "text", "value": "SITE02"},
                    "lines.1.sku": {"kind": "text", "value": "00042"},
                    "lines.1.quantity": {"kind": "decimal", "value": "1.250"},
                    "lines.1.unit": {"kind": "text", "value": "each"},
                }
            )
            if lines > 1:
                expected.update(
                    {
                        "lines.2.sku": {"kind": "text", "value": "00007"},
                        "lines.2.quantity": {"kind": "decimal", "value": "2.000"},
                        "lines.2.unit": {"kind": "text", "value": "case"},
                    }
                )
        cases.append(
            {
                "id": key,
                "supported": supported,
                "line_count": lines,
                "categories": categories,
                "first_arm": "manual" if index % 2 == 0 else "orderdesk",
                "expected": expected,
            }
        )
        for arm in ("manual", "orderdesk"):
            active = 600 + index * 30 if arm == "manual" else 330 + index * 45
            actual = {path: field["value"] for path, field in expected.items()}
            if key == "case-conversion" and arm == "orderdesk":
                actual["lines.1.unit"] = "case"  # Intentional scoring failure.
            observations.append(
                {
                    "case_id": key,
                    "arm": arm,
                    "timing_method": "synthetic_simulation",
                    "observer": "fabricated-simulator",
                    "session_reference": f"simulation/{key}/{arm}",
                    "active_seconds": str(active),
                    "queue_wait_seconds": "120",
                    "elapsed_seconds": str(active + 180),
                    "post_export_seconds": "60",
                    "completed": key != "invalid-quantity",
                    "corrections": int(key in {"case-conversion", "revised-request"}),
                    "review_returns": int(key == "invalid-quantity"),
                    "exceptions": int(mode != "complete"),
                    "destination_outcome": "unknown"
                    if mode == "complete"
                    else "not_attempted",
                    "extraction_outcome": "unsupported"
                    if not supported
                    else "failed"
                    if mode == "return"
                    else "succeeded",
                    "actual": actual,
                }
            )
    fixture = {
        "schema": "orderdesk-evaluation-v1",
        "dataset_kind": "synthetic",
        "independently_reviewed": False,
        "provenance": "Fabricated case definitions and durations; "
        "not extracted documents, observed staff work "
        "or independent customer ground truth.",
        "cases": cases,
        "observations": observations,
        "eligible_monthly_order_volume": {
            "value": "1000",
            "basis": "assumed",
            "reference": "Fabricated instrumentation example only",
        },
    }
    destination = Path(__file__).with_name("synthetic-observations.json")
    destination.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
