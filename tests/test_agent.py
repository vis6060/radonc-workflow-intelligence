import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from strands.types.exceptions import MaxTokensReachedException

from rad_intel.agent.bedrock_agent import (
    DEFAULT_MODEL_ID,
    AgentInvocationError,
    AgentPayload,
    AgentSettings,
    CompactAgentResult,
    WorkflowIntelligenceAgent,
    create_bedrock_model,
    create_root_authorized_synthetic_smoke_model,
    discover_bedrock,
)
from rad_intel.agent.demo import (
    SYNTHETIC_AS_OF,
    SYNTHETIC_PATIENT,
    SyntheticSmokeStore,
    main,
)
from rad_intel.agent.prompts import COMPACT_LIMITATIONS, COMPACT_WARNINGS
from rad_intel.agent.tool_adapters import (
    STRANDS_TOOLS,
    get_patient_context,
    patient_tool_session,
)
from rad_intel.tools import IntelligenceStore


def test_settings_are_environment_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_PROFILE", "least-privilege-dev")
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "verified-model-id")
    settings = AgentSettings.from_environment()
    assert settings.aws_profile == "least-privilege-dev"
    assert settings.aws_region == "us-east-2"
    assert settings.bedrock_model_id == "verified-model-id"


def test_all_five_strands_tools_are_registered() -> None:
    assert [registered.tool_name for registered in STRANDS_TOOLS] == [
        "get_patient_context",
        "get_workflow_state",
        "find_similar_patients",
        "get_cohort_next_steps",
        "get_evidence",
    ]


def test_offline_result_executes_tools_and_validates() -> None:
    result = WorkflowIntelligenceAgent(SyntheticSmokeStore()).build_offline(
        SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, k=3
    )
    assert result.patient_context["patient_id"] == SYNTHETIC_PATIENT
    assert result.current_workflow_state["provenance"] == "synthetic_workflow"
    assert len(result.similar_historical_patients) == 3
    assert result.synthetic_cohort_next_step_statistics["cohort_denominator"] == 3
    assert {item["tool_name"] for item in result.tool_execution_trace} == {
        registered.tool_name for registered in STRANDS_TOOLS
    }
    assert result.execution_metrics.total_tokens == 0


def test_offline_result_validates_against_actual_m3_outputs() -> None:
    store = IntelligenceStore(Path("data/processed"))
    patient_id = sorted(store.patients)[0]
    as_of = store.snapshots[patient_id]["as_of"]
    result = WorkflowIntelligenceAgent(store).build_offline(
        patient_id, as_of, k=3
    )
    assert result.patient_context == store.get_patient_context(patient_id)
    assert result.current_workflow_state == store.get_workflow_state(patient_id, as_of)
    assert result.similar_historical_patients == store.find_similar_patients(
        patient_id, 3
    )


def test_python_patient_isolation_rejects_cross_patient_request() -> None:
    with patient_tool_session(SyntheticSmokeStore(), SYNTHETIC_PATIENT):
        with pytest.raises(ValueError, match="cross-patient"):
            get_patient_context("SYNTHETIC-DEMO-OTHER")


def test_tool_call_limit_is_enforced_in_python() -> None:
    with patient_tool_session(
        SyntheticSmokeStore(), SYNTHETIC_PATIENT, max_tool_calls=5
    ):
        for _ in range(5):
            get_patient_context(SYNTHETIC_PATIENT)
        with pytest.raises(RuntimeError, match="maximum tool-call"):
            get_patient_context(SYNTHETIC_PATIENT)


def test_live_smoke_rejects_any_patient_data_path() -> None:
    with pytest.raises(SystemExit, match="does not accept"):
        main(
            [
                "--live-smoke",
                "--allow-root-synthetic-smoke",
                "--data-directory",
                "data/processed",
            ]
        )


def test_validation_rejects_unsupported_numbers_and_citations() -> None:
    service = WorkflowIntelligenceAgent(SyntheticSmokeStore())
    result = service.build_offline(SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, k=3)
    unsupported = result.model_copy(deep=True)
    unsupported.synthetic_cohort_next_step_statistics["cohort_denominator"] = 999
    with pytest.raises(ValueError, match="unsupported cohort"):
        service.validate(unsupported, SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, 3)
    bad_citation = result.model_copy(deep=True)
    bad_citation.evidence_references[0]["patient_id"] = "OTHER"
    with pytest.raises(ValueError, match="cross-patient evidence"):
        service.validate(bad_citation, SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, 3)


