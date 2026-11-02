"""Metric primitives with explicit numerators, denominators, and edge handling."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RateMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None
    status: str

    @classmethod
    def from_counts(cls, numerator: int, denominator: int) -> RateMetric:
        if numerator < 0 or denominator < 0 or numerator > denominator:
            raise ValueError("metric counts must satisfy 0 <= numerator <= denominator")
        if denominator == 0:
            return cls(
                numerator=numerator,
                denominator=denominator,
                rate=None,
                status="NOT_MEASURED",
            )
        return cls(
            numerator=numerator,
            denominator=denominator,
            rate=round(numerator / denominator, 8),
            status="MEASURED",
        )


def percentile(values: list[float], percent: float) -> float | None:
    """Return a linearly interpolated percentile without hidden dependencies."""
    if not values:
        return None
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between zero and one hundred")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def latency_summary(values: list[float], errors: int = 0) -> dict[str, Any]:
    attempts = len(values) + errors
    return {
        "sample_size": attempts,
        "successful_samples": len(values),
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "maximum_ms": round(max(values), 6) if values else None,
        "error_rate": round(errors / attempts, 8) if attempts else None,
    }
