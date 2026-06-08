"""Grouped cohort A/E analysis."""

from __future__ import annotations

from pathlib import Path
import math
from typing import Any, Callable

import pandas as pd

from experience_study.ae_math import compute_ae_ci, compute_ae_ci_amount
from experience_study.artifacts import (
    MethodologyEvent,
    WorkflowContext,
    append_methodology_event,
    build_state_fingerprint,
    file_sha256,
    source_artifact,
    update_manifest_fingerprint,
    upsert_artifact_entry,
)
from experience_study.contracts import (
    AE_SUMMARY_COLUMNS,
    EXCLUDED_DIMENSIONS,
    MAX_TOP_N,
    REQUIRED_NUMERIC_COLUMNS,
    SEMANTIC_NUMERIC_NON_DIMENSIONS,
    VALID_MEASURES,
    VALID_SORT_COLUMNS,
)
from experience_study.io import read_tabular_input


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric) or not math.isfinite(numeric):
        return None
    return numeric


def _positive_denominator(value: Any) -> float | None:
    numeric = _finite_float(value)
    if numeric is None or numeric <= 0:
        return None
    return numeric


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    numerator_value = _finite_float(numerator)
    denominator_value = _positive_denominator(denominator)
    if numerator_value is None or denominator_value is None:
        return None
    return numerator_value / denominator_value


def parse_filters(filters_json: str | None) -> list[dict[str, Any]]:
    """Parse filter JSON into normalized filter specs."""

    if not filters_json:
        return []
    import json

    payload = json.loads(filters_json)
    if not isinstance(payload, list):
        raise ValueError("--filters-json must be a JSON list.")
    filters: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each filter must be a JSON object.")
        column = item.get("column")
        operator = item.get("op", item.get("operator"))
        if column is None or operator is None or "value" not in item:
            raise ValueError("Each filter requires column, op/operator, and value.")
        filters.append({"column": str(column), "operator": _normalize_operator(str(operator)), "value": item["value"]})
    return filters


def _normalize_operator(operator: str) -> str:
    mapping = {"==": "=", "=": "=", "!=": "!=", ">": ">", ">=": ">=", "<": "<", "<=": "<="}
    if operator not in mapping:
        raise ValueError(f"Unsupported filter operator: {operator}")
    return mapping[operator]


def apply_filters(df: pd.DataFrame, filters: list[dict[str, Any]]) -> pd.DataFrame:
    """Apply scalar filters before aggregation."""

    filtered = df
    operator_map: dict[str, Callable[[pd.Series, Any], pd.Series]] = {
        "=": lambda series, value: series == value,
        "!=": lambda series, value: series != value,
        ">": lambda series, value: series > value,
        ">=": lambda series, value: series >= value,
        "<": lambda series, value: series < value,
        "<=": lambda series, value: series <= value,
    }
    for filter_spec in filters:
        column = filter_spec["column"]
        if column not in filtered.columns:
            raise KeyError(column)
        filtered = filtered[operator_map[filter_spec["operator"]](filtered[column], filter_spec["value"])]
    return filtered


def validate_group_by(df: pd.DataFrame, group_by: list[str]) -> None:
    """Validate grouping dimensions for MVP A/E analysis."""

    if not 1 <= len(group_by) <= 2:
        raise ValueError("MVP A/E analysis supports one or two grouping columns.")
    missing = [column for column in group_by if column not in df.columns]
    if missing:
        raise KeyError(missing[0])
    invalid = [
        column
        for column in group_by
        if column in EXCLUDED_DIMENSIONS or column in SEMANTIC_NUMERIC_NON_DIMENSIONS
    ]
    if invalid:
        raise ValueError(f"Column `{invalid[0]}` is not eligible as an A/E grouping dimension.")


def default_sort_by(measure: str) -> str:
    if measure == "count":
        return "AE_Ratio_Count"
    return "AE_Ratio_Amount"


