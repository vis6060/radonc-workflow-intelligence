"""Deterministic, demonstration-only synthetic workflow histories."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rad_intel.schemas import (
    EvidenceReference,
    ProvenanceMetadata,
    ProvenanceType,
    WorkflowEvent,
    WorkflowSnapshot,
)

BASE_EVENT_TYPES = (
    "referral_received",
    "consult_scheduled",
    "consult_completed",
    "authorization_requested",
    "authorization_approved",
    "simulation_scheduled",
    "simulation_completed",
    "contour_task_opened",
    "contour_task_completed",
    "planning_started",
    "plan_approved",
    "treatment_scheduled",
    "treatment_started",
)

EVENTS_OUTPUT_FIELDS = (
    "event_id",
    "patient_id",
    "event_type",
    "occurred_at",
    "provenance_type",
    "source_name",
    "source_version",
    "evidence_id",
    "phenotype",
    "is_exceptional",
    "event_metadata_json",
)

SNAPSHOTS_OUTPUT_FIELDS = (
    "patient_id",
    "as_of",
    "phenotype",
    "current_workflow_stage",
    "completed_event_ids_json",
    "outstanding_tasks_json",
    "evidence_ids_json",
    "provenance_type",
)

SYNTHETIC_SOURCE_NAME = "rad-intel-synthetic-workflow-generator"
SYNTHETIC_SOURCE_VERSION = "m2-v1"
SYNTHETIC_ASSUMPTION_LABEL = "synthetic_demonstration_assumption"
ID_NAMESPACE = uuid.UUID("16bce0c5-d76c-48ca-9851-62b22509e456")


class WorkflowPhenotype(StrEnum):
    """Synthetic operational patterns represented in the demonstration cohort."""

    NORMAL_PROGRESSION = "normal_progression"
    AUTHORIZATION_DELAY = "authorization_delay"
    LATE_CONTOURING = "late_contouring"
    PLANNING_DELAY = "planning_delay"
    RESCHEDULING = "rescheduling"
    NO_SHOW = "no_show"
    HOSPITALIZATION_INTERRUPTION = "hospitalization_interruption"
    TREATMENT_START_DELAY = "treatment_start_delay"


class TimingRange(BaseModel):
    """Inclusive whole-hour range used only for synthetic demonstration timing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_hours: int = Field(ge=1)
    maximum_hours: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> TimingRange:
        if self.maximum_hours < self.minimum_hours:
            raise ValueError("maximum_hours must be at least minimum_hours")
        return self


def _default_timings() -> dict[str, TimingRange]:
    return {
        "consult_scheduled": TimingRange(minimum_hours=24, maximum_hours=72),
        "consult_completed": TimingRange(minimum_hours=72, maximum_hours=168),
        "authorization_requested": TimingRange(minimum_hours=4, maximum_hours=24),
        "authorization_approved": TimingRange(minimum_hours=24, maximum_hours=96),
        "simulation_scheduled": TimingRange(minimum_hours=24, maximum_hours=72),
        "simulation_completed": TimingRange(minimum_hours=48, maximum_hours=120),
        "contour_task_opened": TimingRange(minimum_hours=1, maximum_hours=8),
        "contour_task_completed": TimingRange(minimum_hours=48, maximum_hours=120),
        "planning_started": TimingRange(minimum_hours=4, maximum_hours=24),
        "plan_approved": TimingRange(minimum_hours=72, maximum_hours=168),
        "treatment_scheduled": TimingRange(minimum_hours=24, maximum_hours=72),
        "treatment_started": TimingRange(minimum_hours=72, maximum_hours=168),
        "authorization_delay_extra": TimingRange(
            minimum_hours=168,
            maximum_hours=336,
        ),
        "late_contouring_extra": TimingRange(
            minimum_hours=120,
            maximum_hours=240,
        ),
        "planning_delay_extra": TimingRange(
            minimum_hours=168,
            maximum_hours=336,
        ),
        "treatment_start_delay_extra": TimingRange(
            minimum_hours=168,
            maximum_hours=336,
        ),
        "reschedule_notice": TimingRange(minimum_hours=12, maximum_hours=48),
        "no_show_reschedule": TimingRange(minimum_hours=24, maximum_hours=72),
        "hospitalization_start": TimingRange(minimum_hours=24, maximum_hours=72),
        "hospitalization_duration": TimingRange(minimum_hours=72, maximum_hours=240),
    }


