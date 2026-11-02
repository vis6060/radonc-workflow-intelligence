"""Deterministic, entirely fictional public showcase cohort.

This module does not read RADCURE-derived files.  Its compact in-memory cohort is
designed to exercise the same M3 intelligence methods as the private local cohort
while remaining safe to distribute with the source code.
"""

from __future__ import annotations

import copy
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from rad_intel.similarity import rank_similar
from rad_intel.workflow_generator import BASE_EVENT_TYPES

SHOWCASE_COHORT_SIZE = 32
SHOWCASE_PATIENT = "SYNTHETIC-DEMO-001"
SHOWCASE_SOURCE = "rad-intel-fictional-showcase"
SHOWCASE_VERSION = "m6.1-v2"

_CLINICAL_FIELDS = (
    "disease_site",
    "subsite",
    "age",
    "cancer_stage",
    "hpv_status",
    "p16_status",
    "systemic_therapy",
    "radiation_treatment_characteristics",
)

_CLINICAL_TEMPLATES = (
    ("oropharynx", "tonsil", "T2", "N1", "M0", "positive", "positive"),
    (
        "oropharynx",
        "base_of_tongue",
        "T3",
        "N1",
        "M0",
        "positive",
        "positive",
    ),
    ("oropharynx", "tonsil", "T2", "N2", "M0", "negative", "negative"),
    (
        "oropharynx",
        "base_of_tongue",
        "T2",
        "N1",
        "M0",
        "negative",
        "negative",
    ),
    (
        "larynx",
        "glottis",
        "T2",
        "N0",
        "M0",
        "not_applicable",
        "not_applicable",
    ),
    (
        "larynx",
        "supraglottis",
        "T3",
        "N1",
        "M0",
        "not_applicable",
        "not_applicable",
    ),
    (
        "hypopharynx",
        "pyriform_sinus",
        "T3",
        "N1",
        "M0",
        "not_applicable",
        "not_applicable",
    ),
    (
        "oral_cavity",
        "oral_tongue",
        "T2",
        "N1",
        "M0",
        "not_applicable",
        "not_applicable",
    ),
)

_AJCC8_CLINICAL_STAGE_GROUPS = {
    ("oropharynx", "positive", "T2", "N1", "M0"): "I",
    ("oropharynx", "positive", "T3", "N1", "M0"): "II",
    ("oropharynx", "negative", "T2", "N2", "M0"): "IVA",
    ("oropharynx", "negative", "T2", "N1", "M0"): "III",
    ("larynx", "not_applicable", "T2", "N0", "M0"): "II",
    ("larynx", "not_applicable", "T3", "N1", "M0"): "III",
    ("hypopharynx", "not_applicable", "T3", "N1", "M0"): "III",
    ("oral_cavity", "not_applicable", "T2", "N1", "M0"): "III",
}
_CONCURRENT_THERAPY_TEMPLATE_INDEXES = {1, 2, 5, 6, 7}

# Number of baseline events visible at the stored snapshot.  The primary record has
# seven visible events, while the rest span early, active, and completed workflows.
_SNAPSHOT_PROGRESS = (
    7,  # 001: primary showcase record
    4,
    5,
    6,
    8,
    9,
    10,
    11,
    12,
    13,
    3,
    7,
    5,
    8,
    13,  # 015: active hospitalization interruption snapshot
    6,
    9,
    4,
    12,
    10,
    7,
    11,
    5,
    13,
    13,  # 025: censored exact-clinical comparator
    6,
    9,
    12,
    4,
    10,
    7,
    13,
)

_EVENT_GAPS_HOURS = (0, 36, 72, 8, 60, 36, 72, 4, 84, 12, 96, 36, 96)


def derive_ajcc8_clinical_stage(
    disease_site: str,
    p16_status: str,
    t_category: str,
    n_category: str,
    m_category: str,
) -> str:
    """Return an AJCC 8 clinical stage for an explicitly supported fixture tuple."""
    key = (disease_site, p16_status, t_category, n_category, m_category)
    try:
        return _AJCC8_CLINICAL_STAGE_GROUPS[key]
    except KeyError as exc:
        raise ValueError(
            "showcase TNM/p16 combination lacks an explicit AJCC 8 mapping"
        ) from exc