def run_ae_analysis(
    context: WorkflowContext,
    *,
    measure: str,
    group_by: list[str],
    filters: list[dict[str, Any]] | None = None,
    min_claims: int = 0,
    top_n: int = MAX_TOP_N,
    sort_by: str | None = None,
    data_path: str | Path | None = None,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Run deterministic grouped cohort A/E analysis."""

    if measure not in VALID_MEASURES:
        raise ValueError(f"measure must be one of {sorted(VALID_MEASURES)}.")
    resolved_sort_by = sort_by or default_sort_by(measure)
    if resolved_sort_by not in VALID_SORT_COLUMNS:
        raise ValueError(f"sort_by must be one of {sorted(VALID_SORT_COLUMNS)}.")
    source_path = Path(data_path).expanduser().resolve() if data_path else context.prepared_data_path
    if source_path is None or not source_path.exists():
        raise FileNotFoundError("No prepared dataset exists. Profile a dataset first.")

    df = read_tabular_input(source_path)
    missing_core = [column for column in REQUIRED_NUMERIC_COLUMNS if column not in df.columns]
    if missing_core:
        raise ValueError(f"Prepared dataset is missing required columns: {missing_core}.")
    validate_group_by(df, group_by)

    filters = filters or []
    try:
        filtered_df = apply_filters(df, filters)
    except KeyError as exc:
        missing_column = str(exc).strip("'")
        raise KeyError(f"Column `{missing_column}` was not found in the prepared dataset.") from exc

    grouped = (
        filtered_df.groupby(group_by, dropna=False)
        .agg(
            Sum_MAC=("MAC", "sum"),
            Sum_MOC=("MOC", "sum"),
            Sum_MEC=("MEC", "sum"),
            Sum_MAF=("MAF", "sum"),
            Sum_MEF=("MEF", "sum"),
        )
        .reset_index()
    )
    grouped = grouped[grouped["Sum_MAC"] >= min_claims]

    rows: list[dict[str, Any]] = []
    for _, row in grouped.iterrows():
        count_ratio = _safe_ratio(row["Sum_MAC"], row["Sum_MEC"])
        amount_ratio = _safe_ratio(row["Sum_MAF"], row["Sum_MEF"])
        count_ci = (
            compute_ae_ci(row["Sum_MAC"], row["Sum_MOC"], row["Sum_MEC"], confidence_level)
            if _positive_denominator(row["Sum_MEC"]) is not None
            else (None, None)
        )
        amount_ci = (
            compute_ae_ci_amount(
                row["Sum_MAC"],
                row["Sum_MOC"],
                row["Sum_MEC"],
                row["Sum_MAF"],
                row["Sum_MEF"],
                confidence_level,
            )
            if _positive_denominator(row["Sum_MEF"]) is not None
            else (None, None)
        )
        rows.append(
            {
                "Dimensions": " | ".join(f"{column}={row[column]}" for column in group_by),
                "Sum_MAC": int(row["Sum_MAC"]),
                "Sum_MOC": float(row["Sum_MOC"]),
                "Sum_MEC": float(row["Sum_MEC"]),
                "Sum_MAF": float(row["Sum_MAF"]),
                "Sum_MEF": float(row["Sum_MEF"]),
                "AE_Ratio_Count": _finite_float(count_ratio),
                "AE_Ratio_Amount": _finite_float(amount_ratio),
                "AE_Count_CI_Lower": _finite_float(count_ci[0]),
                "AE_Count_CI_Upper": _finite_float(count_ci[1]),
                "AE_Amount_CI_Lower": _finite_float(amount_ci[0]),
                "AE_Amount_CI_Upper": _finite_float(amount_ci[1]),
            }
        )

    result_df = pd.DataFrame(rows, columns=AE_SUMMARY_COLUMNS)
    if not result_df.empty:
        result_df = result_df.sort_values(resolved_sort_by, ascending=False, na_position="last")

    context.ensure_dirs()
    way = len(group_by)
    scenario_path = context.ae_summary_path(group_by)
    latest_path = context.latest_ae_alias_path
    latest_way_path = context.latest_way_path(way)
    result_df.to_csv(scenario_path, index=False)
    result_df.to_csv(latest_path, index=False)
    result_df.to_csv(latest_way_path, index=False)

    parameters = {
        "measure": measure,
        "group_by": group_by,
        "filters": filters,
        "min_claims": min_claims,
        "top_n": min(max(1, top_n), MAX_TOP_N),
        "sort_by": resolved_sort_by,
        "way": way,
    }
    context.latest_ae_path = latest_path
    context.latest_ae_paths_by_way[way] = latest_way_path
    context.artifact_manifest_path = context.default_artifact_manifest_path
    context.methodology_log_path = context.default_methodology_log_path

    append_methodology_event(
        context.default_methodology_log_path,
        MethodologyEvent(
            step_name="Grouped A/E analysis run",
            tool_name="ae",
            input_path=str(source_path),
            output_path=str(latest_path),
            parameters=parameters,
        ),
    )
    prepared_source = source_artifact("prepared_dataset", source_path)
    upsert_artifact_entry(
        context.default_artifact_manifest_path,
        artifact_type="ae_summary",
        path=scenario_path,
        generating_tool="ae",
        parameters=parameters,
        source_artifacts=prepared_source,
    )
    upsert_artifact_entry(
        context.default_artifact_manifest_path,
        artifact_type="latest_ae_summary",
        path=latest_path,
        generating_tool="ae",
        parameters=parameters,
        source_artifacts=prepared_source,
    )
    upsert_artifact_entry(
        context.default_artifact_manifest_path,
        artifact_type="latest_ae_summary_by_way",
        path=latest_way_path,
        generating_tool="ae",
        parameters=parameters,
        source_artifacts=prepared_source,
    )
    source_hashes = {
        "prepared_data_path": file_sha256(source_path) if source_path.exists() else None,
        "latest_ae_path": file_sha256(latest_path) if latest_path.exists() else None,
    }
    fingerprint, fingerprint_inputs = build_state_fingerprint(
        source_hashes=source_hashes,
        group_by=group_by,
        filters=filters,
        measure=measure,
        min_claims=min_claims,
        sort_by=resolved_sort_by,
    )
    context.state_fingerprint = fingerprint
    update_manifest_fingerprint(
        context.default_artifact_manifest_path,
        fingerprint=fingerprint,
        fingerprint_inputs=fingerprint_inputs,
    )
    context.write()

    top_results = result_df.head(min(max(1, top_n), MAX_TOP_N))
    safe_results = top_results.replace([float("inf"), float("-inf")], pd.NA)
    safe_results = safe_results.astype(object).where(pd.notna(safe_results), None)
    return {
        "ok": True,
        "kind": "ae",
        "message": f"Completed grouped A/E analysis by {', '.join(group_by)} and saved `{latest_path}`.",
        "artifacts": {
            "ae_summary_path": str(scenario_path),
            "latest_ae_path": str(latest_path),
            "latest_way_path": str(latest_way_path),
        },
        "data": {
            "results": safe_results.to_dict(orient="records"),
            "row_count": len(result_df),
            "measure": measure,
            "group_by": group_by,
            "way": way,
        },
    }
