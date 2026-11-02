"""Patient-scoped Strands adapters for the five deterministic M3 tools."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol

from strands import tool


class IntelligenceBackend(Protocol):
    """Subset of IntelligenceStore used by the agent boundary."""

    def get_patient_context(self, patient_id: str) -> dict[str, Any]: ...
    def get_workflow_state(self, patient_id: str, as_of: str) -> dict[str, Any]: ...
    def find_similar_patients(
        self, patient_id: str, k: int = 10, weights: dict[str, float] | None = None
    ) -> list[dict[str, Any]]: ...
    def get_cohort_next_steps(self, patient_ids: list[str]) -> dict[str, Any]: ...
    def get_evidence(
        self, patient_id: str, evidence_ids: list[str]
    ) -> list[dict[str, Any]]: ...


@dataclass
class ToolRuntime:
    store: IntelligenceBackend
    patient_id: str
    max_tool_calls: int = 10
    allowed_cohort_ids: set[str] = field(default_factory=set)
    trace: list[dict[str, Any]] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)


_RUNTIME: ContextVar[ToolRuntime | None] = ContextVar("m4_tool_runtime", default=None)


@contextmanager
def patient_tool_session(
    store: IntelligenceBackend, patient_id: str, max_tool_calls: int = 10
) -> Iterator[ToolRuntime]:
    """Bind one patient and one store to the current execution context."""
    if max_tool_calls < 1:
        raise ValueError("max_tool_calls must be positive")
    runtime = ToolRuntime(
        store=store, patient_id=patient_id, max_tool_calls=max_tool_calls
    )
    token = _RUNTIME.set(runtime)
    try:
        yield runtime
    finally:
        _RUNTIME.reset(token)


def _runtime() -> ToolRuntime:
    runtime = _RUNTIME.get()
    if runtime is None:
        raise RuntimeError("tool called outside a patient-scoped session")
    return runtime


def _target(runtime: ToolRuntime, patient_id: str) -> None:
    if patient_id != runtime.patient_id:
        raise ValueError("cross-patient tool request rejected")


def _start(runtime: ToolRuntime) -> float:
    if len(runtime.trace) >= runtime.max_tool_calls:
        raise RuntimeError("maximum tool-call count reached")
    return time.perf_counter()


def _record(
    runtime: ToolRuntime,
    name: str,
    patient_ids: list[str],
    started: float,
    success: bool,
) -> None:
    runtime.trace.append(
        {
            "sequence": len(runtime.trace) + 1,
            "tool_name": name,
            "patient_ids": patient_ids,
            "success": success,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    )


@tool
def get_patient_context(patient_id: str) -> dict[str, Any]:
    """Return observed clinical context and evidence for the scoped patient."""
    runtime = _runtime()
    started = _start(runtime)
    try:
        _target(runtime, patient_id)
        result = runtime.store.get_patient_context(patient_id)
    except Exception:
        _record(runtime, "get_patient_context", [patient_id], started, False)
        raise
    _record(runtime, "get_patient_context", [patient_id], started, True)
    runtime.outputs["get_patient_context"] = result
    return result


@tool
def get_workflow_state(patient_id: str, as_of: str) -> dict[str, Any]:
    """Reconstruct synthetic point-in-time workflow state for the scoped patient."""
    runtime = _runtime()
    started = _start(runtime)
    try:
        _target(runtime, patient_id)
        result = runtime.store.get_workflow_state(patient_id, as_of)
    except Exception:
        _record(runtime, "get_workflow_state", [patient_id], started, False)
        raise
    _record(runtime, "get_workflow_state", [patient_id], started, True)
    runtime.outputs["get_workflow_state"] = result
    return result


@tool
def find_similar_patients(patient_id: str, k: int = 10) -> list[dict[str, Any]]:
    """Return deterministic similar historical patients for the scoped patient."""
    runtime = _runtime()
    started = _start(runtime)
    try:
        _target(runtime, patient_id)
        result = runtime.store.find_similar_patients(patient_id, k)
        runtime.allowed_cohort_ids = {item["patient_id"] for item in result}
    except Exception:
        _record(runtime, "find_similar_patients", [patient_id], started, False)
        raise
    _record(runtime, "find_similar_patients", [patient_id], started, True)
    runtime.outputs["find_similar_patients"] = result
    return result


@tool
def get_cohort_next_steps(patient_ids: list[str]) -> dict[str, Any]:
    """Summarize synthetic next steps for only the last similarity cohort."""
    runtime = _runtime()
    started = _start(runtime)
    try:
        requested = set(patient_ids)
        if not requested or requested != runtime.allowed_cohort_ids:
            raise ValueError("cohort must exactly match the scoped similarity result")
        result = runtime.store.get_cohort_next_steps(patient_ids)
    except Exception:
        _record(runtime, "get_cohort_next_steps", patient_ids, started, False)
        raise
    _record(runtime, "get_cohort_next_steps", patient_ids, started, True)
    runtime.outputs["get_cohort_next_steps"] = result
    return result


@tool
def get_evidence(patient_id: str, evidence_ids: list[str]) -> list[dict[str, Any]]:
    """Resolve evidence references belonging only to the scoped patient."""
    runtime = _runtime()
    started = _start(runtime)
    try:
        _target(runtime, patient_id)
        result = runtime.store.get_evidence(patient_id, evidence_ids)
    except Exception:
        _record(runtime, "get_evidence", [patient_id], started, False)
        raise
    _record(runtime, "get_evidence", [patient_id], started, True)
    runtime.outputs["get_evidence"] = result
    return result


STRANDS_TOOLS = [
    get_patient_context,
    get_workflow_state,
    find_similar_patients,
    get_cohort_next_steps,
    get_evidence,
]
