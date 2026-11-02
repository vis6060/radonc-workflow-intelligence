"""Pure, testable data binding for the four-panel Streamlit demonstration."""

from __future__ import annotations

import json
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from rad_intel.agent.bedrock_agent import OperationalResult, WorkflowIntelligenceAgent
from rad_intel.agent.demo import SYNTHETIC_PATIENT, SyntheticSmokeStore
from rad_intel.agentcore_runtime.runtime_service import DataProvider


class DataMode(StrEnum):
    LOCAL_FULL_COHORT = "Local Full Cohort"
    SYNTHETIC_AGENT_DEMO = "Synthetic Agent Demonstration"


class AnalysisBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: DataMode
    patient_id: str
    as_of: str
    patient_context: dict[str, Any]
    workflow_state: dict[str, Any]
    timeline: list[dict[str, Any]]
    similar_patients: list[dict[str, Any]]
    cohort_next_steps: dict[str, Any]
    evidence: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    validation_status: str


class RecordedAgentArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    trace_label: str
    response: OperationalResult
    validation_status: str


def representative_patient_ids(patient_ids: list[str], count: int = 5) -> list[str]:
    """Select stable examples from real available identifiers, never inventing IDs."""
    ordered = sorted(set(patient_ids))
    if not ordered or count < 1:
        return []
    if len(ordered) <= count:
        return ordered
    positions = [
        round(index * (len(ordered) - 1) / (count - 1))
        for index in range(count)
    ]
    return [ordered[position] for position in positions]


def available_patient_ids(provider: DataProvider) -> list[str]:
    patients = getattr(provider.store, "patients", None)
    if isinstance(patients, dict):
        return sorted(patients)
    if getattr(provider.store, "synthetic_smoke_fixture", False):
        return [SYNTHETIC_PATIENT]
    raise ValueError("selected provider does not expose patient identifiers")


def run_analysis(
    provider: DataProvider,
    mode: DataMode,
    patient_id: str,
    as_of: str | None,
    *,
    k: int = 10,
) -> AnalysisBundle:
    """Execute the five real M3 operations and capture their local trace."""
    if patient_id not in available_patient_ids(provider):
        raise KeyError("patient is not available in the selected data mode")
    resolved_as_of = provider.resolve_as_of(patient_id, as_of)
    store = provider.store
    trace: list[dict[str, Any]] = []

    context = _timed(
        trace,
        "get_patient_context",
        store.get_patient_context,
        patient_id,
    )
    state = _timed(
        trace,
        "get_workflow_state",
        store.get_workflow_state,
        patient_id,
        resolved_as_of,
    )
    similar = _timed(
        trace,
        "find_similar_patients",
        store.find_similar_patients,
        patient_id,
        k,
    )
    cohort_ids = [item["patient_id"] for item in similar]
    cohort = _timed(
        trace,
        "get_cohort_next_steps",
        store.get_cohort_next_steps,
        cohort_ids,
    )
    evidence_ids = list(
        dict.fromkeys(
            item["evidence_id"]
            for item in (
                context["evidence_references"] + state["evidence_references"]
            )
        )
    )
    evidence = _timed(
        trace,
        "get_evidence",
        store.get_evidence,
        patient_id,
        evidence_ids,
    )
    _validate_bundle(patient_id, resolved_as_of, similar, cohort, evidence, state)
    timeline = [
        {
            "event": item["field_or_event"],
            "occurred_at": item["value"].get("occurred_at"),
            "evidence_id": item["evidence_id"],
            "source_type": item["source_type"],
        }
        for item in evidence
        if item["source_type"] == "synthetic_workflow"
        and isinstance(item.get("value"), dict)
    ]
    timeline.sort(key=lambda item: item["occurred_at"] or "")
    return AnalysisBundle(
        mode=mode,
        patient_id=patient_id,
        as_of=state["as_of"],
        patient_context=context,
        workflow_state=state,
        timeline=timeline,
        similar_patients=similar,
        cohort_next_steps=cohort,
        evidence=evidence,
        tool_trace=trace,
        validation_status=(
            "Deterministic M3 outputs validated; no model was invoked."
        ),
    )


def load_recorded_agent_artifact(
    path: Path | None,
    provider: DataProvider,
) -> RecordedAgentArtifact | None:
    """Load only an authentic, sanitized M4 artifact explicitly supplied on disk."""
    if path is None or not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    result = OperationalResult.model_validate(raw)
    metrics = result.execution_metrics
    if (
        metrics.mode != "bedrock"
        or not metrics.model_id
        or metrics.stop_reason != "end_turn"
        or metrics.total_tokens <= 0
        or not result.grounded_agent_narrative
        or result.response_assembly_method
        != "deterministic_python_with_plain_text"
    ):
        raise ValueError("recorded artifact is not a live Bedrock result")
    if result.patient_context.get("patient_id") != SYNTHETIC_PATIENT:
        raise ValueError("recorded artifact is not the synthetic demonstration")
    as_of = result.current_workflow_state["as_of"]
    # Recorded M4 artifacts are grounded in the fixed one-patient smoke fixture.
    # The richer M6.1 showcase deliberately remains a separate data product.
    WorkflowIntelligenceAgent(SyntheticSmokeStore()).validate(
        result,
        SYNTHETIC_PATIENT,
        as_of,
        len(result.similar_historical_patients),
    )
    return RecordedAgentArtifact(
        source_path=str(path),
        trace_label="Recorded live Bedrock agent execution",
        response=result,
        validation_status="Artifact schema and deterministic M3 grounding validated.",
    )


def missing_comparison_features(item: dict[str, Any]) -> list[str]:
    expected = {
        "age",
        "disease_site",
        "subsite",
        "t",
        "n",
        "m",
        "stage",
        "hpv_status",
        "workflow_stage",
        "completed_prerequisites",
        "outstanding_tasks",
        "elapsed_days",
    }
    return sorted(expected - set(item.get("feature_comparisons", {})))


def _timed(
    trace: list[dict[str, Any]],
    name: str,
    function: Any,
    *args: Any,
) -> Any:
    started = time.perf_counter()
    try:
        result = function(*args)
    except Exception:
        trace.append(
            {
                "sequence": len(trace) + 1,
                "tool_name": name,
                "success": False,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "trace_type": "deterministic_local_execution",
            }
        )
        raise
    trace.append(
        {
            "sequence": len(trace) + 1,
            "tool_name": name,
            "success": True,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "trace_type": "deterministic_local_execution",
        }
    )
    return result


def _validate_bundle(
    patient_id: str,
    as_of: str,
    similar: list[dict[str, Any]],
    cohort: dict[str, Any],
    evidence: list[dict[str, Any]],
    state: dict[str, Any],
) -> None:
    if state["patient_id"] != patient_id or state["as_of"] != as_of:
        raise ValueError("workflow state is outside the selected patient/time scope")
    if len(similar) != cohort["cohort_denominator"]:
        raise ValueError("cohort denominator does not match similarity results")
    if any(item["patient_id"] != patient_id for item in evidence):
        raise ValueError("cross-patient evidence was returned")
    state_ids = {item["evidence_id"] for item in state["evidence_references"]}
    resolved_ids = {item["evidence_id"] for item in evidence}
    if not state_ids <= resolved_ids:
        raise ValueError("workflow evidence resolution is incomplete")
