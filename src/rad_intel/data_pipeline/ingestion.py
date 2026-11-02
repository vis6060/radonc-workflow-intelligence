"""Deterministic ingestion of explicitly mapped RADCURE clinical files."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any

from openpyxl import load_workbook
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


def _preserve_nonblank_source_column(value: str) -> str:
    if not value.strip():
        raise ValueError("source column name must not be blank")
    return value


SourceColumn = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_preserve_nonblank_source_column),
]

SUPPORTED_SUFFIXES = {".csv", ".xlsx"}
CLINICAL_FIELDS = (
    "disease_site",
    "subsite",
    "age",
    "cancer_stage",
    "hpv_status",
    "systemic_therapy",
    "radiation_treatment_characteristics",
)
VALUE_MAPPABLE_FIELDS = {
    "disease_site",
    "subsite",
    "cancer_stage",
    "hpv_status",
    "systemic_therapy",
}
OUTPUT_FIELDS = (
    "patient_id",
    *CLINICAL_FIELDS,
    "clinical_provenance_type",
    "clinical_source_name",
    "clinical_source_file",
    "clinical_source_sha256",
    "clinical_source_record_identifier",
)


class StrictModel(BaseModel):
    """Configuration model that rejects undeclared settings."""

    model_config = ConfigDict(extra="forbid")


class FieldMapping(StrictModel):
    """Explicit source-column mapping; only patient_id is mandatory."""

    patient_id: SourceColumn
    disease_site: SourceColumn | None = None
    subsite: SourceColumn | None = None
    age: SourceColumn | None = None
    cancer_stage: SourceColumn | dict[NonEmptyString, SourceColumn] | None = None
    hpv_status: SourceColumn | None = None
    systemic_therapy: (
        SourceColumn | dict[NonEmptyString, SourceColumn] | None
    ) = None
    radiation_treatment_characteristics: dict[NonEmptyString, SourceColumn] = (
        Field(default_factory=dict)
    )


class IngestionConfig(StrictModel):
    """Reproducible instructions for interpreting one clinical source file."""

    source_name: NonEmptyString
    fields: FieldMapping
    sheet_name: NonEmptyString | None = None
    value_maps: dict[str, dict[str, str]] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        unsupported = set(self.value_maps) - VALUE_MAPPABLE_FIELDS
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(f"value_maps contains unsupported fields: {names}")
        composite_value_maps = {
            name
            for name in ("cancer_stage", "systemic_therapy")
            if isinstance(getattr(self.fields, name), dict) and name in self.value_maps
        }
        if composite_value_maps:
            names = ", ".join(sorted(composite_value_maps))
            raise ValueError(f"value_maps cannot target composite fields: {names}")


@dataclass(frozen=True)
class IngestionResult:
    """Aggregate result paths and counts; contains no patient-level values."""

    patients_path: Path
    data_quality_path: Path
    field_mapping_path: Path
    total_source_records: int
    unique_patient_count: int
    excluded_record_count: int


class IngestionError(ValueError):
    """Raised when a source file cannot satisfy its explicit ingestion contract."""


@dataclass(frozen=True)
class _SourceTable:
    headers: tuple[str, ...]
    rows: tuple[tuple[int, dict[str, Any]], ...]
    sheet_name: str | None


def load_config(path: Path) -> IngestionConfig:
    """Load and validate a JSON mapping without inferring any source columns."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionError(f"unable to read mapping file: {path}") from exc
    return IngestionConfig.model_validate(payload)


