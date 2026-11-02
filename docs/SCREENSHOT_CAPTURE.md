# Public screenshot capture checklist

The three M9A README images were captured manually from the built-in synthetic fixture
and reviewed with this procedure. Repeat it if any screenshot is replaced:

1. Start the app with `python -m streamlit run src/rad_intel/ui/app.py`.
2. Select **Synthetic Agent Demonstration**. Confirm the sidebar says no RADCURE record
   is loaded and no automatic AWS invocation occurs.
3. Select **Run Analysis** for `SYNTHETIC-DEMO-001`.
4. Capture the full four-panel dashboard.
5. Capture patient context and workflow state.
6. Capture similar patients and historical next steps.
7. Expand **Evidence, provenance, and execution trace** and capture the deterministic
   local trace.
8. Review every image for local paths, notifications, unrelated windows, credentials,
   real patient identifiers, or observed RADCURE attributes.
9. Save reviewed PNG files under `docs/images/` and embed only those real files with
   relative Markdown paths.

Do not switch to **Local Full Cohort** for public screenshots. Do not manufacture or
redact a synthetic screenshot to make it appear like a live Bedrock result.

Validated M9A files are `dashboard-overview.png`, `workflow-evidence.png`, and
`similarity-cohort.png` under `docs/images/`.
