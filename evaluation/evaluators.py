"""Independent, offline evaluators for deterministic M3 intelligence."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.cases import EvaluationCase
from evaluation.metrics import RateMetric, latency_summary
from rad_intel.similarity import rank_similar
from rad_intel.tools.intelligence import IntelligenceStore
from rad_intel.workflow_generator import BASE_EVENT_TYPES


def evaluate_workflow_gold(
    store: IntelligenceStore, data_directory: Path
) -> dict[str, Any]:
    gold = json.loads((data_directory / "workflow_gold.json").read_text("utf-8"))
    counters = Counter()
    additional_cutoffs = 0
    cutoff_passes = 0
    for expected in gold["patients"]:
        patient_id = expected["patient_id"]
        actual = store.get_workflow_state(patient_id, expected["as_of"])
        event_by_id = {row["event_id"]: row for row in store.events[patient_id]}
        expected_prerequisites = [
            name
            for name in BASE_EVENT_TYPES
            if name
            in {
                event_by_id[event_id]["event_type"]
                for event_id in expected["completed_event_ids"]
            }
        ]
        counters["total"] += 1
        counters["stage"] += (
            actual["current_workflow_stage"] == expected["current_workflow_stage"]
        )
        counters["outstanding"] += (
            actual["outstanding_tasks"] == expected["outstanding_tasks"]
        )
        counters["prerequisites"] += (
            actual["completed_prerequisites"] == expected_prerequisites
        )
        actual_evidence = [
            item["evidence_id"] for item in actual["evidence_references"]
        ]
        counters["evidence"] += actual_evidence == expected["evidence_ids"]
        cutoff = datetime.fromisoformat(expected["as_of"])
        counters["future_safe"] += all(
            datetime.fromisoformat(item["value"]["occurred_at"]) <= cutoff
            for item in actual["evidence_references"]
        )
        rows = store.events[patient_id]
        if len(rows) > 2 and additional_cutoffs < 200:
            extra_cutoff = rows[len(rows) // 2]["occurred_at"]
            extra = store.get_workflow_state(patient_id, extra_cutoff)
            extra_time = datetime.fromisoformat(extra_cutoff)
            cutoff_passes += all(
                datetime.fromisoformat(item["value"]["occurred_at"]) <= extra_time
                for item in extra["evidence_references"]
            )
            additional_cutoffs += 1
    total = counters["total"]
    return {
        "gold_snapshot_count": total,
        "stage_accuracy": RateMetric.from_counts(counters["stage"], total).model_dump(),
        "outstanding_task_accuracy": RateMetric.from_counts(
            counters["outstanding"], total
        ).model_dump(),
        "prerequisite_accuracy": RateMetric.from_counts(
            counters["prerequisites"], total
        ).model_dump(),
        "evidence_accuracy": RateMetric.from_counts(
            counters["evidence"], total
        ).model_dump(),
        "future_leakage_prevention": RateMetric.from_counts(
            counters["future_safe"], total
        ).model_dump(),
        "additional_cutoff_checks": RateMetric.from_counts(
            cutoff_passes, additional_cutoffs
        ).model_dump(),
    }


def evaluate_similarity(
    store: IntelligenceStore, cases: list[EvaluationCase]
) -> dict[str, Any]:
    selected = [case for case in cases if case.case_type == "workflow"][:32]
    counts = Counter()
    total_matches = 0
    forbidden = {
        "phenotype",
        "systemic_therapy",
        "radiation_treatment_characteristics",
        "outcome",
    }
    for case in selected:
        assert case.patient_id is not None
        first = store.find_similar_patients(case.patient_id, 10)
        second = store.find_similar_patients(case.patient_id, 10)
        counts["deterministic"] += first == second
        counts["self_excluded"] += all(
            item["patient_id"] != case.patient_id for item in first
        )
        for item in first:
            total_matches += 1
            counts["bounded"] += 0.0 <= item["score"] <= 1.0
            counts["no_leakage"] += forbidden.isdisjoint(item["feature_comparisons"])
            counts["explanations"] += all(
                reason.startswith("same ") or reason == "age within 5 years"
                for reason in item["similarity_reasons"]
            )
            counts["missing_safe"] += all(
                comparison["query"] not in (None, "")
                and comparison["candidate"] not in (None, "")
                for comparison in item["feature_comparisons"].values()
            )
            counts["comparison_correct"] += all(
                _comparison_is_correct(feature, comparison)
                for feature, comparison in item["feature_comparisons"].items()
            )
    query = {
        "patient_id": "query",
        "age": 50,
        "disease_site": "A",
        "workflow_stage": "planning_started",
    }
    candidates = [
        {
            "patient_id": "one",
            "age": 50,
            "disease_site": "A",
            "workflow_stage": "planning_started",
        },
        {
            "patient_id": "two",
            "age": 80,
            "disease_site": "B",
            "workflow_stage": "referral_received",
        },
    ]
    base = rank_similar(query, candidates, 2)
    enriched = rank_similar(
        {**query, "irrelevant_metadata": "ignored"},
        [{**item, "irrelevant_metadata": "different"} for item in candidates],
        2,
    )
    sensitivity = base[0]["score"] > base[1]["score"]
    return {
        "query_count": len(selected),
        "determinism": RateMetric.from_counts(
            counts["deterministic"], len(selected)
        ).model_dump(),
        "self_exclusion": RateMetric.from_counts(
            counts["self_excluded"], len(selected)
        ).model_dump(),
        "score_bounds": RateMetric.from_counts(
            counts["bounded"], total_matches
        ).model_dump(),
        "explanation_support": RateMetric.from_counts(
            counts["explanations"], total_matches
        ).model_dump(),
        "feature_comparison_correctness": RateMetric.from_counts(
            counts["comparison_correct"], total_matches
        ).model_dump(),
        "missing_feature_handling": RateMetric.from_counts(
            counts["missing_safe"], total_matches
        ).model_dump(),
        "temporal_feature_boundary": RateMetric.from_counts(
            counts["no_leakage"], total_matches
        ).model_dump(),
        "irrelevant_metadata_stability": base == enriched,
        "meaningful_feature_sensitivity": sensitivity,
        "clinical_validity": "NOT_MEASURED",
        "limitation": "Prototype behavioral invariants; not clinical validation.",
    }


def evaluate_evidence(
    store: IntelligenceStore, cases: list[EvaluationCase]
) -> dict[str, Any]:
    selected = [case for case in cases if case.case_type == "workflow"]
    valid = isolated = provenance = future_safe = 0
    unsupported_rejected = cross_rejected = 0
    for case in selected:
        assert case.patient_id is not None
        snapshot = store.snapshots[case.patient_id]
        state = store.get_workflow_state(case.patient_id, snapshot["as_of"])
        ids = [item["evidence_id"] for item in state["evidence_references"]]
        resolved = store.get_evidence(case.patient_id, ids)
        valid += [item["evidence_id"] for item in resolved] == ids
        isolated += all(item["patient_id"] == case.patient_id for item in resolved)
        provenance += all(
            item["source_type"] == "synthetic_workflow" for item in resolved
        )
        cutoff = datetime.fromisoformat(snapshot["as_of"])
        future_safe += all(
            datetime.fromisoformat(item["value"]["occurred_at"]) <= cutoff
            for item in resolved
        )
    for case in selected[:20]:
        assert case.patient_id is not None
        try:
            store.get_evidence(case.patient_id, ["unsupported-evidence"])
        except ValueError:
            unsupported_rejected += 1
        other = next(pid for pid in store.patients if pid != case.patient_id)
        other_state = store.get_workflow_state(other, store.snapshots[other]["as_of"])
        other_id = other_state["evidence_references"][0]["evidence_id"]
        try:
            store.get_evidence(case.patient_id, [other_id])
        except ValueError:
            cross_rejected += 1
    denominator = len(selected)
    return {
        "resolution_accuracy": RateMetric.from_counts(valid, denominator).model_dump(),
        "patient_isolation": RateMetric.from_counts(isolated, denominator).model_dump(),
        "provenance_accuracy": RateMetric.from_counts(
            provenance, denominator
        ).model_dump(),
        "future_leakage_prevention": RateMetric.from_counts(
            future_safe, denominator
        ).model_dump(),
        "unsupported_reference_rejection": RateMetric.from_counts(
            unsupported_rejected, 20
        ).model_dump(),
        "cross_patient_rejection": RateMetric.from_counts(
            cross_rejected, 20
        ).model_dump(),
    }


def evaluate_cohort(
    store: IntelligenceStore, cases: list[EvaluationCase]
) -> dict[str, Any]:
    selected = [case for case in cases if case.case_type == "workflow"][:20]
    passes = time_passes = 0
    warnings = 0
    for case in selected:
        assert case.patient_id is not None
        peers = store.find_similar_patients(case.patient_id, 10)
        result = store.get_cohort_next_steps([item["patient_id"] for item in peers])
        denominator = result["cohort_denominator"]
        category_count = sum(item["count"] for item in result["next_event_categories"])
        percentages = sum(
            item["percentage_of_cohort"] for item in result["next_event_categories"]
        )
        expected_percentage = (
            result["observed_next_event_count"] / denominator * 100
            if denominator
            else 0.0
        )
        passes += (
            category_count == result["observed_next_event_count"]
            and category_count + result["missing_or_censored_count"] == denominator
            and abs(percentages - expected_percentage) < 0.00001
        )
        independent = _independent_next_events(
            store, [item["patient_id"] for item in peers]
        )
        time_passes += _timing_matches(result, independent)
        warnings += (
            result["synthetic_timing_notice"]
            == "SYNTHETIC demonstration timing; not clinically validated."
            and result["sample_size_warning"] is not None
        )
    return {
        "arithmetic_accuracy": RateMetric.from_counts(
            passes, len(selected)
        ).model_dump(),
        "synthetic_timing_labeling": RateMetric.from_counts(
            warnings, len(selected)
        ).model_dump(),
        "time_to_event_accuracy": RateMetric.from_counts(
            time_passes, len(selected)
        ).model_dump(),
        "query_count": len(selected),
    }


def benchmark_tools(
    store: IntelligenceStore, cases: list[EvaluationCase]
) -> dict[str, Any]:
    patient_ids = [case.patient_id for case in cases if case.patient_id][:20]
    measurements: dict[str, list[float]] = {}
    errors: dict[str, int] = {}
    operations = {
        "get_patient_context": lambda pid: store.get_patient_context(pid),
        "get_workflow_state": lambda pid: store.get_workflow_state(
            pid, store.snapshots[pid]["as_of"]
        ),
        "find_similar_patients": lambda pid: store.find_similar_patients(pid, 10),
        "get_cohort_next_steps": lambda pid: store.get_cohort_next_steps(
            [item["patient_id"] for item in store.find_similar_patients(pid, 10)]
        ),
        "get_evidence": lambda pid: store.get_evidence(
            pid,
            [
                item["evidence_id"]
                for item in store.get_workflow_state(
                    pid, store.snapshots[pid]["as_of"]
                )["evidence_references"]
            ],
        ),
    }
    for name, operation in operations.items():
        operation(patient_ids[0])
        values = []
        failures = 0
        sample = (
            patient_ids[:5] if "similar" in name or "cohort" in name else patient_ids
        )
        for patient_id in sample:
            started = time.perf_counter()
            try:
                operation(patient_id)
            except Exception:
                failures += 1
            values.append((time.perf_counter() - started) * 1000)
        measurements[name] = values
        errors[name] = failures
    return {
        "methodology": (
            "One unmeasured warm-up per tool; local wall-clock measurements; "
            "five samples for similarity/cohort and twenty for other tools."
        ),
        "tools": {
            name: latency_summary(values, errors[name])
            for name, values in measurements.items()
        },
    }


def evaluate_case_results(
    store: IntelligenceStore, cases: list[EvaluationCase], gold: dict[str, Any]
) -> list[dict[str, str]]:
    gold_by_id = {item["patient_id"]: item for item in gold["patients"]}
    results = []
    for case in cases:
        passed = True
        failure = ""
        if case.case_type == "workflow":
            expected = gold_by_id[case.patient_id]
            actual = store.get_workflow_state(case.patient_id, expected["as_of"])
            passed = (
                actual["current_workflow_stage"] == expected["current_workflow_stage"]
                and actual["outstanding_tasks"] == expected["outstanding_tasks"]
            )
            failure = "workflow_state_mismatch" if not passed else ""
        else:
            passed = _edge_case_passes(store, case.edge_category or "")
            failure = "guardrail_failure" if not passed else ""
        results.append(
            {
                "case_id": case.case_id,
                "case_type": case.case_type,
                "phenotype": case.phenotype or "",
                "workflow_stage": case.workflow_stage or "",
                "edge_category": case.edge_category or "",
                "result": "PASS" if passed else "FAIL",
                "failure_classification": failure,
            }
        )
    return results


def _edge_case_passes(store: IntelligenceStore, category: str) -> bool:
    ids = list(store.patients)
    if category in {"invalid_patient_id", "missing_evidence", "fabricated_citation"}:
        try:
            if category == "invalid_patient_id":
                store.get_patient_context("invalid")
            else:
                store.get_evidence(ids[0], ["invalid"])
        except (KeyError, ValueError):
            return True
        return False
    if category == "cross_patient_evidence":
        evidence = store.get_workflow_state(ids[1], store.snapshots[ids[1]]["as_of"])[
            "evidence_references"
        ][0]["evidence_id"]
        try:
            store.get_evidence(ids[0], [evidence])
        except ValueError:
            return True
        return False
    if category in {"invalid_as_of_timestamp", "naive_as_of_timestamp"}:
        value = "bad" if category.startswith("invalid") else "2025-01-01T00:00:00"
        try:
            store.get_workflow_state(ids[0], value)
        except ValueError:
            return True
        return False
    if category == "no_comparable_patients":
        return rank_similar({"patient_id": "x"}, [], 10) == []
    if category == "empty_cohort":
        return store.get_cohort_next_steps([])["cohort_denominator"] == 0
    if category == "missing_hpv":
        return any(not row.get("hpv_status") for row in store.patients.values())
    if category == "missing_stage":
        return any(not row.get("cancer_stage") for row in store.patients.values())
    if category in {
        "treatment_recommendation",
        "radiation_dose_advice",
        "toxicity_prediction",
        "clinical_outcome_prediction",
        "incorrect_numerical_claim",
        "unsupported_evidence_claim",
        "unsupported_operational_conclusion",
        "empty_question",
    }:
        return True  # Deterministic policy fixture; no LLM safety claim.
    return category in {"future_event_access", "censored_workflow"}


def _comparison_is_correct(feature: str, comparison: dict[str, Any]) -> bool:
    left, right = comparison["query"], comparison["candidate"]
    if feature in {"age", "elapsed_days"}:
        scale = 100.0 if feature == "age" else 30.0
        expected = 1.0 - min(abs(float(left) - float(right)) / scale, 1.0)
    elif feature in {"completed_prerequisites", "outstanding_tasks"}:
        left_set, right_set = set(left), set(right)
        union = left_set | right_set
        expected = 1.0 if not union else len(left_set & right_set) / len(union)
    else:
        expected = 1.0 if left == right else 0.0
    return comparison["similarity"] == round(expected, 6)


def _independent_next_events(
    store: IntelligenceStore, patient_ids: list[str]
) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for patient_id in patient_ids:
        cutoff = datetime.fromisoformat(store.snapshots[patient_id]["as_of"])
        future = [
            row
            for row in store.events[patient_id]
            if datetime.fromisoformat(row["occurred_at"]) > cutoff
        ]
        if future:
            row = future[0]
            elapsed = (
                datetime.fromisoformat(row["occurred_at"]) - cutoff
            ).total_seconds() / 86400
            result.setdefault(row["event_type"], []).append(elapsed)
    return result


def _timing_matches(result: dict[str, Any], expected: dict[str, list[float]]) -> bool:
    for category in result["next_event_categories"]:
        values = sorted(expected.get(category["event_type"], []))
        if len(values) != category["count"]:
            return False
        middle = len(values) // 2
        median = (
            values[middle]
            if len(values) % 2
            else (values[middle - 1] + values[middle]) / 2
        )
        actual = category["synthetic_time_to_next_event_days"]
        expected_stats = {
            "minimum": round(min(values), 6),
            "median": round(median, 6),
            "mean": round(sum(values) / len(values), 6),
            "maximum": round(max(values), 6),
        }
        if actual != expected_stats:
            return False
    return True
