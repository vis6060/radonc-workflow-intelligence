from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rad_intel.showcase import (
    SHOWCASE_COHORT_SIZE,
    SHOWCASE_PATIENT,
    SHOWCASE_VERSION,
    SyntheticShowcaseStore,
    derive_ajcc8_clinical_stage,
)
from rad_intel.ui.components import comparison_factor_rows
from rad_intel.workflow_generator import BASE_EVENT_TYPES


@pytest.fixture
def store() -> SyntheticShowcaseStore:
    return SyntheticShowcaseStore()


def test_showcase_is_reproducible_and_entirely_in_memory() -> None:
    first = SyntheticShowcaseStore()
    second = SyntheticShowcaseStore()
    assert first.patients == second.patients
    assert first.events == second.events
    assert first.snapshots == second.snapshots
    assert len(first.patients) == SHOWCASE_COHORT_SIZE == 32
    assert all(
        patient_id.startswith("SYNTHETIC-DEMO-") for patient_id in first.patients
    )


def test_showcase_does_not_read_private_cohort_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_file_read(*args: object, **kwargs: object) -> None:
        raise AssertionError("showcase construction must not open a local cohort file")

    monkeypatch.setattr(Path, "open", reject_file_read)
    store = SyntheticShowcaseStore()
    assert len(store.patients) == SHOWCASE_COHORT_SIZE


def test_clinical_context_is_meaningful_and_evidence_linked(
    store: SyntheticShowcaseStore,
) -> None:
    context = store.get_patient_context(SHOWCASE_PATIENT)
    disease = context["disease_characteristics"]
    assert context["age"] is not None
    assert all(
        disease[field] is not None
        for field in ("disease_site", "subsite", "cancer_stage", "hpv_status")
    )
    assert context["provenance"]["source_type"] == "fictional_showcase_clinical"
    evidence_ids = [item["evidence_id"] for item in context["evidence_references"]]
    resolved = store.get_evidence(SHOWCASE_PATIENT, evidence_ids)
    assert {item["field_or_event"] for item in resolved} == {
        field
        for field, is_missing in context["missing_data"].items()
        if not is_missing
    }
    assert all(item["patient_id"] == SHOWCASE_PATIENT for item in resolved)
    assert all(
        item["source_type"] == "fictional_showcase_clinical" for item in resolved
    )
    assert all(
        item["provenance"]["source_version"] == SHOWCASE_VERSION
        for item in resolved
    )


def test_clinical_combinations_and_treatment_availability_are_coherent(
    store: SyntheticShowcaseStore,
) -> None:
    expected_stage_groups = {
        ("oropharynx", "positive", "T2", "N1", "M0"): "I",
        ("oropharynx", "positive", "T3", "N1", "M0"): "II",
        ("oropharynx", "negative", "T2", "N2", "M0"): "IVA",
        ("oropharynx", "negative", "T2", "N1", "M0"): "III",
        ("larynx", "not_applicable", "T2", "N0", "M0"): "II",
        ("larynx", "not_applicable", "T3", "N1", "M0"): "III",
        ("hypopharynx", "not_applicable", "T3", "N1", "M0"): "III",
        ("oral_cavity", "not_applicable", "T2", "N1", "M0"): "III",
    }
    for patient_id, row in store.patients.items():
        stage = row["cancer_stage"]
        assert all(stage[key] for key in ("t", "n", "m", "stage"))
        staging_key = (
            row["disease_site"],
            row["p16_status"],
            stage["t"],
            stage["n"],
            stage["m"],
        )
        assert stage["stage"] == expected_stage_groups[staging_key]
        assert stage["staging_system"] == "AJCC"
        assert stage["staging_edition"] == "8th edition"
        assert stage["staging_type"] == "clinical_prognostic_stage_group"
        if row["disease_site"] == "oropharynx":
            assert row["hpv_status"] in {"positive", "negative"}
            assert row["p16_status"] == row["hpv_status"]
        else:
            assert row["hpv_status"] == "not_applicable"
            assert row["p16_status"] == "not_applicable"
        state = store.get_workflow_state(
            patient_id, store.snapshots[patient_id]["as_of"]
        )
        planning_visible = "planning_started" in state["completed_prerequisites"]
        assert (row["systemic_therapy"] is not None) == planning_visible
        assert (
            row["radiation_treatment_characteristics"] is not None
        ) == planning_visible

    primary = store.patients[SHOWCASE_PATIENT]
    assert primary["p16_status"] == "positive"
    assert primary["cancer_stage"]["stage"] == "I"


