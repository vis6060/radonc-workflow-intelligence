"""Safe Strands/Bedrock orchestration with deterministic result validation."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from typing import Any, Literal

import boto3
from botocore.config import Config
from pydantic import BaseModel, ConfigDict, Field, field_validator
from strands import Agent
from strands.models import BedrockModel

from rad_intel.agent.prompts import LIMITATIONS, SYSTEM_PROMPT, WARNINGS
from rad_intel.agent.tool_adapters import (
    STRANDS_TOOLS,
    IntelligenceBackend,
    find_similar_patients,
    get_cohort_next_steps,
    get_evidence,
    get_patient_context,
    get_workflow_state,
    patient_tool_session,
)

DEFAULT_REGION = "us-east-1"
DEFAULT_PROFILE = "rad-intel"
DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSettings(StrictModel):
    """Environment-configurable bounded AWS/model settings."""

    aws_profile: str = DEFAULT_PROFILE
    aws_region: str = DEFAULT_REGION
    bedrock_model_id: str = DEFAULT_MODEL_ID
    connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    read_timeout_seconds: int = Field(default=45, ge=1, le=120)
    max_attempts: int = Field(default=2, ge=1, le=4)
    max_agent_steps: int = Field(default=8, ge=5, le=12)
    max_tool_calls: int = Field(default=10, ge=5, le=10)
    max_output_tokens: int = Field(default=4096, ge=256, le=4096)
    max_cumulative_output_tokens: int = Field(default=8000, ge=1000, le=8000)
    max_total_tokens: int = Field(default=12000, ge=1000, le=50000)

    @classmethod
    def from_environment(cls) -> AgentSettings:
        return cls(
            aws_profile=os.getenv("AWS_PROFILE", DEFAULT_PROFILE),
            aws_region=os.getenv("AWS_REGION", DEFAULT_REGION),
            bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        )


class AgentPayload(StrictModel):
    patient_context: dict[str, Any]
    current_workflow_state: dict[str, Any]
    similar_historical_patients: list[dict[str, Any]]
    synthetic_cohort_next_step_statistics: dict[str, Any]
    evidence_references: list[dict[str, Any]]
    limitations: list[str]
    warnings: list[str]


class CompactAgentResult(StrictModel):
    """Small model-authored layer; detailed numerical truth stays in Python."""

    patient_id: str
    short_summary: str = Field(min_length=1, max_length=1200)
    workflow_interpretation: str = Field(min_length=1, max_length=800)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    limitations: list[str] = Field(min_length=1, max_length=4)
    warnings: list[str] = Field(min_length=1, max_length=4)

    @field_validator("short_summary", "workflow_interpretation")
    @classmethod
    def reject_numeric_narrative_claims(cls, value: str) -> str:
        if re.search(r"\d", value):
            raise ValueError("compact narrative must not contain numeric claims")
        return value


class ExecutionMetrics(StrictModel):
    mode: Literal["offline", "bedrock"]
    model_id: str | None
    stop_reason: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int


class OperationalResult(AgentPayload):
    tool_execution_trace: list[dict[str, Any]]
    execution_metrics: ExecutionMetrics
    grounded_agent_narrative: str | None = None
    response_assembly_method: Literal[
        "deterministic_python_offline",
        "deterministic_python_with_native_strands_output",
        "deterministic_python_with_validated_text_fallback",
        "deterministic_python_with_plain_text",
    ] = "deterministic_python_offline"


class InvocationDiagnostics(StrictModel):
    exception_type: str
    message: str
    tool_names: list[str]
    completed_tool_call_count: int
    tool_execution_trace: list[dict[str, Any]]
    last_known_stop_reason: str | None
    elapsed_ms: float
    token_usage: dict[str, int] | None
    result_stop_reason: str | None = None
    structured_output_present: bool | None = None
    message_metadata: dict[str, Any] | None = None


class AgentInvocationError(RuntimeError):
    """Sanitized model invocation failure with preserved tool diagnostics."""

    def __init__(self, message: str, diagnostics: InvocationDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class IdentitySummary(StrictModel):
    profile: str
    region: str
    identity_type: Literal["root", "non-root"]
    credential_method: str | None


class WorkflowIntelligenceAgent:
    """Build and validate operational intelligence without moving numerical truth."""

    def __init__(
        self,
        store: IntelligenceBackend,
        settings: AgentSettings | None = None,
        agent_factory: Callable[..., Any] = Agent,
    ) -> None:
        self.store = store
        self.settings = settings or AgentSettings.from_environment()
        self.agent_factory = agent_factory

    def build_offline(
        self, patient_id: str, as_of: str, k: int = 10
    ) -> OperationalResult:
        """Execute all five deterministic adapters without any model invocation."""
        started = time.perf_counter()
        with patient_tool_session(
            self.store, patient_id, self.settings.max_tool_calls
        ) as runtime:
            payload = self._execute_tools(patient_id, as_of, k)
            trace = list(runtime.trace)
        result = OperationalResult(
            **payload.model_dump(),
            tool_execution_trace=trace,
            execution_metrics=ExecutionMetrics(
                mode="offline",
                model_id=None,
                stop_reason="deterministic_complete",
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
            ),
        )
        self.validate(result, patient_id, as_of, k)
        return result

    def _execute_tools(self, patient_id: str, as_of: str, k: int) -> AgentPayload:
        context = get_patient_context(patient_id)
        state = get_workflow_state(patient_id, as_of)
        similar = find_similar_patients(patient_id, k)
        cohort_ids = [item["patient_id"] for item in similar]
        cohort = get_cohort_next_steps(cohort_ids)
        evidence_ids = [
            item["evidence_id"]
            for item in context["evidence_references"] + state["evidence_references"]
        ]
        evidence = get_evidence(patient_id, list(dict.fromkeys(evidence_ids)))
        return AgentPayload(
            patient_context=context,
            current_workflow_state=state,
            similar_historical_patients=similar,
            synthetic_cohort_next_step_statistics=cohort,
            evidence_references=evidence,
            limitations=LIMITATIONS,
            warnings=WARNINGS,
        )

    def build_strands_agent(self, model: Any) -> Agent:
        """Create the actual Strands Agent with all five registered tools."""
        return self.agent_factory(
            model=model,
            tools=STRANDS_TOOLS,
            system_prompt=SYSTEM_PROMPT,
            callback_handler=None,
        )

    def run_with_model(
        self,
        patient_id: str,
        as_of: str,
        model: Any,
        k: int = 10,
        question: str | None = None,
    ) -> OperationalResult:
        """Run a model-backed agent and reject any divergence from M3 truth."""
        agent = self.build_strands_agent(model)
        prompt = (
            f"For synthetic patient {patient_id!r} at {as_of!r}, use all five tools "
            "to retrieve patient context, workflow status, comparable patients, "
            "historical next steps, and supporting evidence. First call context, "
            "workflow, and similarity tools together. Then call cohort and evidence "
            f"tools together. Call each tool at least once and request {k} comparable "
            "patients. After the tools finish, return a concise plain-English "
            "operational summary of roughly one-hundred to one-hundred-fifty words. "
            "Do not output JSON, numerical values, patient identifiers, or evidence "
            "identifiers. Do not reproduce tool payloads or make recommendations. "
            "Explicitly state that workflow information is synthetic. "
            f"The user's operational question is {question!r}."
        )
        started = time.perf_counter()
        runtime = None
        try:
            with patient_tool_session(
                self.store, patient_id, self.settings.max_tool_calls
            ) as runtime:
                response = agent(
                    prompt,
                    limits={
                        "turns": self.settings.max_agent_steps,
                        "output_tokens": (
                            self.settings.max_cumulative_output_tokens
                        ),
                        "total_tokens": self.settings.max_total_tokens,
                    },
                )
                trace = list(runtime.trace)
                tool_outputs = dict(runtime.outputs)
        except Exception as exc:
            diagnostics = _invocation_diagnostics(
                agent,
                runtime,
                exc,
                time.perf_counter() - started,
            )
            raise AgentInvocationError(str(exc), diagnostics) from exc
        try:
            if str(response.stop_reason) != "end_turn":
                raise ValueError(
                    f"agent ended abnormally with stop reason {response.stop_reason}"
                )
            narrative = _extract_assistant_text(response.message)
            deterministic = self._payload_from_tool_outputs(tool_outputs)
            _validate_plain_text_narrative(narrative, patient_id, deterministic)
        except Exception as exc:
            diagnostics = _result_diagnostics(
                response,
                trace,
                time.perf_counter() - started,
                type(exc).__name__,
                str(exc),
            )
            raise AgentInvocationError(str(exc), diagnostics) from exc
        usage = getattr(response.metrics, "accumulated_usage", {})
        result = OperationalResult(
            **deterministic.model_dump(),
            tool_execution_trace=trace,
            execution_metrics=ExecutionMetrics(
                mode="bedrock",
                model_id=self.settings.bedrock_model_id,
                stop_reason=str(response.stop_reason),
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
                total_tokens=usage.get("totalTokens", 0),
            ),
            grounded_agent_narrative=narrative,
            response_assembly_method="deterministic_python_with_plain_text",
        )
        try:
            self.validate(result, patient_id, as_of, k)
        except Exception as exc:
            diagnostics = _result_diagnostics(
                response,
                trace,
                time.perf_counter() - started,
                type(exc).__name__,
                str(exc),
            )
            raise AgentInvocationError(str(exc), diagnostics) from exc
        return result

    def _deterministic_payload(
        self, patient_id: str, as_of: str, k: int
    ) -> AgentPayload:
        """Assemble full detail directly from M3, never from model-authored values."""
        context = self.store.get_patient_context(patient_id)
        state = self.store.get_workflow_state(patient_id, as_of)
        similar = self.store.find_similar_patients(patient_id, k)
        cohort_ids = [item["patient_id"] for item in similar]
        cohort = self.store.get_cohort_next_steps(cohort_ids)
        evidence_ids = [
            item["evidence_id"]
            for item in context["evidence_references"] + state["evidence_references"]
        ]
        evidence = self.store.get_evidence(
            patient_id, list(dict.fromkeys(evidence_ids))
        )
        return AgentPayload(
            patient_context=context,
            current_workflow_state=state,
            similar_historical_patients=similar,
            synthetic_cohort_next_step_statistics=cohort,
            evidence_references=evidence,
            limitations=LIMITATIONS,
            warnings=WARNINGS,
        )

    @staticmethod
    def _payload_from_tool_outputs(outputs: dict[str, Any]) -> AgentPayload:
        """Build detailed output exclusively from this invocation's tool results."""
        required = {registered.tool_name for registered in STRANDS_TOOLS}
        missing = required - outputs.keys()
        if missing:
            raise ValueError(
                "missing captured tool outputs: " + ", ".join(sorted(missing))
            )
        return AgentPayload(
            patient_context=outputs["get_patient_context"],
            current_workflow_state=outputs["get_workflow_state"],
            similar_historical_patients=outputs["find_similar_patients"],
            synthetic_cohort_next_step_statistics=outputs[
                "get_cohort_next_steps"
            ],
            evidence_references=outputs["get_evidence"],
            limitations=LIMITATIONS,
            warnings=WARNINGS,
        )

    def validate(
        self, result: OperationalResult, patient_id: str, as_of: str, k: int
    ) -> None:
        """Reject unsupported numbers, citations, or cross-patient attribution."""
        expected_context = self.store.get_patient_context(patient_id)
        expected_state = self.store.get_workflow_state(patient_id, as_of)
        expected_similar = self.store.find_similar_patients(patient_id, k)
        cohort_ids = [item["patient_id"] for item in expected_similar]
        expected_cohort = self.store.get_cohort_next_steps(cohort_ids)
        if result.patient_context != expected_context:
            raise ValueError("unsupported patient context returned by agent")
        if result.current_workflow_state != expected_state:
            raise ValueError("unsupported workflow state returned by agent")
        if result.similar_historical_patients != expected_similar:
            raise ValueError("unsupported similarity result returned by agent")
        if result.synthetic_cohort_next_step_statistics != expected_cohort:
            raise ValueError("unsupported cohort statistics returned by agent")
        expected_ids = {
            item["evidence_id"]
            for item in expected_context["evidence_references"]
            + expected_state["evidence_references"]
        }
        actual_ids = {item["evidence_id"] for item in result.evidence_references}
        if actual_ids != expected_ids or any(
            item["patient_id"] != patient_id for item in result.evidence_references
        ):
            raise ValueError("invalid or cross-patient evidence attribution")
        if result.grounded_agent_narrative is not None:
            _validate_plain_text_narrative(
                result.grounded_agent_narrative,
                patient_id,
                AgentPayload(
                    patient_context=result.patient_context,
                    current_workflow_state=result.current_workflow_state,
                    similar_historical_patients=result.similar_historical_patients,
                    synthetic_cohort_next_step_statistics=(
                        result.synthetic_cohort_next_step_statistics
                    ),
                    evidence_references=result.evidence_references,
                    limitations=result.limitations,
                    warnings=result.warnings,
                ),
            )
        successful_tools = {
            item["tool_name"]
            for item in result.tool_execution_trace
            if item["success"]
        }
        required = {registered.tool_name for registered in STRANDS_TOOLS}
        if successful_tools != required:
            raise ValueError("agent did not successfully execute all five tools")


