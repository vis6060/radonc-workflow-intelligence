from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from rad_intel.agent.bedrock_agent import ExecutionMetrics, WorkflowIntelligenceAgent
from rad_intel.agent.demo import (
    SYNTHETIC_AS_OF,
    SYNTHETIC_PATIENT,
    SyntheticSmokeStore,
)
from rad_intel.agentcore_runtime.runtime_service import (
    LocalCohortProvider,
    SyntheticFixtureProvider,
)
from rad_intel.ui.analysis import (
    DataMode,
    load_recorded_agent_artifact,
    representative_patient_ids,
    run_analysis,
)


def test_representative_patient_ids_are_real_and_stable() -> None:
    provider = LocalCohortProvider(Path("data/processed"))
    available = set(provider.store.patients)
    examples = representative_patient_ids(list(available))
    assert len(examples) == 5
    assert examples == representative_patient_ids(list(reversed(sorted(available))))
    assert set(examples) <= available


def test_local_full_cohort_binds_exact_m3_results() -> None:
    provider = LocalCohortProvider(Path("data/processed"))
    patient_id = representative_patient_ids(list(provider.store.patients))[0]
    analysis = run_analysis(
        provider,
        DataMode.LOCAL_FULL_COHORT,
        patient_id,
        None,
    )
    assert analysis.patient_context == provider.store.get_patient_context(patient_id)
    assert analysis.workflow_state == provider.store.get_workflow_state(
        patient_id, analysis.as_of
    )
    assert analysis.similar_patients == provider.store.find_similar_patients(
        patient_id, 10
    )
    cohort_ids = [item["patient_id"] for item in analysis.similar_patients]
    assert analysis.cohort_next_steps == provider.store.get_cohort_next_steps(
        cohort_ids
    )
    assert len(analysis.similar_patients) == 10
    assert len(provider.store.patients) == 3346


def test_point_in_time_timeline_contains_no_future_events() -> None:
    provider = LocalCohortProvider(Path("data/processed"))
    patient_id = representative_patient_ids(list(provider.store.patients))[1]
    snapshot = provider.store.snapshots[patient_id]["as_of"]
    analysis = run_analysis(
        provider,
        DataMode.LOCAL_FULL_COHORT,
        patient_id,
        snapshot,
    )
    cutoff = datetime.fromisoformat(snapshot)
    assert all(
        datetime.fromisoformat(item["occurred_at"]) <= cutoff
        for item in analysis.timeline
    )
    visible_ids = {item["evidence_id"] for item in analysis.timeline}
    state_ids = {
        item["evidence_id"]
        for item in analysis.workflow_state["evidence_references"]
    }
    assert visible_ids == state_ids


def test_similarity_cohort_and_evidence_integrity() -> None:
    provider = LocalCohortProvider(Path("data/processed"))
    patient_id = representative_patient_ids(list(provider.store.patients))[2]
    analysis = run_analysis(
        provider,
        DataMode.LOCAL_FULL_COHORT,
        patient_id,
        None,
    )
    assert all(0 <= item["score"] <= 1 for item in analysis.similar_patients)
    assert all(item["patient_id"] != patient_id for item in analysis.similar_patients)
    cohort = analysis.cohort_next_steps
    assert sum(item["count"] for item in cohort["next_event_categories"]) == cohort[
        "observed_next_event_count"
    ]
    assert cohort["observed_next_event_count"] + cohort[
        "missing_or_censored_count"
    ] == cohort["cohort_denominator"]
    assert all(item["patient_id"] == patient_id for item in analysis.evidence)
    assert {item["source_type"] for item in analysis.evidence} <= {
        "observed_clinical",
        "synthetic_workflow",
    }