def ingest_clinical_data(
    input_path: Path,
    output_directory: Path,
    config: IngestionConfig,
) -> IngestionResult:
    """Create deterministic normalized CSV, quality, and mapping artifacts."""
    source_path = input_path.resolve()
    if not source_path.is_file():
        raise IngestionError(f"input file does not exist: {input_path}")
    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestionError("input format must be .csv or .xlsx")

    source_sha256 = _sha256(source_path)
    table = _read_source(source_path, config.sheet_name)
    mapped_columns = _mapped_source_columns(config.fields)
    mapped_field_paths = _mapped_clinical_field_paths(config.fields)
    missing_columns = mapped_columns - set(table.headers)
    if missing_columns:
        names = ", ".join(sorted(missing_columns))
        raise IngestionError(f"mapped source columns are missing: {names}")

    normalized_rows: list[dict[str, str]] = []
    seen_patient_ids: set[str] = set()
    duplicate_patient_ids: set[str] = set()
    excluded_reasons: Counter[str] = Counter()
    invalid_counts: Counter[str] = Counter()
    unmapped_counts: Counter[str] = Counter()
    mapped_source_missing_counts: Counter[str] = Counter()
    total_source_records = 0

    for source_row_number, source_row in table.rows:
        total_source_records += 1
        patient_id = _normalize_scalar(source_row.get(config.fields.patient_id))
        if patient_id is None:
            excluded_reasons["missing_patient_id"] += 1
            continue
        if patient_id in seen_patient_ids:
            duplicate_patient_ids.add(patient_id)
            excluded_reasons["duplicate_patient_id"] += 1
            continue
        seen_patient_ids.add(patient_id)

        for field_path, source_column in mapped_field_paths.items():
            if _normalize_scalar(source_row.get(source_column)) is None:
                mapped_source_missing_counts[field_path] += 1

        normalized = _normalize_row(
            source_row,
            config,
            invalid_counts,
            unmapped_counts,
        )
        normalized.update(
            {
                "patient_id": patient_id,
                "clinical_provenance_type": "observed_clinical",
                "clinical_source_name": config.source_name,
                "clinical_source_file": source_path.name,
                "clinical_source_sha256": source_sha256,
                "clinical_source_record_identifier": (
                    f"{source_path.name}:row:{source_row_number}"
                ),
            }
        )
        normalized_rows.append(normalized)

    missingness = _missingness(normalized_rows)
    output_directory.mkdir(parents=True, exist_ok=True)
    patients_path = output_directory / "patients.csv"
    data_quality_path = output_directory / "data_quality.json"
    field_mapping_path = output_directory / "field_mapping.json"

    _write_csv(patients_path, normalized_rows)
    quality_payload = {
        "schema_version": 1,
        "source": {
            "file_name": source_path.name,
            "format": suffix.removeprefix("."),
            "sha256": source_sha256,
            "sheet_name": table.sheet_name,
        },
        "total_source_records": total_source_records,
        "unique_patient_count": len(normalized_rows),
        "duplicate_identifiers": {
            "count": len(duplicate_patient_ids),
            "duplicate_record_count": excluded_reasons["duplicate_patient_id"],
        },
        "missingness_by_clinical_field": missingness,
        "missingness_by_mapped_source_field": {
            field_path: {
                "count": mapped_source_missing_counts[field_path],
                "percent": round(
                    (
                        mapped_source_missing_counts[field_path]
                        / len(normalized_rows)
                        * 100
                    )
                    if normalized_rows
                    else 0.0,
                    4,
                ),
                "source_column": source_column,
            }
            for field_path, source_column in sorted(mapped_field_paths.items())
        },
        "invalid_or_unmapped_values": {
            field: {
                "invalid_count": invalid_counts[field],
                "unmapped_count": unmapped_counts[field],
            }
            for field in CLINICAL_FIELDS
        },
        "excluded_records": {
            "count": sum(excluded_reasons.values()),
            "reasons": dict(sorted(excluded_reasons.items())),
        },
    }
    _write_json(data_quality_path, quality_payload)

    mapping_payload = {
        "schema_version": 1,
        "source_name": config.source_name,
        "source_file_name": source_path.name,
        "source_sha256": source_sha256,
        "source_sheet_name": table.sheet_name,
        "fields": config.fields.model_dump(mode="json"),
        "value_maps": config.value_maps,
        "mapped_clinical_fields": _mapped_clinical_fields(config.fields),
        "unmapped_source_columns": sorted(set(table.headers) - mapped_columns),
    }
    _write_json(field_mapping_path, mapping_payload)

    return IngestionResult(
        patients_path=patients_path,
        data_quality_path=data_quality_path,
        field_mapping_path=field_mapping_path,
        total_source_records=total_source_records,
        unique_patient_count=len(normalized_rows),
        excluded_record_count=sum(excluded_reasons.values()),
    )


def _read_source(path: Path, requested_sheet: str | None) -> _SourceTable:
    if path.suffix.lower() == ".csv":
        if requested_sheet is not None:
            raise IngestionError("sheet_name is only valid for .xlsx input")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = _validate_headers(reader.fieldnames)
            rows = tuple(
                (row_number, dict(row))
                for row_number, row in enumerate(reader, start=2)
            )
        return _SourceTable(headers=headers, rows=rows, sheet_name=None)

    workbook = load_workbook(path, read_only=True, data_only=True)
    if requested_sheet is not None and requested_sheet not in workbook.sheetnames:
        workbook.close()
        raise IngestionError(f"worksheet does not exist: {requested_sheet}")
    worksheet = workbook[requested_sheet] if requested_sheet else workbook.active
    try:
        row_iterator = worksheet.iter_rows(values_only=True)
        raw_headers = next(row_iterator)
        headers = _validate_headers(raw_headers)
        rows = tuple(
            (row_number, dict(zip(headers, values, strict=False)))
            for row_number, values in enumerate(row_iterator, start=2)
        )
    except StopIteration as exc:
        workbook.close()
        raise IngestionError("source file has no header row") from exc
    finally:
        workbook.close()
    return _SourceTable(
        headers=headers,
        rows=rows,
        sheet_name=worksheet.title,
    )


