# Product roadmap

The current product is an operational workflow research prototype. The roadmap favors
governance, evidence quality, and human review before scale.

## Near-term productization

1. **AgentCore remote deployment:** review the generated infrastructure plan, create a
   least-privilege execution role, deploy only the synthetic provider, and add bounded
   observability and cost controls.
2. **Governed cloud data storage:** design authorization, encryption, access review,
   retention, lineage, deletion, and audit controls before considering real cohort data.
3. **Controlled live LLM batch evaluation:** prespecify invocation count and spend,
   use synthetic or sanitized artifacts, and measure tool selection, grounding, safety,
   isolation, tokens, latency, and failure modes.
4. **Retrieval and agent comparisons:** compare transparent baselines, feature sets,
   orchestration strategies, model choices, and deterministic-only fallbacks.

## Validation required for clinical environments

5. **Multi-site operational validation:** use independently governed data and labels,
   test site-specific workflow variation, missingness, subgroup behavior, and drift.
6. **Human-in-the-loop evaluation:** study whether qualified users can identify the
   evidence, correct errors, understand uncertainty, and make better operational
   decisions without automation bias.

## Explicitly outside current scope

- predictive clinical models or outcome prediction
- treatment or radiation-dose recommendations
- toxicity prediction
- autonomous task creation, scheduling, escalation, or care decisions
- replacing source records, clinical judgment, or institutional workflow controls

Any scope expansion requires new governance, safety analysis, validation, and explicit
authorization; it is not implied by the existing prototype.
