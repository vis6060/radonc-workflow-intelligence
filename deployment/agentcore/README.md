# AgentCore Runtime deployment preparation

M5A prepares but does not deploy the M4 agent. The supported Runtime entrypoint is
`rad_intel.agentcore_runtime.app:app`; the direct-code entrypoint file is
`rad_intel/agentcore_runtime/app.py`. It exposes AgentCore's required `POST
/invocations` and `GET /ping` endpoints through `BedrockAgentCoreApp`.

## Local verification

From the repository root, install the project and run the offline suite:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

The HTTP tests inject a fake Strands model and use only `SyntheticFixtureProvider`;
they make no AWS calls. To start the SDK server manually without invoking the model:

```powershell
$env:RAD_INTEL_DATA_PROVIDER = "synthetic"
python -m rad_intel.agentcore_runtime.app
```

`GET http://localhost:8080/ping` is safe. Do not call `/invocations` unless an
authorized model credential context is intentionally available.

## Packaging boundary

For a future direct-code package, create a fresh staging directory, copy
`src/rad_intel` into it as top-level `rad_intel`, and copy this directory's pinned
`requirements.txt`. Use `package-manifest.txt` as an allowlist. Inspect the archive
before upload. The archive must not contain `data/`, `.env` files, AWS configuration,
credentials, tests, logs, Git metadata, or any RADCURE-derived patient-level output.

The initial remote candidate sets `RAD_INTEL_DATA_PROVIDER=synthetic`. Local
full-cohort execution may explicitly select `local` and a local processed-data path,
but that path and its files are never portable deployment inputs.

## Current CLI and future M5B

AWS currently documents the Node.js AgentCore CLI (`@aws/agentcore`) for create,
development, build, deploy, invoke, status, logs, traces, and export workflows. The
older Python starter toolkit is not the selected deployment interface. In M5B, install
and inspect the current CLI without letting scaffolding overwrite this repository:

```powershell
npm install -g @aws/agentcore
agentcore --version
agentcore --help
```

Only after reviewing the generated plan should M5B configure this existing entrypoint
for direct code deployment with runtime `PYTHON_3_13`. M5A intentionally does not run
`agentcore create`, `build`, `deploy`, `launch`, or any AWS API that changes resources.

Official references reviewed for this preparation:

- [AgentCore interfaces and current CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/develop-agents.html)
- [Python direct code deployment](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html)
- [Supported Runtime language versions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-code-deploy-supported-runtimes.html)

## Cleanup

M5A creates no cloud resources, so no AWS cleanup is required. Local cleanup consists
only of removing an explicitly created temporary staging directory or virtual
environment. Future M5B cleanup must stop active runtime sessions, remove the Runtime,
delete only the deployment archive and its dedicated storage, and confirm log-retention
requirements before deleting log groups.