def _compact(**updates: object) -> CompactAgentResult:
    values = {
        "patient_id": SYNTHETIC_PATIENT,
        "short_summary": (
            "The available context is synthetic and preserves missing clinical "
            "attributes without inference. Comparable records are demonstration "
            "examples selected by deterministic tools for operational review."
        ),
        "workflow_interpretation": (
            "Consultation is complete and authorization remains the outstanding "
            "workflow task. Historical next steps are descriptive synthetic "
            "evidence and require human review."
        ),
        "evidence_ids": ["synthetic-evidence-001"],
        "limitations": COMPACT_LIMITATIONS,
        "warnings": COMPACT_WARNINGS,
    }
    values.update(updates)
    return CompactAgentResult(**values)


def _narrative(**updates: str) -> str:
    values = {
        "text": (
            "The clinical context is limited to the available synthetic smoke "
            "fixture and preserves missing attributes without inference. The "
            "synthetic workflow shows consultation complete with authorization "
            "remaining as the outstanding operational task. Comparable records "
            "and cohort observations were retrieved by deterministic tools and "
            "are descriptive demonstration information only. Supporting workflow "
            "evidence was verified for the scoped patient. Human review and source "
            "verification remain necessary, and no clinical guidance is provided."
        )
    }
    values.update(updates)
    return values["text"]


def test_compact_schema_is_smaller_and_rejects_numeric_claims() -> None:
    assert len(json.dumps(CompactAgentResult.model_json_schema())) < len(
        json.dumps(AgentPayload.model_json_schema())
    )
    with pytest.raises(ValueError, match="numeric claims"):
        _compact(short_summary="The cohort count is 10.")


def test_invalid_narrative_evidence_and_patient_attribution_are_rejected() -> None:
    service = WorkflowIntelligenceAgent(SyntheticSmokeStore())
    result = service.build_offline(SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, k=3)
    result.grounded_agent_narrative = _narrative().replace(
        "Supporting workflow evidence", "Foreign-evidence-reference evidence"
    )
    with pytest.raises(ValueError, match="invalid evidence"):
        service.validate(result, SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, 3)
    result.grounded_agent_narrative = _narrative() + " " + SYNTHETIC_PATIENT
    with pytest.raises(ValueError, match="patient identifier"):
        service.validate(result, SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, 3)


def test_treatment_language_is_rejected() -> None:
    service = WorkflowIntelligenceAgent(SyntheticSmokeStore())
    result = service.build_offline(SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, k=3)
    result.grounded_agent_narrative = _narrative() + " The patient should receive it."
    with pytest.raises(ValueError, match="clinical product boundary"):
        service.validate(result, SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, 3)


def test_numeric_narrative_claim_is_rejected() -> None:
    service = WorkflowIntelligenceAgent(SyntheticSmokeStore())
    result = service.build_offline(SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, k=3)
    result.grounded_agent_narrative = (
        _narrative() + " The cohort contained 999 records."
    )
    with pytest.raises(ValueError, match="numeric claim"):
        service.validate(result, SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, 3)


