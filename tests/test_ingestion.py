import csv
import json
from pathlib import Path

import pytest
from openpyxl import Workbook
from pydantic import ValidationError

from rad_intel.data_pipeline.cli import main
from rad_intel.data_pipeline.ingestion import (
    FieldMapping,
    IngestionConfig,
    IngestionError,
    ingest_clinical_data,
)


def write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)


def base_config() -> IngestionConfig:
    return IngestionConfig(
        source_name="synthetic-test-fixture",
        fields=FieldMapping(
            patient_id="Source ID",
            disease_site="Site",
            age="Age at treatment",
            cancer_stage="Stage",
            hpv_status="HPV",
            radiation_treatment_characteristics={
                "dose_gy": "Dose Gy",
                "fractions": "Fractions",
            },
        ),
        value_maps={"hpv_status": {"POS": "positive", "NEG": "negative"}},
    )


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_mapping_schema_rejects_blank_identifier_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        FieldMapping(patient_id=" ")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FieldMapping(patient_id="ID", invented_field="value")


def test_missing_mapped_source_column_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    write_csv(source, ["Source ID", "Site"], [["P-1", "site-a"]])

    with pytest.raises(IngestionError, match="mapped source columns are missing"):
        ingest_clinical_data(source, tmp_path / "output", base_config())


