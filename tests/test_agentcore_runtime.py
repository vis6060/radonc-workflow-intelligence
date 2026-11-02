from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from rad_intel.agent.bedrock_agent import AgentSettings, create_agentcore_bedrock_model
from rad_intel.agent.demo import SYNTHETIC_PATIENT
from rad_intel.agent.tool_adapters import (
    find_similar_patients,
    get_cohort_next_steps,
    get_evidence,
    get_patient_context,
    get_workflow_state,
)
from rad_intel.agentcore_runtime.app import create_app
from rad_intel.agentcore_runtime.runtime_service import (
    LocalCohortProvider,
    RuntimeService,
    SyntheticFixtureProvider,
    provider_from_environment,
)
from rad_intel.showcase import SyntheticShowcaseStore

SHOWCASE_AS_OF = SyntheticShowcaseStore().snapshots[SYNTHETIC_PATIENT]["as_of"]


def _plain_narrative() -> str:
    return (
        "The available clinical context preserves missing attributes without "
        "inference. Synthetic workflow information shows consultation complete "
        "while authorization remains the outstanding operational task. Comparable "
        "demonstration records and cohort observations came from deterministic "
        "tools and remain descriptive only. Supporting workflow evidence was "
        "resolved within the scoped patient record. Human review and source "
        "verification remain necessary, and this summary supplies no clinical "
        "guidance or outcome prediction."
    )


class FakeTextAgent:
    init_kwargs: dict[str, object] | None = None

    def __init__(self, **kwargs: object) -> None:
        FakeTextAgent.init_kwargs = kwargs

    def __call__(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        context = get_patient_context(SYNTHETIC_PATIENT)
        state = get_workflow_state(SYNTHETIC_PATIENT, SHOWCASE_AS_OF)
        similar = find_similar_patients(SYNTHETIC_PATIENT, 10)
        cohort = get_cohort_next_steps([item["patient_id"] for item in similar])
        evidence_ids = [
            item["evidence_id"]
            for item in context["evidence_references"]
            + state["evidence_references"]
        ]
        evidence = get_evidence(SYNTHETIC_PATIENT, evidence_ids)
        assert context and state and similar and cohort and evidence
        return SimpleNamespace(
            stop_reason="end_turn",
            message={"role": "assistant", "content": [{"text": _plain_narrative()}]},
            metrics=SimpleNamespace(
                accumulated_usage={
                    "inputTokens": 50,
                    "outputTokens": 20,
                    "totalTokens": 70,
                }
            ),
        )


def _service(**updates: object) -> RuntimeService:
    values = {
        "provider": SyntheticFixtureProvider(),
        "settings": AgentSettings(max_attempts=1),
        "model_factory": lambda settings: object(),
        "agent_factory": FakeTextAgent,
    }
    values.update(updates)
    return RuntimeService(**values)


def test_agentcore_health_and_valid_invocation_are_serializable() -> None:
    with TestClient(create_app(_service())) as client:
        health = client.get("/ping")
        response = client.post(
            "/invocations",
            json={
                "patient_id": SYNTHETIC_PATIENT,
                "question": "Summarize the operational workflow.",
                "as_of": None,
            },
        )
    assert health.status_code == 200
    assert health.json()["status"] == "Healthy"
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["request_id"]
    assert body["elapsed_ms"] >= 0
    assert body["data_provider"] == "synthetic_fixture"
    result = body["response"]
    assert result["patient_context"]["patient_id"] == SYNTHETIC_PATIENT
    assert result["grounded_agent_narrative"] == _plain_narrative()
    assert result["response_assembly_method"] == (
        "deterministic_python_with_plain_text"
    )
    assert [item["tool_name"] for item in result["tool_execution_trace"]] == [
        "get_patient_context",
        "get_workflow_state",
        "find_similar_patients",
        "get_cohort_next_steps",
        "get_evidence",
    ]
    assert all(item["success"] for item in result["tool_execution_trace"])
    assert result["evidence_references"][0]["patient_id"] == SYNTHETIC_PATIENT
    assert result["current_workflow_state"]["provenance"] == "synthetic_workflow"


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"patient_id": "UNKNOWN", "question": "Workflow?"}, 404, "PATIENT_NOT_FOUND"),
        ({"patient_id": SYNTHETIC_PATIENT}, 400, "INVALID_REQUEST"),
        (
            {
                "patient_id": SYNTHETIC_PATIENT,
                "question": "Workflow?",
                "as_of": "2035-01-10T12:00:00",
            },
            400,
            "INVALID_REQUEST",
        ),
    ],
)
def test_structured_request_errors(
    payload: dict[str, object], status: int, code: str
) -> None:
    with TestClient(create_app(_service())) as client:
        response = client.post("/invocations", json=payload)
    assert response.status_code == status
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == code
    assert body["request_id"]
    assert "traceback" not in response.text.lower()


