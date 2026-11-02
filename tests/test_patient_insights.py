from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from rad_intel.agentcore_runtime.runtime_service import (
    LocalCohortProvider,
    SyntheticFixtureProvider,
)
from rad_intel.insights import SupportType, assemble_patient_insights
from rad_intel.insights.schemas import PatientInsights
from rad_intel.showcase import SHOWCASE_PATIENT
from rad_intel.ui.analysis import (
    DataMode,
    representative_patient_ids,
    run_analysis,
    selection_matches_bundle,
)


@pytest.fixture
def synthetic_bundle() -> Any:
    return run_analysis(
        SyntheticFixtureProvider(),
        DataMode.SYNTHETIC_AGENT_DEMO,
        SHOWCASE_PATIENT,
        None,
    )


def test_assembler_is_deterministic_and_preserves_corrected_stage(
    synthetic_bundle: Any,
) -> None:
    first = assemble_patient_insights(synthetic_bundle)
    second = assemble_patient_insights(synthetic_bundle)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.clinical_snapshot.t == "T2"
    assert first.clinical_snapshot.n == "N1"
    assert first.clinical_snapshot.m == "M0"
    assert first.clinical_snapshot.overall_stage == "I"
    assert first.clinical_snapshot.p16_status == "positive"
    assert first.data_mode == DataMode.SYNTHETIC_AGENT_DEMO.value


def test_run_analysis_invokes_each_existing_tool_once_before_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rad_intel.ui import analysis as analysis_module

    provider = SyntheticFixtureProvider()
    top_level_calls: list[str] = []
    names = (
        "get_patient_context",
        "get_workflow_state",
        "find_similar_patients",
        "get_cohort_next_steps",
        "get_evidence",
    )
    original_timed = analysis_module._timed

    def counting_timed(
        trace: list[dict[str, Any]],
        name: str,
        function: Any,
        *args: Any,
    ) -> Any:
        top_level_calls.append(name)
        return original_timed(trace, name, function, *args)

    monkeypatch.setattr(analysis_module, "_timed", counting_timed)
    bundle = run_analysis(
        provider,
        DataMode.SYNTHETIC_AGENT_DEMO,
        SHOWCASE_PATIENT,
        None,
    )
    trace_before = bundle.tool_trace.copy()
    assemble_patient_insights(bundle)
    assert top_level_calls == list(names)
    assert bundle.tool_trace == trace_before


def test_missing_attribute_is_preserved_without_inference(
    synthetic_bundle: Any,
) -> None:
    bundle = synthetic_bundle.model_copy(deep=True)
    context = bundle.patient_context
    context["disease_characteristics"]["subsite"] = None
    context["missing_data"]["subsite"] = True
    removed_ids = {
        item["evidence_id"]
        for item in context["evidence_references"]
        if item["field_or_event"] == "subsite"
    }
    context["evidence_references"] = [
        item
        for item in context["evidence_references"]
        if item["evidence_id"] not in removed_ids
    ]
    bundle.evidence = [
        item for item in bundle.evidence if item["evidence_id"] not in removed_ids
    ]
    insights = assemble_patient_insights(bundle)
    assert insights.clinical_snapshot.subsite is None
    missing = next(item for item in insights.statements if item.label == "Subsite")
    assert missing.support_type is SupportType.EXPLICIT_MISSINGNESS
    assert missing.text == "Subsite: Not available."
    assert not missing.evidence_ids


def test_direct_statements_resolve_to_target_patient_evidence(
    synthetic_bundle: Any,
) -> None:
    insights = assemble_patient_insights(synthetic_bundle)
    direct = [
        item
        for item in insights.statements
        if item.support_type is SupportType.DIRECT_EVIDENCE
    ]
    assert direct
    for statement in direct:
        for evidence_id, field in zip(
            statement.evidence_ids,
            statement.evidence_fields,
            strict=True,
        ):
            evidence = insights.evidence_index[evidence_id]
            assert evidence.patient_id == SHOWCASE_PATIENT
            assert evidence.field_or_event == field


def test_cross_patient_evidence_injection_is_rejected(
    synthetic_bundle: Any,
) -> None:
    bundle = synthetic_bundle.model_copy(deep=True)
    store = SyntheticFixtureProvider().store
    foreign_id = store.get_patient_context("SYNTHETIC-DEMO-002")[
        "evidence_references"
    ][0]["evidence_id"]
    bundle.evidence.append(store.get_evidence("SYNTHETIC-DEMO-002", [foreign_id])[0])
    with pytest.raises(ValueError, match="cross-patient"):
        assemble_patient_insights(bundle)


def test_future_dated_workflow_evidence_is_rejected(
    synthetic_bundle: Any,
) -> None:
    bundle = synthetic_bundle.model_copy(deep=True)
    future = datetime.fromisoformat(bundle.as_of) + timedelta(days=1)
    workflow = next(
        item for item in bundle.evidence if item["source_type"] == "synthetic_workflow"
    )
    workflow["value"]["occurred_at"] = future.isoformat()
    with pytest.raises(ValueError, match="future-dated"):
        assemble_patient_insights(bundle)


