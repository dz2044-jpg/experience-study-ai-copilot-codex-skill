"""Deterministic feature engineering for Experience Study cohort dimensions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from experience_study.artifacts import (
    MethodologyEvent,
    WorkflowContext,
    append_methodology_event,
    file_sha256,
    read_artifact_manifest,
    source_artifact,
    upsert_artifact_entry,
    write_artifact_manifest,
)

MISSING_LABEL = "Missing"
OUT_OF_RANGE_LABEL = "Out of Range"
DEFAULT_UNMAPPED_VALUE = "Other"
VALID_BAND_STRATEGIES = {"custom", "equal-width", "quantile"}
_RAW_MISSING_TOKENS = {"", "na", "nan", "null", "none", "n/a"}


def format_band_edge(value: float) -> str:
    """Format a numeric band edge into a stable, readable label fragment."""

    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _missing_mask(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series.isna()
    strings = series.astype("string")
    return series.isna() | strings.str.strip().str.lower().isin(_RAW_MISSING_TOKENS)


def _coerce_numeric_source(series: pd.Series, *, column: str) -> pd.Series:
    missing = _missing_mask(series)
    numeric = pd.to_numeric(series.where(~missing), errors="coerce")
    invalid_count = int((~missing & numeric.isna()).sum())
    if invalid_count:
        raise ValueError(
            f"Column `{column}` must be numeric for banding; found {invalid_count} non-numeric value(s)."
        )
    return numeric.astype("float64")


def _validate_band_count(band_count: int) -> None:
    if band_count < 1:
        raise ValueError("--bins must be at least 1.")


def _validate_labels(labels: list[Any], expected_count: int) -> list[str]:
    if len(labels) != expected_count:
        raise ValueError(f"Expected {expected_count} label(s), received {len(labels)}.")
    normalized = [str(label) for label in labels]
    if any(not label for label in normalized):
        raise ValueError("Band labels must not be empty.")
    if len(set(normalized)) != len(normalized):
        raise ValueError("Band labels must be unique.")
    return normalized


def build_equal_width_band(
    series: pd.Series,
    *,
    band_count: int,
    source_column: str = "source",
) -> pd.Series:
    """Return deterministic equal-width bands for a numeric series.

    Args:
        series: Source values to band.
        band_count: Number of equal-width bands to create.
        source_column: Column name used in validation errors.

    Returns:
        String labels for each row, with missing values labeled `Missing`.

    Raises:
        ValueError: If the band count is invalid or non-missing values are not numeric.
    """

    _validate_band_count(band_count)
    numeric = _coerce_numeric_source(series, column=source_column)
    non_null = numeric.dropna()
    if non_null.empty:
        return pd.Series([MISSING_LABEL] * len(series), index=series.index, dtype="string")

    minimum = float(non_null.min())
    maximum = float(non_null.max())
    if minimum == maximum:
        label = f"{format_band_edge(minimum)} to {format_band_edge(maximum)}"
        return pd.Series(
            [label if pd.notna(value) else MISSING_LABEL for value in numeric],
            index=series.index,
            dtype="string",
        )

    width = (maximum - minimum) / band_count
    edges = [minimum + (width * index) for index in range(band_count)] + [maximum]
    labels = [
        f"{format_band_edge(edges[index])} to {format_band_edge(edges[index + 1])}"
        for index in range(band_count)
    ]
    banded = pd.cut(numeric, bins=edges, labels=labels, include_lowest=True, duplicates="raise")
    return banded.astype("string").fillna(MISSING_LABEL)


def build_quantile_band(
    series: pd.Series,
    *,
    band_count: int,
    source_column: str = "source",
) -> pd.Series:
    """Return deterministic equal-frequency bands for a numeric series."""

    _validate_band_count(band_count)
    numeric = _coerce_numeric_source(series, column=source_column)
    non_null = numeric.dropna()
    if non_null.empty:
        return pd.Series([MISSING_LABEL] * len(series), index=series.index, dtype="string")
    if band_count == 1:
        label = f"{format_band_edge(float(non_null.min()))} to {format_band_edge(float(non_null.max()))}"
        return pd.Series(
            [label if pd.notna(value) else MISSING_LABEL for value in numeric],
            index=series.index,
            dtype="string",
        )

    try:
        _, edges = pd.qcut(non_null, q=band_count, retbins=True, duplicates="raise")
    except ValueError as exc:
        raise ValueError(
            f"Column `{source_column}` does not have enough distinct numeric values for {band_count} quantile bins."
        ) from exc

    labels = [
        f"{format_band_edge(float(edges[index]))} to {format_band_edge(float(edges[index + 1]))}"
        for index in range(len(edges) - 1)
    ]
    banded = pd.cut(numeric, bins=edges, labels=labels, include_lowest=True, duplicates="raise")
    return banded.astype("string").fillna(MISSING_LABEL)


def _normalize_custom_bins(raw_bins: list[Any]) -> tuple[list[float], bool]:
    if len(raw_bins) < 2:
        raise ValueError("--custom-bins must contain at least two edges.")
    open_ended_upper = raw_bins[-1] is None
    if any(edge is None for edge in raw_bins[:-1]):
        raise ValueError("Only the final custom bin edge may be null for an open-ended upper bound.")

    numeric_edge_values = raw_bins[:-1] if open_ended_upper else raw_bins
    try:
        finite_edges = [float(edge) for edge in numeric_edge_values]
    except (TypeError, ValueError) as exc:
        raise ValueError("Custom bin edges must be numeric, except for a final null.") from exc
    if len(finite_edges) != len(set(finite_edges)):
        raise ValueError("Custom bin edges must be unique.")
    for previous, current in zip(finite_edges, finite_edges[1:]):
        if current <= previous:
            raise ValueError("Custom bin edges must be strictly increasing.")

    edges = finite_edges + ([float("inf")] if open_ended_upper else [])
    return edges, open_ended_upper


def build_custom_band(
    series: pd.Series,
    *,
    custom_bins: list[Any],
    labels: list[Any],
    source_column: str = "source",
) -> pd.Series:
    """Return deterministic custom bands for a numeric series."""

    edges, _ = _normalize_custom_bins(custom_bins)
    normalized_labels = _validate_labels(labels, expected_count=len(edges) - 1)
    numeric = _coerce_numeric_source(series, column=source_column)
    missing = numeric.isna()
    banded = pd.cut(
        numeric,
        bins=edges,
        labels=normalized_labels,
        include_lowest=True,
        duplicates="raise",
    )
    result = banded.astype("string")
    result = result.mask(missing, MISSING_LABEL)
    result = result.mask(~missing & result.isna(), OUT_OF_RANGE_LABEL)
    return result


def regroup_categorical(
    series: pd.Series,
    *,
    mapping: dict[str, list[Any]],
    source_column: str = "source",
    unmapped_value: str = DEFAULT_UNMAPPED_VALUE,
    keep_unmapped: bool = False,
) -> pd.Series:
    """Regroup a categorical series using a new-group to old-category mapping."""

    if pd.api.types.is_numeric_dtype(series):
        raise ValueError(f"Column `{source_column}` must be categorical for regrouping.")
    if not mapping:
        raise ValueError("--mapping-json must contain at least one group.")

    category_to_group: dict[str, str] = {}
    for group, categories in mapping.items():
        group_label = str(group)
        if not group_label:
            raise ValueError("Regroup target labels must not be empty.")
        if not isinstance(categories, list) or not categories:
            raise ValueError(f"Mapping for `{group_label}` must be a non-empty list.")
        for category in categories:
            category_label = str(category)
            if category_label in category_to_group:
                raise ValueError(f"Category `{category_label}` is assigned to more than one regroup label.")
            category_to_group[category_label] = group_label

    missing = _missing_mask(series)
    source_values = series.astype("string")
    result: list[str] = []
    for value, is_missing in zip(source_values, missing):
        if is_missing:
            result.append(MISSING_LABEL)
            continue
        value_label = str(value)
        mapped = category_to_group.get(value_label)
        if mapped is not None:
            result.append(mapped)
        elif keep_unmapped:
            result.append(value_label)
        else:
            result.append(str(unmapped_value))
    return pd.Series(result, index=series.index, dtype="string")


def _json_list(raw_value: str | None, *, argument_name: str) -> list[Any] | None:
    if raw_value is None:
        return None
    payload = json.loads(raw_value)
    if not isinstance(payload, list):
        raise ValueError(f"{argument_name} must be a JSON list.")
    return payload


def _json_mapping(raw_value: str) -> dict[str, list[Any]]:
    payload = json.loads(raw_value)
    if not isinstance(payload, dict):
        raise ValueError("--mapping-json must be a JSON object.")
    return {str(group): categories for group, categories in payload.items()}


def _prepared_data_path(context: WorkflowContext) -> Path:
    source_path = context.prepared_data_path
    if source_path is None or not source_path.exists():
        raise FileNotFoundError("No prepared dataset exists. Profile a dataset first.")
    return source_path


def _validate_feature_columns(
    df: pd.DataFrame,
    *,
    source_column: str,
    new_column: str,
    overwrite: bool,
) -> None:
    if source_column not in df.columns:
        raise KeyError(f"Column `{source_column}` was not found in the prepared dataset.")
    if new_column in df.columns and not overwrite:
        raise ValueError(f"Column `{new_column}` already exists. Use --overwrite to replace it.")


def _clear_stale_analysis_state(context: WorkflowContext) -> None:
    context.latest_ae_path = None
    context.latest_ae_paths_by_way = {}
    context.latest_packet_path = None
    context.state_fingerprint = None


def _clear_manifest_fingerprint(manifest_path: Path) -> None:
    payload = read_artifact_manifest(manifest_path)
    payload.pop("state_fingerprint", None)
    payload.pop("fingerprint_inputs", None)
    write_artifact_manifest(manifest_path, payload)


def _record_prepared_dataset_update(
    context: WorkflowContext,
    *,
    tool_name: str,
    step_name: str,
    prepared_path: Path,
    previous_content_hash: str,
    parameters: dict[str, Any],
) -> None:
    context.artifact_manifest_path = context.default_artifact_manifest_path
    context.methodology_log_path = context.default_methodology_log_path
    event_parameters = dict(parameters)
    event_parameters["previous_prepared_content_hash"] = previous_content_hash

    append_methodology_event(
        context.default_methodology_log_path,
        MethodologyEvent(
            step_name=step_name,
            tool_name=tool_name,
            input_path=str(prepared_path),
            output_path=str(prepared_path),
            parameters=event_parameters,
        ),
    )

    prior_prepared_source = {
        "artifact_type": "prepared_dataset_prior",
        "path": str(prepared_path),
        "content_hash": previous_content_hash,
    }
    upsert_artifact_entry(
        context.default_artifact_manifest_path,
        artifact_type="prepared_dataset",
        path=prepared_path,
        generating_tool=tool_name,
        parameters=event_parameters,
        source_artifacts=[
            *source_artifact("source_dataset", context.source_data_path),
            prior_prepared_source,
        ],
    )
    _clear_manifest_fingerprint(context.default_artifact_manifest_path)


def _feature_result(
    *,
    kind: str,
    message: str,
    prepared_path: Path,
    source_column: str,
    new_column: str,
    unique_values: list[str],
) -> dict[str, Any]:
    return {
        "ok": True,
        "kind": kind,
        "message": message,
        "artifacts": {"prepared_data_path": str(prepared_path)},
        "data": {
            "source_column": source_column,
            "new_column": new_column,
            "unique_values": unique_values,
        },
    }


def run_band(
    context: WorkflowContext,
    *,
    source_column: str,
    new_column: str,
    strategy: str,
    bins: int | None = None,
    custom_bins_json: str | None = None,
    labels_json: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create a deterministic categorical band column on the prepared dataset."""

    if strategy not in VALID_BAND_STRATEGIES:
        raise ValueError(f"strategy must be one of {sorted(VALID_BAND_STRATEGIES)}.")
    prepared_path = _prepared_data_path(context)
    df = pd.read_parquet(prepared_path)
    _validate_feature_columns(
        df,
        source_column=source_column,
        new_column=new_column,
        overwrite=overwrite,
    )

    if strategy in {"equal-width", "quantile"}:
        if bins is None:
            raise ValueError("--bins is required for equal-width and quantile banding.")
        if custom_bins_json is not None or labels_json is not None:
            raise ValueError("--custom-bins and --labels are only valid with --strategy custom.")
        engineered = (
            build_equal_width_band(df[source_column], band_count=bins, source_column=source_column)
            if strategy == "equal-width"
            else build_quantile_band(df[source_column], band_count=bins, source_column=source_column)
        )
        custom_bins = None
        labels = None
    else:
        if bins is not None:
            raise ValueError("--bins is not valid with --strategy custom.")
        custom_bins = _json_list(custom_bins_json, argument_name="--custom-bins")
        labels = _json_list(labels_json, argument_name="--labels")
        if custom_bins is None or labels is None:
            raise ValueError("--custom-bins and --labels are required for custom banding.")
        engineered = build_custom_band(
            df[source_column],
            custom_bins=custom_bins,
            labels=labels,
            source_column=source_column,
        )

    previous_content_hash = file_sha256(prepared_path)
    df[new_column] = engineered
    df.to_parquet(prepared_path, engine="pyarrow", index=False)
    context.prepared_data_path = prepared_path
    _clear_stale_analysis_state(context)

    parameters = {
        "source_column": source_column,
        "new_column": new_column,
        "strategy": strategy,
        "bins": bins,
        "custom_bins": custom_bins,
        "labels": labels,
        "overwrite": overwrite,
    }
    _record_prepared_dataset_update(
        context,
        tool_name="band",
        step_name="Feature engineering band created",
        prepared_path=prepared_path,
        previous_content_hash=previous_content_hash,
        parameters=parameters,
    )
    context.write()

    unique_values = sorted(str(value) for value in df[new_column].dropna().unique())
    return _feature_result(
        kind="band",
        message=f"Created `{new_column}` from `{source_column}` and updated `{prepared_path}`.",
        prepared_path=prepared_path,
        source_column=source_column,
        new_column=new_column,
        unique_values=unique_values,
    )


