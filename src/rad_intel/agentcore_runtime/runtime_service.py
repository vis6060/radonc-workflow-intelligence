"""Portable AgentCore request service and explicitly scoped data providers."""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.responses import JSONResponse

from rad_intel.agent.bedrock_agent import (
    AgentInvocationError,
    AgentSettings,
    WorkflowIntelligenceAgent,
    create_agentcore_bedrock_model,
)
from rad_intel.showcase import SyntheticShowcaseStore
from rad_intel.tools import IntelligenceStore

LOGGER = logging.getLogger("rad_intel.agentcore_runtime")
DEFAULT_LOCAL_DATA_DIRECTORY = Path("data/processed")


class RuntimeRequest(BaseModel):
    """Validated AgentCore invocation contract."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=1000)
    as_of: str | None = None

    @field_validator("patient_id", "question")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value


class DataProvider(Protocol):
    """Select a scoped M3 backend without hiding where its data comes from."""

    name: str
    deployment_safe: bool

    @property
    def store(self) -> Any: ...

    def resolve_as_of(self, patient_id: str, requested: str | None) -> str: ...


class LocalCohortProvider:
    """Full local M1-M3 cohort; never included in the deployment artifact."""

    name = "local_full_cohort"
    deployment_safe = False

    def __init__(self, data_directory: Path = DEFAULT_LOCAL_DATA_DIRECTORY) -> None:
        self.data_directory = data_directory
        self._store: IntelligenceStore | None = None

    @property
    def store(self) -> IntelligenceStore:
        if self._store is None:
            self._store = IntelligenceStore(self.data_directory)
        return self._store

    def resolve_as_of(self, patient_id: str, requested: str | None) -> str:
        if patient_id not in self.store.patients:
            raise KeyError("patient is not available in the selected provider")
        if requested is not None:
            return requested
        return str(self.store.snapshots[patient_id]["as_of"])


class SyntheticFixtureProvider:
    """Fictional showcase provider containing no RADCURE-derived records."""

    name = "synthetic_fixture"
    deployment_safe = True

    def __init__(self) -> None:
        self._store = SyntheticShowcaseStore()

    @property
    def store(self) -> SyntheticShowcaseStore:
        return self._store

    def resolve_as_of(self, patient_id: str, requested: str | None) -> str:
        if patient_id not in self.store.patients:
            raise KeyError("patient is not available in the synthetic fixture")
        return requested or self.store.snapshots[patient_id]["as_of"]


def provider_from_environment() -> DataProvider:
    """Select data explicitly; remote preparation defaults to synthetic-only."""
    selection = os.getenv("RAD_INTEL_DATA_PROVIDER", "synthetic").strip().lower()
    if selection == "synthetic":
        return SyntheticFixtureProvider()
    if selection == "local":
        path = Path(
            os.getenv(
                "RAD_INTEL_DATA_DIRECTORY",
                str(DEFAULT_LOCAL_DATA_DIRECTORY),
            )
        )
        return LocalCohortProvider(path)
    raise ValueError("RAD_INTEL_DATA_PROVIDER must be 'synthetic' or 'local'")


class RuntimeService:
    """Invoke the validated M4 agent behind a bounded, sanitized HTTP boundary."""

    def __init__(
        self,
        provider: DataProvider,
        *,
        settings: AgentSettings | None = None,
        model_factory: Callable[[AgentSettings], Any] = create_agentcore_bedrock_model,
        agent_factory: Callable[..., Any] | None = None,
        request_timeout_seconds: float = 60.0,
    ) -> None:
        self.provider = provider
        self.settings = settings or AgentSettings.from_environment().model_copy(
            update={"max_agent_steps": 8, "max_tool_calls": 10}
        )
        self.model_factory = model_factory
        self.agent_factory = agent_factory
        self.request_timeout_seconds = request_timeout_seconds

    def handle(
        self,
        payload: Any,
        *,
        request_id: str | None = None,
    ) -> JSONResponse:
        started = time.perf_counter()
        safe_request_id = request_id or str(uuid.uuid4())
        try:
            request = RuntimeRequest.model_validate(payload)
        except ValidationError as exc:
            return self._error(
                safe_request_id,
                started,
                status_code=400,
                code="INVALID_REQUEST",
                message="Request validation failed.",
                details=[
                    {"field": ".".join(map(str, item["loc"])), "type": item["type"]}
                    for item in exc.errors()
                ],
            )

        try:
            as_of = self.provider.resolve_as_of(request.patient_id, request.as_of)
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(self._invoke, request, as_of)
                result = future.result(timeout=self.request_timeout_seconds)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        except KeyError:
            return self._error(
                safe_request_id,
                started,
                status_code=404,
                code="PATIENT_NOT_FOUND",
                message="Patient is not available in the selected data provider.",
            )
        except TimeoutError:
            future.cancel()
            return self._error(
                safe_request_id,
                started,
                status_code=504,
                code="REQUEST_TIMEOUT",
                message="The bounded agent invocation timed out.",
            )
        except AgentInvocationError as exc:
            LOGGER.warning(
                "request_id=%s agent_failure=%s completed_tools=%d",
                safe_request_id,
                exc.diagnostics.exception_type,
                exc.diagnostics.completed_tool_call_count,
            )
            return self._error(
                safe_request_id,
                started,
                status_code=502,
                code="AGENT_INVOCATION_FAILED",
                message="The agent could not produce a validated response.",
            )
        except Exception as exc:
            LOGGER.error(
                "request_id=%s runtime_failure=%s",
                safe_request_id,
                type(exc).__name__,
            )
            return self._error(
                safe_request_id,
                started,
                status_code=500,
                code="INTERNAL_ERROR",
                message="The runtime could not complete the request.",
            )

        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        LOGGER.info(
            "request_id=%s provider=%s status=success elapsed_ms=%.3f",
            safe_request_id,
            self.provider.name,
            elapsed_ms,
        )
        return JSONResponse(
            {
                "ok": True,
                "request_id": safe_request_id,
                "elapsed_ms": elapsed_ms,
                "data_provider": self.provider.name,
                "response": result.model_dump(mode="json"),
            }
        )

    def _invoke(self, request: RuntimeRequest, as_of: str) -> Any:
        model = self.model_factory(self.settings)
        kwargs: dict[str, Any] = {}
        if self.agent_factory is not None:
            kwargs["agent_factory"] = self.agent_factory
        service = WorkflowIntelligenceAgent(
            self.provider.store,
            self.settings,
            **kwargs,
        )
        return service.run_with_model(
            request.patient_id,
            as_of,
            model,
            k=10,
            question=request.question,
        )

    @staticmethod
    def _error(
        request_id: str,
        started: float,
        *,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, str]] | None = None,
    ) -> JSONResponse:
        body: dict[str, Any] = {
            "ok": False,
            "request_id": request_id,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": {"code": code, "message": message},
        }
        if details:
            body["error"]["details"] = details
        return JSONResponse(body, status_code=status_code)