class GeneratorConfig(BaseModel):
    """Configurable deterministic assumptions for synthetic generation."""

    model_config = ConfigDict(extra="forbid")

    seed: int = 42
    anchor_start: datetime = datetime(2025, 1, 1, 9, 0, tzinfo=UTC)
    anchor_spread_days: int = Field(default=365, ge=1)
    timings: dict[str, TimingRange] = Field(default_factory=_default_timings)

    @model_validator(mode="after")
    def validate_config(self) -> GeneratorConfig:
        if self.anchor_start.tzinfo is None or self.anchor_start.utcoffset() is None:
            raise ValueError("anchor_start must be timezone-aware")
        required = set(_default_timings())
        missing = required - set(self.timings)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"timings missing required keys: {names}")
        return self


@dataclass(frozen=True)
class GenerationResult:
    """Aggregate paths and counts without patient-level values."""

    events_path: Path
    snapshots_path: Path
    gold_path: Path
    report_path: Path
    patient_count: int
    total_event_count: int
    phenotype_counts: dict[str, int]
    snapshot_stage_counts: dict[str, int]


@dataclass(frozen=True)
class _PatientHistory:
    patient_id: str
    phenotype: WorkflowPhenotype
    events: tuple[WorkflowEvent, ...]
    evidence: tuple[EvidenceReference, ...]
    snapshot: WorkflowSnapshot
    gold: dict[str, Any]


class GenerationError(ValueError):
    """Raised when input identifiers or generated state violate M2 contracts."""


def generate_workflows(
    patients_path: Path,
    output_directory: Path,
    config: GeneratorConfig | None = None,
) -> GenerationResult:
    """Generate all M2 artifacts from patient identifiers only."""
    resolved_config = config or GeneratorConfig()
    patient_ids = _load_patient_ids(patients_path)
    phenotypes = _balanced_assignments(
        list(WorkflowPhenotype),
        len(patient_ids),
        resolved_config.seed,
    )
    snapshot_positions = _balanced_assignments(
        list(range(1, len(BASE_EVENT_TYPES) + 1)),
        len(patient_ids),
        resolved_config.seed + 1,
    )

    histories: list[_PatientHistory] = []
    for patient_id, phenotype, snapshot_position in zip(
        patient_ids,
        phenotypes,
        snapshot_positions,
        strict=True,
    ):
        histories.append(
            _generate_patient_history(
                patient_id,
                phenotype,
                snapshot_position,
                resolved_config,
            )
        )

    validation = _validate_histories(histories, set(patient_ids))
    if any(validation.values()):
        raise GenerationError(f"generated workflow validation failed: {validation}")

    output_directory.mkdir(parents=True, exist_ok=True)
    events_path = output_directory / "workflow_events.csv"
    snapshots_path = output_directory / "workflow_snapshots.csv"
    gold_path = output_directory / "workflow_gold.json"
    report_path = output_directory / "generation_report.json"

    _write_events(events_path, histories)
    _write_snapshots(snapshots_path, histories)
    _write_gold(gold_path, histories, resolved_config)

    phenotype_counts = Counter(history.phenotype.value for history in histories)
    stage_counts = Counter(
        history.snapshot.current_workflow_stage for history in histories
    )
    event_type_counts = Counter(
        event.event_type for history in histories for event in history.events
    )
    source_sha256 = _sha256(patients_path)
    report = {
        "schema_version": 1,
        "synthetic_data_notice": (
            "All workflow events, dates, phenotypes, and states are synthetic "
            "demonstration data, not observed RADCURE operational records."
        ),
        "seed": resolved_config.seed,
        "patient_source": {
            "file_name": patients_path.name,
            "sha256": source_sha256,
        },
        "patient_count": len(histories),
        "total_event_count": sum(len(history.events) for history in histories),
        "phenotype_counts": dict(sorted(phenotype_counts.items())),
        "snapshot_stage_counts": dict(sorted(stage_counts.items())),
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "validation": {
            **validation,
            "exact_patient_id_coverage": True,
            "gold_state_count": len(histories),
        },
        "configuration": resolved_config.model_dump(mode="json"),
    }
    _write_json(report_path, report)

    return GenerationResult(
        events_path=events_path,
        snapshots_path=snapshots_path,
        gold_path=gold_path,
        report_path=report_path,
        patient_count=len(histories),
        total_event_count=report["total_event_count"],
        phenotype_counts=dict(sorted(phenotype_counts.items())),
        snapshot_stage_counts=dict(sorted(stage_counts.items())),
    )