def boto_session(settings: AgentSettings) -> boto3.Session:
    """Resolve the explicit profile and region without hardcoded credentials."""
    return boto3.Session(
        profile_name=settings.aws_profile, region_name=settings.aws_region
    )


def identity_summary(
    settings: AgentSettings, session: boto3.Session | None = None
) -> IdentitySummary:
    """Read the current caller identity without exposing account identifiers."""
    session = session or boto_session(settings)
    identity = session.client(
        "sts", config=_client_config(settings)
    ).get_caller_identity()
    credentials = session.get_credentials()
    return IdentitySummary(
        profile=session.profile_name or settings.aws_profile,
        region=session.region_name or settings.aws_region,
        identity_type="root" if identity["Arn"].endswith(":root") else "non-root",
        credential_method=getattr(credentials, "method", None),
    )


def discover_bedrock(settings: AgentSettings, session: boto3.Session) -> dict[str, Any]:
    """Use only read-only Bedrock catalog APIs and verify the configured exact ID."""
    client = session.client("bedrock", config=_client_config(settings))
    models = client.list_foundation_models().get("modelSummaries", [])
    profiles: list[dict[str, Any]] = []
    token = None
    while True:
        kwargs = {"typeEquals": "SYSTEM_DEFINED"}
        if token:
            kwargs["nextToken"] = token
        response = client.list_inference_profiles(**kwargs)
        profiles.extend(response.get("inferenceProfileSummaries", []))
        token = response.get("nextToken")
        if not token:
            break
    model_ids = {item["modelId"] for item in models}
    profile_ids = {item["inferenceProfileId"] for item in profiles}
    known_ids = model_ids | profile_ids
    return {
        "foundation_model_count": len(model_ids),
        "inference_profile_count": len(profile_ids),
        "configured_model_id": settings.bedrock_model_id,
        "configured_model_found": settings.bedrock_model_id in known_ids,
        "configured_id_type": (
            "inference_profile"
            if settings.bedrock_model_id in profile_ids
            else "foundation_model"
            if settings.bedrock_model_id in model_ids
            else None
        ),
    }


