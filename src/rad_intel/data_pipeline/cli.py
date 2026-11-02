"""Command-line entry point for explicit clinical-file ingestion."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from rad_intel.data_pipeline.ingestion import (
    IngestionError,
    ingest_clinical_data,
    load_config,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize an explicitly mapped local RADCURE CSV or XLSX file."
    )
    parser.add_argument("--input", required=True, type=Path, help="Source CSV or XLSX")
    parser.add_argument(
        "--mapping",
        required=True,
        type=Path,
        help="Explicit JSON source-column mapping",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory for the three generated artifacts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.mapping)
        result = ingest_clinical_data(args.input, args.output, config)
    except (IngestionError, ValidationError) as exc:
        build_parser().exit(2, f"ingestion failed: {exc}\n")

    print("Clinical ingestion completed.")
    print(f"Source records: {result.total_source_records}")
    print(f"Unique patients written: {result.unique_patient_count}")
    print(f"Excluded records: {result.excluded_record_count}")
    print(f"Output directory: {args.output.resolve()}")
    return 0