def _validate_headers(raw_headers: Iterable[Any] | None) -> tuple[str, ...]:
    if raw_headers is None:
        raise IngestionError("source file has no header row")
    headers = tuple(str(value) if value is not None else "" for value in raw_headers)
    if not headers or any(not header.strip() for header in headers):
        raise IngestionError("source contains an empty column header")
    normalized_headers = tuple(header.strip() for header in headers)
    duplicates = [
        name for name, count in Counter(normalized_headers).items() if count > 1
    ]
    if duplicates:
        raise IngestionError("source contains duplicate column headers")
    return headers


def _mapped_source_columns(fields: FieldMapping) -> set[str]:
    payload = fields.model_dump()
    columns: set[str] = set()
    for value in payload.values():
        if isinstance(value, str):
            columns.add(value)
        elif isinstance(value, dict):
            columns.update(value.values())
    return columns


def _mapped_clinical_fields(fields: FieldMapping) -> list[str]:
    payload = fields.model_dump()
    return [
        name
        for name in CLINICAL_FIELDS
        if payload[name]
    ]


def _mapped_clinical_field_paths(fields: FieldMapping) -> dict[str, str]:
    payload = fields.model_dump()
    paths: dict[str, str] = {}
    for field in CLINICAL_FIELDS:
        value = payload[field]
        if isinstance(value, str):
            paths[field] = value
        elif isinstance(value, dict):
            paths.update(
                {f"{field}.{component}": column for component, column in value.items()}
            )
    return paths


def _normalize_row(
    source_row: Mapping[str, Any],
    config: IngestionConfig,
    invalid_counts: Counter[str],
    unmapped_counts: Counter[str],
) -> dict[str, str]:
    result = {field: "" for field in CLINICAL_FIELDS}
    fields = config.fields
    for field in ("disease_site", "subsite", "hpv_status"):
        source_column = getattr(fields, field)
        if source_column is None:
            continue
        value = _normalize_scalar(source_row.get(source_column))
        result[field] = _apply_value_map(
            field,
            value,
            config.value_maps,
            unmapped_counts,
        )

    for field in ("cancer_stage", "systemic_therapy"):
        mapping = getattr(fields, field)
        if isinstance(mapping, str):
            value = _normalize_scalar(source_row.get(mapping))
            result[field] = _apply_value_map(
                field,
                value,
                config.value_maps,
                unmapped_counts,
            )
        elif isinstance(mapping, dict):
            result[field] = _normalize_structured_field(source_row, mapping)

    if fields.age is not None:
        age, is_invalid = _normalize_age(source_row.get(fields.age))
        result["age"] = age
        if is_invalid:
            invalid_counts["age"] += 1

    result["radiation_treatment_characteristics"] = _normalize_structured_field(
        source_row,
        fields.radiation_treatment_characteristics,
    )
    return result


def _normalize_structured_field(
    source_row: Mapping[str, Any],
    mapping: Mapping[str, str],
) -> str:
    values = {
        name: value
        for name, column in mapping.items()
        if (value := _normalize_scalar(source_row.get(column))) is not None
    }
    if not values:
        return ""
    return json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _apply_value_map(
    field: str,
    value: str | None,
    value_maps: Mapping[str, Mapping[str, str]],
    unmapped_counts: Counter[str],
) -> str:
    if value is None:
        return ""
    mapping = value_maps.get(field)
    if mapping is None:
        return value
    if value not in mapping:
        unmapped_counts[field] += 1
        return value
    return mapping[value]


def _normalize_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return str(int(value))
    text = str(value).strip()
    return text or None


def _normalize_age(value: Any) -> tuple[str, bool]:
    text = _normalize_scalar(value)
    if text is None:
        return "", False
    try:
        number = Decimal(text)
    except InvalidOperation:
        return "", True
    if not number.is_finite() or number < 0 or number > 130:
        return "", True
    normalized = format(number.normalize(), "f")
    return normalized, False


def _missingness(rows: list[dict[str, str]]) -> dict[str, dict[str, int | float]]:
    total = len(rows)
    result: dict[str, dict[str, int | float]] = {}
    for field in CLINICAL_FIELDS:
        count = sum(not row[field] for row in rows)
        percent = round((count / total * 100) if total else 0.0, 4)
        result[field] = {"count": count, "percent": percent}
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
