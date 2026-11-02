"""Strict contracts for deterministic, evidence-grounded patient insights."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
AwareDatetime = Annotated[datetime, AfterValidator(_aware)]


class StrictModel(BaseModel):
    """Reject undeclared fields in every insights contract."""

    model_config = ConfigDict(extra="forbid")


class InsightCategory(StrEnum):
    CLINICAL = "clinical"
    WORKFLOW = "workflow"
    SIMILARITY = "similarity"
    COHORT = "cohort"
    MISSINGNESS = "missingness"


class SupportType(StrEnum):
    DIRECT_EVIDENCE = "direct_evidence"
    DETERMINISTIC_DERIVATION = "deterministic_derivation"
    DESCRIPTIVE_COHORT_AGGREGATE = "descriptive_cohort_aggregate"
    EXPLICIT_MISSINGNESS = "explicit_missingness"


class ProvenanceType(StrEnum):
    OBSERVED_CLINICAL = "observed_clinical"
    FICTIONAL_SHOWCASE_CLINICAL = "fictional_showcase_clinical"
    SYNTHETIC_WORKFLOW = "synthetic_workflow"
    DETERMINISTIC_TOOL = "deterministic_tool"
    SYNTHETIC_COHORT_AGGREGATE = "synthetic_cohort_aggregate"


class PatientInsightStatement(StrictModel):
    statement_id: NonEmptyString
    category: InsightCategory
    label: NonEmptyString
    text: NonEmptyString
    evidence_ids: list[NonEmptyString] = Field(default_factory=list)
    evidence_fields: list[NonEmptyString] = Field(default_factory=list)
    support_type: SupportType
    provenance_type: ProvenanceType
    time_scope: NonEmptyString
    source_tool: NonEmptyString
    derivation: NonEmptyString
    caveat: str | None = None

    @model_validator(mode="after")
    def validate_support_contract(self) -> PatientInsightStatement:
        if len(self.evidence_ids) != len(self.evidence_fields):
            raise ValueError("evidence IDs and fields must have equal length")
        if self.support_type is SupportType.DIRECT_EVIDENCE:
            if not self.evidence_ids or not self.evidence_fields:
                raise ValueError("direct evidence statements require IDs and fields")
        elif self.support_type in {
            SupportType.EXPLICIT_MISSINGNESS,
            SupportType.DESCRIPTIVE_COHORT_AGGREGATE,
        } and (self.evidence_ids or self.evidence_fields):
            raise ValueError(
                "missingness and cohort statements cannot claim direct evidence"
            )
        return self


class TreatmentAttribute(StrictModel):
    value: Any | None
    temporal_label: str | None


class ClinicalSnapshot(StrictModel):
    disease_site: Any | None
    subsite: Any | None
    age: Any | None
    t: Any | None
    n: Any | None
    m: Any | None
    overall_stage: Any | None
    staging_system: Any | None
    staging_edition: Any | None
    staging_type: Any | None
    staging_schema: Any | None
    hpv_status: Any | None
    p16_status: Any | None
    treatment_attributes: dict[str, TreatmentAttribute]
    missing_fields: list[NonEmptyString]


class FeatureComparison(StrictModel):
    query: Any | None
    candidate: Any | None
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)


class SimilaritySummaryItem(StrictModel):
    patient_id: NonEmptyString
    score: float = Field(ge=0.0, le=1.0)
    similarity_reasons: list[NonEmptyString]
    missing_features: list[NonEmptyString]
    feature_comparisons: dict[str, FeatureComparison]


class SyntheticTimingSummary(StrictModel):
    minimum: float
    median: float
    mean: float
    maximum: float


class SyntheticNextEventCategory(StrictModel):
    event_type: NonEmptyString
    count: int = Field(ge=0)
    percentage_of_cohort: float = Field(ge=0.0, le=100.0)
    synthetic_time_to_next_event_days: SyntheticTimingSummary


class EvidenceIndexEntry(StrictModel):
    evidence_id: NonEmptyString
    patient_id: NonEmptyString
    source_type: NonEmptyString
    source_record: NonEmptyString
    field_or_event: NonEmptyString
    occurred_at: AwareDatetime | None = None


class PatientInsights(StrictModel):
    patient_id: NonEmptyString
    as_of: AwareDatetime
    data_mode: Literal["Local Full Cohort", "Synthetic Agent Demonstration"]
    clinical_snapshot: ClinicalSnapshot
    current_workflow_stage: NonEmptyString
    elapsed_days_in_stage: float | None = Field(default=None, ge=0.0)
    completed_prerequisites: list[NonEmptyString]
    outstanding_tasks: list[NonEmptyString]
    similar_patient_count: int = Field(ge=0)
    similarity_summary: list[SimilaritySummaryItem]
    comparison_time_basis: NonEmptyString
    cohort_denominator: int = Field(ge=0)
    observed_next_event_count: int = Field(ge=0)
    censored_or_incomplete_count: int = Field(ge=0)
    synthetic_next_event_categories: list[SyntheticNextEventCategory]
    sample_size_warning: str | None
    synthetic_timing_notice: NonEmptyString
    statements: list[PatientInsightStatement]
    evidence_index: dict[str, EvidenceIndexEntry]
    limitations: list[NonEmptyString] = Field(min_length=1)
    validation_status: Literal["validated"]

    @model_validator(mode="after")
    def validate_grounding(self) -> PatientInsights:
        if self.similar_patient_count != len(self.similarity_summary):
            raise ValueError("similar patient count does not match summary")
        if self.cohort_denominator != self.similar_patient_count:
            raise ValueError("cohort denominator does not match retrieved comparators")
        if (
            self.observed_next_event_count + self.censored_or_incomplete_count
            != self.cohort_denominator
        ):
            raise ValueError("cohort observation counts do not reconcile")
        if sum(item.count for item in self.synthetic_next_event_categories) != (
            self.observed_next_event_count
        ):
            raise ValueError("synthetic category counts do not reconcile")
        if len({item.statement_id for item in self.statements}) != len(
            self.statements
        ):
            raise ValueError("statement IDs must be unique")
        for key, item in self.evidence_index.items():
            if key != item.evidence_id:
                raise ValueError("evidence index key does not match evidence ID")
            if item.patient_id != self.patient_id:
                raise ValueError("cross-patient evidence is not allowed")
            if item.occurred_at is not None and item.occurred_at > self.as_of:
                raise ValueError("future-dated workflow evidence is not allowed")
        for statement in self.statements:
            for evidence_id, field in zip(
                statement.evidence_ids,
                statement.evidence_fields,
                strict=True,
            ):
                item = self.evidence_index.get(evidence_id)
                if item is None:
                    raise ValueError("statement references unresolved evidence")
                if item.field_or_event != field:
                    raise ValueError("statement evidence does not match claimed field")
        forbidden = (
            "recommended treatment",
            "urgent clinical action",
            "patient-specific prediction",
            "outcome probability",
        )
        if any(
            phrase in statement.text.lower()
            for statement in self.statements
            for phrase in forbidden
        ):
            raise ValueError("unsupported clinical conclusion in statement")
        return self
