# Implementation status

## Milestone checklist

- [x] M0 — Repository foundation
- [x] M1 — RADCURE ingestion
- [x] M2 — Synthetic workflow generation
- [x] M3 — Deterministic intelligence tools
- [x] M4 — Strands/Bedrock agent
- [x] M5A — AgentCore Runtime deployment preparation
- [ ] M5B — AgentCore Runtime deployment
- [x] M6 — Four-panel Streamlit application
- [x] M6.1 — Fictional showcase data and UI fidelity
- [ ] M7 — Quantitative evaluation
- [ ] M8 — GitHub documentation
- [ ] M9 — Final validation and demonstration

## Verified M0 work

- Standard Python `src` package structure and placeholder namespaces.
- Strict, typed Pydantic v2 schemas with provenance and point-in-time validation.
- Responsible-AI, product-scope, roadmap, architecture, and data-handling docs.
- Local package, schema, validation, and serialization tests.
- Secret, environment, patient-data, result, log, and machine-file exclusions.

## Verification commands

```powershell
python -m pytest -q
python -m ruff check .
```

Verified on 2026-10-31 with Python 3.13.1 in `.venv`:

- `python -m pytest -q`: 86 passed.
- `python -m ruff check .`: all checks passed.

## M1 verified implementation

Verified scaffold functionality:

- Explicit, validated source-column mappings with no assumed RADCURE headers.
- Deterministic CSV and XLSX ingestion.
- Normalized patient fields for source-supported disease site/subsite, age, stage,
  HPV status, systemic therapy, and named radiation-treatment characteristics.
- Per-row observed-clinical provenance with source-file SHA-256 and row reference.
- Aggregate source counts, unique-patient count, duplicate counts, clinical-field
  missingness, invalid/unmapped counts, and excluded-record reasons.
- Deterministic `patients.csv`, `data_quality.json`, and `field_mapping.json` output.
- Tests for mapping validation, missing source fields, normalization, missingness,
  duplicates, invalid/unmapped values, reproducibility, and XLSX input.

Validated source workbooks:

- `data/raw/RADCURE_Clinical_v04_20241219.xlsx`
- `data/raw/Field-Descriptions-for-Patient-and-Treatment-Characteristics.xlsx`

The primary worksheet is `RADCURE_TCIA_Clinical_r2_offset`; its internal
`Data Dictionary` is the primary mapping reference. The external field-description
workbook was reviewed as a supplementary reference.

Verified run results:

- 3,346 source records and 3,346 unique patient identifiers.
- Zero blank identifiers, duplicate identifiers, or excluded records.
- All 14 prioritized source columns mapped: `patient_id`, `Age`, `Ds Site`,
  `Subsite`, `T`, `N`, `M `, `Stage`, `HPV`, `Tx Modality`, `Chemo`, `RT Start`,
  `Dose`, and `Fx`.
- Zero invalid ages and zero explicitly unmapped categorical values. No categorical
  value maps were applied; observed source values were preserved.
- Repeated CLI runs produced byte-identical output artifacts.

Mapped-source missingness:

| Normalized field or component | Missing | Percent |
| --- | ---: | ---: |
| Age | 0 | 0.0000% |
| Disease site | 0 | 0.0000% |
| Subsite | 374 | 11.1775% |
| T | 12 | 0.3586% |
| N | 13 | 0.3885% |
| M | 14 | 0.4184% |
| Overall stage | 27 | 0.8069% |
| HPV | 1,629 | 48.6850% |
| Treatment modality | 0 | 0.0000% |
| Concurrent chemotherapy | 0 | 0.0000% |
| RT start | 0 | 0.0000% |
| Total dose | 0 | 0.0000% |
| Fractions | 0 | 0.0000% |

## M2 verified implementation

The seed-42 cohort run generated:

- 3,346 patient histories with an exact identifier-set match to M1.
- 45,588 timestamped, timezone-aware synthetic workflow events.
- 3,346 point-in-time snapshots and 3,346 separate gold reference states.
- Zero sequence, chronology, future-information, evidence-provenance,
  cross-patient-evidence, or gold-state mismatch violations.
- Byte-identical events, snapshots, gold, and report artifacts on a repeated run.

Phenotype distribution:

| Synthetic phenotype | Patients |
| --- | ---: |
| Normal progression | 419 |
| Authorization delay | 419 |
| Late contouring | 418 |
| Planning delay | 418 |
| Rescheduling | 418 |
| No-show | 418 |
| Hospitalization interruption | 418 |
| Treatment-start delay | 418 |

