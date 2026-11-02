# Four-minute hiring-manager demonstration

## 0:00–0:30 — Problem and product opportunity

“Radiation oncology delivery is a longitudinal workflow with many interdependent
handoffs. The product question is not simply what is in the chart; it is what stage the
workflow is in now, what remains outstanding, what comparable histories show, and what
evidence supports each statement. This prototype demonstrates an AWS-oriented specialty
intelligence layer while keeping numerical truth outside the language model.”

## 0:30–1:30 — Four-panel local demonstration

Use **Synthetic Agent Demonstration** mode and run the built-in patient.

“Panel one shows available patient context and missingness. Panel two reconstructs the
synthetic workflow strictly through the selected point in time, including completed
prerequisites and outstanding work. Panel three retrieves ten comparable synthetic
histories with transparent feature comparisons. Panel four summarizes descriptive next
events, timing, and censoring. The evidence expander exposes provenance and the actual
local tool sequence. Nothing on this screen is a treatment recommendation or outcome
prediction.”

## 1:30–2:30 — Strands, Bedrock, and deterministic tools

“A Strands agent running Claude Haiku 4.5 through Amazon Bedrock orchestrates five
tools: context, workflow state, similarity, cohort next steps, and evidence. In the
verified smoke test the model invoked all five. The model produces concise prose, but
Python captures the tool outputs and assembles the detailed JSON deterministically.
Pydantic, patient isolation, evidence resolution, and numerical equality checks reject
unsupported content. This separates flexible orchestration from correctness.”

## 2:30–3:20 — Evaluation and safety boundaries

“The offline framework passed 200 of 200 cases, including 160 stratified workflows and
40 edge cases. All 3,346 synthetic gold states matched, with no future-information
violation, and 12 deterministic safety fixtures passed. Similarity p50 was 69.26
milliseconds and cohort p50 was 63.17. These are software results: synthetic gold is
not clinical truth, similarity is not clinically validated, and LLM safety is not
measured because a live batch was not run.”

## 3:20–4:00 — AgentCore readiness and roadmap

“The repository includes a tested `BedrockAgentCoreApp` boundary, invocation and health
routes, packaging, and a synthetic deployment provider. It is prepared—not deployed.
The next steps are a least-privilege synthetic deployment, governed storage, controlled
live evaluation, architecture comparisons, multi-site validation, and human-in-the-loop
workflow studies. Predictive clinical models and autonomous actions remain out of
scope.”

## Likely technical questions

**1. How do you prevent the model from changing a statistic?**  The final detailed
response is assembled from captured deterministic tool results. Validation recomputes
the expected M3 result and rejects any divergence.

**2. How is future-information leakage prevented?**  Workflow reconstruction includes
only events at or before `as_of`; all 3,346 gold snapshots and 200 additional cutoffs
passed temporal evidence checks.

**3. Why use an agent instead of a single prompt?**  The workflow requires scoped calls
to different sources and calculations. The agent handles sequencing and narrative;
bounded deterministic tools preserve auditability and correctness.

**4. Is the similarity clinically meaningful?**  That has not been established. M7A
tests deterministic software invariants and transparent feature behavior, not clinical
validity. Multi-site expert evaluation is required.

**5. Is this deployed in production?**  No. One synthetic-only Bedrock smoke test
succeeded. AgentCore packaging is prepared locally, but M5B deployment has not started
and no clinical production deployment exists.
