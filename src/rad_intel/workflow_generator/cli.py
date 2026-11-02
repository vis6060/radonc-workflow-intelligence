"""Command-line entry point for synthetic M2 workflow generation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from rad_intel.workflow_generator.generator import (
    GenerationError,
    GeneratorConfig,
    generate_workflows,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate deterministic synthetic radiation-oncology workflow histories."
        )
    )
    parser.add_argument(
        "--patients",
        required=True,
        type=Path,
        help="Normalized M1 patients.csv",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory for synthetic workflow artifacts",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic random seed (default: 42)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = generate_workflows(
            args.patients,
            args.output,
            GeneratorConfig(seed=args.seed),
        )
    except (GenerationError, ValidationError) as exc:
        build_parser().exit(2, f"workflow generation failed: {exc}\n")

    print("Synthetic workflow generation completed.")
    print(f"Patient histories: {result.patient_count}")
    print(f"Workflow events: {result.total_event_count}")
    print(f"Output directory: {args.output.resolve()}")
    return 0