Snapshot stage distribution:

| Point-in-time stage | Patients |
| --- | ---: |
| Referral received | 258 |
| Consult scheduled | 231 |
| Consult no-show | 27 |
| Consult completed | 258 |
| Authorization requested | 258 |
| Authorization approved | 258 |
| Simulation scheduled | 257 |
| Simulation completed | 257 |
| Contour task opened | 257 |
| Contour task completed | 257 |
| Planning started | 257 |
| Plan approved | 257 |
| Treatment scheduled | 226 |
| Hospitalization interruption | 31 |
| Treatment started | 257 |

The generator reads only `patient_id`. All timing distributions, dates, workflow
events, exception events, phenotypes, snapshots, and gold states are synthetic
demonstration assumptions and are not observed RADCURE operational facts.

## M3 verified implementation

- Five deterministic tools provide patient context, point-in-time workflow state,
  similar-patient retrieval, descriptive cohort next steps, and evidence resolution.
- Independent reconstruction matched all 3,346 M2 gold states: 100% stage,
  outstanding-task, and visible-evidence agreement.
- Weighted Gower-style similarity uses age (1.0), disease site (2.0), subsite
  (1.5), T/N/M (1.0 each), overall stage (1.5), HPV (1.0), workflow stage (2.0),
  completed prerequisites (1.5), outstanding tasks (1.5), and elapsed stage time
  (1.0). Missing feature pairs are omitted and scores are bounded to 0–1.
- A deterministic representative top-10 retrieval returned scores from 0.780726 to
  0.903743 with self-match excluded.
- Its 10-patient cohort had 10 observed next events, zero censored observations,
  and one next-event category (`treatment_scheduled`, 10/10). This is synthetic,
  descriptive, and not clinically validated.
- Patient-isolated evidence resolution succeeded; cross-patient resolution is
  rejected. Production tools never read `workflow_gold.json`.
- Median warm-process timings over five representative calls were 0.009 ms for
  context, 0.010 ms for state, 70.359 ms for top-10 similarity, and 0.185 ms for
  cohort analytics. These local measurements are environment-specific.

## M4 verified implementation

M4 status is **PASS**. Offline validation and one bounded, synthetic-only live
Strands/Bedrock invocation completed successfully on 2026-11-01.

- Pinned and installed: Python 3.13.1, Strands Agents 1.63.0, Boto3 1.43.123,
  Botocore 1.43.123, and AWS CRT 0.38.0.
- The explicit `boto3.Session(profile_name="rad-intel", region_name="us-east-1")`
  resolves through the SDK's `login` credential provider when the local AWS
  configuration is available.
- Read-only STS inspection verified that `rad-intel` currently uses the AWS root
  identity. No modifying AWS operation was attempted.
- Read-only Bedrock discovery returned 124 foundation models and 99 system-defined
  inference profiles in `us-east-1` on 2026-11-01.
- Selected inference profile: `us.anthropic.claude-haiku-4-5-20251001-v1:0`.
  It was present in discovery, and AWS documents Claude Haiku 4.5 tool use.
- Registered tools: `get_patient_context`, `get_workflow_state`,
  `find_similar_patients`, `get_cohort_next_steps`, and `get_evidence`.
- Patient/cohort isolation is enforced before M3 calls. The model returns ordinary
  plain-English text; native Strands structured output is intentionally disabled.
  Detailed JSON is assembled deterministically in Python from the five captured M3
  tool results, never from model-authored clinical or numerical values.
- Narrative validation rejects abnormal termination, empty or tool-only messages,
  JSON, unsupported numbers, invalid evidence identifiers, patient identifiers,
  missing synthetic provenance, clinical recommendations, and overlong output.
- The mock-model suite verifies ordinary output extraction, actual adapter results
  and traces, token/latency plumbing, bounded turns/tokens, root blocking, discovery,
  isolation, deterministic assembly, and result-tamper rejection without AWS calls.
- Root remains blocked by the normal model constructor. A CLI-only
  `--allow-root-synthetic-smoke` exception requires the built-in synthetic fixture,
  exact profile/region/model, eight or fewer turns, ten or fewer tool calls, at most
  4,096 output tokens per turn, at most 8,000 cumulative output tokens, and one total
  AWS attempt. It cannot accept patient IDs,
  as-of input, a data path, or an `IntelligenceStore`.
- The final authorized synthetic invocation returned normal `end_turn` completion.
  Genuine tool order was `get_patient_context`, `get_workflow_state`,
  `find_similar_patients`, `get_cohort_next_steps`, then `get_evidence`; all succeeded.