def create_bedrock_model(
    settings: AgentSettings, session: boto3.Session | None = None
) -> BedrockModel:
    """Create BedrockModel only for a verified non-root identity and discovered ID."""
    session = session or boto_session(settings)
    identity = identity_summary(settings, session)
    if identity.identity_type == "root":
        raise PermissionError(
            "live Bedrock invocation is blocked for AWS root identity"
        )
    discovery = discover_bedrock(settings, session)
    if not discovery["configured_model_found"]:
        raise ValueError("configured Bedrock model ID was not found by discovery")
    return BedrockModel(
        boto_session=session,
        boto_client_config=_client_config(settings),
        model_id=settings.bedrock_model_id,
        max_tokens=settings.max_output_tokens,
        temperature=0.0,
        streaming=False,
    )


def create_agentcore_bedrock_model(
    settings: AgentSettings,
    session: boto3.Session | None = None,
) -> BedrockModel:
    """Create a model from the runtime role/default credential provider chain.

    This path deliberately does not resolve a named local profile. AgentCore must
    supply short-lived execution-role credentials through the default chain.
    """
    session = session or boto3.Session(region_name=settings.aws_region)
    if session.profile_name is not None:
        raise PermissionError("AgentCore runtime must not use a named AWS profile")
    return BedrockModel(
        boto_session=session,
        boto_client_config=_client_config(settings),
        model_id=settings.bedrock_model_id,
        max_tokens=settings.max_output_tokens,
        temperature=0.0,
        streaming=False,
    )


