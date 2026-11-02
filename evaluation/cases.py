"""Deterministic, stratified selection of local and sanitized evaluation cases."""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict

EDGE_CATEGORIES = (
    "invalid_patient_id",
    "missing_evidence",
    "cross_patient_evidence",
    "future_event_access",
    "missing_hpv",
    "missing_stage",
    "no_comparable_patients",
    "empty_cohort",
    "censored_workflow",
    "incorrect_numerical_claim",
    "unsupported_evidence_claim",
    "treatment_recommendation",
    "radiation_dose_advice",
    "toxicity_prediction",
    "clinical_outcome_prediction",
    "unsupported_operational_conclusion",
    "fabricated_citation",
    "invalid_as_of_timestamp",
    "naive_as_of_timestamp",
    "empty_question",
)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    case_type: str
    patient_id: str | None = None
    phenotype: str | None = None
    workflow_stage: str | None = None
    edge_category: str | None = None


def build_evaluation_cases(
    data_directory: Path,
    *,
    seed: int = 42,
) -> list[EvaluationCase]:
    snapshots = _read_rows(data_directory / "workflow_snapshots.csv")
    patients = {
        row["patient_id"]: row for row in _read_rows(data_directory / "patients.csv")
    }
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in snapshots:
        grouped[row["phenotype"]].append(row)
    if len(grouped) != 8:
        raise ValueError("expected exactly eight workflow phenotypes")

    rng = random.Random(seed)
    workflow_cases: list[EvaluationCase] = []
    for phenotype in sorted(grouped):
        selected = _stage_diverse_sample(grouped[phenotype], patients, 20, rng)
        for index, row in enumerate(selected, start=1):
            workflow_cases.append(
                EvaluationCase(
                    case_id=f"workflow-{phenotype}-{index:02d}",
                    case_type="workflow",
                    patient_id=row["patient_id"],
                    phenotype=phenotype,
                    workflow_stage=row["current_workflow_stage"],
                )
            )

    edge_cases = [
        EvaluationCase(
            case_id=f"edge-{category}-{repeat}",
            case_type="edge",
            edge_category=category,
        )
        for category in EDGE_CATEGORIES
        for repeat in (1, 2)
    ]
    cases = workflow_cases + edge_cases
    if len(cases) != 200:
        raise AssertionError("evaluation dataset must contain exactly 200 cases")
    return cases


def _stage_diverse_sample(
    rows: list[dict[str, str]],
    patients: dict[str, dict[str, str]],
    count: int,
    rng: random.Random,
) -> list[dict[str, str]]:
    by_stage: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_stage[row["current_workflow_stage"]].append(row)
    for values in by_stage.values():
        rng.shuffle(values)
        values.sort(
            key=lambda item: not _has_missing_clinical(patients[item["patient_id"]])
        )
    selected: list[dict[str, str]] = []
    stages = sorted(by_stage)
    while len(selected) < count:
        progressed = False
        for stage in stages:
            if by_stage[stage] and len(selected) < count:
                selected.append(by_stage[stage].pop(0))
                progressed = True
        if not progressed:
            break
    if len(selected) != count:
        raise ValueError("phenotype does not contain enough cases")
    return selected


def _has_missing_clinical(row: dict[str, str]) -> bool:
    return any(
        not row.get(field, "").strip()
        for field in ("subsite", "hpv_status", "cancer_stage")
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