- The validated live response used 6,231 input tokens and 595 output tokens (6,826
  total), with 4,790.511 ms measured model-and-agent latency. The ordinary narrative,
  deterministic detailed JSON, evidence scope, numerical values, synthetic provenance,
  patient isolation, and clinical safety boundary all validated successfully.

## M5A verified implementation

M5A status is **PASS**. M5B is **NOT STARTED**. No AWS resource was created,
modified, invoked, launched, or deployed during M5A.

- Pinned `bedrock-agentcore==1.25.2`; the supported `BedrockAgentCoreApp` entrypoint
  is `rad_intel.agentcore_runtime.app:app` with `POST /invocations` and `GET /ping`.
- Request validation accepts `patient_id`, `question`, and optional timezone-aware
  `as_of`. Responses include a request ID and elapsed time; errors use stable codes
  and do not return raw application exceptions.
- The service preserves the M4 Strands agent, five M3 tools, ordinary model text,
  deterministic Python JSON assembly, evidence validation, patient isolation,
  synthetic provenance, clinical-safety checks, and bounded turns/tool calls/tokens.
- AgentCore model creation uses the default AWS credential provider chain and rejects
  named profiles. Existing local M4 profile and root-identity guards are unchanged.
- `LocalCohortProvider` lazily uses the Git-ignored processed cohort for local-only
  execution. `SyntheticFixtureProvider` contains no RADCURE patient record and is the
  default and only initial deployment candidate.
- Deployment assets under `deployment/agentcore/` provide pinned dependencies,
  non-secret environment examples, an allowlisted package manifest, local test and
  future CLI instructions, cleanup guidance, and a readiness/security report.
- AgentCore direct code deployment supports `PYTHON_3_13`. Current AWS guidance uses
  the Node.js `@aws/agentcore` CLI; the older Python starter toolkit is not used.
- Local HTTP tests inject a fake model and verify health, complete five-tool execution,
  JSON serialization, malformed/invalid requests, patient isolation, evidence scope,
  safe errors/logging, provider selection, credential portability, and artifact
  exclusions without AWS calls.

Remaining M5B blockers include explicit deployment authorization, a least-privilege
non-root runtime execution role, review of the CLI-generated infrastructure plan,
inbound authentication and network policy, budget/monitoring/retention controls, and
a governed cloud provider before any non-synthetic cohort use.

## M6 verified implementation

M6 status is **PASS**. The local four-panel Streamlit application starts successfully
and serves its page over HTTP without an AWS call.

- Pinned Streamlit 1.66.1 and added the entrypoint at
  `src/rad_intel/ui/app.py` with the required title, subtitle, prototype notice, and
  clinical-use boundary.
- Local Full Cohort mode uses `LocalCohortProvider`, exposes five stable representative
  identifiers selected from the 3,346 available records, and executes only local M3
  tools. Observed clinical context and retrospective treatment attributes are labeled
  separately from synthetic point-in-time workflow information.
- Synthetic Agent Demonstration mode uses only `SyntheticFixtureProvider`. It makes no
  automatic Bedrock or other AWS call and does not label fixture execution as an LLM
  result.
- Patient context, workflow state/timeline, top-10 similarity, and descriptive next
  steps are displayed in four distinct panels. Similarity scores and cohort statistics
  come directly from M3 and are not recalculated in the UI.
- The workflow timeline is assembled only from evidence visible at or before `as_of`;
  exceptional stages and outstanding tasks use the existing M3 reconstruction.
- The evidence expander shows source/event provenance and a measured deterministic
  local tool trace. Live model metrics appear only if an explicitly configured,
  sanitized artifact validates as a Bedrock `end_turn` M4 result against current M3
  outputs. No such artifact is bundled or fabricated.
- Native Streamlit AppTest coverage verifies imports/startup, both modes, actual patient
  selection, exact M3 binding, point-in-time correctness, similarity/cohort integrity,
  evidence isolation, invalid IDs, recorded-trace labeling, and no automatic AWS call.
- A real headless Streamlit process started on localhost and returned HTTP 200 before
  being stopped. No AWS infrastructure was deployed during M6.

## M6.1 fictional showcase fidelity

M6.1 status is **PASS**. The public demonstration now uses a reproducible, entirely
fictional 32-patient cohort; it does not read or copy RADCURE patient records.

- Root cause: the Streamlit synthetic mode previously reused the deliberately minimal
  one-patient M4 Bedrock smoke fixture. That fixture was sufficient for bounded live
  orchestration validation but intentionally contained sparse clinical context, one
  visible workflow event, and hardcoded comparator/cohort responses. It was not a
  portfolio-quality demonstration dataset.