def create_root_authorized_synthetic_smoke_model(
    settings: AgentSettings,
    store: IntelligenceBackend,
    *,
    allow_root_synthetic_smoke: bool,
    session: boto3.Session | None = None,
) -> BedrockModel:
    """Create the one explicitly authorized synthetic-only root smoke model.

    This does not weaken :func:`create_bedrock_model`; that normal application path
    always rejects root. The override is fail-closed unless every user-authorized
    profile, region, model, fixture, and invocation bound matches exactly.
    """
    if not allow_root_synthetic_smoke:
        raise PermissionError("explicit synthetic root-smoke opt-in is required")
    if (
        settings.aws_profile != DEFAULT_PROFILE
        or settings.aws_region != DEFAULT_REGION
        or settings.bedrock_model_id != DEFAULT_MODEL_ID
    ):
        raise PermissionError("synthetic root-smoke AWS configuration mismatch")
    if getattr(store, "synthetic_smoke_fixture", False) is not True:
        raise PermissionError("root override requires the built-in synthetic fixture")
    if (
        settings.max_agent_steps > 8
        or settings.max_tool_calls > 10
        or settings.max_output_tokens > 4096
        or settings.max_cumulative_output_tokens > 8000
        or settings.max_attempts > 1
    ):
        raise PermissionError("synthetic root-smoke invocation bounds are too broad")
    session = session or boto_session(settings)
    identity = identity_summary(settings, session)
    if identity.profile != DEFAULT_PROFILE or identity.region != DEFAULT_REGION:
        raise PermissionError("resolved AWS session does not match smoke-test scope")
    discovery = discover_bedrock(settings, session)
    if (
        not discovery["configured_model_found"]
        or discovery["configured_id_type"] != "inference_profile"
    ):
        raise ValueError("authorized Bedrock inference profile was not found")
    return BedrockModel(
        boto_session=session,
        boto_client_config=_client_config(settings),
        model_id=settings.bedrock_model_id,
        max_tokens=settings.max_output_tokens,
        temperature=0.0,
        streaming=False,
    )


