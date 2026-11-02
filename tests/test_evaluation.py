from __future__ import annotations

import csv
from pathlib import Path

import pytest

from evaluation.agent_harness import evaluate_agent_artifacts
from evaluation.cases import build_evaluation_cases
from evaluation.costs import PricingInputs, modeled_cost
from evaluation.live_runner import run_live_batch
from evaluation.metrics import RateMetric, latency_summary, percentile
from evaluation.runner import run_evaluation

DATA = Path("data/processed")


def test_case_set_is_deterministic_stratified_and_complete() -> None:
    first = build_evaluation_cases(DATA)
    second = build_evaluation_cases(DATA)
    assert first == second
    assert len(first) == 200
    workflow = [case for case in first if case.case_type == "workflow"]
    edge = [case for case in first if case.case_type == "edge"]
    assert len(workflow) == 160
    assert len(edge) == 40
    assert {
        case.phenotype: sum(item.phenotype == case.phenotype for item in workflow)
        for case in workflow
    } == {phenotype: 20 for phenotype in {case.phenotype for case in workflow}}
    assert all(case.patient_id for case in workflow)
    assert len({case.workflow_stage for case in workflow}) > 4


def test_rate_and_latency_math() -> None:
    assert RateMetric.from_counts(3, 4).rate == 0.75
    assert RateMetric.from_counts(0, 0).status == "NOT_MEASURED"
    assert percentile([1.0, 2.0, 3.0], 50) == 2.0
    summary = latency_summary([1.0, 2.0, 3.0], 1)
    assert summary["sample_size"] == 4
    assert summary["error_rate"] == 0.25


def test_agent_harness_does_not_manufacture_metrics() -> None:
    result = evaluate_agent_artifacts([])
    assert result["status"] == "NOT_MEASURED"
    assert result["artifact_count"] == 0
    assert result["json_validity"]["rate"] is None
    assert result["unsupported_claim_rate"]["status"] == "NOT_MEASURED"


def test_costs_require_explicit_versioned_pricing() -> None:
    assert modeled_cost(10, 10, None)["status"] == "NOT_MEASURED"
    pricing = PricingInputs(
        model_id="fixture-model",
        currency="USD",
        effective_date="2026-01-01",
        source="test fixture",
        input_price_per_million_tokens=1,
        output_price_per_million_tokens=2,
    )
    assert modeled_cost(1_000_000, 1_000_000, pricing)["modeled_cost"] == 3


def test_live_runner_is_disabled() -> None:
    with pytest.raises(PermissionError, match="disabled"):
        run_live_batch()


def test_full_runner_writes_only_sanitized_aggregate_artifacts(tmp_path: Path) -> None:
    summary = run_evaluation(DATA, tmp_path)
    assert summary["evaluation_case_count"] == 200
    assert summary["gold_snapshot_count"] == 3346
    assert summary["live_bedrock_invocations"] == 0
    expected = {
        "summary.json",
        "case_results.csv",
        "metrics.json",
        "failure_analysis.md",
        "report.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    combined = "\n".join(path.read_text("utf-8") for path in tmp_path.iterdir())
    assert "RADCURE-" not in combined
    with (tmp_path / "case_results.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert "patient_id" not in (reader.fieldnames or [])
        assert len(list(reader)) == 200
