"""Streamlit renderers for the four data-driven intelligence panels."""

from __future__ import annotations

from typing import Any

import streamlit as st

from rad_intel.ui.analysis import (
    AnalysisBundle,
    RecordedAgentArtifact,
    missing_comparison_features,
)


def render_patient_context(bundle: AnalysisBundle) -> None:
    context = bundle.patient_context
    disease = context["disease_characteristics"]
    stage = disease.get("cancer_stage") or {}
    with st.container(border=True):
        st.subheader("1 · Patient context")
        if context.get("provenance", {}).get("source_type") == "observed_clinical":
            st.caption(
                "Observed clinical record; treatment fields may be retrospective."
            )
        else:
            st.caption(
                "Entirely fictional showcase context; not a RADCURE patient record."
            )
        left, right = st.columns(2)
        left.metric("Disease site", _display(disease.get("disease_site")))
        right.metric("Subsite", _display(disease.get("subsite")))
        if "p16_status" in disease:
            clinical_columns = st.columns(3)
            clinical_columns[0].metric("Age", _display(context.get("age")))
            clinical_columns[1].metric(
                "HPV status", _display(disease.get("hpv_status"))
            )
            clinical_columns[2].metric(
                "p16 status", _display(disease.get("p16_status"))
            )
        else:
            left.metric("Age", _display(context.get("age")))
            right.metric("HPV status", _display(disease.get("hpv_status")))
        stage_columns = st.columns(4)
        for column, label, key in zip(
            stage_columns,
            ("T", "N", "M", "Overall"),
            ("t", "n", "m", "stage"),
            strict=True,
        ):
            column.metric(label, _display(stage.get(key)))
        if stage.get("staging_system"):
            st.caption(
                " · ".join(
                    str(stage[key]).replace("_", " ")
                    for key in (
                        "staging_system",
                        "staging_edition",
                        "staging_type",
                        "staging_schema",
                    )
                    if stage.get(key)
                )
            )
        st.markdown("**Available treatment characteristics**")
        treatment_rows = [
            {
                "Attribute": name.replace("_", " ").title(),
                "Value": _display(item.get("value")),
                "Temporal status": item.get("temporal_label"),
            }
            for name, item in context.get("treatment_attributes", {}).items()
            if item.get("value") is not None
        ]
        if treatment_rows:
            st.dataframe(treatment_rows, hide_index=True, use_container_width=True)
        else:
            st.caption("No treatment characteristics are available.")
        missing = [
            name.replace("_", " ")
            for name, is_missing in context.get("missing_data", {}).items()
            if is_missing
        ]
        st.caption(
            "Missing values: " + (", ".join(missing) if missing else "None")
        )
        st.caption(
            f"Clinical evidence references: {len(context['evidence_references'])}"
        )


def render_workflow_state(bundle: AnalysisBundle) -> None:
    state = bundle.workflow_state
    with st.container(border=True):
        st.subheader("2 · Workflow state")
        st.caption(
            "Synthetic operational workflow reconstructed only through the selected "
            "as-of timestamp."
        )
        left, right = st.columns(2)
        left.metric(
            "Current stage",
            state["current_workflow_stage"].replace("_", " ").title(),
        )
        elapsed = state.get("elapsed_days_in_current_stage")
        right.metric(
            "Elapsed in stage",
            f"{elapsed:.2f} days" if elapsed is not None else "—",
        )
        st.markdown("**Completed prerequisites**")
        st.write(_friendly_list(state["completed_prerequisites"]))
        st.markdown("**Outstanding tasks**")
        st.write(_friendly_list(state["outstanding_tasks"]))
        st.markdown("**Visible event timeline**")
        if bundle.timeline:
            st.dataframe(bundle.timeline, hide_index=True, use_container_width=True)
        else:
            st.caption("No workflow events are visible at this timestamp.")
        st.caption(
            f"Visible synthetic evidence IDs: {len(state['evidence_references'])}"
        )


