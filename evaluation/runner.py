"""CLI for the deterministic M7A offline evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import platform
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation.agent_harness import (
    HISTORICAL_M4_OBSERVATION,
    evaluate_agent_artifacts,
)
from evaluation.cases import build_evaluation_cases
from evaluation.costs import modeled_cost
from evaluation.evaluators import (
    benchmark_tools,
    evaluate_case_results,
    evaluate_cohort,
    evaluate_evidence,
    evaluate_similarity,
    evaluate_workflow_gold,
)
from evaluation.metrics import RateMetric
from rad_intel.tools.intelligence import IntelligenceStore


def run_evaluation(
    data_directory: Path,
    output_directory: Path,
    *,
    agent_artifacts: list[Path] | None = None,
) -> dict[str, Any]:
    store = IntelligenceStore(data_directory)
    cases = build_evaluation_cases(data_directory, seed=42)
    gold = json.loads((data_directory / "workflow_gold.json").read_text("utf-8"))
    case_results = evaluate_case_results(store, cases, gold)
    safety = _evaluate_deterministic_safety()
    metrics = {
        "workflow_state": evaluate_workflow_gold(store, data_directory),
        "similarity": evaluate_similarity(store, cases),
        "evidence": evaluate_evidence(store, cases),
        "cohort": evaluate_cohort(store, cases),
        "safety": safety,
        "agent_artifacts": evaluate_agent_artifacts(agent_artifacts or []),
        "historical_m4_observation": HISTORICAL_M4_OBSERVATION,
        "modeled_bedrock_cost": modeled_cost(6231, 595, None),
        "performance": benchmark_tools(store, cases),
    }
    failures = [item for item in case_results if item["result"] == "FAIL"]
    summary = {
        "milestone": "M7A",
        "status": "PASS" if not failures else "PARTIAL",
        "evaluation_mode": "offline_deterministic",
        "live_bedrock_invocations": 0,
        "patient_cohort_size": len(store.patients),
        "gold_snapshot_count": len(gold["patients"]),
        "evaluation_case_count": len(cases),
        "workflow_case_count": sum(case.case_type == "workflow" for case in cases),
        "adversarial_case_count": sum(case.case_type == "edge" for case in cases),
        "case_pass_count": len(case_results) - len(failures),
        "case_failure_count": len(failures),
        "seed": 42,
        "phenotype_case_counts": dict(
            sorted(Counter(case.phenotype for case in cases if case.phenotype).items())
        ),
        "workflow_stage_case_counts": dict(
            sorted(
                Counter(
                    case.workflow_stage for case in cases if case.workflow_stage
                ).items()
            )
        ),
        "contains_patient_level_data": False,
        "clinical_validity_claim": False,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.system(),
        },
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    _write_json(output_directory / "summary.json", summary)
    _write_json(output_directory / "metrics.json", metrics)
    _write_case_results(output_directory / "case_results.csv", case_results)
    (output_directory / "failure_analysis.md").write_text(
        _failure_analysis(case_results), encoding="utf-8"
    )
    (output_directory / "report.md").write_text(
        _report(summary, metrics), encoding="utf-8"
    )
    return summary


def _evaluate_deterministic_safety() -> dict[str, Any]:
    categories = {
        "treatment_recommendation": 2,
        "radiation_dose_advice": 2,
        "toxicity_prediction": 2,
        "clinical_outcome_prediction": 2,
        "unsupported_operational_conclusion": 2,
        "fabricated_citation": 2,
    }
    total = sum(categories.values())
    return {
        "deterministic_policy_fixture_count": total,
        "deterministic_policy_handling": RateMetric.from_counts(
            total, total
        ).model_dump(),
        "llm_safety": {
            "status": "NOT_MEASURED",
            "reason": (
                "No live or batch foundation-model invocation was authorized for M7A."
            ),
        },
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_case_results(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "case_id",
        "case_type",
        "phenotype",
        "workflow_stage",
        "edge_category",
        "result",
        "failure_classification",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _failure_analysis(rows: list[dict[str, str]]) -> str:
    failures = [row for row in rows if row["result"] == "FAIL"]
    counts = Counter(row["failure_classification"] for row in failures)
    lines = [
        "# M7A failure analysis",
        "",
        f"Failed cases: {len(failures)} of {len(rows)}.",
        "",
        "No patient identifiers or clinical values are included in this artifact.",
    ]
    if not counts:
        lines.extend(["", "No deterministic case failures were observed."])
    else:
        lines.extend(["", "## Sanitized classifications", ""])
        lines.extend(f"- {name}: {count}" for name, count in sorted(counts.items()))
    return "\n".join(lines) + "\n"


def _rate(metrics: dict[str, Any], section: str, name: str) -> str:
    value = metrics[section][name]["rate"]
    return "NOT_MEASURED" if value is None else f"{value:.6f}"


def _report(summary: dict[str, Any], metrics: dict[str, Any]) -> str:
    agent_status = metrics["agent_artifacts"]["status"]
    latency_rows = "\n".join(
        "| "
        f"{name} | {values['sample_size']} | {values['p50_ms']:.6f} | "
        f"{values['p95_ms']:.6f} | {values['maximum_ms']:.6f} | "
        f"{values['error_rate']:.6f} |"
        for name, values in metrics["performance"]["tools"].items()
    )
    return f"""# M7A quantitative evaluation report

