# Architecture decisions

## M0 contracts

- The package uses a standard `src` layout and Pydantic v2 contracts.
- Every clinical or workflow source is labeled `observed_clinical` or
  `synthetic_workflow`.
- Evidence references point to source records without embedding patient values.
- Patient context accepts only observed clinical provenance and evidence.
- Workflow snapshots enforce patient identity and point-in-time boundaries.
- Models reject undeclared fields to surface contract drift early.

Future milestones must record material architecture decisions here without
claiming unimplemented AWS integrations.

## M1 ingestion decisions

- Column mappings are explicit JSON input; the pipeline never guesses RADCURE
  headers or downloads data.
- CSV uses the standard library and XLSX uses read-only `openpyxl` loading.
- Normalized output retains source name, file name, file SHA-256, source row
  reference, and `observed_clinical` provenance on every patient row.
- Missing optional values remain empty. Explicit categorical value maps are
  optional; unknown values are preserved and counted rather than invented.
- Invalid ages become missing and are counted. The accepted range is 0 through
  130 years; no other clinical domain rules are asserted without a dictionary.
- Duplicate patient identifiers use a deterministic first-record policy. Later
  rows are excluded and reported only as aggregate counts, never identifiers.
- Generated artifacts omit run timestamps and absolute paths so identical input
  bytes and mapping configuration produce byte-identical output.
- Composite JSON fields preserve related source columns without changing the M0
  response contracts: T/N/M/Stage form `cancer_stage`; treatment modality and
  concurrent chemotherapy form `systemic_therapy`; and RT start, total dose, and
  fractions form `radiation_treatment_characteristics`.
- Source-column names preserve exact workbook spelling, including meaningful
  leading or trailing whitespace. Whitespace-normalized duplicate headers are
  rejected as ambiguous.

## M2 synthetic workflow decisions

- The generator reads only exact M1 patient identifiers. It does not inspect or
  copy clinical attributes and does not derive operations from clinical RT dates.
- Seed 42, a fixed UTC anchor, per-patient deterministic random streams, and bounded
  hour ranges make output reproducible and independent of input row order.
- Every history contains the same 13 baseline event transitions. Explicit exception
  events represent rescheduling, no-show, and hospitalization interruption.
- Eight phenotypes and 13 baseline snapshot positions use balanced shuffled
  assignments so cohort coverage does not depend on chance.
- Each event has synthetic provenance plus a deterministic evidence reference owned
  by the same patient. IDs use namespace-based UUIDs and contain no clinical value.
- Current snapshots contain only events and evidence at or before `as_of`.
  Evaluation gold is separately derived from the event stream and stored outside
  agent-visible workflow inputs.
- Generated artifacts omit run timestamps and absolute paths. Identical input bytes,
  configuration, and seed produce byte-identical files.

## M3 deterministic intelligence decisions

- All five tools read local M1/M2 artifacts and require no AWS credentials.
- Workflow state is reconstructed from events at or before `as_of`; gold is never
  loaded by production tool code.
- Similarity uses weighted, missing-aware mixed-feature distances. Each candidate
  is compared at its own synthetic snapshot time. Ranking uses descending score
  then patient ID for deterministic tie-breaking.
- Similarity excludes phenotype labels, future events, gold, outcomes, and
  retrospective treatment fields whose earlier availability is not established.
- Cohort analytics select the first observed synthetic event after each patient's
  own snapshot and report censored observations separately.
- Evidence indexes are keyed by both patient and evidence ID. Cross-patient
  resolution is rejected rather than relabeled.
