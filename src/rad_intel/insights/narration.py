"""Future narration boundary; M10A does not invoke a model."""

from __future__ import annotations

from typing import Protocol

from rad_intel.insights.schemas import PatientInsights


class PatientInsightsNarrator(Protocol):
    """Accept only validated insights and return wording, never numerical truth."""

    def narrate(self, insights: PatientInsights) -> str:
        """Return wording grounded exclusively in the supplied validated insights."""
        ...
