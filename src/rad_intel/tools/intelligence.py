"""Read-only deterministic clinical and synthetic workflow intelligence."""

from __future__ import annotations

import csv
import json
import statistics
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from rad_intel.similarity import rank_similar
from rad_intel.workflow_generator import BASE_EVENT_TYPES

DEFAULT_DATA_DIRECTORY = Path("data/processed")
CLINICAL_NAMESPACE = uuid.UUID("9f6550fb-a931-4127-858f-3ce44199ac2f")
RETROSPECTIVE_FIELDS = {"systemic_therapy", "radiation_treatment_characteristics"}


class IntelligenceStore:
    """Indexed local artifact reader; never reads workflow gold labels."""

    def __init__(self, data_directory: Path = DEFAULT_DATA_DIRECTORY) -> None:
        self.data_directory = data_directory
        self.patients = self._read_indexed("patients.csv", "patient_id")
        self.events = self._read_grouped("workflow_events.csv", "patient_id")
        self.snapshots = self._read_indexed("workflow_snapshots.csv", "patient_id")
        self._clinical_evidence: dict[tuple[str, str], dict[str, Any]] = {}
        self._workflow_evidence: dict[tuple[str, str], dict[str, Any]] = {}
        self._build_evidence_indexes()

    def get_patient_context(self, patient_id: str) -> dict[str, Any]:
        row = self._patient(patient_id)
        fields = {
            name: _decode(row.get(name, ""))
            for name in (
                "disease_site",
                "subsite",
                "age",
                "cancer_stage",
                "hpv_status",
                "systemic_therapy",
                "radiation_treatment_characteristics",
            )
        }
        evidence = []
        for name, value in fields.items():
            if value is not None:
                item = self._clinical_evidence[(patient_id, name)]
                evidence.append(
                    {key: value for key, value in item.items() if key != "value"}
                )
        return {
            "patient_id": patient_id,
            "disease_characteristics": {
                key: fields[key]
                for key in ("disease_site", "subsite", "cancer_stage", "hpv_status")
            },
            "age": fields["age"],
            "treatment_attributes": {
                key: {
                    "value": fields[key],
                    "temporal_label": (
                        "retrospective treatment record; availability at earlier "
                        "workflow stages is not established"
                    ),
                }
                for key in RETROSPECTIVE_FIELDS
            },
            "missing_data": {key: value is None for key, value in fields.items()},
            "evidence_references": evidence,
            "provenance": {
                "source_type": "observed_clinical",
                "source_name": row["clinical_source_name"],
                "source_file": row["clinical_source_file"],
                "source_sha256": row["clinical_source_sha256"],
                "source_record_identifier": row["clinical_source_record_identifier"],
            },
        }

    def get_workflow_state(
        self, patient_id: str, as_of: datetime | str
    ) -> dict[str, Any]:
        cutoff = _aware(as_of)
        rows = self._event_rows(patient_id)
        visible = [row for row in rows if _aware(row["occurred_at"]) <= cutoff]
        if not visible:
            return {
                "patient_id": patient_id,
                "as_of": cutoff.isoformat(),
                "current_workflow_stage": "not_started",
                "completed_prerequisites": [],
                "outstanding_tasks": [BASE_EVENT_TYPES[0]],
                "elapsed_days_in_current_stage": None,
                "evidence_references": [],
                "provenance": "synthetic_workflow",
            }
        types = [row["event_type"] for row in visible]
        completed = [name for name in BASE_EVENT_TYPES if name in types]
        stage = completed[-1]
        outstanding = (
            [BASE_EVENT_TYPES[len(completed)]]
            if len(completed) < len(BASE_EVENT_TYPES)
            else []
        )
        if "consult_no_show" in types and "consult_rescheduled" not in types:
            stage = "consult_no_show"
            outstanding.insert(0, "consult_rescheduled")
        if (
            "hospitalization_interruption_started" in types
            and "hospitalization_interruption_resolved" not in types
        ):
            stage = "hospitalization_interruption"
            outstanding.insert(0, "hospitalization_interruption_resolved")
        stage_row = next(
            row
            for row in reversed(visible)
            if row["event_type"] == stage
            or stage == "hospitalization_interruption"
            and row["event_type"] == "hospitalization_interruption_started"
        )
        return {
            "patient_id": patient_id,
            "as_of": cutoff.isoformat(),
            "current_workflow_stage": stage,
            "completed_prerequisites": completed,
            "outstanding_tasks": outstanding,
            "elapsed_days_in_current_stage": round(
                (cutoff - _aware(stage_row["occurred_at"])).total_seconds() / 86400, 6
            ),
            "evidence_references": [
                self._workflow_evidence[(patient_id, row["evidence_id"])]
                for row in visible
            ],
            "provenance": "synthetic_workflow",
        }

    def find_similar_patients(
        self, patient_id: str, k: int = 10, weights: dict[str, float] | None = None
    ) -> list[dict[str, Any]]:
        if k < 1:
            raise ValueError("k must be positive")
        features = {pid: self._similarity_features(pid) for pid in self.patients}
        candidates = [value for pid, value in features.items() if pid != patient_id]
        self._patient(patient_id)
        return rank_similar(features[patient_id], candidates, k, weights)

    def get_cohort_next_steps(self, patient_ids: list[str]) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(patient_ids))
        next_rows = []
        incomplete = 0
        for patient_id in unique_ids:
            snapshot = self._snapshot(patient_id)
            cutoff = _aware(snapshot["as_of"])
            future = [
                row
                for row in self._event_rows(patient_id)
                if _aware(row["occurred_at"]) > cutoff
            ]
            if not future:
                incomplete += 1
                continue
            row = future[0]
            next_rows.append(
                (
                    patient_id,
                    row,
                    (_aware(row["occurred_at"]) - cutoff).total_seconds() / 86400,
                )
            )
        counts = Counter(row[1]["event_type"] for row in next_rows)
        denominator = len(unique_ids)
        categories = []
        for event_type, count in sorted(counts.items()):
            times = [
                item[2] for item in next_rows if item[1]["event_type"] == event_type
            ]
            categories.append(
                {
                    "event_type": event_type,
                    "count": count,
                    "percentage_of_cohort": round(count / denominator * 100, 6)
                    if denominator
                    else 0.0,
                    "synthetic_time_to_next_event_days": {
                        "minimum": round(min(times), 6),
                        "median": round(statistics.median(times), 6),
                        "mean": round(statistics.fmean(times), 6),
                        "maximum": round(max(times), 6),
                    },
                    "evidence_references": [
                        self._workflow_evidence[(pid, row["evidence_id"])]
                        for pid, row, _ in next_rows
                        if row["event_type"] == event_type
                    ],
                }
            )
        return {
            "cohort_denominator": denominator,
            "observed_next_event_count": len(next_rows),
            "missing_or_censored_count": incomplete,
            "next_event_categories": categories,
            "sample_size_warning": (
                "Small descriptive cohort; do not interpret as a prediction."
            )
            if denominator < 30
            else None,
            "synthetic_timing_notice": (
                "SYNTHETIC demonstration timing; not clinically validated."
            ),
        }

    def get_evidence(
        self, patient_id: str, evidence_ids: list[str]
    ) -> list[dict[str, Any]]:
        self._patient(patient_id)
        resolved = []
        for evidence_id in evidence_ids:
            item = self._clinical_evidence.get(
                (patient_id, evidence_id)
            ) or self._workflow_evidence.get((patient_id, evidence_id))
            if item is None:
                raise ValueError(
                    "evidence reference does not belong to requested patient"
                )
            resolved.append(item)
        return resolved

    def _similarity_features(self, patient_id: str) -> dict[str, Any]:
        row = self._patient(patient_id)
        stage = _decode(row.get("cancer_stage", "")) or {}
        snapshot = self._snapshot(patient_id)
        state = self.get_workflow_state(patient_id, snapshot["as_of"])
        return {
            "patient_id": patient_id,
            "age": _number(row.get("age")),
            "disease_site": _blank(row.get("disease_site")),
            "subsite": _blank(row.get("subsite")),
            "t": stage.get("t"),
            "n": stage.get("n"),
            "m": stage.get("m"),
            "stage": stage.get("stage"),
            "hpv_status": _blank(row.get("hpv_status")),
            "workflow_stage": state["current_workflow_stage"],
            "completed_prerequisites": state["completed_prerequisites"],
            "outstanding_tasks": state["outstanding_tasks"],
            "elapsed_days": state["elapsed_days_in_current_stage"],
        }

    def _build_evidence_indexes(self) -> None:
        for patient_id, row in self.patients.items():
            for field in (
                "disease_site",
                "subsite",
                "age",
                "cancer_stage",
                "hpv_status",
                "systemic_therapy",
                "radiation_treatment_characteristics",
            ):
                value = _decode(row.get(field, ""))
                if value is None:
                    continue
                identifier = uuid.uuid5(
                    CLINICAL_NAMESPACE, f"{patient_id}:{field}"
                ).hex
                evidence_id = f"clinical-{identifier}"
                item = {
                    "evidence_id": evidence_id,
                    "patient_id": patient_id,
                    "source_type": "observed_clinical",
                    "source_record": row["clinical_source_record_identifier"],
                    "field_or_event": field,
                    "value": value,
                    "provenance": {
                        "source_name": row["clinical_source_name"],
                        "source_file": row["clinical_source_file"],
                        "source_sha256": row["clinical_source_sha256"],
                    },
                }
                self._clinical_evidence[(patient_id, field)] = item
                self._clinical_evidence[(patient_id, evidence_id)] = item
        for patient_id, rows in self.events.items():
            for row in rows:
                item = {
                    "evidence_id": row["evidence_id"],
                    "patient_id": patient_id,
                    "source_type": "synthetic_workflow",
                    "source_record": row["event_id"],
                    "field_or_event": row["event_type"],
                    "value": {
                        "event_type": row["event_type"],
                        "occurred_at": row["occurred_at"],
                    },
                    "provenance": {
                        "source_name": row["source_name"],
                        "source_version": row["source_version"],
                    },
                }
                self._workflow_evidence[(patient_id, row["evidence_id"])] = item

    def _read_indexed(self, name: str, key: str) -> dict[str, dict[str, str]]:
        with (self.data_directory / name).open(encoding="utf-8", newline="") as handle:
            return {row[key]: row for row in csv.DictReader(handle)}

    def _read_grouped(self, name: str, key: str) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = defaultdict(list)
        with (self.data_directory / name).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                result[row[key]].append(row)
        return dict(result)

    def _patient(self, patient_id: str) -> dict[str, str]:
        try:
            return self.patients[patient_id]
        except KeyError as exc:
            raise KeyError("unknown patient_id") from exc

    def _event_rows(self, patient_id: str) -> list[dict[str, str]]:
        self._patient(patient_id)
        return self.events.get(patient_id, [])

    def _snapshot(self, patient_id: str) -> dict[str, str]:
        self._patient(patient_id)
        return self.snapshots[patient_id]


