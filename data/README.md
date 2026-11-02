# Data directory

No patient-level data is committed to this repository. Future RADCURE source files,
normalized records, and generated patient-level workflow data must remain local or
in approved restricted storage and are excluded by `.gitignore`.

`sample/` is reserved for reviewed, non-identifying fixtures. No sample patient
records are included in M0.

M1 ingestion writes to `data/processed/` only when given an explicit source and
mapping. The entire output directory remains ignored because `patients.csv`
contains patient-level data. `data_quality.json` and `field_mapping.json` are also
kept local so an ingestion run stays together as one controlled artifact set.

M2 also writes synthetic patient-level workflow events, snapshots, gold references,
and an aggregate generation report to `data/processed/`. Synthetic records must
remain explicitly labeled and must never be presented as observed RADCURE workflow
history. Gold references are evaluation-only and must stay separate from future
agent-visible inputs.