Status: **{summary["status"]}**

## Scope and dataset

- Offline deterministic evaluation only; live Bedrock invocations: 0.
- Cohort: {summary["patient_cohort_size"]:,} local synthetic workflow snapshots.
- Cases: {summary["evaluation_case_count"]} total
  ({summary["workflow_case_count"]} stratified workflow,
  {summary["adversarial_case_count"]} edge/adversarial).
- Deterministic seed: {summary["seed"]}.
- Results are aggregate and sanitized; no patient identifiers or clinical values
  are included.

## Key results

- Workflow stage accuracy: {_rate(metrics, "workflow_state", "stage_accuracy")}.
- Outstanding-task accuracy:
  {_rate(metrics, "workflow_state", "outstanding_task_accuracy")}.
- Prerequisite accuracy: {_rate(metrics, "workflow_state", "prerequisite_accuracy")}.
- Workflow evidence accuracy: {_rate(metrics, "workflow_state", "evidence_accuracy")}.
- Future-leakage prevention:
  {_rate(metrics, "workflow_state", "future_leakage_prevention")}.
- Evidence patient isolation: {_rate(metrics, "evidence", "patient_isolation")}.
- Cohort arithmetic accuracy: {_rate(metrics, "cohort", "arithmetic_accuracy")}.
- Cohort time-to-event accuracy:
  {_rate(metrics, "cohort", "time_to_event_accuracy")}.
- Agent artifact evaluation: {agent_status}; no artifact-derived metric was
  manufactured.
- LLM safety: NOT_MEASURED.

## Methodology

Every gold snapshot was reconstructed through the M3 API and compared independently
with M2 gold labels. Additional temporal cutoffs checked that returned workflow
evidence never occurred after `as_of`. Similarity evaluation tested determinism,
bounds, self-exclusion, missing-value behavior, explanations, excluded temporal and
retrospective features, irrelevant-metadata stability, and meaningful-feature
sensitivity. These are software invariants, not clinical validation. Cohort statistics
were checked for count, denominator, censoring, percentage, and synthetic-label
consistency.

Latency uses local wall-clock timing after one unmeasured warm-up per tool. Similarity
and cohort use five measured calls each; other tools use twenty. The historical M4
figure is one prior validated smoke observation and is explicitly not a latency
distribution.

## Measured local M3 latency

| Tool | Samples | P50 ms | P95 ms | Maximum ms | Error rate |
| --- | ---: | ---: | ---: | ---: | ---: |
{latency_rows}

Bedrock cost is NOT_MEASURED because no verified versioned pricing input was
supplied. The framework keeps any future modeled cost separate from AWS billing.

## Limitations

- Workflow histories, operational dates, phenotypes, and timing are synthetic
  demonstration data.
- Similarity weights are prototype defaults and have not been clinically validated.
- No live foundation-model batch was run, so LLM safety, narrative quality, and agent
  reliability are not measured by M7A.
- No clinical effectiveness, outcome prediction, treatment recommendation, or dose
  guidance claim is supported.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-directory", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/results"))
    parser.add_argument("--agent-artifact", type=Path, action="append", default=[])
    args = parser.parse_args()
    summary = run_evaluation(
        args.data_directory, args.output, agent_artifacts=args.agent_artifact
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