def _blank(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _number(value: str | None) -> float | None:
    return float(value) if _blank(value) is not None else None


def _decode(value: str | None) -> Any:
    value = _blank(value)
    if value is None:
        return None
    if value.startswith("{") or value.startswith("["):
        return json.loads(value)
    return value


def _aware(value: datetime | str) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return result


@lru_cache(maxsize=1)
def _default_store() -> IntelligenceStore:
    return IntelligenceStore(DEFAULT_DATA_DIRECTORY)


def get_patient_context(patient_id: str) -> dict[str, Any]:
    return _default_store().get_patient_context(patient_id)


def get_workflow_state(patient_id: str, as_of: datetime | str) -> dict[str, Any]:
    return _default_store().get_workflow_state(patient_id, as_of)


def find_similar_patients(
    patient_id: str, k: int = 10, weights: dict[str, float] | None = None
) -> list[dict[str, Any]]:
    return _default_store().find_similar_patients(patient_id, k, weights)


def get_cohort_next_steps(patient_ids: list[str]) -> dict[str, Any]:
    return _default_store().get_cohort_next_steps(patient_ids)


def get_evidence(patient_id: str, evidence_ids: list[str]) -> list[dict[str, Any]]:
    return _default_store().get_evidence(patient_id, evidence_ids)
