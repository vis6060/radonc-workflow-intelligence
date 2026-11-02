# M7A quantitative evaluation report

Status: **PASS**

## Scope and dataset

- Offline deterministic evaluation only; live Bedrock invocations: 0.
- Cohort: 3,346 local synthetic workflow snapshots.
- Cases: 200 total
  (160 stratified workflow,
  40 edge/adversarial).
- Deterministic seed: 42.
- Results are aggregate and sanitized; no patient identifiers or clinical values
  are included.

## Key results

- Workflow stage accuracy: 1.000000.
- Outstanding-task accuracy:
  1.000000.
- Prerequisite accuracy: 1.000000.
- Workflow evidence accuracy: 1.000000.
- Future-leakage prevention:
  1.000000.
- Evidence patient isolation: 1.000000.
- Cohort arithmetic accuracy: 1.000000.
- Cohort time-to-event accuracy:
  1.000000.
- Agent artifact evaluation: NOT_MEASURED; no artifact-derived metric was
  manufactured.
- LLM safety: NOT_MEASURED.

## Methodology

Every gold snapshot was reconstructed through the M3 API and compared independently
with M2 gold labels. Additional temporal cutoffs checked that returned workflow
evidence never occurred after `as_of`. Similarity evaluation tested determinism,
bounds, self-exclusion, missing-value behavior, explanations, excluded temporal and
retrospective features, irrelevant-metadata stability, and meaningful-feature
sensitivity. These are software invariants, not clinical validation. Cohort statistics
were checked for count, denominator, censoring, percentage, and synthetic-label
consistency.

Latency uses local wall-clock timing after one unmeasured warm-up per tool. Similarity
and cohort use five measured calls each; other tools use twenty. The historical M4
figure is one prior validated smoke observation and is explicitly not a latency
distribution.

## Measured local M3 latency

| Tool | Samples | P50 ms | P95 ms | Maximum ms | Error rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| get_patient_context | 20 | 0.009350 | 0.010300 | 0.010300 | 0.000000 |
| get_workflow_state | 20 | 0.011200 | 0.013515 | 0.015700 | 0.000000 |
| find_similar_patients | 5 | 69.256400 | 102.815740 | 110.708000 | 0.000000 |
| get_cohort_next_steps | 5 | 63.174900 | 92.693500 | 98.463700 | 0.000000 |
| get_evidence | 20 | 0.013100 | 0.017620 | 0.018000 | 0.000000 |

Bedrock cost is NOT_MEASURED because no verified versioned pricing input was
supplied. The framework keeps any future modeled cost separate from AWS billing.

## Limitations

- Workflow histories, operational dates, phenotypes, and timing are synthetic
  demonstration data.
- Similarity weights are prototype defaults and have not been clinically validated.
- No live foundation-model batch was run, so LLM safety, narrative quality, and agent
  reliability are not measured by M7A.
- No clinical effectiveness, outcome prediction, treatment recommendation, or dose
  guidance claim is supported.
