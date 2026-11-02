# AWS agent implementation

## Verified M4 flow

The M4 agent uses Strands Agents with Claude Haiku 4.5 through Amazon Bedrock. The
foundation model orchestrates five deterministic functions:

1. `get_patient_context`
2. `get_workflow_state`
3. `find_similar_patients`
4. `get_cohort_next_steps`
5. `get_evidence`

In the successful live smoke test, the model genuinely invoked all five tools. It
returned an ordinary concise narrative; it did not author the detailed clinical or
numerical response. Python captured the tool results, enforced patient scope, resolved
evidence, rejected unsupported claims, and assembled the final JSON. Pydantic contracts
validated the structured response and provenance boundaries.

The live test used only the built-in synthetic fixture. No RADCURE patient record was
sent to Bedrock.

## Single live observation

| Metric | Value |
| --- | ---: |
| Input tokens | 6,231 |
| Output tokens | 595 |
| Total tokens | 6,826 |
| End-to-end agent latency | 4,790.511 ms |

This is **one successful invocation**, not an average, percentile, reliability estimate,
or benchmark distribution. M7B live batch evaluation was not run. No model transcript,
patient record, credential, account identifier, or fabricated trace is published.

## AgentCore deployment readiness

M5A provides a local AgentCore-compatible boundary:

- `BedrockAgentCoreApp` entrypoint
- `POST /invocations`
- `GET /ping`
- `SyntheticFixtureProvider` as the only initial deployment candidate
- `LocalCohortProvider` for explicitly selected local execution only
- pinned runtime dependencies and an allowlisted package manifest
- default AWS credential-provider behavior for a future execution role

A remote runtime would require a least-privilege execution role, reviewed model
permissions, inbound authentication, network and encryption policy, monitoring,
retention, budget controls, and a governed data provider.

**M5B live AgentCore deployment is NOT STARTED. No AWS-hosted AgentCore Runtime exists.**
