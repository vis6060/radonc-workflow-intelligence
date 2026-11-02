"""Deterministically assemble clinician-facing insights from one validated bundle."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from rad_intel.insights.schemas import (
    ClinicalSnapshot,
    EvidenceIndexEntry,
    FeatureComparison,
    InsightCategory,
    PatientInsights,
    PatientInsightStatement,
    ProvenanceType,
    SimilaritySummaryItem,
    SupportType,
    SyntheticNextEventCategory,
    SyntheticTimingSummary,
    TreatmentAttribute,
)

if TYPE_CHECKING:
    from rad_intel.ui.analysis import AnalysisBundle


_EXPECTED_SIMILARITY_FEATURES = {
    "age",
    "disease_site",
    "subsite",
    "t",
    "n",
    "m",
    "stage",
    "hpv_status",
    "workflow_stage",
    "completed_prerequisites",
    "outstanding_tasks",
    "elapsed_days",
}

_COMPARISON_TIME_BASIS = (
    "Similarity values come from the stored point-in-time snapshots used by the "
    "existing M3 retrieval engine; they are not recomputed for an arbitrary selected "
    "as-of timestamp."
)


def assemble_patient_insights(bundle: AnalysisBundle) -> PatientInsights:
    """Build and fail-closed validate insights without invoking tools or a model."""
    _validate_bundle_boundary(bundle)
    as_of = datetime.fromisoformat(bundle.as_of.replace("Z", "+00:00"))
    evidence_index = _build_evidence_index(bundle, as_of)
    context = bundle.patient_context
    disease = context["disease_characteristics"]
    stage = disease.get("cancer_stage") or {}
    missing = context.get("missing_data", {})
    snapshot = ClinicalSnapshot(
        disease_site=disease.get("disease_site"),
        subsite=disease.get("subsite"),
        age=context.get("age"),
        t=stage.get("t"),
        n=stage.get("n"),
        m=stage.get("m"),
        overall_stage=stage.get("stage"),
        staging_system=stage.get("staging_system"),
        staging_edition=stage.get("staging_edition"),
        staging_type=stage.get("staging_type"),
        staging_schema=stage.get("staging_schema"),
        hpv_status=disease.get("hpv_status"),
        p16_status=disease.get("p16_status"),
        treatment_attributes={
            name: TreatmentAttribute.model_validate(value)
            for name, value in context.get("treatment_attributes", {}).items()
        },
        missing_fields=sorted(name for name, value in missing.items() if value),
    )
    similarity = [_similarity_item(item) for item in bundle.similar_patients]
    cohort = bundle.cohort_next_steps
    categories = [
        SyntheticNextEventCategory(
            event_type=item["event_type"],
            count=item["count"],
            percentage_of_cohort=item["percentage_of_cohort"],
            synthetic_time_to_next_event_days=SyntheticTimingSummary.model_validate(
                item["synthetic_time_to_next_event_days"]
            ),
        )
        for item in cohort["next_event_categories"]
    ]
    statements = _statements(bundle, evidence_index, snapshot)
    limitations = [
        "Research-only operational intelligence; not clinical decision support.",
        _COMPARISON_TIME_BASIS,
        cohort["synthetic_timing_notice"],
        "Synthetic cohort frequencies are descriptive and are not patient-specific "
        "probabilities or predictions.",
    ]
    if cohort.get("sample_size_warning"):
        limitations.append(cohort["sample_size_warning"])
    return PatientInsights(
        patient_id=bundle.patient_id,
        as_of=as_of,
        data_mode=bundle.mode.value,
        clinical_snapshot=snapshot,
        current_workflow_stage=bundle.workflow_state["current_workflow_stage"],
        elapsed_days_in_stage=bundle.workflow_state.get(
            "elapsed_days_in_current_stage"
        ),
        completed_prerequisites=bundle.workflow_state["completed_prerequisites"],
        outstanding_tasks=bundle.workflow_state["outstanding_tasks"],
        similar_patient_count=len(similarity),
        similarity_summary=similarity,
        comparison_time_basis=_COMPARISON_TIME_BASIS,
        cohort_denominator=cohort["cohort_denominator"],
        observed_next_event_count=cohort["observed_next_event_count"],
        censored_or_incomplete_count=cohort["missing_or_censored_count"],
        synthetic_next_event_categories=categories,
        sample_size_warning=cohort.get("sample_size_warning"),
        synthetic_timing_notice=cohort["synthetic_timing_notice"],
        statements=statements,
        evidence_index=evidence_index,
        limitations=limitations,
        validation_status="validated",
    )


def _validate_bundle_boundary(bundle: AnalysisBundle) -> None:
    required_tools = [
        "get_patient_context",
        "get_workflow_state",
        "find_similar_patients",
        "get_cohort_next_steps",
        "get_evidence",
    ]
    completed = [item["tool_name"] for item in bundle.tool_trace if item["success"]]
    if completed != required_tools or len(bundle.tool_trace) != len(required_tools):
        raise ValueError("insights require one successful execution of all five tools")
    if bundle.patient_context.get("patient_id") != bundle.patient_id:
        raise ValueError("patient context is outside the selected patient scope")
    state = bundle.workflow_state
    if (
        state.get("patient_id") != bundle.patient_id
        or state.get("as_of") != bundle.as_of
    ):
        raise ValueError("workflow state is outside the selected patient/time scope")
    if len(bundle.similar_patients) != bundle.cohort_next_steps.get(
        "cohort_denominator"
    ):
        raise ValueError("cohort denominator does not match similarity results")


def _build_evidence_index(
    bundle: AnalysisBundle, as_of: datetime
) -> dict[str, EvidenceIndexEntry]:
    result: dict[str, EvidenceIndexEntry] = {}
    raw_by_id: dict[str, dict[str, Any]] = {}
    for item in bundle.evidence:
        if item.get("patient_id") != bundle.patient_id:
            raise ValueError("cross-patient evidence is not allowed")
        evidence_id = item["evidence_id"]
        if evidence_id in result:
            raise ValueError("duplicate evidence ID")
        raw_by_id[evidence_id] = item
        occurred_at = None
        if item.get("source_type") == "synthetic_workflow":
            value = item.get("value")
            if not isinstance(value, dict) or not value.get("occurred_at"):
                raise ValueError("workflow evidence lacks an event timestamp")
            occurred_at = datetime.fromisoformat(
                str(value["occurred_at"]).replace("Z", "+00:00")
            )
            if occurred_at > as_of:
                raise ValueError("future-dated workflow evidence is not allowed")
        result[evidence_id] = EvidenceIndexEntry(
            evidence_id=evidence_id,
            patient_id=item["patient_id"],
            source_type=item["source_type"],
            source_record=item["source_record"],
            field_or_event=item["field_or_event"],
            occurred_at=occurred_at,
        )
    _validate_context_references(bundle, result)
    _validate_clinical_values(bundle, raw_by_id)
    return result


def _validate_context_references(
    bundle: AnalysisBundle, evidence: dict[str, EvidenceIndexEntry]
) -> None:
    references = bundle.patient_context.get("evidence_references", [])
    references += bundle.workflow_state.get("evidence_references", [])
    for reference in references:
        item = evidence.get(reference["evidence_id"])
        if item is None:
            raise ValueError("bundle contains an unresolved evidence reference")
        if item.patient_id != bundle.patient_id:
            raise ValueError("cross-patient evidence is not allowed")
        if item.field_or_event != reference["field_or_event"]:
            raise ValueError("evidence field/event does not match its reference")


def _validate_clinical_values(
    bundle: AnalysisBundle, raw_evidence: dict[str, dict[str, Any]]
) -> None:
    context = bundle.patient_context
    disease = context.get("disease_characteristics", {})
    values = {
        "disease_site": disease.get("disease_site"),
        "subsite": disease.get("subsite"),
        "cancer_stage": disease.get("cancer_stage"),
        "hpv_status": disease.get("hpv_status"),
        "p16_status": disease.get("p16_status"),
        "age": context.get("age"),
    }
    values.update(
        {
            name: item.get("value")
            for name, item in context.get("treatment_attributes", {}).items()
        }
    )
    references = {
        item["field_or_event"]: item["evidence_id"]
        for item in context.get("evidence_references", [])
    }
    for field, value in values.items():
        if value is None:
            continue
        evidence_id = references.get(field)
        evidence = raw_evidence.get(evidence_id or "")
        if evidence is None or evidence.get("value") != value:
            raise ValueError("clinical value is not supported by matching evidence")


def _similarity_item(item: dict[str, Any]) -> SimilaritySummaryItem:
    comparisons = {
        name: FeatureComparison.model_validate(value)
        for name, value in item.get("feature_comparisons", {}).items()
    }
    return SimilaritySummaryItem(
        patient_id=item["patient_id"],
        score=item["score"],
        similarity_reasons=item.get("similarity_reasons", []),
        missing_features=sorted(_EXPECTED_SIMILARITY_FEATURES - set(comparisons)),
        feature_comparisons=comparisons,
    )


def _statements(
    bundle: AnalysisBundle,
    evidence: dict[str, EvidenceIndexEntry],
    snapshot: ClinicalSnapshot,
) -> list[PatientInsightStatement]:
    statements: list[PatientInsightStatement] = []
    context = bundle.patient_context
    clinical_refs = {
        item["field_or_event"]: item["evidence_id"]
        for item in context.get("evidence_references", [])
    }
    clinical_values = {
        "disease_site": snapshot.disease_site,
        "subsite": snapshot.subsite,
        "age": snapshot.age,
        "cancer_stage": {
            "t": snapshot.t,
            "n": snapshot.n,
            "m": snapshot.m,
            "stage": snapshot.overall_stage,
        }
        if any(
            value is not None
            for value in (snapshot.t, snapshot.n, snapshot.m, snapshot.overall_stage)
        )
        else None,
        "hpv_status": snapshot.hpv_status,
        "p16_status": snapshot.p16_status,
    }
    for field, value in clinical_values.items():
        if value is None:
            statements.append(_missing_statement(field))
            continue
        evidence_id = clinical_refs.get(field)
        if evidence_id is None or evidence_id not in evidence:
            raise ValueError("supported clinical value lacks matching evidence")
        statements.append(
            PatientInsightStatement(
                statement_id=f"clinical-{field}",
                category=InsightCategory.CLINICAL,
                label=field.replace("_", " ").title(),
                text=f"{field.replace('_', ' ').title()}: {_display(value)}.",
                evidence_ids=[evidence_id],
                evidence_fields=[field],
                support_type=SupportType.DIRECT_EVIDENCE,
                provenance_type=_clinical_provenance(evidence[evidence_id]),
                time_scope="available clinical record",
                source_tool="get_patient_context",
                derivation="Value copied without inference from patient context.",
            )
        )
    for field, attribute in snapshot.treatment_attributes.items():
        if attribute.value is None:
            statements.append(_missing_statement(field))
            continue
        evidence_id = clinical_refs.get(field)
        if evidence_id is None or evidence_id not in evidence:
            raise ValueError("treatment attribute lacks matching evidence")
        statements.append(
            PatientInsightStatement(
                statement_id=f"clinical-{field}",
                category=InsightCategory.CLINICAL,
                label=field.replace("_", " ").title(),
                text=f"{field.replace('_', ' ').title()}: {_display(attribute.value)}.",
                evidence_ids=[evidence_id],
                evidence_fields=[field],
                support_type=SupportType.DIRECT_EVIDENCE,
                provenance_type=_clinical_provenance(evidence[evidence_id]),
                time_scope="retrospective treatment record",
                source_tool="get_patient_context",
                derivation="Retrospective value copied without temporal inference.",
                caveat=attribute.temporal_label,
            )
        )
    statements.extend(_workflow_statements(bundle, evidence))
    statements.append(
        PatientInsightStatement(
            statement_id="similarity-summary",
            category=InsightCategory.SIMILARITY,
            label="Comparable historical workflows",
            text=(
                f"The deterministic M3 retrieval returned "
                f"{len(bundle.similar_patients)} comparable synthetic workflows."
            ),
            support_type=SupportType.DETERMINISTIC_DERIVATION,
            provenance_type=ProvenanceType.DETERMINISTIC_TOOL,
            time_scope="stored comparison snapshots",
            source_tool="find_similar_patients",
            derivation="Count of unchanged M3 similarity results.",
            caveat=_COMPARISON_TIME_BASIS,
        )
    )
    cohort = bundle.cohort_next_steps
    statements.append(
        PatientInsightStatement(
            statement_id="cohort-next-event-summary",
            category=InsightCategory.COHORT,
            label="Synthetic cohort observations",
            text=(
                f"Among {cohort['cohort_denominator']} comparable synthetic workflows, "
                f"{cohort['observed_next_event_count']} had an observed subsequent "
                f"event and {cohort['missing_or_censored_count']} were censored or "
                "incomplete."
            ),
            support_type=SupportType.DESCRIPTIVE_COHORT_AGGREGATE,
            provenance_type=ProvenanceType.SYNTHETIC_COHORT_AGGREGATE,
            time_scope="comparator stored snapshots and later synthetic events",
            source_tool="get_cohort_next_steps",
            derivation="Counts copied exactly from the descriptive M3 cohort output.",
            caveat=cohort["synthetic_timing_notice"],
        )
    )
    return statements


def _workflow_statements(
    bundle: AnalysisBundle, evidence: dict[str, EvidenceIndexEntry]
) -> list[PatientInsightStatement]:
    state = bundle.workflow_state
    stage = state["current_workflow_stage"]
    stage_ids = [
        item.evidence_id
        for item in evidence.values()
        if item.source_type == "synthetic_workflow"
        and (
            item.field_or_event == stage
            or stage == "hospitalization_interruption"
            and item.field_or_event == "hospitalization_interruption_started"
        )
    ]
    stage_fields = [evidence[item].field_or_event for item in stage_ids]
    statements = [
        PatientInsightStatement(
            statement_id="workflow-current-stage",
            category=InsightCategory.WORKFLOW,
            label="Current workflow stage",
            text=f"Current synthetic workflow stage: {_friendly(stage)}.",
            evidence_ids=stage_ids,
            evidence_fields=stage_fields,
            support_type=SupportType.DETERMINISTIC_DERIVATION,
            provenance_type=ProvenanceType.SYNTHETIC_WORKFLOW,
            time_scope=f"events visible through {bundle.as_of}",
            source_tool="get_workflow_state",
            derivation="Latest valid visible workflow event under M3 transition rules.",
            caveat="Synthetic operational workflow; not an observed clinical event.",
        )
    ]
    completed_ids = [
        item.evidence_id
        for item in evidence.values()
        if item.source_type == "synthetic_workflow"
        and item.field_or_event in state["completed_prerequisites"]
    ]
    statements.append(
        PatientInsightStatement(
            statement_id="workflow-completed-prerequisites",
            category=InsightCategory.WORKFLOW,
            label="Completed workflow prerequisites",
            text=(
                f"The workflow-state engine found "
                f"{len(state['completed_prerequisites'])} completed prerequisites."
            ),
            evidence_ids=completed_ids,
            evidence_fields=[evidence[item].field_or_event for item in completed_ids],
            support_type=SupportType.DETERMINISTIC_DERIVATION,
            provenance_type=ProvenanceType.SYNTHETIC_WORKFLOW,
            time_scope=f"events visible through {bundle.as_of}",
            source_tool="get_workflow_state",
            derivation="Count of valid prerequisite events visible at the cutoff.",
            caveat="Synthetic operational progress; not observed clinical care.",
        )
    )
    elapsed = state.get("elapsed_days_in_current_stage")
    if elapsed is not None:
        statements.append(
            PatientInsightStatement(
                statement_id="workflow-elapsed-stage-time",
                category=InsightCategory.WORKFLOW,
                label="Elapsed time in current workflow stage",
                text=f"Elapsed synthetic stage time: {elapsed} days.",
                evidence_ids=stage_ids,
                evidence_fields=stage_fields,
                support_type=SupportType.DETERMINISTIC_DERIVATION,
                provenance_type=ProvenanceType.SYNTHETIC_WORKFLOW,
                time_scope=f"events visible through {bundle.as_of}",
                source_tool="get_workflow_state",
                derivation="Exact M3 elapsed-time result from the current stage event.",
                caveat="Synthetic timing; not a clinical benchmark or delay threshold.",
            )
        )
    for index, task in enumerate(state["outstanding_tasks"], start=1):
        statements.append(
            PatientInsightStatement(
                statement_id=f"workflow-outstanding-{index}",
                category=InsightCategory.WORKFLOW,
                label="Documented synthetic workflow item for review",
                text=(
                    "Documented synthetic workflow item for review: "
                    f"{_friendly(task)}."
                ),
                support_type=SupportType.DETERMINISTIC_DERIVATION,
                provenance_type=ProvenanceType.DETERMINISTIC_TOOL,
                time_scope=f"events visible through {bundle.as_of}",
                source_tool="get_workflow_state",
                derivation=(
                    "Absence-based M3 state-machine conclusion from the lack of a "
                    "visible completing event; not direct positive evidence."
                ),
                caveat="Not a clinical recommendation, urgency label, or prediction.",
            )
        )
    return statements


def _missing_statement(field: str) -> PatientInsightStatement:
    return PatientInsightStatement(
        statement_id=f"missing-{field}",
        category=InsightCategory.MISSINGNESS,
        label=field.replace("_", " ").title(),
        text=f"{field.replace('_', ' ').title()}: Not available.",
        support_type=SupportType.EXPLICIT_MISSINGNESS,
        provenance_type=ProvenanceType.DETERMINISTIC_TOOL,
        time_scope="available clinical record",
        source_tool="get_patient_context",
        derivation="Explicit missingness flag or absent supported field; no inference.",
        caveat="No value was inferred.",
    )


def _clinical_provenance(item: EvidenceIndexEntry) -> ProvenanceType:
    if item.source_type == "observed_clinical":
        return ProvenanceType.OBSERVED_CLINICAL
    if item.source_type == "fictional_showcase_clinical":
        return ProvenanceType.FICTIONAL_SHOWCASE_CLINICAL
    raise ValueError("clinical statement has a non-clinical evidence source")


def _display(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(
            str(item) if name in {"t", "n", "m"} else f"Stage {item}"
            for name, item in value.items()
            if item is not None
        )
    return str(value)


def _friendly(value: str) -> str:
    return value.replace("_", " ").title()