def test_invalid_json_is_handled_by_agentcore_sdk() -> None:
    with TestClient(create_app(_service())) as client:
        response = client.post(
            "/invocations",
            content=b"{not-json",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 400
    assert response.json()["error"] == "Invalid JSON"


def test_runtime_exception_is_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    def fail_model(settings: AgentSettings) -> object:
        raise RuntimeError("secret raw patient value")

    with TestClient(create_app(_service(model_factory=fail_model))) as client:
        response = client.post(
            "/invocations",
            json={"patient_id": SYNTHETIC_PATIENT, "question": "Workflow?"},
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret raw patient value" not in response.text
    assert "secret raw patient value" not in caplog.text


def test_provider_selection_is_explicit_and_synthetic_does_not_touch_local_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    forbidden = tmp_path / "must-not-be-read"
    monkeypatch.setenv("RAD_INTEL_DATA_PROVIDER", "synthetic")
    monkeypatch.setenv("RAD_INTEL_DATA_DIRECTORY", str(forbidden))
    provider = provider_from_environment()
    assert isinstance(provider, SyntheticFixtureProvider)
    assert provider.deployment_safe is True
    assert not forbidden.exists()

    monkeypatch.setenv("RAD_INTEL_DATA_PROVIDER", "local")
    local = provider_from_environment()
    assert isinstance(local, LocalCohortProvider)
    assert local.deployment_safe is False
    assert local.data_directory == forbidden
    assert local._store is None


def test_synthetic_provider_rejects_cross_patient_access() -> None:
    provider = SyntheticFixtureProvider()
    with pytest.raises(KeyError, match="synthetic fixture"):
        provider.resolve_as_of("OTHER-PATIENT", None)


def test_local_provider_preserves_full_cohort_access() -> None:
    provider = LocalCohortProvider(Path("data/processed"))
    assert len(provider.store.patients) == 3346


class RuntimeSession:
    profile_name = None
    region_name = "us-east-1"


def test_agentcore_model_uses_no_named_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "rad_intel.agent.bedrock_agent.BedrockModel", lambda **kwargs: kwargs
    )
    model = create_agentcore_bedrock_model(AgentSettings(), RuntimeSession())
    assert model["boto_session"].profile_name is None
    assert model["model_id"] == AgentSettings().bedrock_model_id


def test_agentcore_model_rejects_named_profile() -> None:
    session = RuntimeSession()
    session.profile_name = "rad-intel"
    with pytest.raises(PermissionError, match="named AWS profile"):
        create_agentcore_bedrock_model(AgentSettings(), session)


def test_deployment_assets_are_synthetic_only_and_allowlisted() -> None:
    root = Path("deployment/agentcore")
    files = [path for path in root.rglob("*") if path.is_file()]
    names = {path.name.lower() for path in files}
    assert ".env" not in names
    assert not any("credential" in path.name.lower() for path in files)
    restricted_suffixes = {".csv", ".xlsx", ".parquet"}
    assert not any(path.suffix.lower() in restricted_suffixes for path in files)
    manifest = (root / "package-manifest.txt").read_text(encoding="utf-8")
    assert "data/" in manifest
    assert "rad_intel/" in manifest
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    assert "bedrock-agentcore==1.25.2" in requirements
    assert "strands-agents==1.63.0" in requirements
