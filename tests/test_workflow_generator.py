import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

from rad_intel.workflow_generator import (
    BASE_EVENT_TYPES,
    GenerationError,
    GeneratorConfig,
    WorkflowPhenotype,
    generate_workflows,
)


def write_patients(path: Path, patient_ids: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["patient_id", "Age", "Ds Site", "HPV"],
            lineterminator="\n",
        )
        writer.writeheader()
        for index, patient_id in enumerate(patient_ids):
            writer.writerow(
                {
                    "patient_id": patient_id,
                    "Age": 40 + index,
                    "Ds Site": f"clinical-site-{index}",
                    "HPV": f"clinical-value-{index}",
                }
            )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    root = tmp_path_factory.mktemp("workflow-generation")
    patients_path = root / "patients.csv"
    patient_ids = [f"PAT-{index:03d}" for index in range(16)]
    write_patients(patients_path, patient_ids)
    result = generate_workflows(
        patients_path,
        root / "output",
        GeneratorConfig(seed=42),
    )
    return {
        "root": root,
        "patients_path": patients_path,
        "patient_ids": patient_ids,
        "result": result,
        "events": read_csv(result.events_path),
        "snapshots": read_csv(result.snapshots_path),
        "gold": json.loads(result.gold_path.read_text(encoding="utf-8")),
        "report": json.loads(result.report_path.read_text(encoding="utf-8")),
    }


def test_exact_patient_coverage(generated: dict[str, object]) -> None:
    expected = set(generated["patient_ids"])
    events = generated["events"]
    snapshots = generated["snapshots"]
    gold = generated["gold"]

    assert {row["patient_id"] for row in events} == expected
    assert {row["patient_id"] for row in snapshots} == expected
    assert {row["patient_id"] for row in gold["patients"]} == expected
    assert len(snapshots) == len(expected)
    assert len(gold["patients"]) == len(expected)


def test_all_phenotypes_and_required_events_are_represented(
    generated: dict[str, object],
) -> None:
    events_by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in generated["events"]:
        events_by_patient[row["patient_id"]].append(row)

    represented = set()
    for rows in events_by_patient.values():
        represented.add(rows[0]["phenotype"])
        baseline = [
            row["event_type"]
            for row in rows
            if row["event_type"] in BASE_EVENT_TYPES
        ]
        assert tuple(baseline) == BASE_EVENT_TYPES

    assert represented == {phenotype.value for phenotype in WorkflowPhenotype}
    assert generated["report"]["phenotype_counts"] == {
        phenotype.value: 2 for phenotype in WorkflowPhenotype
    }


def test_events_are_strictly_chronological(generated: dict[str, object]) -> None:
    events_by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in generated["events"]:
        events_by_patient[row["patient_id"]].append(row)

    for rows in events_by_patient.values():
        timestamps = [datetime.fromisoformat(row["occurred_at"]) for row in rows]
        assert all(timestamp.tzinfo is not None for timestamp in timestamps)
        assert all(
            later > earlier
            for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        )


def test_exceptional_events_match_phenotypes(generated: dict[str, object]) -> None:
    event_types_by_phenotype: dict[str, set[str]] = defaultdict(set)
    for row in generated["events"]:
        event_types_by_phenotype[row["phenotype"]].add(row["event_type"])

    assert "consult_rescheduled" in event_types_by_phenotype["rescheduling"]
    assert {"consult_no_show", "consult_rescheduled"}.issubset(
        event_types_by_phenotype["no_show"]
    )
    assert {
        "hospitalization_interruption_started",
        "hospitalization_interruption_resolved",
    }.issubset(event_types_by_phenotype["hospitalization_interruption"])


