# M7A quantitative evaluation methodology

## Scope

M7A is an offline evaluation of deterministic M3 behavior over the local M2
synthetic workflow cohort. It performs no Bedrock invocation and creates no AWS
resource. The fixed seed is 42.

The 200-case evaluation set contains 160 workflow cases (20 from each of the eight
synthetic phenotypes) and 40 adversarial or edge cases. Selection is deterministic,
stage-diverse, and gives priority to records with missing available clinical fields.
Patient identifiers are used only in memory and are not written to evaluation output.

## Workflow gold evaluation

All 3,346 M2 gold snapshots are reconstructed with `get_workflow_state`. Stage,
outstanding tasks, completed prerequisites, and evidence identifiers are compared
with the independently generated gold file. Every returned event timestamp must be
at or before `as_of`. Two hundred additional mid-history cutoffs exercise the same
future-information boundary.

## Similarity evaluation

Similarity is checked through behavioral invariants: repeated-call determinism,
self-exclusion, score bounds, explanation support, missing-pair exclusion, restricted
feature boundaries, stability under irrelevant metadata, and sensitivity to meaningful
feature changes. This is software evaluation only. It does not validate the clinical
appropriateness of the weights, features, or neighbors.

## Evidence and cohort evaluation

Evidence checks validate resolution, patient ownership, provenance, temporal scope,
unsupported-reference rejection, and cross-patient rejection. Cohort checks validate
denominators, observed and censored counts, percentages, and required synthetic-timing
labels. Historical next-step summaries remain descriptive and are not predictions.

## Agent and safety boundaries

The artifact harness accepts only explicitly supplied, sanitized M4 result JSON. With
no artifact supplied, all agent-derived metrics are `NOT_MEASURED`; traces, token use,
and model performance are never fabricated. The M7A live runner is disabled by
default. The single M4 latency/token record is retained only as a historical
observation, not a distribution.

Twelve deterministic policy fixtures cover treatment recommendations, dose advice,
toxicity and outcome predictions, unsupported operational conclusions, and fabricated
citations. Because no model was invoked, LLM safety is explicitly `NOT_MEASURED`.

## Performance

Each M3 tool receives one unmeasured warm-up. Context, workflow, and evidence use 20
local wall-clock samples; similarity and cohort use five because similarity scans the
full cohort. Reports include p50, p95, maximum, sample size, and error rate. These
measurements describe this development machine and are not service-level objectives.
Bedrock cost is `NOT_MEASURED` unless explicit versioned pricing inputs are supplied;
modeled cost is kept separate from AWS billing.

## Reproduction

```powershell
python -m evaluation.runner `
  --data-directory data\processed `
  --output evaluation\results
```

The generated aggregate artifacts are `summary.json`, `case_results.csv`,
`metrics.json`, `failure_analysis.md`, and `report.md`. Raw and processed patient-level
files remain Git-ignored.

Future clinical validation requires governed multi-site data, independently adjudicated
operational labels, prespecified clinical and subgroup analyses, calibration review,
privacy/security approval, and prospective monitoring. M7A provides none of those.
