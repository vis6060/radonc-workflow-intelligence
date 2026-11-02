"""M4 offline demo, read-only discovery, and synthetic-only live smoke entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rad_intel.agent.bedrock_agent import (
    AgentInvocationError,
    AgentSettings,
    WorkflowIntelligenceAgent,
    boto_session,
    create_bedrock_model,
    create_root_authorized_synthetic_smoke_model,
    discover_bedrock,
    identity_summary,
)
from rad_intel.tools import IntelligenceStore

SYNTHETIC_PATIENT = "SYNTHETIC-DEMO-001"
SYNTHETIC_AS_OF = "2035-01-10T12:00:00+00:00"


class SyntheticSmokeStore:
    """Small fabricated backend that contains no RADCURE patient-level content."""

    synthetic_smoke_fixture = True

    def get_patient_context(self, patient_id: str) -> dict[str, Any]:
        self._target(patient_id)
        return {
            "patient_id": patient_id,
            "disease_characteristics": {
                "disease_site": "synthetic-site",
                "subsite": None,
                "cancer_stage": None,
                "hpv_status": None,
            },
            "age": None,
            "treatment_attributes": {},
            "missing_data": {"age": True},
            "evidence_references": [],
            "provenance": {"source_type": "synthetic_smoke_fixture"},
        }

    def get_workflow_state(self, patient_id: str, as_of: str) -> dict[str, Any]:
        self._target(patient_id)
        return {
            "patient_id": patient_id,
            "as_of": as_of,
            "current_workflow_stage": "consult_completed",
            "completed_prerequisites": [
                "referral_received",
                "consult_scheduled",
                "consult_completed",
            ],
            "outstanding_tasks": ["authorization_requested"],
            "elapsed_days_in_current_stage": 1.0,
            "evidence_references": [self._evidence(patient_id)],
            "provenance": "synthetic_workflow",
        }

    def find_similar_patients(
        self, patient_id: str, k: int = 10, weights: dict[str, float] | None = None
    ) -> list[dict[str, Any]]:
        self._target(patient_id)
        return [
            {
                "patient_id": f"SYNTHETIC-HISTORICAL-{index:03d}",
                "score": round(1 - index / 100, 2),
                "feature_comparisons": {},
            }
            for index in range(1, k + 1)
        ]

    def get_cohort_next_steps(self, patient_ids: list[str]) -> dict[str, Any]:
        return {
            "cohort_denominator": len(patient_ids),
            "observed_next_event_count": len(patient_ids),
            "missing_or_censored_count": 0,
            "next_event_categories": [
                {
                    "event_type": "authorization_requested",
                    "count": len(patient_ids),
                    "percentage_of_cohort": 100.0,
                    "synthetic_time_to_next_event_days": {
                        "minimum": 1.0,
                        "median": 1.0,
                        "mean": 1.0,
                        "maximum": 1.0,
                    },
                    "evidence_references": [],
                }
            ],
            "sample_size_warning": "Synthetic smoke fixture only.",
            "synthetic_timing_notice": "SYNTHETIC demonstration timing.",
        }

    def get_evidence(
        self, patient_id: str, evidence_ids: list[str]
    ) -> list[dict[str, Any]]:
        self._target(patient_id)
        if evidence_ids != ["synthetic-evidence-001"]:
            raise ValueError("unknown synthetic evidence")
        return [self._evidence(patient_id)]

    @staticmethod
    def _target(patient_id: str) -> None:
        if patient_id != SYNTHETIC_PATIENT:
            raise KeyError("unknown synthetic patient")

    @staticmethod
    def _evidence(patient_id: str) -> dict[str, Any]:
        return {
            "evidence_id": "synthetic-evidence-001",
            "patient_id": patient_id,
            "source_type": "synthetic_workflow",
            "source_record": "synthetic-event-001",
            "field_or_event": "consult_completed",
            "value": {
                "event_type": "consult_completed",
                "occurred_at": "2035-01-09T12:00:00+00:00",
            },
            "provenance": {"source_name": "m4-synthetic-smoke-fixture"},
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patient-id")
    parser.add_argument("--as-of")
    parser.add_argument("--data-directory", type=Path)
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--live-smoke", action="store_true")
    parser.add_argument("--allow-root-synthetic-smoke", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = AgentSettings.from_environment()
    if args.allow_root_synthetic_smoke and not args.live_smoke:
        raise SystemExit("root synthetic-smoke opt-in requires --live-smoke")
    if args.discover:
        session = boto_session(settings)
        report = {
            "identity": identity_summary(settings, session).model_dump(),
            "discovery": discover_bedrock(settings, session),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.live_smoke:
        if args.patient_id or args.as_of or args.data_directory is not None:
            raise SystemExit(
                "live smoke does not accept patient, as-of, or data-path input"
            )
        store = SyntheticSmokeStore()
        smoke_settings = settings.model_copy(
            update={
                "max_agent_steps": 8,
                "max_tool_calls": 10,
                "max_output_tokens": 4096,
                "max_cumulative_output_tokens": 8000,
                "max_attempts": 1,
            }
        )
        try:
            if args.allow_root_synthetic_smoke:
                model = create_root_authorized_synthetic_smoke_model(
                    smoke_settings,
                    store,
                    allow_root_synthetic_smoke=True,
                )
            else:
                model = create_bedrock_model(smoke_settings)
        except PermissionError as exc:
            raise SystemExit(str(exc)) from exc
        service = WorkflowIntelligenceAgent(store, smoke_settings)
        try:
            result = service.run_with_model(
                SYNTHETIC_PATIENT,
                SYNTHETIC_AS_OF,
                model,
                k=10,
            )
        except AgentInvocationError as exc:
            print(exc.diagnostics.model_dump_json(indent=2))
            raise SystemExit("live smoke failed; diagnostic emitted") from exc
        print(result.model_dump_json(indent=2))
        return 0
    if not args.patient_id or not args.as_of:
        raise SystemExit("offline mode requires --patient-id and --as-of")
    store = IntelligenceStore(args.data_directory or Path("data/processed"))
    result = WorkflowIntelligenceAgent(store, settings).build_offline(
        args.patient_id, args.as_of
    )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