def _client_config(settings: AgentSettings) -> Config:
    return Config(
        connect_timeout=settings.connect_timeout_seconds,
        read_timeout=settings.read_timeout_seconds,
        retries={
            "mode": "standard",
            "total_max_attempts": settings.max_attempts,
        },
        user_agent_extra="rad-intel-m4",
    )


def _invocation_diagnostics(
    agent: Any,
    runtime: Any,
    exception: Exception,
    elapsed_seconds: float,
) -> InvocationDiagnostics:
    trace = list(runtime.trace) if runtime is not None else []
    sanitized_trace = _sanitize_trace(trace)
    metrics = getattr(agent, "event_loop_metrics", None)
    token_usage = _usage_from_metrics(metrics)
    stop_reason = getattr(exception, "stop_reason", None)
    if stop_reason is None and type(exception).__name__ == "MaxTokensReachedException":
        stop_reason = "max_tokens"
    return InvocationDiagnostics(
        exception_type=type(exception).__name__,
        message=str(exception)[:500],
        tool_names=[item["tool_name"] for item in sanitized_trace],
        completed_tool_call_count=sum(
            bool(item["success"]) for item in sanitized_trace
        ),
        tool_execution_trace=sanitized_trace,
        last_known_stop_reason=stop_reason,
        elapsed_ms=round(elapsed_seconds * 1000, 3),
        token_usage=token_usage,
    )