def _load_patient_ids(path: Path) -> list[str]:
    if not path.is_file():
        raise GenerationError(f"patients file does not exist: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "patient_id" not in reader.fieldnames:
            raise GenerationError("patients file must contain patient_id")
        patient_ids: list[str] = []
        for row in reader:
            patient_id = (row.get("patient_id") or "").strip()
            if not patient_id:
                raise GenerationError("patients file contains a blank patient_id")
            patient_ids.append(patient_id)
    duplicates = len(patient_ids) - len(set(patient_ids))
    if duplicates:
        raise GenerationError("patients file contains duplicate patient_id values")
    if not patient_ids:
        raise GenerationError("patients file contains no patient records")
    return sorted(patient_ids)


def _balanced_assignments(items: list[Any], count: int, seed: int) -> list[Any]:
    assignments = [items[index % len(items)] for index in range(count)]
    random.Random(seed).shuffle(assignments)
    return assignments


def _generate_patient_history(
    patient_id: str,
    phenotype: WorkflowPhenotype,
    snapshot_position: int,
    config: GeneratorConfig,
) -> _PatientHistory:
    rng = random.Random(_patient_seed(config.seed, patient_id))
    current = config.anchor_start + timedelta(
        days=rng.randrange(config.anchor_spread_days),
        hours=rng.randrange(9),
    )
    events: list[WorkflowEvent] = []
    evidence: list[EvidenceReference] = []
    sequence = 0

    def append_event(
        event_type: str,
        elapsed_hours: int,
        *,
        exceptional: bool = False,
    ) -> None:
        nonlocal current, sequence
        current += timedelta(hours=elapsed_hours)
        sequence += 1
        event_id = _stable_id(
            "wfe",
            config.seed,
            patient_id,
            sequence,
            event_type,
        )
        evidence_id = _stable_id(
            "syn-evidence",
            config.seed,
            patient_id,
            sequence,
            event_type,
        )
        event = WorkflowEvent(
            event_id=event_id,
            patient_id=patient_id,
            event_type=event_type,
            occurred_at=current,
            provenance=ProvenanceMetadata(
                provenance_type=ProvenanceType.SYNTHETIC_WORKFLOW,
                source_name=SYNTHETIC_SOURCE_NAME,
                source_version=SYNTHETIC_SOURCE_VERSION,
            ),
            event_metadata={
                "evidence_id": evidence_id,
                "phenotype": phenotype.value,
                "is_exceptional": exceptional,
                "timing_assumption": SYNTHETIC_ASSUMPTION_LABEL,
                "elapsed_hours_from_prior_event": elapsed_hours,
            },
        )
        reference = EvidenceReference(
            evidence_id=evidence_id,
            patient_id=patient_id,
            source_type=ProvenanceType.SYNTHETIC_WORKFLOW,
            source_record_identifier=event_id,
            field_path="workflow_event",
            timestamp=current,
        )
        events.append(event)
        evidence.append(reference)

    append_event("referral_received", 0)
    for event_type in BASE_EVENT_TYPES[1:]:
        if event_type == "consult_completed":
            if phenotype is WorkflowPhenotype.RESCHEDULING:
                append_event(
                    "consult_rescheduled",
                    _sample(config, "reschedule_notice", rng),
                    exceptional=True,
                )
            elif phenotype is WorkflowPhenotype.NO_SHOW:
                append_event(
                    "consult_no_show",
                    _sample(config, "consult_completed", rng),
                    exceptional=True,
                )
                append_event(
                    "consult_rescheduled",
                    _sample(config, "no_show_reschedule", rng),
                    exceptional=True,
                )

        if (
            event_type == "treatment_started"
            and phenotype is WorkflowPhenotype.HOSPITALIZATION_INTERRUPTION
        ):
            append_event(
                "hospitalization_interruption_started",
                _sample(config, "hospitalization_start", rng),
                exceptional=True,
            )
            append_event(
                "hospitalization_interruption_resolved",
                _sample(config, "hospitalization_duration", rng),
                exceptional=True,
            )

        elapsed = _sample(config, event_type, rng)
        extra_key = _phenotype_extra_key(phenotype, event_type)
        if extra_key is not None:
            elapsed += _sample(config, extra_key, rng)
        append_event(event_type, elapsed)

    baseline_events = [
        event for event in events if event.event_type in BASE_EVENT_TYPES
    ]
    completed_baseline = baseline_events[:snapshot_position]
    if snapshot_position < len(BASE_EVENT_TYPES):
        next_event = baseline_events[snapshot_position]
        prior_event = completed_baseline[-1]
        as_of = prior_event.occurred_at + (
            next_event.occurred_at - prior_event.occurred_at
        ) / 2
    else:
        as_of = events[-1].occurred_at + timedelta(hours=1)

    snapshot = _derive_snapshot(patient_id, phenotype, events, evidence, as_of)
    gold = _derive_gold_state(patient_id, events, evidence, as_of)
    return _PatientHistory(
        patient_id=patient_id,
        phenotype=phenotype,
        events=tuple(events),
        evidence=tuple(evidence),
        snapshot=snapshot,
        gold=gold,
    )


def _derive_snapshot(
    patient_id: str,
    phenotype: WorkflowPhenotype,
    events: list[WorkflowEvent],
    evidence: list[EvidenceReference],
    as_of: datetime,
) -> WorkflowSnapshot:
    visible_events = [event for event in events if event.occurred_at <= as_of]
    visible_ids = {event.event_id for event in visible_events}
    visible_evidence = [
        reference
        for reference in evidence
        if reference.source_record_identifier in visible_ids
    ]
    stage, outstanding = _snapshot_state_from_visible_events(visible_events)
    return WorkflowSnapshot(
        patient_id=patient_id,
        as_of=as_of,
        current_workflow_stage=stage,
        completed_events=visible_events,
        outstanding_tasks=outstanding,
        evidence_references=visible_evidence,
    )


def _derive_gold_state(
    patient_id: str,
    events: list[WorkflowEvent],
    evidence: list[EvidenceReference],
    as_of: datetime,
) -> dict[str, Any]:
    visible = tuple(event for event in events if event.occurred_at <= as_of)
    visible_event_ids = tuple(event.event_id for event in visible)
    visible_event_id_set = set(visible_event_ids)
    stage, outstanding = _gold_state_from_visible_events(visible)
    visible_evidence_ids = tuple(
        reference.evidence_id
        for reference in evidence
        if reference.source_record_identifier in visible_event_id_set
        and reference.timestamp is not None
        and reference.timestamp <= as_of
    )
    return {
        "patient_id": patient_id,
        "as_of": as_of.isoformat(),
        "current_workflow_stage": stage,
        "completed_event_ids": list(visible_event_ids),
        "outstanding_tasks": outstanding,
        "evidence_ids": list(visible_evidence_ids),
    }


def _snapshot_state_from_visible_events(
    visible_events: list[WorkflowEvent],
) -> tuple[str, list[str]]:
    event_types = [event.event_type for event in visible_events]
    completed_baseline = [name for name in BASE_EVENT_TYPES if name in event_types]
    stage = completed_baseline[-1]
    outstanding = (
        [BASE_EVENT_TYPES[len(completed_baseline)]]
        if len(completed_baseline) < len(BASE_EVENT_TYPES)
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
    return stage, outstanding


def _gold_state_from_visible_events(
    visible_events: tuple[WorkflowEvent, ...],
) -> tuple[str, list[str]]:
    visible_types = {event.event_type for event in visible_events}
    completed_count = 0
    for required_event in BASE_EVENT_TYPES:
        if required_event not in visible_types:
            break
        completed_count += 1
    stage = BASE_EVENT_TYPES[completed_count - 1]
    outstanding = (
        [BASE_EVENT_TYPES[completed_count]]
        if completed_count < len(BASE_EVENT_TYPES)
        else []
    )
    if (
        "consult_no_show" in visible_types
        and "consult_rescheduled" not in visible_types
    ):
        stage = "consult_no_show"
        outstanding.insert(0, "consult_rescheduled")
    if (
        "hospitalization_interruption_started" in visible_types
        and "hospitalization_interruption_resolved" not in visible_types
    ):
        stage = "hospitalization_interruption"
        outstanding.insert(0, "hospitalization_interruption_resolved")
    return stage, outstanding


def _validate_histories(
    histories: list[_PatientHistory],
    expected_patient_ids: set[str],
) -> dict[str, int]:
    sequence_violations = 0
    chronology_violations = 0
    future_information_violations = 0
    evidence_provenance_violations = 0
    cross_patient_evidence_violations = 0
    gold_state_mismatches = 0

    generated_patient_ids = {history.patient_id for history in histories}
    if generated_patient_ids != expected_patient_ids:
        sequence_violations += 1

    for history in histories:
        baseline = [
            event.event_type
            for event in history.events
            if event.event_type in BASE_EVENT_TYPES
        ]
        if tuple(baseline) != BASE_EVENT_TYPES:
            sequence_violations += 1
        timestamps = [event.occurred_at for event in history.events]
        if any(
            later <= earlier
            for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        ):
            chronology_violations += 1

        snapshot_event_ids = {
            event.event_id for event in history.snapshot.completed_events
        }
        if any(
            event.occurred_at > history.snapshot.as_of
            for event in history.snapshot.completed_events
        ):
            future_information_violations += 1
        if any(
            reference.timestamp is None
            or reference.timestamp > history.snapshot.as_of
            for reference in history.snapshot.evidence_references
        ):
            future_information_violations += 1
        if any(
            reference.source_type is not ProvenanceType.SYNTHETIC_WORKFLOW
            for reference in history.evidence
        ):
            evidence_provenance_violations += 1
        if any(
            reference.patient_id != history.patient_id
            for reference in history.evidence
        ):
            cross_patient_evidence_violations += 1

        gold = history.gold
        if (
            set(gold["completed_event_ids"]) != snapshot_event_ids
            or gold["current_workflow_stage"]
            != history.snapshot.current_workflow_stage
            or gold["outstanding_tasks"] != history.snapshot.outstanding_tasks
            or set(gold["evidence_ids"])
            != {
                reference.evidence_id
                for reference in history.snapshot.evidence_references
            }
        ):
            gold_state_mismatches += 1

    return {
        "sequence_violations": sequence_violations,
        "chronology_violations": chronology_violations,
        "future_information_violations": future_information_violations,
        "evidence_provenance_violations": evidence_provenance_violations,
        "cross_patient_evidence_violations": cross_patient_evidence_violations,
        "gold_state_mismatches": gold_state_mismatches,
    }


def _phenotype_extra_key(
    phenotype: WorkflowPhenotype,
    event_type: str,
) -> str | None:
    lookup = {
        (WorkflowPhenotype.AUTHORIZATION_DELAY, "authorization_approved"):
            "authorization_delay_extra",
        (WorkflowPhenotype.LATE_CONTOURING, "contour_task_completed"):
            "late_contouring_extra",
        (WorkflowPhenotype.PLANNING_DELAY, "plan_approved"):
            "planning_delay_extra",
        (WorkflowPhenotype.TREATMENT_START_DELAY, "treatment_started"):
            "treatment_start_delay_extra",
    }
    return lookup.get((phenotype, event_type))


def _sample(config: GeneratorConfig, key: str, rng: random.Random) -> int:
    timing = config.timings[key]
    return rng.randint(timing.minimum_hours, timing.maximum_hours)


def _patient_seed(seed: int, patient_id: str) -> int:
    digest = hashlib.sha256(f"{seed}:{patient_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _stable_id(
    prefix: str,
    seed: int,
    patient_id: str,
    sequence: int,
    event_type: str,
) -> str:
    value = uuid.uuid5(
        ID_NAMESPACE,
        f"{seed}:{patient_id}:{sequence}:{event_type}:{prefix}",
    )
    return f"{prefix}-{value.hex}"


def _write_events(path: Path, histories: list[_PatientHistory]) -> None:
    rows: list[dict[str, str | bool]] = []
    for history in histories:
        for event in history.events:
            metadata = event.event_metadata or {}
            rows.append(
                {
                    "event_id": event.event_id,
                    "patient_id": event.patient_id,
                    "event_type": event.event_type,
                    "occurred_at": event.occurred_at.isoformat(),
                    "provenance_type": event.provenance.provenance_type.value,
                    "source_name": event.provenance.source_name,
                    "source_version": event.provenance.source_version or "",
                    "evidence_id": str(metadata["evidence_id"]),
                    "phenotype": history.phenotype.value,
                    "is_exceptional": bool(metadata["is_exceptional"]),
                    "event_metadata_json": json.dumps(
                        metadata,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                }
            )
    _write_csv(path, EVENTS_OUTPUT_FIELDS, rows)


def _write_snapshots(path: Path, histories: list[_PatientHistory]) -> None:
    rows: list[dict[str, str]] = []
    for history in histories:
        snapshot = history.snapshot
        rows.append(
            {
                "patient_id": history.patient_id,
                "as_of": snapshot.as_of.isoformat(),
                "phenotype": history.phenotype.value,
                "current_workflow_stage": snapshot.current_workflow_stage,
                "completed_event_ids_json": _compact_json(
                    [event.event_id for event in snapshot.completed_events]
                ),
                "outstanding_tasks_json": _compact_json(snapshot.outstanding_tasks),
                "evidence_ids_json": _compact_json(
                    [
                        reference.evidence_id
                        for reference in snapshot.evidence_references
                    ]
                ),
                "provenance_type": ProvenanceType.SYNTHETIC_WORKFLOW.value,
            }
        )
    _write_csv(path, SNAPSHOTS_OUTPUT_FIELDS, rows)


def _write_gold(
    path: Path,
    histories: list[_PatientHistory],
    config: GeneratorConfig,
) -> None:
    _write_json(
        path,
        {
            "schema_version": 1,
            "seed": config.seed,
            "synthetic_data_notice": (
                "Gold states are synthetic references derived only from synthetic "
                "events at or before each as_of timestamp."
            ),
            "patients": [history.gold for history in histories],
        },
    )


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
