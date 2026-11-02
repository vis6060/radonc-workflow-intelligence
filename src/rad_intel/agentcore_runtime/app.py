"""Amazon Bedrock AgentCore Runtime HTTP entrypoint."""

from __future__ import annotations

from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.runtime.models import PingStatus

from rad_intel.agentcore_runtime.runtime_service import (
    RuntimeService,
    provider_from_environment,
)


def create_app(service: RuntimeService | None = None) -> BedrockAgentCoreApp:
    """Build an injectable AgentCore-compatible application."""
    runtime_service = service or RuntimeService(provider_from_environment())
    application = BedrockAgentCoreApp(debug=False)

    @application.entrypoint
    def invoke(payload: Any, context: Any) -> Any:
        request_id = getattr(context, "request_id", None)
        return runtime_service.handle(payload, request_id=request_id)

    @application.ping
    def ping() -> PingStatus:
        return PingStatus.HEALTHY

    return application


app = create_app()


if __name__ == "__main__":
    app.run()
