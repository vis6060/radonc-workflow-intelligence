"""Optional modeled cost calculation from explicit, versioned price inputs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PricingInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    currency: str
    effective_date: str
    source: str
    input_price_per_million_tokens: float = Field(ge=0)
    output_price_per_million_tokens: float = Field(ge=0)


def modeled_cost(
    input_tokens: int, output_tokens: int, pricing: PricingInputs | None
) -> dict[str, object]:
    if pricing is None:
        return {"status": "NOT_MEASURED", "reason": "No verified pricing input."}
    input_cost = input_tokens / 1_000_000 * pricing.input_price_per_million_tokens
    output_cost = output_tokens / 1_000_000 * pricing.output_price_per_million_tokens
    return {
        "status": "MODELED",
        "modeled_cost": round(input_cost + output_cost, 8),
        "currency": pricing.currency,
        "pricing": pricing.model_dump(),
        "aws_billing_amount": "NOT_MEASURED",
    }