def render_similar_patients(bundle: AnalysisBundle) -> None:
    with st.container(border=True):
        st.subheader("3 · Similar patients")
        st.caption(
            "Deterministic weighted Gower-style retrieval; the UI does not recalculate "
            "scores."
        )
        rows = []
        for item in bundle.similar_patients:
            rows.append(
                {
                    "Patient ID": item["patient_id"],
                    "Score": item["score"],
                    "Similarity reasons": ", ".join(
                        item.get("similarity_reasons", [])
                    )
                    or "No exact-match reason",
                    "Missing comparisons": ", ".join(
                        missing_comparison_features(item)
                    )
                    or "None",
                }
            )
        st.dataframe(rows, hide_index=True, use_container_width=True)
        if rows:
            st.bar_chart(rows, x="Patient ID", y="Score", horizontal=True)
        with st.expander("Inspect comparison factors"):
            for item in bundle.similar_patients:
                st.markdown(f"**{item['patient_id']} · {item['score']:.3f}**")
                st.dataframe(
                    comparison_factor_rows(item),
                    hide_index=True,
                    use_container_width=True,
                )


def comparison_factor_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Present M3 comparison values verbatim without recalculating them."""
    return [
        {
            "Feature": feature.replace("_", " ").title(),
            "Selected patient": comparison.get("query"),
            "Comparator": comparison.get("candidate"),
            "Feature similarity": comparison.get("similarity"),
        }
        for feature, comparison in item.get("feature_comparisons", {}).items()
    ]


def render_next_steps(bundle: AnalysisBundle) -> None:
    cohort = bundle.cohort_next_steps
    with st.container(border=True):
        st.subheader("4 · Historical next steps")
        st.caption(
            "SYNTHETIC demonstration-only workflow statistics—not clinical outcomes "
            "or predictions."
        )
        metrics = st.columns(3)
        metrics[0].metric("Comparable cohort", cohort["cohort_denominator"])
        metrics[1].metric("Observed next events", cohort["observed_next_event_count"])
        metrics[2].metric("Censored / incomplete", cohort["missing_or_censored_count"])
        rows = []
        for item in cohort["next_event_categories"]:
            timing = item["synthetic_time_to_next_event_days"]
            rows.append(
                {
                    "Synthetic next event": item["event_type"],
                    "Count": item["count"],
                    "Percent": item["percentage_of_cohort"],
                    "Median days": timing["median"],
                    "Range days": f"{timing['minimum']} – {timing['maximum']}",
                }
            )
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)
            st.bar_chart(rows, x="Synthetic next event", y="Count")
        else:
            st.caption("No subsequent event was observed in this synthetic cohort.")
        if cohort.get("sample_size_warning"):
            st.warning(cohort["sample_size_warning"])
        st.info(cohort["synthetic_timing_notice"])


def render_evidence_and_trace(
    bundle: AnalysisBundle,
    recorded: RecordedAgentArtifact | None,
) -> None:
    with st.expander("Evidence, provenance, and execution trace", expanded=False):
        st.markdown("### Evidence registry")
        rows = [
            {
                "Evidence ID": item["evidence_id"],
                "Field / event": item["field_or_event"],
                "Source type": item["source_type"],
                "Source record": item["source_record"],
            }
            for item in bundle.evidence
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.success(bundle.validation_status)
        st.markdown("### Deterministic local tool execution")
        st.dataframe(bundle.tool_trace, hide_index=True, use_container_width=True)
        if recorded is None:
            st.info(
                "No authentic sanitized live-agent artifact is configured. No agent "
                "trace or model metrics are displayed."
            )
            return
        st.markdown(f"### {recorded.trace_label}")
        st.caption(recorded.validation_status)
        metrics = recorded.response.execution_metrics
        st.json(
            {
                "model_id": metrics.model_id,
                "stop_reason": metrics.stop_reason,
                "latency_ms": metrics.latency_ms,
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "total_tokens": metrics.total_tokens,
            }
        )
        st.dataframe(
            recorded.response.tool_execution_trace,
            hide_index=True,
            use_container_width=True,
        )


def _display(value: Any) -> str:
    if value is None or value == "":
        return "Not available"
    return str(value)


def _friendly_list(values: list[str]) -> str:
    if not values:
        return "None"
    return " · ".join(value.replace("_", " ").title() for value in values)
