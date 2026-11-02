"""Evaluation of explicitly supplied, sanitized M4 result artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from evaluation.metrics import RateMetric
from rad_intel.agent.bedrock_agent import OperationalResult


def evaluate_agent_artifacts(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        return {
            "status": "NOT_MEASURED",
            "artifact_count": 0,
            "reason": "No explicitly supplied sanitized M4 artifacts.",
            "json_validity": RateMetric.from_counts(0, 0).model_dump(),
            "required_tool_completion": RateMetric.from_counts(0, 0).model_dump(),
            "narrative_evidence_grounding": RateMetric.from_counts(0, 0).model_dump(),
            "unsupported_claim_rate": RateMetric.from_counts(0, 0).model_dump(),
            "prohibited_clinical_recommendation_rate": RateMetric.from_counts(
                0, 0
            ).model_dump(),
            "patient_isolation": RateMetric.from_counts(0, 0).model_dump(),
            "token_consumption": "NOT_MEASURED",
            "end_to_end_latency": "NOT_MEASURED",
            "live_batch_runner": "DISABLED",
        }
    valid = tools = 0
    for path in paths:
        try:
            result = OperationalResult.model_validate_json(path.read_text("utf-8"))
        except (OSError, ValidationError, json.JSONDecodeError):
            continue
        valid += 1
        required = {
            "get_patient_context",
            "get_workflow_state",
            "find_similar_patients",
            "get_cohort_next_steps",
            "get_evidence",
        }
        completed = {
            item["tool_name"]
            for item in result.tool_execution_trace
            if item.get("success")
        }
        tools += completed == required
    return {
        "status": "MEASURED",
        "artifact_count": len(paths),
        "json_validity": RateMetric.from_counts(valid, len(paths)).model_dump(),
        "required_tool_completion": RateMetric.from_counts(
            tools, len(paths)
        ).model_dump(),
        "narrative_evidence_grounding": RateMetric.from_counts(0, 0).model_dump(),
        "unsupported_claim_rate": RateMetric.from_counts(0, 0).model_dump(),
        "prohibited_clinical_recommendation_rate": RateMetric.from_counts(
            0, 0
        ).model_dump(),
        "patient_isolation": RateMetric.from_counts(0, 0).model_dump(),
        "token_consumption": "available_per_validated_artifact",
        "end_to_end_latency": "available_per_validated_artifact",
        "live_batch_runner": "DISABLED",
    }


HISTORICAL_M4_OBSERVATION = {
    "sample_size": 1,
    "input_tokens": 6231,
    "output_tokens": 595,
    "latency_ms": 4790.511,
    "distribution_estimate": False,
    "note": "Historical single validated M4 smoke observation; not rerun by M7.",
}