def _staging_schema(disease_site: str, p16_status: str) -> str:
    if disease_site == "oropharynx" and p16_status == "positive":
        return "hpv_mediated_p16_positive_oropharynx"
    if disease_site == "oropharynx" and p16_status == "negative":
        return "p16_negative_oropharynx"
    return disease_site


class SyntheticShowcaseStore:
    """In-memory M3-compatible store backed only by fictional records."""

    synthetic_showcase_fixture = True

    def __init__(self) -> None:
        self.patients: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.snapshots: dict[str, dict[str, str]] = {}
        self._clinical_evidence: dict[tuple[str, str], dict[str, Any]] = {}
        self._workflow_evidence: dict[tuple[str, str], dict[str, Any]] = {}
        for index in range(SHOWCASE_COHORT_SIZE):
            self._build_patient(index)

    def get_patient_context(self, patient_id: str) -> dict[str, Any]:
        row = self._patient(patient_id)
        evidence = [
            self._clinical_evidence[(patient_id, field)]
            for field in _CLINICAL_FIELDS
            if row[field] is not None
        ]
        return copy.deepcopy(
            {
                "patient_id": patient_id,
                "disease_characteristics": {
                    "disease_site": row["disease_site"],
                    "subsite": row["subsite"],
                    "cancer_stage": row["cancer_stage"],
                    "hpv_status": row["hpv_status"],
                    "p16_status": row["p16_status"],
                },
                "age": row["age"],
                "treatment_attributes": {
                    field: {
                        "value": row[field],
                        "temporal_label": (
                            "fictional demonstration attribute available at the "
                            "stored workflow snapshot"
                        ),
                    }
                    for field in (
                        "systemic_therapy",
                        "radiation_treatment_characteristics",
                    )
                },
                "missing_data": {
                    field: row[field] is None for field in _CLINICAL_FIELDS
                },
                "evidence_references": [
                    {key: value for key, value in item.items() if key != "value"}
                    for item in evidence
                ],
                "provenance": {
                    "source_type": "fictional_showcase_clinical",
                    "source_name": SHOWCASE_SOURCE,
                    "source_version": SHOWCASE_VERSION,
                    "synthetic_notice": (
                        "Entirely fictional; not derived from RADCURE records."
                    ),
                },
            }
        )

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
        event_types = [row["event_type"] for row in visible]
        completed = [name for name in BASE_EVENT_TYPES if name in event_types]
        stage = completed[-1]
        outstanding = (
            [BASE_EVENT_TYPES[len(completed)]]
            if len(completed) < len(BASE_EVENT_TYPES)
            else []
        )
        if (
            "consult_no_show" in event_types
            and "consult_rescheduled" not in event_types
        ):
            stage = "consult_no_show"
            outstanding.insert(0, "consult_rescheduled")
        if (
            "hospitalization_interruption_started" in event_types
            and "hospitalization_interruption_resolved" not in event_types
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
        return copy.deepcopy(
            {
                "patient_id": patient_id,
                "as_of": cutoff.isoformat(),
                "current_workflow_stage": stage,
                "completed_prerequisites": completed,
                "outstanding_tasks": outstanding,
                "elapsed_days_in_current_stage": round(
                    (cutoff - _aware(stage_row["occurred_at"])).total_seconds()
                    / 86400,
                    6,
                ),
                "evidence_references": [
                    self._workflow_evidence[(patient_id, row["evidence_id"])]
                    for row in visible
                ],
                "provenance": "synthetic_workflow",
            }
        )

    def find_similar_patients(
        self,
        patient_id: str,
        k: int = 10,
        weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        if k < 1:
            raise ValueError("k must be positive")
        self._patient(patient_id)
        features = {pid: self._similarity_features(pid) for pid in self.patients}
        candidates = [value for pid, value in features.items() if pid != patient_id]
        return rank_similar(features[patient_id], candidates, k, weights)

    def get_cohort_next_steps(self, patient_ids: list[str]) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(patient_ids))
        next_rows: list[tuple[str, dict[str, Any], float]] = []
        censored = 0
        for patient_id in unique_ids:
            cutoff = _aware(self._snapshot(patient_id)["as_of"])
            future = [
                row
                for row in self._event_rows(patient_id)
                if _aware(row["occurred_at"]) > cutoff
            ]
            if not future:
                censored += 1
                continue
            row = future[0]
            days = (_aware(row["occurred_at"]) - cutoff).total_seconds() / 86400
            next_rows.append((patient_id, row, days))
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
            "missing_or_censored_count": censored,
            "next_event_categories": categories,
            "sample_size_warning": (
                "Small fictional showcase cohort; do not interpret as a prediction."
            ),
            "synthetic_timing_notice": (
                "FICTIONAL synthetic timing for product demonstration only; not "
                "clinically validated or representative of RADCURE."
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
            resolved.append(copy.deepcopy(item))
        return resolved

    def _build_patient(self, zero_index: int) -> None:
        number = zero_index + 1
        patient_id = f"SYNTHETIC-DEMO-{number:03d}"
        template = _CLINICAL_TEMPLATES[zero_index % len(_CLINICAL_TEMPLATES)]
        site, subsite, t_value, n_value, m_value, hpv, p16 = template
        stage = derive_ajcc8_clinical_stage(
            site, p16, t_value, n_value, m_value
        )
        progress = _SNAPSHOT_PROGRESS[zero_index]
        treatment_available = progress >= BASE_EVENT_TYPES.index("planning_started") + 1
        row = {
            "patient_id": patient_id,
            "disease_site": site,
            "subsite": subsite,
            "age": 43 + (zero_index * 7) % 35,
            "cancer_stage": {
                "t": t_value,
                "n": n_value,
                "m": m_value,
                "stage": stage,
                "staging_system": "AJCC",
                "staging_edition": "8th edition",
                "staging_type": "clinical_prognostic_stage_group",
                "staging_schema": _staging_schema(site, p16),
            },
            "hpv_status": hpv,
            "p16_status": p16,
            "systemic_therapy": (
                {
                    "modality": (
                        "fictional_concurrent_systemic_therapy"
                        if zero_index % len(_CLINICAL_TEMPLATES)
                        in _CONCURRENT_THERAPY_TEMPLATE_INDEXES
                        else "fictional_radiation_only"
                    )
                }
                if treatment_available
                else None
            ),
            "radiation_treatment_characteristics": (
                {
                    "planned_total_dose_gy": 66 + 2 * (zero_index % 3),
                    "planned_fractions": 30 + (zero_index % 3) * 3,
                    "status": "fictional_plan",
                }
                if treatment_available
                else None
            ),
        }
        self.patients[patient_id] = row
        self._index_clinical_evidence(patient_id, row)
        events = self._build_events(patient_id, zero_index)
        self.events[patient_id] = events
        self._index_workflow_evidence(patient_id, events)
        snapshot_event_type = (
            "hospitalization_interruption_started"
            if zero_index == 14
            else BASE_EVENT_TYPES[progress - 1]
        )
        snapshot_event = next(
            item for item in events if item["event_type"] == snapshot_event_type
        )
        snapshot_time = _aware(snapshot_event["occurred_at"]) + timedelta(hours=6)
        self.snapshots[patient_id] = {"as_of": snapshot_time.isoformat()}

    def _build_events(
        self, patient_id: str, zero_index: int
    ) -> list[dict[str, Any]]:
        current = datetime(2035, 1, 6, 9, tzinfo=UTC) + timedelta(
            days=zero_index * 3
        )
        events = []
        for event_index, (event_type, gap) in enumerate(
            zip(BASE_EVENT_TYPES, _EVENT_GAPS_HOURS, strict=True),
            start=1,
        ):
            current += timedelta(hours=gap + (zero_index + event_index) % 9)
            if event_type == "consult_completed" and zero_index in {9, 21}:
                events.append(
                    self._event(
                        patient_id,
                        "consult_no_show",
                        current - timedelta(hours=30),
                        len(events) + 1,
                        exceptional=True,
                    )
                )
                events.append(
                    self._event(
                        patient_id,
                        "consult_rescheduled",
                        current - timedelta(hours=18),
                        len(events) + 1,
                        exceptional=True,
                    )
                )
            if event_type == "treatment_started" and zero_index in {14, 27}:
                events.append(
                    self._event(
                        patient_id,
                        "hospitalization_interruption_started",
                        current - timedelta(hours=72),
                        len(events) + 1,
                        exceptional=True,
                    )
                )
                events.append(
                    self._event(
                        patient_id,
                        "hospitalization_interruption_resolved",
                        current - timedelta(hours=36),
                        len(events) + 1,
                        exceptional=True,
                    )
                )
            events.append(
                self._event(patient_id, event_type, current, len(events) + 1)
            )
        events.sort(key=lambda item: item["occurred_at"])
        return events

    @staticmethod
    def _event(
        patient_id: str,
        event_type: str,
        occurred_at: datetime,
        sequence: int,
        *,
        exceptional: bool = False,
    ) -> dict[str, Any]:
        suffix = patient_id.rsplit("-", 1)[-1]
        return {
            "event_id": f"showcase-event-{suffix}-{sequence:02d}",
            "patient_id": patient_id,
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "evidence_id": f"showcase-workflow-{suffix}-{sequence:02d}",
            "is_exceptional": exceptional,
        }

    def _index_clinical_evidence(
        self, patient_id: str, row: dict[str, Any]
    ) -> None:
        suffix = patient_id.rsplit("-", 1)[-1]
        for field in _CLINICAL_FIELDS:
            value = row[field]
            if value is None:
                continue
            evidence_id = f"showcase-clinical-{suffix}-{field}"
            item = {
                "evidence_id": evidence_id,
                "patient_id": patient_id,
                "source_type": "fictional_showcase_clinical",
                "source_record": f"fictional-record-{suffix}",
                "field_or_event": field,
                "value": copy.deepcopy(value),
                "provenance": {
                    "source_name": SHOWCASE_SOURCE,
                    "source_version": SHOWCASE_VERSION,
                    "synthetic_notice": "Entirely fictional demonstration record.",
                },
            }
            self._clinical_evidence[(patient_id, field)] = item
            self._clinical_evidence[(patient_id, evidence_id)] = item

    def _index_workflow_evidence(
        self, patient_id: str, rows: list[dict[str, Any]]
    ) -> None:
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
                    "is_exceptional": row["is_exceptional"],
                },
                "provenance": {
                    "source_name": SHOWCASE_SOURCE,
                    "source_version": SHOWCASE_VERSION,
                    "synthetic_notice": "Entirely fictional workflow event.",
                },
            }
            self._workflow_evidence[(patient_id, row["evidence_id"])] = item

    def _similarity_features(self, patient_id: str) -> dict[str, Any]:
        row = self._patient(patient_id)
        stage = row["cancer_stage"]
        state = self.get_workflow_state(patient_id, self._snapshot(patient_id)["as_of"])
        return {
            "patient_id": patient_id,
            "age": row["age"],
            "disease_site": row["disease_site"],
            "subsite": row["subsite"],
            "t": stage["t"],
            "n": stage["n"],
            "m": stage["m"],
            "stage": stage["stage"],
            "hpv_status": row["hpv_status"],
            "workflow_stage": state["current_workflow_stage"],
            "completed_prerequisites": state["completed_prerequisites"],
            "outstanding_tasks": state["outstanding_tasks"],
            "elapsed_days": state["elapsed_days_in_current_stage"],
        }

    def _patient(self, patient_id: str) -> dict[str, Any]:
        try:
            return self.patients[patient_id]
        except KeyError as exc:
            raise KeyError("unknown patient_id") from exc

    def _event_rows(self, patient_id: str) -> list[dict[str, Any]]:
        self._patient(patient_id)
        return self.events[patient_id]

    def _snapshot(self, patient_id: str) -> dict[str, str]:
        self._patient(patient_id)
        return self.snapshots[patient_id]


def _aware(value: datetime | str) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return result