class MockAgent:
    init_kwargs = None
    call_kwargs = None

    def __init__(self, **kwargs: object) -> None:
        MockAgent.init_kwargs = kwargs

    def __call__(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        from rad_intel.agent.tool_adapters import (
            find_similar_patients,
            get_cohort_next_steps,
            get_evidence,
            get_workflow_state,
        )

        MockAgent.call_kwargs = kwargs
        context = get_patient_context(SYNTHETIC_PATIENT)
        state = get_workflow_state(SYNTHETIC_PATIENT, SYNTHETIC_AS_OF)
        similar = find_similar_patients(SYNTHETIC_PATIENT, 3)
        cohort = get_cohort_next_steps([item["patient_id"] for item in similar])
        evidence = get_evidence(SYNTHETIC_PATIENT, ["synthetic-evidence-001"])
        assert context and state and similar and cohort and evidence
        metrics = SimpleNamespace(
            accumulated_usage={
                "inputTokens": 100,
                "outputTokens": 25,
                "totalTokens": 125,
            }
        )
        return SimpleNamespace(
            stop_reason="end_turn",
            message={"role": "assistant", "content": [{"text": _narrative()}]},
            metrics=metrics,
        )


def test_mock_model_path_has_trace_usage_limits_and_no_aws() -> None:
    service = WorkflowIntelligenceAgent(
        SyntheticSmokeStore(), agent_factory=MockAgent
    )
    result = service.run_with_model(
        SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, model=object(), k=3
    )
    assert MockAgent.init_kwargs["tools"] == STRANDS_TOOLS
    assert "structured_output_model" not in MockAgent.init_kwargs
    assert "structured_output_prompt" not in MockAgent.init_kwargs
    assert MockAgent.call_kwargs["limits"] == {
        "turns": 8,
        "output_tokens": 8000,
        "total_tokens": 12000,
    }
    assert "structured_output_model" not in MockAgent.call_kwargs
    assert result.execution_metrics.total_tokens == 125
    assert result.execution_metrics.mode == "bedrock"
    assert len(result.tool_execution_trace) == 5
    assert result.grounded_agent_narrative == _narrative()
    assert result.response_assembly_method == (
        "deterministic_python_with_plain_text"
    )
    assert result.patient_context == SyntheticSmokeStore().get_patient_context(
        SYNTHETIC_PATIENT
    )


class TruncatingAgent:
    def __init__(self, **kwargs: object) -> None:
        self.event_loop_metrics = SimpleNamespace(
            accumulated_usage={
                "inputTokens": 200,
                "outputTokens": 800,
                "totalTokens": 1000,
            }
        )

    def __call__(self, prompt: str, **kwargs: object) -> None:
        from rad_intel.agent.tool_adapters import get_workflow_state

        get_patient_context(SYNTHETIC_PATIENT)
        get_workflow_state(SYNTHETIC_PATIENT, SYNTHETIC_AS_OF)
        raise MaxTokensReachedException("synthetic truncation")


def test_truncated_output_fails_safely_and_preserves_trace() -> None:
    service = WorkflowIntelligenceAgent(
        SyntheticSmokeStore(), agent_factory=TruncatingAgent
    )
    with pytest.raises(AgentInvocationError) as captured:
        service.run_with_model(
            SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, model=object(), k=3
        )
    diagnostic = captured.value.diagnostics
    assert diagnostic.exception_type == "MaxTokensReachedException"
    assert diagnostic.last_known_stop_reason == "max_tokens"
    assert diagnostic.tool_names == [
        "get_patient_context",
        "get_workflow_state",
    ]
    assert diagnostic.completed_tool_call_count == 2
    assert diagnostic.token_usage == {
        "inputTokens": 200,
        "outputTokens": 800,
        "totalTokens": 1000,
    }
    assert all("patient_ids" not in item for item in diagnostic.tool_execution_trace)


def _execute_all_synthetic_tools() -> None:
    from rad_intel.agent.tool_adapters import (
        find_similar_patients,
        get_cohort_next_steps,
        get_evidence,
        get_workflow_state,
    )

    get_patient_context(SYNTHETIC_PATIENT)
    get_workflow_state(SYNTHETIC_PATIENT, SYNTHETIC_AS_OF)
    similar = find_similar_patients(SYNTHETIC_PATIENT, 3)
    get_cohort_next_steps([item["patient_id"] for item in similar])
    get_evidence(SYNTHETIC_PATIENT, ["synthetic-evidence-001"])


class MissingStructuredAgent:
    stop_reason = "end_turn"
    narrative = _narrative()

    def __init__(self, **kwargs: object) -> None:
        pass

    def __call__(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        _execute_all_synthetic_tools()
        return SimpleNamespace(
            structured_output=None,
            stop_reason=self.stop_reason,
            message={"role": "assistant", "content": [{"text": self.narrative}]},
            metrics=SimpleNamespace(
                accumulated_usage={
                    "inputTokens": 321,
                    "outputTokens": 123,
                    "totalTokens": 444,
                }
            ),
        )


def test_ordinary_text_uses_deterministic_python_assembly() -> None:
    service = WorkflowIntelligenceAgent(
        SyntheticSmokeStore(), agent_factory=MissingStructuredAgent
    )
    result = service.run_with_model(
        SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, model=object(), k=3
    )
    assert result.response_assembly_method == (
        "deterministic_python_with_plain_text"
    )
    assert len(result.tool_execution_trace) == 5
    assert result.execution_metrics.stop_reason == "end_turn"
    assert result.execution_metrics.total_tokens == 444
    assert result.grounded_agent_narrative == _narrative()
    assert result.patient_context == SyntheticSmokeStore().get_patient_context(
        SYNTHETIC_PATIENT
    )


@pytest.mark.parametrize("stop_reason", ["limit_turns", "limit_output_tokens"])
def test_limit_termination_without_usable_payload_retains_diagnostics(
    stop_reason: str,
) -> None:
    class LimitAgent(MissingStructuredAgent):
        narrative = "No usable grounded narrative was returned."

        def __init__(self, **kwargs: object) -> None:
            self.stop_reason = stop_reason

    service = WorkflowIntelligenceAgent(
        SyntheticSmokeStore(), agent_factory=LimitAgent
    )
    with pytest.raises(AgentInvocationError) as captured:
        service.run_with_model(
            SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, model=object(), k=3
        )
    diagnostic = captured.value.diagnostics
    assert diagnostic.exception_type == "ValueError"
    assert diagnostic.result_stop_reason == stop_reason
    assert diagnostic.last_known_stop_reason == stop_reason
    assert diagnostic.structured_output_present is False
    assert diagnostic.completed_tool_call_count == 5
    assert diagnostic.token_usage == {
        "inputTokens": 321,
        "outputTokens": 123,
        "totalTokens": 444,
    }
    assert diagnostic.message_metadata == {
        "available": True,
        "role": "assistant",
        "content_block_types": ["text"],
        "text_character_count": 42,
        "tool_use_names": [],
    }


def test_validation_failure_retains_complete_tool_trace() -> None:
    class InvalidNarrativeAgent(MissingStructuredAgent):
        def __call__(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            response = super().__call__(prompt, **kwargs)
            response.message = {
                "role": "assistant",
                "content": [
                    {
                        "text": _narrative().replace(
                            "Supporting workflow evidence",
                            "Foreign-evidence-reference evidence",
                        )
                    }
                ],
            }
            return response

    service = WorkflowIntelligenceAgent(
        SyntheticSmokeStore(), agent_factory=InvalidNarrativeAgent
    )
    with pytest.raises(AgentInvocationError) as captured:
        service.run_with_model(
            SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, model=object(), k=3
        )
    diagnostic = captured.value.diagnostics
    assert diagnostic.exception_type == "ValueError"
    assert diagnostic.structured_output_present is False
    assert diagnostic.completed_tool_call_count == 5
    assert diagnostic.tool_names == [
        "get_patient_context",
        "get_workflow_state",
        "find_similar_patients",
        "get_cohort_next_steps",
        "get_evidence",
    ]


@pytest.mark.parametrize(
    "message",
    [
        {"role": "assistant", "content": [{"toolUse": {"name": "unused"}}]},
        {"role": "assistant", "content": [{"text": ""}]},
        {"role": "user", "content": [{"text": _narrative()}]},
    ],
)
def test_tool_only_missing_or_non_assistant_narrative_fails_closed(
    message: dict[str, object],
) -> None:
    class NoNarrativeAgent(MissingStructuredAgent):
        def __call__(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            response = super().__call__(prompt, **kwargs)
            response.message = message
            return response

    service = WorkflowIntelligenceAgent(
        SyntheticSmokeStore(), agent_factory=NoNarrativeAgent
    )
    with pytest.raises(AgentInvocationError) as captured:
        service.run_with_model(
            SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, model=object(), k=3
        )
    assert captured.value.diagnostics.completed_tool_call_count == 5


def test_final_assembly_requires_all_five_captured_tool_outputs() -> None:
    class FourToolAgent(MissingStructuredAgent):
        def __call__(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            from rad_intel.agent.tool_adapters import (
                find_similar_patients,
                get_cohort_next_steps,
                get_workflow_state,
            )

            get_patient_context(SYNTHETIC_PATIENT)
            get_workflow_state(SYNTHETIC_PATIENT, SYNTHETIC_AS_OF)
            similar = find_similar_patients(SYNTHETIC_PATIENT, 3)
            get_cohort_next_steps([item["patient_id"] for item in similar])
            return SimpleNamespace(
                stop_reason="end_turn",
                message={
                    "role": "assistant",
                    "content": [{"text": _narrative()}],
                },
                metrics=SimpleNamespace(accumulated_usage={}),
            )

    service = WorkflowIntelligenceAgent(
        SyntheticSmokeStore(), agent_factory=FourToolAgent
    )
    with pytest.raises(AgentInvocationError, match="missing captured tool outputs"):
        service.run_with_model(
            SYNTHETIC_PATIENT, SYNTHETIC_AS_OF, model=object(), k=3
        )


class FakeCredentials:
    method = "login"


class FakeClient:
    def __init__(
        self, root: bool = False, profile_id: str = "verified-profile-id"
    ) -> None:
        self.root = root
        self.profile_id = profile_id
        self.profile_calls = 0

    def get_caller_identity(self) -> dict[str, str]:
        suffix = "root" if self.root else "assumed-role/dev/session"
        return {"Arn": f"arn:aws:iam::synthetic-test:{suffix}"}

    def list_foundation_models(self) -> dict[str, list[dict[str, str]]]:
        return {"modelSummaries": [{"modelId": "foundation-id"}]}

    def list_inference_profiles(self, **kwargs: str) -> dict[str, object]:
        self.profile_calls += 1
        if self.profile_calls == 1:
            return {
                "inferenceProfileSummaries": [
                    {"inferenceProfileId": self.profile_id}
                ],
                "nextToken": "page-2",
            }
        return {"inferenceProfileSummaries": []}


class FakeSession:
    def __init__(
        self,
        root: bool = False,
        profile_name: str = "test-profile",
        profile_id: str = "verified-profile-id",
    ) -> None:
        self.profile_name = profile_name
        self.region_name = "us-east-1"
        self.client_instance = FakeClient(root=root, profile_id=profile_id)

    def client(self, name: str, config: object | None = None) -> FakeClient:
        return self.client_instance

    def get_credentials(self) -> FakeCredentials:
        return FakeCredentials()


def test_read_only_discovery_verifies_exact_inference_profile() -> None:
    settings = AgentSettings(bedrock_model_id="verified-profile-id")
    report = discover_bedrock(settings, FakeSession())
    assert report["configured_model_found"] is True
    assert report["configured_id_type"] == "inference_profile"
    assert report["inference_profile_count"] == 1


def test_root_identity_blocks_model_creation_before_discovery() -> None:
    with pytest.raises(PermissionError, match="root identity"):
        create_bedrock_model(AgentSettings(), FakeSession(root=True))


def test_root_override_is_synthetic_only_and_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AgentSettings(max_output_tokens=4096, max_attempts=1)
    session = FakeSession(
        root=True,
        profile_name="rad-intel",
        profile_id=DEFAULT_MODEL_ID,
    )
    with pytest.raises(PermissionError, match="opt-in"):
        create_root_authorized_synthetic_smoke_model(
            settings,
            SyntheticSmokeStore(),
            allow_root_synthetic_smoke=False,
            session=session,
        )
    with pytest.raises(PermissionError, match="built-in synthetic"):
        create_root_authorized_synthetic_smoke_model(
            settings,
            object(),
            allow_root_synthetic_smoke=True,
            session=session,
        )
    monkeypatch.setattr(
        "rad_intel.agent.bedrock_agent.BedrockModel", lambda **kwargs: kwargs
    )
    model_config = create_root_authorized_synthetic_smoke_model(
        settings,
        SyntheticSmokeStore(),
        allow_root_synthetic_smoke=True,
        session=FakeSession(
            root=True,
            profile_name="rad-intel",
            profile_id=DEFAULT_MODEL_ID,
        ),
    )
    assert model_config["model_id"] == DEFAULT_MODEL_ID
    assert model_config["max_tokens"] == 4096