- `SyntheticFixtureProvider` now serves the separate in-memory showcase cohort. The
  original `SyntheticSmokeStore`, root guard, and validated M4 artifact contract remain
  intact and independent.
- All asserted fictional clinical fields have patient-scoped evidence. Fictional
  clinical provenance is distinct from both `observed_clinical` RADCURE provenance and
  `synthetic_workflow` event provenance.
- All 32 records now use an explicit AJCC 8th edition clinical prognostic staging
  convention. Fictional p16 status is asserted and evidence-linked for oropharyngeal
  records. Stage is derived from an allowlisted site/p16/T/N/M mapping: p16-positive
  oropharyngeal T2 N1 M0 is Stage I, p16-positive T3 N1 M0 is Stage II, p16-negative
  T2 N1 M0 is Stage III, and p16-negative T2 N2 M0 is Stage IVA. Supported larynx,
  hypopharynx, and oral-cavity tuples are likewise checked against AJCC 8 clinical
  groupings; unsupported tuples fail closed.
- Every fictional history includes the 13 M2 baseline events in chronological order.
  The cohort includes resolved no-show/rescheduling and hospitalization examples, an
  active point-in-time interruption, varied snapshot stages, future events, and
  completed/censored histories. State and visible evidence are restricted to `as_of`.
- The existing M3 missing-aware weighted Gower engine is used without changing its
  weights or full-cohort behavior. Ten comparators expose computed scores, all twelve
  feature comparisons, and deterministic reasons. Comparison factors are displayed as
  readable tables containing the exact M3 values, not presentation-layer calculations.
  Next-step categories, counts,
  censoring, evidence, and timing summaries are derived from generated events.
- The UI now labels fictional context explicitly and shows an aggregate-only provenance
  boundary: full local mode has 3,346 RADCURE clinical records (14 mapped priority columns),
  3,346 synthetic histories, and 45,588 synthetic events; showcase mode has 32 entirely
  fictional contexts and histories. No patient-level private data are embedded.
- M7A reports and metrics are unchanged. M4 remains the single live synthetic Bedrock
  invocation; deterministic UI execution is not labeled as a live-agent trace.
- The complete repository suite passes 104 tests; Ruff passes.
- Updated authentic screenshots remain required. M6.1 did not fabricate images or add
  nonexistent screenshot links, and M9A remains partial on that publication gate.

## M7A verified implementation

M7A status is **PASS**. M7B/live model batch evaluation is **NOT RUN**. No Bedrock
invocation or AWS resource operation occurred.

- Built a deterministic 200-case set with seed 42: 160 workflow cases, 20 per
  synthetic phenotype, plus 40 adversarial and edge cases. All 200 passed.
- Reconstructed all 3,346 gold snapshots. Stage, outstanding-task, prerequisite,
  evidence-reference, and future-leakage-prevention accuracy were each 3,346/3,346.
  An additional 200 temporal cutoffs also passed.
- Evidence resolution, provenance, patient isolation, unsupported-reference rejection,
  and cross-patient rejection all passed their measured checks.
- Similarity passed determinism, self-exclusion, score-bound, explanation,
  missing-value, temporal-feature-boundary, metadata-stability, and sensitivity
  invariants. Clinical validity is explicitly `NOT_MEASURED`.
- Twenty cohort checks passed denominator, censoring, arithmetic, and synthetic timing
  labeling validation. LLM safety is `NOT_MEASURED` because no model was invoked.
- No sanitized M4 artifact was supplied, so agent JSON, trace, narrative, token, and
  latency distribution metrics remain `NOT_MEASURED`. The one historical M4 smoke
  observation is labeled sample size one and not treated as a distribution.
- Local M3 tool benchmarks use one warm-up, explicit sample sizes, and report p50,
  p95, maximum, and error rate in `evaluation/results/metrics.json`.
- Evaluation outputs contain no patient identifiers or clinical values. Local clinical
  and workflow patient-level artifacts remain Git-ignored.
- The complete suite passes 92 tests; Ruff passes.

## M8 local portfolio documentation

M8 local portfolio status is **PASS** after final local validation. Public GitHub
release is **NOT STARTED**.

- The root README now leads with the workflow problem, product capabilities,
  deterministic correctness boundary, AWS implementation, evaluation highlights,
  limitations, and a GitHub-renderable Mermaid architecture diagram.