def test_unsupported_staging_combination_fails_closed() -> None:
    with pytest.raises(ValueError, match="lacks an explicit AJCC 8 mapping"):
        derive_ajcc8_clinical_stage(
            "oropharynx", "positive", "T4", "N3", "M0"
        )


def test_workflow_timeline_is_complete_and_chronological(
    store: SyntheticShowcaseStore,
) -> None:
    for patient_id, events in store.events.items():
        timestamps = [datetime.fromisoformat(item["occurred_at"]) for item in events]
        assert timestamps == sorted(timestamps)
        event_types = {item["event_type"] for item in events}
        assert set(BASE_EVENT_TYPES) <= event_types
        assert len({item["evidence_id"] for item in events}) == len(events)
        assert all(item["patient_id"] == patient_id for item in events)


def test_point_in_time_state_and_evidence_exclude_future_events(
    store: SyntheticShowcaseStore,
) -> None:
    as_of = store.snapshots[SHOWCASE_PATIENT]["as_of"]
    cutoff = datetime.fromisoformat(as_of)
    state = store.get_workflow_state(SHOWCASE_PATIENT, as_of)
    assert len(state["completed_prerequisites"]) == 7
    assert state["current_workflow_stage"] == "simulation_completed"
    assert state["outstanding_tasks"] == ["contour_task_opened"]
    assert all(
        datetime.fromisoformat(item["value"]["occurred_at"]) <= cutoff
        for item in state["evidence_references"]
    )
    assert any(
        datetime.fromisoformat(item["occurred_at"]) > cutoff
        for item in store.events[SHOWCASE_PATIENT]
    )


def test_showcase_contains_resolved_exceptions_and_active_interruption(
    store: SyntheticShowcaseStore,
) -> None:
    event_types = {
        item["event_type"]
        for events in store.events.values()
        for item in events
        if item["is_exceptional"]
    }
    assert {
        "consult_no_show",
        "consult_rescheduled",
        "hospitalization_interruption_started",
        "hospitalization_interruption_resolved",
    } <= event_types
    active = store.get_workflow_state(
        "SYNTHETIC-DEMO-015",
        store.snapshots["SYNTHETIC-DEMO-015"]["as_of"],
    )
    assert active["current_workflow_stage"] == "hospitalization_interruption"
    assert "hospitalization_interruption_resolved" in active["outstanding_tasks"]


def test_similarity_uses_existing_engine_with_real_comparisons(
    store: SyntheticShowcaseStore,
) -> None:
    first = store.find_similar_patients(SHOWCASE_PATIENT, 10)
    second = store.find_similar_patients(SHOWCASE_PATIENT, 10)
    assert first == second
    assert len(first) == 10
    assert all(item["patient_id"] != SHOWCASE_PATIENT for item in first)
    assert all(0 <= item["score"] <= 1 for item in first)
    assert all(len(item["feature_comparisons"]) == 12 for item in first)
    assert all(item["similarity_reasons"] for item in first)


def test_comparison_table_preserves_exact_m3_values(
    store: SyntheticShowcaseStore,
) -> None:
    result = store.find_similar_patients(SHOWCASE_PATIENT, 1)[0]
    rows = comparison_factor_rows(result)
    assert len(rows) == len(result["feature_comparisons"])
    for row, (feature, comparison) in zip(
        rows, result["feature_comparisons"].items(), strict=True
    ):
        assert row == {
            "Feature": feature.replace("_", " ").title(),
            "Selected patient": comparison["query"],
            "Comparator": comparison["candidate"],
            "Feature similarity": comparison["similarity"],
        }


def test_cohort_next_steps_are_derived_diverse_and_include_censoring(
    store: SyntheticShowcaseStore,
) -> None:
    similar = store.find_similar_patients(SHOWCASE_PATIENT, 10)
    result = store.get_cohort_next_steps([item["patient_id"] for item in similar])
    categories = result["next_event_categories"]
    assert result["cohort_denominator"] == 10
    assert result["observed_next_event_count"] + result[
        "missing_or_censored_count"
    ] == 10
    assert result["missing_or_censored_count"] >= 1
    assert len(categories) >= 3
    assert sum(item["count"] for item in categories) == result[
        "observed_next_event_count"
    ]
    assert all(item["evidence_references"] for item in categories)


def test_cross_patient_evidence_is_rejected(store: SyntheticShowcaseStore) -> None:
    foreign = store.get_patient_context("SYNTHETIC-DEMO-002")[
        "evidence_references"
    ][0]["evidence_id"]
    with pytest.raises(ValueError, match="does not belong"):
        store.get_evidence(SHOWCASE_PATIENT, [foreign])