def run_regroup(
    context: WorkflowContext,
    *,
    source_column: str,
    new_column: str,
    mapping_json: str,
    unmapped_value: str = DEFAULT_UNMAPPED_VALUE,
    keep_unmapped: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create a deterministic regrouped categorical column on the prepared dataset."""

    prepared_path = _prepared_data_path(context)
    df = pd.read_parquet(prepared_path)
    _validate_feature_columns(
        df,
        source_column=source_column,
        new_column=new_column,
        overwrite=overwrite,
    )
    mapping = _json_mapping(mapping_json)
    engineered = regroup_categorical(
        df[source_column],
        mapping=mapping,
        source_column=source_column,
        unmapped_value=unmapped_value,
        keep_unmapped=keep_unmapped,
    )

    previous_content_hash = file_sha256(prepared_path)
    df[new_column] = engineered
    df.to_parquet(prepared_path, engine="pyarrow", index=False)
    context.prepared_data_path = prepared_path
    _clear_stale_analysis_state(context)

    parameters = {
        "source_column": source_column,
        "new_column": new_column,
        "mapping": mapping,
        "unmapped_value": unmapped_value,
        "keep_unmapped": keep_unmapped,
        "overwrite": overwrite,
    }
    _record_prepared_dataset_update(
        context,
        tool_name="regroup",
        step_name="Feature engineering regroup created",
        prepared_path=prepared_path,
        previous_content_hash=previous_content_hash,
        parameters=parameters,
    )
    context.write()

    unique_values = sorted(str(value) for value in df[new_column].dropna().unique())
    return _feature_result(
        kind="regroup",
        message=f"Created `{new_column}` from `{source_column}` and updated `{prepared_path}`.",
        prepared_path=prepared_path,
        source_column=source_column,
        new_column=new_column,
        unique_values=unique_values,
    )