- Public-facing documents cover M7A results, the single M4 live Bedrock invocation,
  M5A AgentCore readiness, the product roadmap, and a four-minute hiring-manager demo.
- The architecture distinguishes implemented local components, one live-verified
  synthetic Bedrock flow, and AgentCore preparation with no deployed Runtime.
- Synthetic fixture mode was verified in the running four-panel UI. Automated image
  export was unavailable, so no screenshot was fabricated or linked; a manual capture
  checklist is documented.
- The current tree contains no username-bearing absolute Windows path, credential,
  AWS account identifier, or patient-level RADCURE record. Raw and processed data
  remain Git-ignored.
- A prior private commit contains a username-bearing Windows path. By explicit owner
  decision, the original private history is retained and must never be pushed for
  public distribution.
- **Do not push `master` or the original Git history. Publish only the reviewed orphan
  `main` branch explicitly.** Public GitHub release remains a separate future action.

## M9A final local demo and release review

M9A status is **PASS**. Local validation, reproducibility, documentation, security, and
the three required authentic public screenshots pass. M9B local staging is **PASS**;
M9C is **NOT STARTED**.

- The authorized local cohort loads all 3,346 patients. Deterministic top-10
  similarity is reproducible, cohort counts reconcile, evidence resolves within the
  selected patient scope, and the four Streamlit panels pass AppTest validation.
- Synthetic Agent Demonstration uses only `SyntheticFixtureProvider`; a test replaces
  `boto3.Session` with a failure sentinel and confirms that UI analysis makes no AWS
  call.
- Python 3.13.1, editable installation, package import, the public fixture test subset,
  full private-cohort suite, Ruff, and Streamlit startup are verified locally.
- M7A numbers, the single M4 live observation, M5B **NOT STARTED**, M7B **NOT RUN**,
  synthetic provenance, and clinical-validity limitations were rechecked.
- Current and intended publication files pass credential, account-identifier,
  patient-data, provenance-hash, sensitive-trace, and absolute-path review. Raw and
  processed patient-level files remain excluded.
- `dashboard-overview.png`, `workflow-evidence.png`, and `similarity-cohort.png` are
  authentic M6.1 synthetic-showcase captures and are embedded with GitHub-relative
  README paths. They show fictional identifiers, corrected Stage I context, computed
  similarity explanations, synthetic disclosure, and no fabricated live-agent trace.
- Visual review and PNG metadata/byte-pattern checks found no RADCURE patient record,
  credential, AWS account identifier, username-bearing path, or sensitive trace.
- Aggregate evidence remains prominent and separate: 3,346 retrospective clinical
  records, 14 mapped priority columns, 45,588 synthetic workflow events, and 200/200
  offline evaluation cases passed. The public showcase remains 32 fictional records.
- Remaining independent-history publication work is recorded in
  `docs/PUBLIC_RELEASE_CHECKLIST.md`; public GitHub release is **NOT STARTED**.

## Known limitations

- Processed patient-level artifacts are intentionally local and Git-ignored; a
  fresh authorized source copy is required to reproduce them on another machine.
- M2 timing ranges have not been calibrated to real operational workflow data and
  must not be interpreted as benchmarks or clinical expectations.
- Similarity weights and numeric ranges are transparent prototype defaults, not
  clinically validated importance estimates. Cohort analytics remain descriptive.
- Bedrock access depends on account permissions and catalog availability; the exact
  configured ID is rechecked before every live model construction.
- AgentCore deployment and live foundation-model batch evaluation are not implemented.
- Schema fields may be extended after inspecting actual RADCURE columns in M1;
  M0 does not assume dataset-specific columns.

## M9B orphan publication history

M9B local staging status is **PASS**. Public GitHub release remains **NOT STARTED**.

- Verified the approved M9A source commit
  `d64434d2d0c482a5357a0d6bc8f4b496f9696cac` and committed the required DOI and
  publication-documentation corrections on `master` without rewriting history.
- Preserved `master` and created orphan `main` with one parentless initial commit.
- Staged only reviewed source, tests, documentation, three approved synthetic
  screenshots, and aggregate evaluation reports. The supplemental screenshot and all
  patient-level or restricted artifacts are excluded.
- Repeated credential, account-identifier, absolute-path, private-hash, restricted-
  file, screenshot, Markdown-link, public-fixture, and Ruff checks.
- No remote was attached and no push occurred. A future authorized publication must
  push only `main` explicitly and must never use `--all`, `--mirror`, or `--force`.

## Next step

M5B, M7B, M9C, and public GitHub release remain not started. Stop before M9C or any
remote operation.