def test_normalization_missingness_and_provenance(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    write_csv(
        source,
        [
            "Source ID",
            "Site",
            "Age at treatment",
            "Stage",
            "HPV",
            "Dose Gy",
            "Fractions",
            "Unmapped source note",
        ],
        [
            [" P-001 ", " Head and neck ", "65.0", "III", "POS", "70", "35", "x"],
            ["P-002", "Head and neck", "", "", "NEG", "", "", "y"],
        ],
    )

    result = ingest_clinical_data(source, tmp_path / "output", base_config())

    with result.patients_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["patient_id"] == "P-001"
    assert rows[0]["age"] == "65"
    assert rows[0]["hpv_status"] == "positive"
    assert rows[0]["clinical_provenance_type"] == "observed_clinical"
    assert rows[0]["radiation_treatment_characteristics"] == (
        '{"dose_gy":"70","fractions":"35"}'
    )
    assert rows[1]["age"] == ""

    quality = load_json(result.data_quality_path)
    missingness = quality["missingness_by_clinical_field"]
    assert missingness["age"] == {"count": 1, "percent": 50.0}
    assert missingness["systemic_therapy"] == {"count": 2, "percent": 100.0}
    source_missingness = quality["missingness_by_mapped_source_field"]
    assert source_missingness["radiation_treatment_characteristics.dose_gy"] == {
        "count": 1,
        "percent": 50.0,
        "source_column": "Dose Gy",
    }

    mapping = load_json(result.field_mapping_path)
    assert mapping["mapped_clinical_fields"] == [
        "disease_site",
        "age",
        "cancer_stage",
        "hpv_status",
        "radiation_treatment_characteristics",
    ]
    assert mapping["unmapped_source_columns"] == ["Unmapped source note"]


def test_subsite_and_systemic_therapy_normalization(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    write_csv(
        source,
        ["ID", "Subsite", "Therapy"],
        [["P-001", " oropharynx ", " concurrent therapy "]],
    )
    config = IngestionConfig(
        source_name="synthetic-test-fixture",
        fields=FieldMapping(
            patient_id="ID",
            subsite="Subsite",
            systemic_therapy="Therapy",
        ),
    )

    result = ingest_clinical_data(source, tmp_path / "output", config)

    with result.patients_path.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["subsite"] == "oropharynx"
    assert row["systemic_therapy"] == "concurrent therapy"


def test_composite_stage_and_treatment_fields(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    write_csv(
        source,
        ["ID", "T", "N", "M ", "Stage", "Modality", "Chemo"],
        [["P-001", "T2", "N1", "M0", "III", "RT+C", "Yes"]],
    )
    config = IngestionConfig(
        source_name="synthetic-test-fixture",
        fields=FieldMapping(
            patient_id="ID",
            cancer_stage={"t": "T", "n": "N", "m": "M ", "stage": "Stage"},
            systemic_therapy={
                "treatment_modality": "Modality",
                "concurrent_chemotherapy": "Chemo",
            },
        ),
    )

    result = ingest_clinical_data(source, tmp_path / "output", config)

    with result.patients_path.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["cancer_stage"] == '{"m":"M0","n":"N1","stage":"III","t":"T2"}'
    assert row["systemic_therapy"] == (
        '{"concurrent_chemotherapy":"Yes","treatment_modality":"RT+C"}'
    )


def test_duplicates_and_missing_identifiers_are_excluded(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    headers = [
        "Source ID",
        "Site",
        "Age at treatment",
        "Stage",
        "HPV",
        "Dose Gy",
        "Fractions",
    ]
    write_csv(
        source,
        headers,
        [
            ["P-001", "site-a", "60", "II", "POS", "60", "30"],
            ["P-001", "site-b", "61", "III", "NEG", "70", "35"],
            ["", "site-c", "62", "I", "NEG", "50", "25"],
            ["P-002", "site-a", "63", "II", "POS", "60", "30"],
        ],
    )

    result = ingest_clinical_data(source, tmp_path / "output", base_config())
    quality = load_json(result.data_quality_path)

    assert result.total_source_records == 4
    assert result.unique_patient_count == 2
    assert quality["duplicate_identifiers"] == {
        "count": 1,
        "duplicate_record_count": 1,
    }
    assert quality["excluded_records"] == {
        "count": 2,
        "reasons": {"duplicate_patient_id": 1, "missing_patient_id": 1},
    }


def test_invalid_age_and_unmapped_category_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    write_csv(
        source,
        [
            "Source ID",
            "Site",
            "Age at treatment",
            "Stage",
            "HPV",
            "Dose Gy",
            "Fractions",
        ],
        [["P-001", "site-a", "not-an-age", "II", "UNKNOWN", "60", "30"]],
    )

    result = ingest_clinical_data(source, tmp_path / "output", base_config())
    quality = load_json(result.data_quality_path)

    assert quality["invalid_or_unmapped_values"]["age"]["invalid_count"] == 1
    assert quality["invalid_or_unmapped_values"]["hpv_status"]["unmapped_count"] == 1
    with result.patients_path.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["age"] == ""
    assert row["hpv_status"] == "UNKNOWN"


def test_outputs_are_reproducible(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    write_csv(
        source,
        [
            "Source ID",
            "Site",
            "Age at treatment",
            "Stage",
            "HPV",
            "Dose Gy",
            "Fractions",
        ],
        [["P-001", "site-a", "50", "I", "NEG", "50", "25"]],
    )

    first = ingest_clinical_data(source, tmp_path / "first", base_config())
    second = ingest_clinical_data(source, tmp_path / "second", base_config())

    assert first.patients_path.read_bytes() == second.patients_path.read_bytes()
    assert first.data_quality_path.read_bytes() == second.data_quality_path.read_bytes()
    assert (
        first.field_mapping_path.read_bytes()
        == second.field_mapping_path.read_bytes()
    )


def test_xlsx_input_uses_explicit_sheet(tmp_path: Path) -> None:
    source = tmp_path / "fixture.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Clinical"
    worksheet.append(
        [
            "Source ID",
            "Site",
            "Age at treatment",
            "Stage",
            "HPV",
            "Dose Gy",
            "Fractions",
        ]
    )
    worksheet.append([1001, "site-a", 55, "II", "POS", 60, 30])
    workbook.save(source)

    config = base_config().model_copy(update={"sheet_name": "Clinical"})
    result = ingest_clinical_data(source, tmp_path / "output", config)

    with result.patients_path.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["patient_id"] == "1001"
    assert row["age"] == "55"
    assert load_json(result.data_quality_path)["source"]["sheet_name"] == "Clinical"


def test_cli_reports_aggregates_without_patient_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "fixture.csv"
    write_csv(source, ["ID", "Site"], [["SECRET-PATIENT-ID", "secret-site"]])
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "source_name": "synthetic-test-fixture",
                "fields": {"patient_id": "ID", "disease_site": "Site"},
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--input",
            str(source),
            "--mapping",
            str(mapping),
            "--output",
            str(tmp_path / "output"),
        ]
    )

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert "Unique patients written: 1" in captured
    assert "SECRET-PATIENT-ID" not in captured
    assert "secret-site" not in captured