def test_unsupported_positive_clinical_value_is_rejected(
    synthetic_bundle: Any,
) -> None:
    bundle = synthetic_bundle.model_copy(deep=True)
    bundle.patient_context["disease_characteristics"]["disease_site"] = "invented"
    with pytest.raises(ValueError, match="not supported"):
        assemble_patient_insights(bundle)


def test_empty_or_unresolved_evidence_fails_closed(synthetic_bundle: Any) -> None:
    bundle = synthetic_bundle.model_copy(deep=True)
    bundle.evidence = []
    with pytest.raises(ValueError, match="unresolved"):
        assemble_patient_insights(bundle)


def test_workflow_similarity_and_cohort_values_are_unchanged(
    synthetic_bundle: Any,
) -> None:
    insights = assemble_patient_insights(synthetic_bundle)
    state = synthetic_bundle.workflow_state
    assert insights.current_workflow_stage == state["current_workflow_stage"]
    assert insights.elapsed_days_in_stage == state["elapsed_days_in_current_stage"]
    assert insights.completed_prerequisites == state["completed_prerequisites"]
    assert insights.outstanding_tasks == state["outstanding_tasks"]
    assert [item.model_dump() for item in insights.similarity_summary] == [
        {
            "patient_id": item["patient_id"],
            "score": item["score"],
            "similarity_reasons": item["similarity_reasons"],
            "missing_features": [],
            "feature_comparisons": item["feature_comparisons"],
        }
        for item in synthetic_bundle.similar_patients
    ]
    cohort = synthetic_bundle.cohort_next_steps
    assert insights.cohort_denominator == cohort["cohort_denominator"]
    assert insights.observed_next_event_count == cohort["observed_next_event_count"]
    assert insights.censored_or_incomplete_count == cohort[
        "missing_or_censored_count"
    ]
    assert [item.model_dump() for item in insights.synthetic_next_event_categories] == [
        {
            key: value
            for key, value in item.items()
            if key != "evidence_references"
        }
        for item in cohort["next_event_categories"]
    ]


def test_cohort_claims_are_aggregate_not_patient_predictions(
    synthetic_bundle: Any,
) -> None:
    insights = assemble_patient_insights(synthetic_bundle)
    cohort = next(
        item
        for item in insights.statements
        if item.support_type is SupportType.DESCRIPTIVE_COHORT_AGGREGATE
    )
    assert not cohort.evidence_ids
    assert "prediction" not in cohort.text.lower()
    assert "probability" not in cohort.text.lower()
    assert insights.sample_size_warning == synthetic_bundle.cohort_next_steps[
        "sample_size_warning"
    ]
    assert insights.synthetic_timing_notice == synthetic_bundle.cohort_next_steps[
        "synthetic_timing_notice"
    ]
    assert "stored point-in-time snapshots" in insights.comparison_time_basis


def test_schema_rejects_unknown_fields(synthetic_bundle: Any) -> None:
    payload = assemble_patient_insights(synthetic_bundle).model_dump(mode="json")
    payload["unsupported_claim"] = "invented"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PatientInsights.model_validate(payload)


def test_changed_patient_or_as_of_invalidates_prior_bundle(
    synthetic_bundle: Any,
) -> None:
    assert selection_matches_bundle(
        synthetic_bundle,
        DataMode.SYNTHETIC_AGENT_DEMO,
        SHOWCASE_PATIENT,
        synthetic_bundle.as_of,
    )
    assert not selection_matches_bundle(
        synthetic_bundle,
        DataMode.SYNTHETIC_AGENT_DEMO,
        "SYNTHETIC-DEMO-002",
        None,
    )
    changed = (datetime.fromisoformat(synthetic_bundle.as_of) + timedelta(hours=1))
    assert not selection_matches_bundle(
        synthetic_bundle,
        DataMode.SYNTHETIC_AGENT_DEMO,
        SHOWCASE_PATIENT,
        changed.isoformat(),
    )


@pytest.mark.skipif(
    not Path("data/processed/patients.csv").is_file(),
    reason="authorized private cohort is not present",
)
def test_full_cohort_insights_never_invoke_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_aws(*args: object, **kwargs: object) -> None:
        raise AssertionError("deterministic local insights must not invoke AWS")

    monkeypatch.setattr("boto3.Session", reject_aws)
    provider = LocalCohortProvider(Path("data/processed"))
    patient_id = representative_patient_ids(list(provider.store.patients))[0]
    bundle = run_analysis(provider, DataMode.LOCAL_FULL_COHORT, patient_id, None)
    insights = assemble_patient_insights(bundle)
    assert insights.patient_id == patient_id
    assert insights.data_mode == DataMode.LOCAL_FULL_COHORT.value