def test_gold_and_snapshots_use_only_point_in_time_events(
    generated: dict[str, object],
) -> None:
    events_by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in generated["events"]:
        events_by_patient[row["patient_id"]].append(row)
    snapshots = {row["patient_id"]: row for row in generated["snapshots"]}

    for gold in generated["gold"]["patients"]:
        patient_id = gold["patient_id"]
        as_of = datetime.fromisoformat(gold["as_of"])
        expected_visible = [
            row
            for row in events_by_patient[patient_id]
            if datetime.fromisoformat(row["occurred_at"]) <= as_of
        ]
        future = [
            row
            for row in events_by_patient[patient_id]
            if datetime.fromisoformat(row["occurred_at"]) > as_of
        ]
        expected_ids = [row["event_id"] for row in expected_visible]
        expected_evidence = [row["evidence_id"] for row in expected_visible]

        assert gold["completed_event_ids"] == expected_ids
        assert gold["evidence_ids"] == expected_evidence
        assert not set(gold["completed_event_ids"]) & {
            row["event_id"] for row in future
        }

        snapshot = snapshots[patient_id]
        assert json.loads(snapshot["completed_event_ids_json"]) == expected_ids
        assert json.loads(snapshot["evidence_ids_json"]) == expected_evidence
        assert snapshot["current_workflow_stage"] == gold["current_workflow_stage"]
        assert json.loads(snapshot["outstanding_tasks_json"]) == gold[
            "outstanding_tasks"
        ]


def test_synthetic_evidence_provenance_and_patient_isolation(
    generated: dict[str, object],
) -> None:
    evidence_owner: dict[str, str] = {}
    for row in generated["events"]:
        assert row["provenance_type"] == "synthetic_workflow"
        assert row["source_name"] == "rad-intel-synthetic-workflow-generator"
        assert row["evidence_id"] not in evidence_owner
        evidence_owner[row["evidence_id"]] = row["patient_id"]

    for snapshot in generated["snapshots"]:
        for evidence_id in json.loads(snapshot["evidence_ids_json"]):
            assert evidence_owner[evidence_id] == snapshot["patient_id"]


def test_generator_does_not_copy_clinical_attributes(
    generated: dict[str, object],
) -> None:
    forbidden = {"Age", "Ds Site", "HPV", "clinical-site", "clinical-value"}
    result = generated["result"]
    event_text = result.events_path.read_text(encoding="utf-8")
    snapshot_text = result.snapshots_path.read_text(encoding="utf-8")

    for value in forbidden:
        assert value not in event_text
        assert value not in snapshot_text
    for row in generated["events"]:
        metadata = json.loads(row["event_metadata_json"])
        assert set(metadata) == {
            "elapsed_hours_from_prior_event",
            "evidence_id",
            "is_exceptional",
            "phenotype",
            "timing_assumption",
        }


def test_outputs_are_byte_reproducible(generated: dict[str, object]) -> None:
    root = generated["root"]
    first = generated["result"]
    second = generate_workflows(
        generated["patients_path"],
        root / "repeat",
        GeneratorConfig(seed=42),
    )

    assert first.events_path.read_bytes() == second.events_path.read_bytes()
    assert first.snapshots_path.read_bytes() == second.snapshots_path.read_bytes()
    assert first.gold_path.read_bytes() == second.gold_path.read_bytes()
    assert first.report_path.read_bytes() == second.report_path.read_bytes()


def test_snapshot_stage_distribution_and_gold_validation(
    generated: dict[str, object],
) -> None:
    report = generated["report"]
    assert len(report["snapshot_stage_counts"]) >= len(BASE_EVENT_TYPES)
    assert report["validation"] == {
        "chronology_violations": 0,
        "cross_patient_evidence_violations": 0,
        "evidence_provenance_violations": 0,
        "exact_patient_id_coverage": True,
        "future_information_violations": 0,
        "gold_state_count": 16,
        "gold_state_mismatches": 0,
        "sequence_violations": 0,
    }


def test_duplicate_patient_ids_are_rejected(tmp_path: Path) -> None:
    patients_path = tmp_path / "patients.csv"
    write_patients(patients_path, ["PAT-001", "PAT-001"])

    with pytest.raises(GenerationError, match="duplicate patient_id"):
        generate_workflows(patients_path, tmp_path / "output")
