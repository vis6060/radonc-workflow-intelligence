# Public release checklist

M9A status: **PASS**. M9B local orphan-branch staging status: **PASS**. The three
required public screenshots and local publication checks pass review. Public GitHub
release remains **NOT STARTED**.

## Security and privacy

- [x] Original private Git history is preserved without rewriting and has no remote.
- [x] Publication warning states: publish only the reviewed orphan `main` branch;
  never push `master`, tags, all branches, or a mirror.
- [x] Current tracked source reviewed for AWS access keys, secret-key assignments,
  private keys, account/root ARNs, username-bearing absolute paths, patient IDs,
  provenance hashes, and sensitive traces.
- [x] `data/raw/` and `data/processed/` are excluded from publication.
- [x] Virtual environments, caches, `.env` files, credentials, logs, and generated
  patient timelines are excluded.
- [x] No original-history rewrite, force push, GitHub remote, or AWS change occurred.

## Intended sanitized snapshot contents

Include only reviewed source, tests, aggregate evaluation reports, architecture and
documentation, non-secret examples, and deployment-preparation files. Exclude:

- `.git/` and every object from the private development history;
- all RADCURE workbooks, normalized rows, mappings tied to restricted runs, patient
  tables, workflow events, snapshots, and gold patient-level records;
- authentic or synthetic patient-level generated exports not explicitly reviewed as
  public fixtures;
- AWS configuration, credentials, account identifiers, login state, local paths,
  logs, traces, and recorded prompts;
- `.venv/`, caches, build output, editor settings, and temporary files.

## Screenshot review

- [x] `docs/images/dashboard-overview.png` — authentic M6.1 four-panel UI; fictional
  `SYNTHETIC-DEMO-001`, p16-positive T2 N1 M0 Stage I, and synthetic disclosure visible.
- [x] `docs/images/workflow-evidence.png` — fictional clinical/workflow evidence,
  deterministic five-tool trace, and explicit no-live-agent-artifact notice visible.
- [x] `docs/images/similarity-cohort.png` — computed top-ten explanations, exact M3
  comparison-factor table, synthetic cohort analytics, and disclosure visible.
- [x] README uses existing GitHub-relative image paths; no placeholder is embedded.
- [x] All captures use **Synthetic Agent Demonstration**. Visual and binary-metadata
  review found no RADCURE record, credential, account identifier, username path, or
  fabricated Bedrock trace.
- [x] The supplemental `workflow-evidence-top.png` capture is excluded from `main`.

## Reproducibility

- [x] Python 3.13.1 environment verified.
- [x] Editable package installation completed from the repository.
- [x] Public synthetic/file-generated pytest subset documented and verified.
- [x] Complete private-cohort suite documented separately and verified locally.
- [x] Package import and Streamlit AppTest startup verified.
- [x] Synthetic four-panel mode verified without an AWS call.
- [x] README explains how to obtain and prepare an authorized local RADCURE copy
  without redistributing it.

## Technical-claim review

- [x] M7A metrics match the committed aggregate reports.
- [x] M4 token and latency numbers are labeled as one successful live invocation.
- [x] M5B AgentCore deployment is explicitly **NOT STARTED**.
- [x] M7B live LLM batch evaluation is explicitly **NOT RUN**.
- [x] Synthetic workflow provenance and clinical-use limitations are explicit.
- [x] Mermaid block structure and local Markdown references pass validation.

## GitHub publishing prerequisites

- [x] Complete and review all three synthetic screenshots.
- [x] Create orphan `main` from the reviewed M9A source snapshot.
- [x] Repeat security, identifier, link, fixture-test, and screenshot audits on
  `main`.
- [x] Verify `main` has one root commit with no parent and `master` retains the private
  development history.
- [x] Confirm no remote is configured and no push occurred.
- [ ] Confirm repository visibility, license/attribution, branch protections, and
  release notes through human review.
- [ ] Obtain and verify the exact clone URL for the already-created
  `radonc-workflow-intelligence` destination.
- [ ] Only after separate authorization, attach that remote while on `main` and push
  `main` explicitly. Never use `--all`, `--mirror`, or `--force`.

## Known limitations

- Synthetic workflow gold is not clinical truth.
- Similarity is deterministic and explainable but not clinically validated.
- LLM safety is not measured; M7B was not run.
- AgentCore Runtime is not deployed.
- No multi-site, prospective, human-factors, or clinical effectiveness validation has
  occurred.
- The original `master` branch, tags, and private development history must never be
  pushed.
- Package metadata currently declares `Proprietary`; the owner must confirm the
  intended public license before publication.
