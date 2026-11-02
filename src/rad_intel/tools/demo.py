"""Local deterministic M3 demonstration without LLM or AWS services."""

from __future__ import annotations

import json

from rad_intel.tools.intelligence import IntelligenceStore


def main() -> int:
    store = IntelligenceStore()
    patient_id = sorted(store.patients)[0]
    snapshot = store.snapshots[patient_id]
    context = store.get_patient_context(patient_id)
    state = store.get_workflow_state(patient_id, snapshot["as_of"])
    similar = store.find_similar_patients(patient_id, 10)
    cohort = store.get_cohort_next_steps([item["patient_id"] for item in similar])
    evidence_ids = [item["evidence_id"] for item in state["evidence_references"][:3]]
    response = {
        "patient_context": context,
        "workflow_state": state,
        "similar_patients": similar,
        "historical_next_steps": cohort,
        "resolved_evidence": store.get_evidence(patient_id, evidence_ids),
        "limitations": [
            "Operational workflow only; no diagnosis or treatment recommendation.",
            "Workflow events and timing statistics are synthetic.",
        ],
    }
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
