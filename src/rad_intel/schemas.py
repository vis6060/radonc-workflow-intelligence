"""Shared, provenance-aware data contracts for rad-intel."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


def _timezone_aware(value: datetime) -> datetime:
    """Reject timestamps that do not include a usable UTC offset."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
AwareDatetime = Annotated[datetime, AfterValidator(_timezone_aware)]


class ProvenanceType(StrEnum):
    """Top-level boundary between source clinical and synthetic workflow data."""

    OBSERVED_CLINICAL = "observed_clinical"
    SYNTHETIC_WORKFLOW = "synthetic_workflow"


class StrictModel(BaseModel):
    """Base contract that rejects fields outside the declared schema."""

    model_config = ConfigDict(extra="forbid")


class ProvenanceMetadata(StrictModel):
    """Identifies whether a record is observed or synthetic and where it came from."""

    provenance_type: ProvenanceType
    source_name: NonEmptyString
    source_version: NonEmptyString | None = None


class EvidenceReference(StrictModel):
    """Pointer to evidence without copying the underlying patient-level value."""

    evidence_id: NonEmptyString
    patient_id: NonEmptyString
    source_type: ProvenanceType
    source_record_identifier: NonEmptyString
    field_path: NonEmptyString | None = None
    timestamp: AwareDatetime | None = None


class PatientContext(StrictModel):
    """Available clinical attributes and their observed-source evidence."""

    patient_id: NonEmptyString
    clinical_attributes: dict[str, Any] = Field(default_factory=dict)
    clinical_provenance: ProvenanceMetadata
    evidence_references: list[EvidenceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_clinical_boundary(self) -> PatientContext:
        if (
            self.clinical_provenance.provenance_type
            is not ProvenanceType.OBSERVED_CLINICAL
        ):
            raise ValueError("patient context provenance must be observed clinical")
        for reference in self.evidence_references:
            if reference.patient_id != self.patient_id:
                raise ValueError(
                    "patient context evidence must reference the same patient"
                )
            if reference.source_type is not ProvenanceType.OBSERVED_CLINICAL:
                raise ValueError("patient context evidence must be observed clinical")
        return self


class WorkflowEvent(StrictModel):
    """One explicitly sourced event in a patient's operational timeline."""

    event_id: NonEmptyString
    patient_id: NonEmptyString
    event_type: NonEmptyString
    occurred_at: AwareDatetime
    provenance: ProvenanceMetadata
    event_metadata: dict[str, Any] | None = None


class WorkflowSnapshot(StrictModel):
    """Deterministic point-in-time reconstruction of workflow state."""

    patient_id: NonEmptyString
    as_of: AwareDatetime
    current_workflow_stage: NonEmptyString
    completed_events: list[WorkflowEvent] = Field(default_factory=list)
    outstanding_tasks: list[NonEmptyString] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_point_in_time_boundary(self) -> WorkflowSnapshot:
        for event in self.completed_events:
            if event.patient_id != self.patient_id:
                raise ValueError("completed events must belong to the snapshot patient")
            if event.occurred_at > self.as_of:
                raise ValueError("completed events cannot occur after snapshot as_of")
        for reference in self.evidence_references:
            if reference.patient_id != self.patient_id:
                raise ValueError("snapshot evidence must reference the same patient")
            if reference.timestamp is not None and reference.timestamp > self.as_of:
                raise ValueError(
                    "snapshot evidence cannot be later than snapshot as_of"
                )
        return self


class SimilarPatientMatch(StrictModel):
    """Explainable similarity result produced by a future deterministic tool."""

    patient_id: NonEmptyString
    similarity_score: float = Field(ge=0.0, le=1.0)
    explanation: NonEmptyString
    evidence_references: list[EvidenceReference] = Field(default_factory=list)


class SimilarPatientOutput(StrictModel):
    """Structured container for historical patient matches."""

    method: NonEmptyString
    matches: list[SimilarPatientMatch] = Field(default_factory=list)


class HistoricalNextStepSummary(StrictModel):
    """Descriptive historical pattern, never a clinical recommendation."""

    summary: NonEmptyString
    supporting_patient_ids: list[NonEmptyString] = Field(default_factory=list)


class AgentResponse(StrictModel):
    """Evidence-linked operational response contract for a future agent."""

    patient_id: NonEmptyString
    generated_at: AwareDatetime
    patient_context_summary: NonEmptyString
    workflow_summary: NonEmptyString
    similar_patient_output: SimilarPatientOutput
    historical_next_step_summary: HistoricalNextStepSummary
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    limitations: list[NonEmptyString] = Field(min_length=1)
