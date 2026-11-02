"""Streamlit presentation for validated deterministic patient insights."""

from __future__ import annotations

from typing import Any

import streamlit as st

from rad_intel.insights.schemas import PatientInsights


def render_patient_insights(insights: PatientInsights) -> None:
    """Render a concise primary view without changing any computed value."""
    with st.container(border=True):
        st.header("Radiation Oncology Patient Insights")
        st.caption("Evidence-grounded operational summary")
        if insights.data_mode == "Synthetic Agent Demonstration":
            st.info("FICTIONAL DEMONSTRATION DATA")
        else:
            st.info(
                "Observed clinical record + synthetic workflows. No AWS transmission."
            )

        st.markdown("#### Patient snapshot")
        snapshot = insights.clinical_snapshot
        metrics = st.columns(4)
        disease = _display(snapshot.disease_site)
        if snapshot.subsite is not None:
            disease = f"{disease} · {_display(snapshot.subsite)}"
        metrics[0].metric("Disease", disease)
        metrics[1].metric("Stage", _display(snapshot.overall_stage))
        viral = []
        if snapshot.hpv_status is not None:
            viral.append(f"HPV {_display(snapshot.hpv_status)}")
        if snapshot.p16_status is not None:
            viral.append(f"p16 {_display(snapshot.p16_status)}")
        metrics[2].metric("HPV / p16", " · ".join(viral) or "Not available")
        metrics[3].metric(
            "Current workflow stage", _friendly(insights.current_workflow_stage)
        )

        st.markdown("#### Where the patient is now")
        elapsed = insights.elapsed_days_in_stage
        elapsed_text = (
            f"{elapsed:.2f} days in this stage"
            if elapsed is not None
            else "elapsed time in this stage is not available"
        )
        st.write(
            f"At the selected point in time, the synthetic workflow is at "
            f"**{_friendly(insights.current_workflow_stage)}**, with {elapsed_text}. "
            f"The workflow-state engine found "
            f"{len(insights.completed_prerequisites)} completed prerequisites."
        )

        st.markdown("#### Workflow items for review")
        st.caption(
            "Documented synthetic workflow items for review—not clinical "
            "recommendations or urgency labels."
        )
        if insights.outstanding_tasks:
            for task in insights.outstanding_tasks:
                st.markdown(f"- {_friendly(task)}")
        else:
            st.write("No outstanding synthetic workflow item is represented.")

        st.markdown("#### Comparable historical workflows")
        cohort_metrics = st.columns(3)
        cohort_metrics[0].metric(
            "Retrieved comparators", insights.similar_patient_count
        )
        cohort_metrics[1].metric(
            "Observed subsequent events", insights.observed_next_event_count
        )
        cohort_metrics[2].metric(
            "Censored / incomplete", insights.censored_or_incomplete_count
        )
        categories = [
            {
                "Historical synthetic event": _friendly(item.event_type),
                "Observed count": item.count,
                "Cohort percent": item.percentage_of_cohort,
            }
            for item in insights.synthetic_next_event_categories[:3]
        ]
        if categories:
            st.dataframe(categories, hide_index=True, width="stretch")
        st.caption(
            "These are historical synthetic observations, not patient-specific "
            "predictions or clinical probabilities."
        )

        st.markdown("#### Supporting evidence")
        _render_evidence_expanders(insights)
        st.success(
            "Deterministic tool-derived insights validated. No model was invoked "
            "for this summary."
        )


def _render_evidence_expanders(insights: PatientInsights) -> None:
    clinical = [
        item
        for item in insights.evidence_index.values()
        if item.source_type != "synthetic_workflow"
    ]
    workflow = [
        item
        for item in insights.evidence_index.values()
        if item.source_type == "synthetic_workflow"
    ]
    with st.expander("Clinical evidence"):
        st.dataframe(
            [_evidence_row(item) for item in clinical],
            hide_index=True,
            width="stretch",
        )
    with st.expander("Workflow evidence"):
        st.dataframe(
            [_evidence_row(item) for item in workflow],
            hide_index=True,
            width="stretch",
        )
    with st.expander("How this summary was derived"):
        st.dataframe(
            [
                {
                    "Statement": item.label,
                    "Support": item.support_type.value,
                    "Source tool": item.source_tool,
                    "Derivation": item.derivation,
                }
                for item in insights.statements
            ],
            hide_index=True,
            width="stretch",
        )
    with st.expander("Similar-patient comparison factors"):
        st.caption(insights.comparison_time_basis)
        for item in insights.similarity_summary:
            st.markdown(f"**{item.patient_id} · {item.score:.3f}**")
            st.caption(
                "Reasons: "
                + (", ".join(item.similarity_reasons) or "No exact-match reason")
            )
            st.dataframe(
                [
                    {
                        "Feature": name.replace("_", " ").title(),
                        "Selected patient": _table_value(value.query),
                        "Comparator": _table_value(value.candidate),
                        "Feature similarity": value.similarity,
                    }
                    for name, value in item.feature_comparisons.items()
                ],
                hide_index=True,
                width="stretch",
            )
            if item.missing_features:
                st.caption("Missing comparisons: " + ", ".join(item.missing_features))
    with st.expander("Synthetic cohort limitations"):
        st.markdown("#### Limitations and uncertainty")
        for limitation in insights.limitations:
            st.markdown(f"- {limitation}")


def _evidence_row(item: Any) -> dict[str, Any]:
    return {
        "Evidence ID": item.evidence_id,
        "Field / event": item.field_or_event,
        "Source type": item.source_type,
        "Source record": item.source_record,
        "Occurred at": item.occurred_at,
    }


def _display(value: Any) -> str:
    return "Not available" if value is None or value == "" else str(value)


def _table_value(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, list):
        return " · ".join(_friendly(str(item)) for item in value) or "None"
    return str(value)


def _friendly(value: str) -> str:
    return value.replace("_", " ").title()
