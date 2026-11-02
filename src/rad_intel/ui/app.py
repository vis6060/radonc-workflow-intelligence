"""Radiation Oncology Workflow Intelligence four-panel Streamlit demo."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from rad_intel.agentcore_runtime.runtime_service import (
    LocalCohortProvider,
    SyntheticFixtureProvider,
)
from rad_intel.insights import assemble_patient_insights
from rad_intel.showcase import SHOWCASE_COHORT_SIZE
from rad_intel.ui.analysis import (
    DataMode,
    available_patient_ids,
    load_recorded_agent_artifact,
    representative_patient_ids,
    run_analysis,
    selection_matches_bundle,
)
from rad_intel.ui.components import (
    render_evidence_and_trace,
    render_next_steps,
    render_patient_context,
    render_similar_patients,
    render_workflow_state,
)
from rad_intel.ui.patient_insights import render_patient_insights


@st.cache_resource
def _provider(mode: DataMode) -> LocalCohortProvider | SyntheticFixtureProvider:
    if mode == DataMode.LOCAL_FULL_COHORT:
        return LocalCohortProvider(Path("data/processed"))
    return SyntheticFixtureProvider()


def main() -> None:
    st.set_page_config(
        page_title="Radiation Oncology Workflow Intelligence",
        page_icon="◈",
        layout="wide",
    )
    st.title("Radiation Oncology Workflow Intelligence")
    st.markdown(
        "**Evidence-grounded specialty workflow intelligence powered by "
        "deterministic tools and agentic AI.**"
    )
    st.warning(
        "Research prototype only. Not for diagnosis, treatment decisions, outcome "
        "prediction, or autonomous clinical use. Workflow data are synthetic."
    )
    with st.expander("Dataset provenance and demonstration boundary"):
        st.markdown(
            "- **Full local mode:** 3,346 RADCURE clinical records with 14 mapped "
            "priority columns, paired with 3,346 synthetic workflow histories "
            "and 45,588 synthetic events. Patient-level files remain local and "
            "Git-ignored.\n"
            f"- **Public showcase mode:** {SHOWCASE_COHORT_SIZE} entirely fictional "
            "clinical contexts and fictional synthetic workflow histories embedded "
            "in source code. They are not sampled from or representative of RADCURE."
        )

    with st.sidebar:
        st.header("Analysis controls")
        mode = DataMode(
            st.radio(
                "Data mode",
                [item.value for item in DataMode],
                help="Full cohort is deterministic and local. Synthetic mode never "
                "loads RADCURE records.",
            )
        )
        if mode == DataMode.LOCAL_FULL_COHORT:
            st.info(
                "Local full cohort · 3,346 observed clinical records plus synthetic "
                "workflow histories. No data are sent to Bedrock."
            )
        else:
            st.info(
                f"Fictional showcase · {SHOWCASE_COHORT_SIZE} synthetic patients, "
                "no RADCURE record, and no automatic AWS invocation."
            )
        try:
            provider = _provider(mode)
            patient_ids = available_patient_ids(provider)
        except (FileNotFoundError, ValueError) as exc:
            st.error(f"Data source unavailable: {exc}")
            return
        examples = representative_patient_ids(patient_ids)
        selected = st.selectbox("Representative patient", examples)
        custom = st.text_input(
            "Patient ID override",
            placeholder="Optional exact available patient ID",
        ).strip()
        patient_id = custom or selected
        as_of = st.text_input(
            "As-of timestamp",
            placeholder="Optional; defaults to the stored snapshot",
            help="Use a timezone-aware ISO 8601 timestamp.",
        ).strip()
        run = st.button("Run Analysis", type="primary", use_container_width=True)

    if run:
        st.session_state.pop("analysis_bundle", None)
        try:
            st.session_state["analysis_bundle"] = run_analysis(
                provider,
                mode,
                patient_id,
                as_of or None,
            )
        except KeyError:
            st.error("Patient ID is not available in the selected data mode.")
        except ValueError as exc:
            st.error(f"Analysis validation failed: {exc}")
        except Exception as exc:
            st.error(f"Analysis could not be completed ({type(exc).__name__}).")

    bundle = st.session_state.get("analysis_bundle")
    if bundle is None:
        st.caption(
            "Choose a patient and select **Run Analysis** to populate the panels."
        )
        return
    if not selection_matches_bundle(bundle, mode, patient_id, as_of or None):
        st.warning(
            "Analysis controls changed. Select **Run Analysis** to refresh the "
            "patient insights and panels."
        )
        return

    st.caption(f"Patient {bundle.patient_id} · point-in-time view {bundle.as_of}")
    try:
        insights = assemble_patient_insights(bundle)
    except ValueError as exc:
        st.error(f"Patient insights validation failed: {exc}")
        return
    render_patient_insights(insights)
    top_left, top_right = st.columns(2, gap="large")
    with top_left:
        render_patient_context(bundle)
    with top_right:
        render_workflow_state(bundle)
    bottom_left, bottom_right = st.columns(2, gap="large")
    with bottom_left:
        render_similar_patients(bundle)
    with bottom_right:
        render_next_steps(bundle)

    artifact = None
    if mode == DataMode.SYNTHETIC_AGENT_DEMO:
        configured = os.getenv("RAD_INTEL_RECORDED_AGENT_ARTIFACT")
        try:
            artifact = load_recorded_agent_artifact(
                Path(configured) if configured else None,
                provider,
            )
        except (OSError, ValueError) as exc:
            st.warning(f"Recorded agent artifact was rejected: {exc}")
    render_evidence_and_trace(bundle, artifact)


if __name__ == "__main__":
    main()
