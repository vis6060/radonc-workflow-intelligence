from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from rad_intel.schemas import (
    AgentResponse,
    EvidenceReference,
    HistoricalNextStepSummary,
    PatientContext,
    ProvenanceMetadata,
    ProvenanceType,
    SimilarPatientMatch,
    SimilarPatientOutput,
    WorkflowEvent,
    WorkflowSnapshot,
)

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def clinical_provenance() -> ProvenanceMetadata:
    return ProvenanceMetadata(
        provenance_type=ProvenanceType.OBSERVED_CLINICAL,
        source_name="approved-source",
    )


def synthetic_provenance() -> ProvenanceMetadata:
    return ProvenanceMetadata(
        provenance_type=ProvenanceType.SYNTHETIC_WORKFLOW,
        source_name="synthetic-generator",
        source_version="test",
    )


def clinical_evidence(patient_id: str = "P-001") -> EvidenceReference:
    return EvidenceReference(
        evidence_id="EV-001",
        patient_id=patient_id,
        source_type=ProvenanceType.OBSERVED_CLINICAL,
        source_record_identifier="ROW-001",
        field_path="future_column_name",
        timestamp=NOW,
    )


def workflow_event(patient_id: str = "P-001") -> WorkflowEvent:
    return WorkflowEvent(
        event_id="WE-001",
        patient_id=patient_id,
        event_type="synthetic_task_completed",
        occurred_at=NOW,
        provenance=synthetic_provenance(),
        event_metadata={"label": "synthetic"},
    )


def test_patient_context_creation() -> None:
    context = PatientContext(
        patient_id="P-001",
        clinical_attributes={"available_attribute": "observed-value"},
        clinical_provenance=clinical_provenance(),
        evidence_references=[clinical_evidence()],
    )

    assert context.patient_id == "P-001"


def test_workflow_event_creation() -> None:
    event = workflow_event()

    assert event.provenance.provenance_type is ProvenanceType.SYNTHETIC_WORKFLOW


@pytest.mark.parametrize("patient_id", ["", "   "])
def test_blank_patient_identifier_rejected(patient_id: str) -> None:
    with pytest.raises(ValidationError):
        PatientContext(
            patient_id=patient_id,
            clinical_attributes={},
            clinical_provenance=clinical_provenance(),
        )


def test_timezone_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        WorkflowEvent(
            event_id="WE-001",
            patient_id="P-001",
            event_type="test",
            occurred_at=datetime(2026, 1, 15, 12, 0),
            provenance=synthetic_provenance(),
        )


def test_clinical_and_synthetic_provenance_cannot_be_mixed() -> None:
    with pytest.raises(ValidationError, match="must be observed clinical"):
        PatientContext(
            patient_id="P-001",
            clinical_attributes={},
            clinical_provenance=synthetic_provenance(),
        )

    synthetic_reference = EvidenceReference(
        evidence_id="SYN-001",
        patient_id="P-001",
        source_type=ProvenanceType.SYNTHETIC_WORKFLOW,
        source_record_identifier="SYN-ROW-001",
    )
    with pytest.raises(ValidationError, match="evidence must be observed clinical"):
        PatientContext(
            patient_id="P-001",
            clinical_attributes={},
            clinical_provenance=clinical_provenance(),
            evidence_references=[synthetic_reference],
        )


def test_workflow_snapshot_validation() -> None:
    snapshot = WorkflowSnapshot(
        patient_id="P-001",
        as_of=NOW,
        current_workflow_stage="review",
        completed_events=[workflow_event()],
        outstanding_tasks=["human review"],
        evidence_references=[clinical_evidence()],
    )
    assert snapshot.completed_events[0].event_id == "WE-001"

    with pytest.raises(ValidationError, match="snapshot patient"):
        WorkflowSnapshot(
            patient_id="P-002",
            as_of=NOW,
            current_workflow_stage="review",
            completed_events=[workflow_event("P-001")],
        )


def test_evidence_reference_validation() -> None:
    reference = clinical_evidence()
    assert reference.source_record_identifier == "ROW-001"

    with pytest.raises(ValidationError):
        EvidenceReference(
            evidence_id=" ",
            patient_id="P-001",
            source_type=ProvenanceType.OBSERVED_CLINICAL,
            source_record_identifier="ROW-001",
        )


def test_agent_response_validation() -> None:
    response = AgentResponse(
        patient_id="P-001",
        generated_at=NOW,
        patient_context_summary="Observed context is available.",
        workflow_summary="Synthetic workflow state is under review.",
        similar_patient_output=SimilarPatientOutput(
            method="deterministic test fixture",
            matches=[
                SimilarPatientMatch(
                    patient_id="P-002",
                    similarity_score=0.8,
                    explanation="Matched on an explicitly available attribute.",
                )
            ],
        ),
        historical_next_step_summary=HistoricalNextStepSummary(
            summary="Descriptive historical pattern only.",
            supporting_patient_ids=["P-002"],
        ),
        evidence_references=[clinical_evidence()],
        limitations=["Not for clinical decision-making."],
    )

    assert response.similar_patient_output.matches[0].similarity_score == 0.8


def test_model_serialization_round_trip() -> None:
    original = workflow_event()
    restored = WorkflowEvent.model_validate_json(original.model_dump_json())

    assert restored == original


def test_unexpected_fields_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProvenanceMetadata(
            provenance_type=ProvenanceType.OBSERVED_CLINICAL,
            source_name="source",
            unexpected="not allowed",
        )
