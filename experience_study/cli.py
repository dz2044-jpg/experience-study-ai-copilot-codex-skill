"""Argparse CLI for deterministic Experience Study A/E workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from experience_study.analysis import parse_filters, run_ae_analysis
from experience_study.artifacts import WorkflowContext, load_context
from experience_study.contracts import MAX_TOP_N, VALID_MEASURES, VALID_SORT_COLUMNS
from experience_study.feature_engineering import (
    DEFAULT_UNMAPPED_VALUE,
    VALID_BAND_STRATEGIES,
    run_band,
    run_regroup,
)
from experience_study.io import inspect_schema, profile_dataset
from experience_study.packet import build_ai_packet
from experience_study.validation import run_validation


def _add_output_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", required=True, help="Workflow output directory.")


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""

    parser = argparse.ArgumentParser(
        prog="experience-study",
        description="Deterministic Experience Study A/E workflow CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile = subparsers.add_parser("profile", help="Profile a CSV or Parquet dataset.")
    profile.add_argument("data_path")
    _add_output_dir(profile)

    schema = subparsers.add_parser("schema", help="Inspect dataset schema.")
    _add_output_dir(schema)
    schema.add_argument("--data-path")

    validate = subparsers.add_parser("validate", help="Run actuarial validation checks.")
    _add_output_dir(validate)
    validate.add_argument("--data-path")

    band = subparsers.add_parser("band", help="Create a categorical band column.")
    _add_output_dir(band)
    band.add_argument("--source-column", required=True)
    band.add_argument("--new-column", required=True)
    band.add_argument("--strategy", choices=sorted(VALID_BAND_STRATEGIES), required=True)
    band.add_argument("--bins", type=int)
    band.add_argument("--custom-bins")
    band.add_argument("--labels")
    band.add_argument("--overwrite", action="store_true")

    regroup = subparsers.add_parser("regroup", help="Create a regrouped categorical column.")
    _add_output_dir(regroup)
    regroup.add_argument("--source-column", required=True)
    regroup.add_argument("--new-column", required=True)
    regroup.add_argument("--mapping-json", required=True)
    regroup.add_argument("--unmapped-value", default=DEFAULT_UNMAPPED_VALUE)
    regroup.add_argument("--keep-unmapped", action="store_true")
    regroup.add_argument("--overwrite", action="store_true")

    ae = subparsers.add_parser("ae", help="Run grouped cohort A/E analysis.")
    _add_output_dir(ae)
    ae.add_argument("--measure", choices=sorted(VALID_MEASURES), default="both")
    ae.add_argument("--group-by", nargs="+", required=True)
    ae.add_argument("--filters-json")
    ae.add_argument("--min-claims", type=int, default=0)
    ae.add_argument("--top-n", type=int, default=MAX_TOP_N)
    ae.add_argument("--sort-by", choices=sorted(VALID_SORT_COLUMNS))

    packet = subparsers.add_parser("packet", help="Build sanitized aggregate AI A/E packet.")
    _add_output_dir(packet)
    packet.add_argument("--ae-path")
    packet.add_argument("--top-n", type=int, default=MAX_TOP_N)
    packet.add_argument("--masking-min-claims", type=int)

    doctor = subparsers.add_parser("doctor", help="Inspect workflow artifact readiness.")
    _add_output_dir(doctor)

    run = subparsers.add_parser("run", help="Profile, validate, run A/E, and build packet.")
    run.add_argument("data_path")
    _add_output_dir(run)
    run.add_argument("--ae-by", nargs="+", action="append", default=[])
    run.add_argument("--measure", choices=sorted(VALID_MEASURES), default="both")
    run.add_argument("--filters-json")
    run.add_argument("--min-claims", type=int, default=0)
    run.add_argument("--top-n", type=int, default=MAX_TOP_N)

    return parser


def _format_number(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{numeric:.2f}"


def _escape_table_cell(value: Any) -> str:
    return str(value).replace("\n", "<br>").replace("|", r"\|")


def _print_ae_summary(result: dict[str, Any]) -> None:
    print(result["message"])
    rows = result.get("data", {}).get("results") or []
    if not rows:
        print("No cohorts met the requested criteria.")
        return
    print("")
    print("Summary of A/E Results")
    print("| Cohort Dimension | Actual Deaths (MAC) | Expected (MEC) | A/E Ratio (Count) | A/E Ratio (Amount) |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for row in rows:
        print(
            "| "
            + " | ".join(
                [
                    _escape_table_cell(row.get("Dimensions", "")),
                    _format_number(row.get("Sum_MAC")),
                    _format_number(row.get("Sum_MEC")),
                    _format_number(row.get("AE_Ratio_Count")),
                    _format_number(row.get("AE_Ratio_Amount")),
                ]
            )
            + " |"
        )


def _print_result(result: dict[str, Any]) -> None:
    if result.get("kind") == "ae":
        _print_ae_summary(result)
        return
    print(result["message"])
    if result.get("kind") == "schema":
        data = result["data"]
        print(f"Columns in `{data['source_path']}` ({data['column_count']}):")
        for column in data["columns"]:
            print(f"- {column}: {data['data_types'].get(column, 'unknown')}")
    elif result.get("kind") == "validation":
        issues = result.get("data", {}).get("issues", [])
        if issues:
            print("Issues:")
            for issue in issues:
                print(f"- {issue}")


def _error(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _load(output_dir: str) -> WorkflowContext:
    return load_context(Path(output_dir))


def _doctor_payload(context: WorkflowContext) -> dict[str, Any]:
    return {
        "output_dir": str(context.output_dir),
        "context_path": str(context.context_path),
        "paths": context.to_json_dict(),
        "readiness": context.readiness(),
        "latest_ae_paths_by_way": {
            f"{way}way": str(path) for way, path in sorted(context.latest_ae_paths_by_way.items())
        },
        "missing_prerequisites": _missing_prerequisites(context),
    }


def _missing_prerequisites(context: WorkflowContext) -> list[str]:
    missing: list[str] = []
    if not (context.prepared_data_path and context.prepared_data_path.exists()):
        missing.append("prepared dataset")
    if not (context.latest_ae_path and context.latest_ae_path.exists()):
        missing.append("latest A/E summary")
    if not (context.latest_packet_path and context.latest_packet_path.exists()):
        missing.append("sanitized AI A/E packet")
    return missing


def run_command(args: argparse.Namespace) -> int:
    """Execute a parsed CLI command."""

    context = _load(args.output_dir)
    try:
        if args.command == "profile":
            _print_result(profile_dataset(context, args.data_path))
            return 0
        if args.command == "schema":
            _print_result(inspect_schema(context, args.data_path))
            return 0
        if args.command == "validate":
            _print_result(run_validation(context, args.data_path))
            return 0
        if args.command == "band":
            _print_result(
                run_band(
                    context,
                    source_column=args.source_column,
                    new_column=args.new_column,
                    strategy=args.strategy,
                    bins=args.bins,
                    custom_bins_json=args.custom_bins,
                    labels_json=args.labels,
                    overwrite=args.overwrite,
                )
            )
            return 0
        if args.command == "regroup":
            _print_result(
                run_regroup(
                    context,
                    source_column=args.source_column,
                    new_column=args.new_column,
                    mapping_json=args.mapping_json,
                    unmapped_value=args.unmapped_value,
                    keep_unmapped=args.keep_unmapped,
                    overwrite=args.overwrite,
                )
            )
            return 0
        if args.command == "ae":
            filters = parse_filters(args.filters_json)
            _print_result(
                run_ae_analysis(
                    context,
                    measure=args.measure,
                    group_by=args.group_by,
                    filters=filters,
                    min_claims=args.min_claims,
                    top_n=args.top_n,
                    sort_by=args.sort_by,
                )
            )
            return 0
        if args.command == "packet":
            _print_result(
                build_ai_packet(
                    context,
                    ae_path=args.ae_path,
                    top_n=args.top_n,
                    masking_min_claims=args.masking_min_claims,
                )
            )
            return 0
        if args.command == "doctor":
            print(json.dumps(_doctor_payload(context), indent=2, sort_keys=True))
            return 0
        if args.command == "run":
            if not args.ae_by:
                return _error("At least one --ae-by grouping is required.")
            _print_result(profile_dataset(context, args.data_path))
            validation_result = run_validation(context)
            _print_result(validation_result)
            if validation_result["data"]["status"] == "FAIL":
                return _error("Validation failed; stopping before A/E analysis.")
            filters = parse_filters(args.filters_json)
            last_ae_result: dict[str, Any] | None = None
            for group_by in args.ae_by:
                last_ae_result = run_ae_analysis(
                    context,
                    measure=args.measure,
                    group_by=group_by,
                    filters=filters,
                    min_claims=args.min_claims,
                    top_n=args.top_n,
                )
                _print_result(last_ae_result)
            assert last_ae_result is not None
            _print_result(build_ai_packet(context, top_n=args.top_n))
            return 0
    except (FileNotFoundError, KeyError, ValueError, OSError) as exc:
        return _error(str(exc))
    return _error(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