def test_synthetic_mode_uses_fixture_and_never_calls_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_aws(*args: object, **kwargs: object) -> None:
        raise AssertionError("AWS must not be called by the UI")

    monkeypatch.setattr("boto3.Session", reject_aws)
    provider = SyntheticFixtureProvider()
    analysis = run_analysis(
        provider,
        DataMode.SYNTHETIC_AGENT_DEMO,
        SYNTHETIC_PATIENT,
        None,
    )
    assert analysis.patient_id == SYNTHETIC_PATIENT
    assert analysis.patient_context["provenance"]["source_type"] == (
        "fictional_showcase_clinical"
    )
    assert len(provider.store.patients) == 32
    assert [item["tool_name"] for item in analysis.tool_trace] == [
        "get_patient_context",
        "get_workflow_state",
        "find_similar_patients",
        "get_cohort_next_steps",
        "get_evidence",
    ]
    assert all(
        item["trace_type"] == "deterministic_local_execution"
        for item in analysis.tool_trace
    )


def test_invalid_patient_is_rejected_in_both_modes() -> None:
    providers = [
        (LocalCohortProvider(Path("data/processed")), DataMode.LOCAL_FULL_COHORT),
        (SyntheticFixtureProvider(), DataMode.SYNTHETIC_AGENT_DEMO),
    ]
    for provider, mode in providers:
        with pytest.raises(KeyError, match="not available"):
            run_analysis(provider, mode, "INVENTED-PATIENT", None)


def test_recorded_agent_artifacts_are_explicit_and_strict(tmp_path: Path) -> None:
    provider = SyntheticFixtureProvider()
    assert load_recorded_agent_artifact(None, provider) is None
    smoke_store = SyntheticSmokeStore()
    result = WorkflowIntelligenceAgent(smoke_store).build_offline(
        SYNTHETIC_PATIENT,
        SYNTHETIC_AS_OF,
        k=10,
    )
    offline_path = tmp_path / "offline.json"
    offline_path.write_text(result.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="not a live Bedrock result"):
        load_recorded_agent_artifact(offline_path, provider)

    result.execution_metrics = ExecutionMetrics(
        mode="bedrock",
        model_id="verified-test-model",
        stop_reason="end_turn",
        latency_ms=1.0,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
    )
    result.grounded_agent_narrative = (
        "The available context is synthetic and preserves missing attributes without "
        "inference. Consultation is complete while authorization remains the next "
        "outstanding operational task. Comparable demonstration records and cohort "
        "observations were returned by deterministic tools. Supporting workflow "
        "evidence remains scoped to this synthetic patient. Human review and source "
        "verification remain necessary, and no clinical guidance is provided."
    )
    result.response_assembly_method = "deterministic_python_with_plain_text"
    recorded_path = tmp_path / "recorded.json"
    recorded_path.write_text(
        json.dumps(result.model_dump(mode="json")), encoding="utf-8"
    )
    recorded = load_recorded_agent_artifact(recorded_path, provider)
    assert recorded is not None
    assert recorded.trace_label == "Recorded live Bedrock agent execution"
    assert recorded.response.execution_metrics.total_tokens == 15


def test_streamlit_app_imports_and_starts_without_analysis() -> None:
    app_path = Path("src/rad_intel/ui/app.py").resolve()
    app = AppTest.from_file(app_path, default_timeout=10).run()
    assert not app.exception
    assert app.title[0].value == "Radiation Oncology Workflow Intelligence"
    assert app.button[0].label == "Run Analysis"
    markdown = " ".join(item.value for item in app.markdown)
    assert "3,346 RADCURE clinical records" in markdown
    assert "32 entirely fictional" in markdown


def test_streamlit_synthetic_walkthrough_populates_four_panels() -> None:
    app_path = Path("src/rad_intel/ui/app.py").resolve()
    app = AppTest.from_file(app_path, default_timeout=10).run()
    app.radio[0].set_value(DataMode.SYNTHETIC_AGENT_DEMO.value).run()
    app.button[0].click().run(timeout=10)
    assert not app.exception
    headings = [item.value for item in app.subheader]
    assert headings == [
        "1 · Patient context",
        "2 · Workflow state",
        "3 · Similar patients",
        "4 · Historical next steps",
    ]
    info_text = " ".join(item.value for item in app.info)
    assert "No authentic sanitized live-agent artifact" in info_text