def _result_diagnostics(
    response: Any,
    trace: list[dict[str, Any]],
    elapsed_seconds: float,
    exception_type: str,
    message: str,
) -> InvocationDiagnostics:
    sanitized_trace = _sanitize_trace(trace)
    return InvocationDiagnostics(
        exception_type=exception_type,
        message=message[:500],
        tool_names=[item["tool_name"] for item in sanitized_trace],
        completed_tool_call_count=sum(
            bool(item["success"]) for item in sanitized_trace
        ),
        tool_execution_trace=sanitized_trace,
        last_known_stop_reason=_optional_string(
            getattr(response, "stop_reason", None)
        ),
        elapsed_ms=round(elapsed_seconds * 1000, 3),
        token_usage=_usage_from_metrics(getattr(response, "metrics", None)),
        result_stop_reason=_optional_string(
            getattr(response, "stop_reason", None)
        ),
        structured_output_present=(
            getattr(response, "structured_output", None) is not None
        ),
        message_metadata=_message_metadata(getattr(response, "message", None)),
    )


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _sanitize_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sequence": item["sequence"],
            "tool_name": item["tool_name"],
            "success": item["success"],
            "latency_ms": item["latency_ms"],
        }
        for item in trace
    ]


def _usage_from_metrics(metrics: Any) -> dict[str, int] | None:
    raw_usage = getattr(metrics, "accumulated_usage", None)
    if not isinstance(raw_usage, dict) or not any(raw_usage.values()):
        return None
    return {
        key: int(raw_usage.get(key, 0))
        for key in ("inputTokens", "outputTokens", "totalTokens")
    }


def _message_metadata(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        return {"available": False}
    content = message.get("content", [])
    block_types = []
    text_character_count = 0
    tool_names = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        block_types.extend(block)
        text_character_count += len(str(block.get("text", "")))
        tool_use = block.get("toolUse")
        if isinstance(tool_use, dict) and tool_use.get("name"):
            tool_names.append(str(tool_use["name"]))
    return {
        "available": True,
        "role": message.get("role"),
        "content_block_types": sorted(set(block_types)),
        "text_character_count": text_character_count,
        "tool_use_names": tool_names,
    }


def _extract_assistant_text(message: Any) -> str:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ValueError("agent did not return a final assistant message")
    content = message.get("content")
    if not isinstance(content, list):
        raise ValueError("agent message content is unavailable")
    text = " ".join(
        str(block["text"]).strip()
        for block in content
        if isinstance(block, dict) and str(block.get("text", "")).strip()
    ).strip()
    if not text:
        raise ValueError("agent returned an empty or tool-only message")
    return text


def _validate_plain_text_narrative(
    narrative: str,
    patient_id: str,
    deterministic: AgentPayload,
) -> None:
    """Fail closed on ungrounded identifiers, numbers, or clinical guidance."""
    if narrative.lstrip().startswith(("{", "[", "```")):
        raise ValueError("agent narrative must be plain English, not JSON")
    words = narrative.split()
    if len(words) < 20 or len(words) > 180:
        raise ValueError("agent narrative is outside the concise length boundary")
    if "synthetic" not in narrative.lower():
        raise ValueError("agent narrative omitted synthetic workflow provenance")
    if patient_id in narrative:
        raise ValueError("agent narrative included a patient identifier")
    known_evidence = {
        item["evidence_id"] for item in deterministic.evidence_references
    }
    mentioned_evidence = set(
        re.findall(
            r"\b[A-Za-z0-9]+-evidence-[A-Za-z0-9-]+\b",
            narrative,
            flags=re.IGNORECASE,
        )
    )
    if mentioned_evidence - known_evidence:
        raise ValueError("agent narrative contains an invalid evidence reference")
    if re.search(r"\d", narrative):
        raise ValueError("agent narrative contains an unsupported numeric claim")
    if re.search(
        r"\b(recommend|recommended|recommendation|dose|dosage|prescribe|"
        r"prescription|should receive|treat with|prognosis|survival)\b",
        narrative,
        flags=re.IGNORECASE,
    ):
        raise ValueError("agent narrative crossed the clinical product boundary")
