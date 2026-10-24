"""Score timed work; synthetic results never prove customer benefit."""

import argparse
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median

ARMS = {"manual", "orderdesk"}
OUTCOMES = {
    "not_attempted",
    "accepted_reported",
    "accepted_confirmed",
    "rejected",
    "unknown",
}


def number(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field}: provide an exact decimal string.")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field}: invalid decimal.") from error
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field}: use a finite nonnegative decimal.")
    return result


def distribution(values):
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None, "p90": None}
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * Decimal("0.90")
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    p90 = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return {
        "n": len(values),
        "median": str(median(ordered)),
        "min": str(ordered[0]),
        "max": str(ordered[-1]),
        "p90": str(p90),
    }


def evaluate(data):
    if data.get("schema") != "orderdesk-evaluation-v1":
        raise ValueError("Unsupported evaluation schema.")
    if data.get("dataset_kind") not in {"synthetic", "customer"}:
        raise ValueError("Declare synthetic or customer dataset kind.")
    cases = {}
    for case in data["cases"]:
        key = case["id"]
        if not isinstance(key, str) or not key or key in cases:
            raise ValueError("Case identifiers must be nonempty and unique.")
        if (
            type(case["supported"]) is not bool
            or type(case["line_count"]) is not int
            or case["line_count"] < 0
        ):
            raise ValueError("Declare document support and nonnegative line count.")
        if not isinstance(case["expected"], dict) or not case["expected"]:
            raise ValueError(
                "Each case requires expected critical fields "
                "or expected manual fallback."
            )
        for expected in case["expected"].values():
            if expected.get("kind") not in {"text", "decimal"} or not isinstance(
                expected.get("value"), str
            ):
                raise ValueError(
                    "Critical fields require explicit text/decimal kind "
                    "and string value."
                )
            if expected["kind"] == "decimal":
                number(expected["value"], "expected decimal")
        cases[key] = case
    if not cases:
        raise ValueError(
            "Include every selected case, including failed/unsupported inputs."
        )
    observations = {}
    fields, errors = Counter(), Counter()
    decision_fields, decision_errors = Counter(), Counter()
    all_times = {arm: [] for arm in ARMS}
    queue, elapsed, extra = [], [], []
    corrections = returns = exceptions = 0
    outcomes, extraction = Counter(), Counter()
    complete = 0
    for row in data["observations"]:
        identity = (row["case_id"], row["arm"])
        if (
            identity in observations
            or identity[0] not in cases
            or identity[1] not in ARMS
        ):
            raise ValueError(
                "Observations must uniquely identify a known case and arm."
            )
        methods = {"explicit_timer", "observed_stopwatch"}
        if data["dataset_kind"] == "synthetic":
            methods.add("synthetic_simulation")
        if row.get("timing_method") not in methods:
            raise ValueError(
                "Active time requires explicit timer or observed stopwatch evidence."
            )
        if not row.get("observer") or not row.get("session_reference"):
            raise ValueError("Record an observer and timed-session reference.")
        active = number(row["active_seconds"], "active_seconds")
        wait = number(row["queue_wait_seconds"], "queue_wait_seconds")
        total = number(row["elapsed_seconds"], "elapsed_seconds")
        downstream = number(row["post_export_seconds"], "post_export_seconds")
        if active + wait > total or downstream > active:
            raise ValueError(
                "Active plus queue time cannot exceed elapsed; "
                "post-export work is included in active time."
            )
        if type(row["completed"]) is not bool:
            raise ValueError(
                "Declare whether the equivalent end-to-end task completed."
            )
        observations[identity] = {**row, "active": active}
        all_times[identity[1]].append(active)
        if identity[1] != "orderdesk":
            continue
        for key in ("corrections", "review_returns", "exceptions"):
            if type(row[key]) is not int or row[key] < 0:
                raise ValueError(
                    "Correction, return and exception counts "
                    "must be nonnegative integers."
                )
        if row["destination_outcome"] not in OUTCOMES:
            raise ValueError("Record a supported destination evidence level.")
        if not isinstance(row["actual"], dict):
            raise ValueError(
                "Provide independently scored output fields, including missing outputs."
            )
        outcomes[row["destination_outcome"]] += 1
        if row.get("extraction_outcome") not in {
            "succeeded",
            "unsupported",
            "failed",
            "not_attempted",
        }:
            raise ValueError(
                "Record the observed extraction outcome separately from format support."
            )
        extraction[row["extraction_outcome"]] += 1
        corrections += row["corrections"]
        returns += row["review_returns"]
        exceptions += row["exceptions"]
        complete += int(row["completed"])
        queue.append(wait)
        elapsed.append(total)
        extra.append(downstream)
    # Score the selected cohort, including absent/failed app observations.
    for key, case in cases.items():
        actual_fields = observations.get((key, "orderdesk"), {}).get("actual", {})
        for path, expected in case["expected"].items():
            selected_fields, selected_errors = (
                (fields, errors)
                if expected.get("critical", True)
                else (decision_fields, decision_errors)
            )
            selected_fields[path] += 1
            actual = actual_fields.get(path)
            correct = isinstance(actual, str) and actual == expected["value"]
            if expected["kind"] == "decimal" and isinstance(actual, str):
                try:
                    correct = number(actual, "actual") == number(
                        expected["value"], "expected"
                    )
                except ValueError:
                    correct = False
            selected_errors[path] += int(not correct)
    pairs, exclusions = [], []
    for key in cases:
        manual = observations.get((key, "manual"))
        desk = observations.get((key, "orderdesk"))
        if (
            manual is None
            or desk is None
            or not manual["completed"]
            or not desk["completed"]
        ):
            exclusions.append(
                {
                    "case_id": key,
                    "reason": "missing observation or incomplete equivalent task",
                }
            )
        else:
            pairs.append((manual["active"] - desk["active"]) / 60)
    field_total = sum(fields.values())
    failures = sum(errors.values())
    correctness = (
        (Decimal(field_total - failures) / field_total * 100) if field_total else None
    )
    comparable = len(pairs) == len(cases)
    reduction = None
    if comparable:
        manual_total = sum(
            row["active"] for (key, arm), row in observations.items() if arm == "manual"
        )
        desk_total = sum(
            row["active"]
            for (key, arm), row in observations.items()
            if arm == "orderdesk"
        )
        if manual_total:
            reduction = (manual_total - desk_total) / manual_total * 100
    monthly = data.get("eligible_monthly_order_volume")
    capacity = None
    if monthly is not None and comparable:
        volume = number(monthly["value"], "eligible monthly volume")
        if monthly.get("basis") not in {"measured", "assumed"} or not monthly.get(
            "reference"
        ):
            raise ValueError("Volume requires measured/assumed basis and provenance.")
        # Arithmetic mean is required for additive monthly capacity, not the median.
        capacity = str(volume * sum(pairs) / len(pairs) / 60)
    resolved_destinations = sum(
        outcomes[key] for key in ("accepted_confirmed", "accepted_reported", "rejected")
    )
    observed_lines = sum(
        cases[key]["line_count"] for key, arm in observations if arm == "orderdesk"
    )
    return {
        "schema": data["schema"],
        "input_content_sha256": hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "dataset_kind": data["dataset_kind"],
        "customer_benefit_verdict": "BLOCKED: synthetic instrumentation only"
        if data["dataset_kind"] == "synthetic"
        else "REQUIRES independent evidence review",
        "independent_ground_truth_attested": data.get("independently_reviewed") is True,
        "cases": len(cases),
        "supported_documents": sum(case["supported"] for case in cases.values()),
        "categories": dict(
            Counter(
                tag for case in cases.values() for tag in case.get("categories", [])
            )
        ),
        "observation_counts": dict(Counter(arm for key, arm in observations)),
        "timing_methods": dict(
            Counter(row["timing_method"] for row in observations.values())
        ),
        "extraction_outcomes": dict(extraction),
        "extraction_success_denominator": len(cases),
        "extraction_success_percent": str(
            Decimal(extraction["succeeded"]) / len(cases) * 100
        ),
        "learning_order": dict(
            Counter(case.get("first_arm", "not_recorded") for case in cases.values())
        ),
        "active_seconds_including_failed_observations": {
            arm: distribution(values) for arm, values in sorted(all_times.items())
        },
        "queue_wait_seconds": distribution(queue),
        "elapsed_seconds": distribution(elapsed),
        "post_export_seconds_included_in_active": distribution(extra),
        "completed_orderdesk_tasks": complete,
        "corrections": corrections,
        "corrections_per_observed_order": str(Decimal(corrections) / len(queue))
        if queue
        else None,
        "corrections_per_observed_line": str(Decimal(corrections) / observed_lines)
        if observed_lines
        else None,
        "review_returns": returns,
        "exceptions": exceptions,
        "observed_orderdesk_orders": len(queue),
        "observed_orderdesk_lines": observed_lines,
        "critical_fields": {
            path: {"scored": fields[path], "errors": errors[path]}
            for path in sorted(fields)
        },
        "processing_decisions": {
            path: {"scored": decision_fields[path], "errors": decision_errors[path]}
            for path in sorted(decision_fields)
        },
        "critical_correctness_percent": str(correctness)
        if correctness is not None
        else None,
        "destination_outcomes": dict(outcomes),
        "destination_rejection_denominator": resolved_destinations,
        "destination_reported_rejection_percent": str(
            Decimal(outcomes["rejected"]) / resolved_destinations * 100
        )
        if resolved_destinations
        else None,
        "paired_minutes_saved": distribution(pairs),
        "savings_exclusions": exclusions,
        "complete_cohort_comparison": comparable,
        "cohort_active_time_reduction_percent": str(reduction)
        if reduction is not None
        else None,
        "eligible_monthly_order_volume": monthly,
        "monthly_capacity_hours": capacity,
        "value_interpretation": "Released capacity; "
        "cash expenditure reduction is not established.",
        "targets": {
            "handling_reduction_percent": "50",
            "critical_correctness_percent": "99",
            "customer_targets_met": None,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    report = evaluate(json.loads(arguments.input.read_text(encoding="utf-8")))
    # Do not overwrite an earlier observation/evidence file.
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
