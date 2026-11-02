# Quantitative evaluation results

M7A is a deterministic offline evaluation. The authoritative machine-readable results
are [`evaluation/results/metrics.json`](../evaluation/results/metrics.json) and
[`evaluation/results/summary.json`](../evaluation/results/summary.json).

## Results at a glance

| Evaluation | Result |
| --- | ---: |
| Total cases | 200/200 passed |
| Stratified workflow scenarios | 160 |
| Edge and adversarial scenarios | 40 |
| Synthetic gold-state agreement | 3,346/3,346 |
| Additional temporal cutoffs | 200/200 |
| Deterministic safety fixtures | 12/12 |
| Unauthorized Bedrock invocations | 0 |

All 3,346 synthetic gold snapshots agreed exactly on workflow stage, outstanding
tasks, completed prerequisites, and visible evidence. No future-event leakage was
observed. Evidence checks covered resolution, provenance, patient isolation,
unsupported identifiers, cross-patient contamination, and temporal scope.

Similarity passed deterministic top-k, self-exclusion, score-bound, feature-comparison,
explanation, missing-feature, temporal-boundary, irrelevant-metadata stability, and
meaningful-feature sensitivity checks. Twenty cohort queries passed independent count,
percentage, censoring, time-to-event, warning, and synthetic-provenance checks.

## Measured local latency

One warm-up was excluded. Similarity and cohort next steps used five measured samples;
evidence used twenty. These development-machine measurements are not service-level
objectives.

| Deterministic tool | P50 | P95 | Error rate |
| --- | ---: | ---: | ---: |
| Similarity | 69.26 ms | 102.82 ms | 0% |
| Cohort next steps | 63.17 ms | 92.69 ms | 0% |
| Evidence | 0.01 ms | 0.02 ms | 0% |

## Interpretation limits

- Gold states are generated from synthetic workflow events; they are software
  references, not clinical truth.
- Similarity behavior is tested, but clinical relevance is **not validated**.
- Deterministic safety-policy fixtures are not an LLM safety rate. LLM safety is
  **NOT MEASURED**.
- M7B controlled live model batch evaluation was **NOT RUN**.
- Multi-site, prospective, subgroup, and human-factors validation have not occurred.
- No effectiveness, treatment, dose, toxicity, or outcome claim is supported.
