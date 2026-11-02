import json
from pathlib import Path

import pytest

from rad_intel.tools import IntelligenceStore


@pytest.fixture(scope="module")
def store() -> IntelligenceStore:
    return IntelligenceStore(Path("data/processed"))


def test_patient_context_and_missing_fields(store: IntelligenceStore) -> None:
    patient_id = sorted(store.patients)[0]
    context = store.get_patient_context(patient_id)
    assert context["patient_id"] == patient_id
    assert context["provenance"]["source_type"] == "observed_clinical"
    assert all(
        item["patient_id"] == patient_id for item in context["evidence_references"]
    )
    missing_patient = next(
        pid for pid, row in store.patients.items() if not row["hpv_status"]
    )
    assert store.get_patient_context(missing_patient)["missing_data"]["hpv_status"]


def test_unknown_patient_id(store: IntelligenceStore) -> None:
    with pytest.raises(KeyError, match="unknown patient_id"):
        store.get_patient_context("UNKNOWN-PATIENT")


def test_workflow_state_agrees_with_all_gold_labels(store: IntelligenceStore) -> None:
    gold = json.loads(
        Path("data/processed/workflow_gold.json").read_text(encoding="utf-8")
    )["patients"]
    for expected in gold:
        actual = store.get_workflow_state(expected["patient_id"], expected["as_of"])
        assert actual["current_workflow_stage"] == expected["current_workflow_stage"]
        assert actual["outstanding_tasks"] == expected["outstanding_tasks"]
        assert [
            item["evidence_id"] for item in actual["evidence_references"]
        ] == expected["evidence_ids"]


def test_point_in_time_state_has_no_future_events(store: IntelligenceStore) -> None:
    patient_id = sorted(store.patients)[0]
    first = store.events[patient_id][0]
    before = store.get_workflow_state(
        patient_id,
        store._event_rows(patient_id)[0]["occurred_at"],
    )
    assert before["completed_prerequisites"] == ["referral_received"]
    assert len(before["evidence_references"]) == 1
    assert before["evidence_references"][0]["source_record"] == first["event_id"]


def test_similarity_is_deterministic_bounded_and_excludes_self(
    store: IntelligenceStore,
) -> None:
    patient_id = sorted(store.patients)[0]
    first = store.find_similar_patients(patient_id, 10)
    second = store.find_similar_patients(patient_id, 10)
    assert first == second
    assert len(first) == 10
    assert all(item["patient_id"] != patient_id for item in first)
    assert all(0.0 <= item["score"] <= 1.0 for item in first)
    assert all("phenotype" not in item["feature_comparisons"] for item in first)
    assert all("systemic_therapy" not in item["feature_comparisons"] for item in first)


def test_evidence_resolution_and_patient_isolation(store: IntelligenceStore) -> None:
    patients = sorted(store.patients)
    owner, other = patients[0], patients[1]
    state = store.get_workflow_state(owner, store.snapshots[owner]["as_of"])
    evidence_id = state["evidence_references"][0]["evidence_id"]
    resolved = store.get_evidence(owner, [evidence_id])
    assert resolved[0]["patient_id"] == owner
    assert resolved[0]["source_type"] == "synthetic_workflow"
    with pytest.raises(ValueError, match="does not belong"):
        store.get_evidence(other, [evidence_id])


def test_cohort_frequency_arithmetic_and_empty_cohort(
    store: IntelligenceStore,
) -> None:
    patient_id = sorted(store.patients)[0]
    cohort_ids = [
        item["patient_id"] for item in store.find_similar_patients(patient_id, 10)
    ]
    result = store.get_cohort_next_steps(cohort_ids)
    assert result["cohort_denominator"] == 10
    assert (
        result["observed_next_event_count"] + result["missing_or_censored_count"] == 10
    )
    assert (
        sum(item["count"] for item in result["next_event_categories"])
        == result["observed_next_event_count"]
    )
    assert store.get_cohort_next_steps([])["cohort_denominator"] == 0


def test_incomplete_next_step_observations(store: IntelligenceStore) -> None:
    completed = [
        pid
        for pid, snapshot in store.snapshots.items()
        if snapshot["current_workflow_stage"] == "treatment_started"
    ][:5]
    result = store.get_cohort_next_steps(completed)
    assert result["missing_or_censored_count"] == len(completed)
    assert result["observed_next_event_count"] == 0
