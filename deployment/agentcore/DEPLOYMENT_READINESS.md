# M5A deployment readiness report

## Architecture and entrypoint

`BedrockAgentCoreApp` owns the AgentCore HTTP protocol. The invocation handler validates
`patient_id`, `question`, and optional timezone-aware `as_of`, then delegates to a
bounded `RuntimeService`. The service reuses the M4 Strands agent, all five scoped M3
tools, ordinary model text, deterministic Python response assembly, evidence checks,
patient isolation, and clinical-safety validation. Responses include a request ID and
elapsed time; errors use stable codes and omit raw exception text.

AgentCore execution creates the Bedrock model with `boto3.Session(region_name=...)` and
the default credential provider chain. It rejects named profiles. Local M4 execution
retains its existing named-profile and root-identity guards.

## Data-provider strategy

- `LocalCohortProvider` lazily opens the Git-ignored M1-M3 processed directory and
  preserves local access to all 3,346 patients. It is explicitly not deployment-safe.
- `SyntheticFixtureProvider` contains no RADCURE record and supports patient context,
  workflow state, ten comparable synthetic histories, cohort next steps, and scoped
  evidence. It is the only initial deployment candidate.

Governed cloud cohort storage, encryption, retention, access review, and patient-data
authorization remain future design work and are not implied by this package.

## Dependencies and artifact

The prepared runtime pins Python SDK and model dependencies in `requirements.txt`.
Python 3.13 is supported by AgentCore direct code deployment as `PYTHON_3_13`. The
allowlisted artifact contains only the `rad_intel` package and runtime requirements.
No archive was built or uploaded in M5A.

## Resources and permissions required by M5B

Depending on the reviewed CLI plan, M5B would create or use an AgentCore Runtime,
runtime execution role, direct-code artifact storage, CloudWatch logs/traces, and
possibly build infrastructure. It may use S3 and/or ECR according to the selected
deployment mode. None exists because of M5A.

The runtime execution role should trust only the AgentCore runtime service and grant
least-privilege `bedrock:InvokeModel` and, if required by the selected Strands transport,
`bedrock:InvokeModelWithResponseStream` on the chosen inference profile and underlying
model resources. Logging permissions should be scoped to the runtime log destination.
No permission to local profiles, RADCURE storage, IAM administration, arbitrary S3, or
unrelated AWS services is required for the synthetic candidate.

## Costs, monitoring, security, and cleanup

Expected cost categories are AgentCore Runtime compute/session duration, Bedrock model
input/output tokens, logs/traces, artifact storage, and build/container services if the
chosen mode uses them. No estimate is claimed before deployment configuration and load
are known.

Monitor invocation count, failures, latency, token usage, runtime sessions, model
throttling, and sanitized logs. Alerts must avoid patient identifiers or tool payloads.
The runtime remains a prototype: inbound authentication, network policy, encryption
key policy, concurrency/load behavior, log retention, dependency scanning, and a
governed clinical-data design require review before any non-synthetic use.

Cleanup in M5B must stop sessions and remove only explicitly identified runtime,
artifact, build, and observability resources after retention review.

## Remaining blockers

- M5B authorization and a least-privilege non-root execution role.
- Review of the current AgentCore CLI-generated infrastructure plan.
- Inbound authentication and network policy decisions.
- A governed cloud data provider before any real-cohort deployment.
- Cost budget, alarms, retention policy, and security review.

M5B is **NOT STARTED**. No AgentCore Runtime is deployed.
