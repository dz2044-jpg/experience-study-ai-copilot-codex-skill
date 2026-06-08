"""Tabular input, profiling, and schema inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from experience_study.artifacts import (
    MethodologyEvent,
    WorkflowContext,
    append_methodology_event,
    source_artifact,
    upsert_artifact_entry,
)
from experience_study.contracts import REQUIRED_NUMERIC_COLUMNS, SUPPORTED_INPUT_SUFFIXES

DEFAULT_ISSUE_AGE_BAND_COUNT = 4
ISSUE_AGE_BAND_COLUMN = "Issue_Age_Band"


def read_tabular_input(path: str | Path) -> pd.DataFrame:
    """Read supported CSV or Parquet input and coerce core numeric columns."""

    input_path = Path(path)
    suffix = input_path.suffix.lower()
    if suffix not in SUPPORTED_INPUT_SUFFIXES:
        raise ValueError(
            f"Unsupported file type: {suffix or '<none>'}. Supported formats: {sorted(SUPPORTED_INPUT_SUFFIXES)}"
        )
    if suffix == ".csv":
        df = pd.read_csv(input_path)
    else:
        df = pd.read_parquet(input_path)

    for column in REQUIRED_NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").astype("float64")
    if "Policy_Number" in df.columns:
        df["Policy_Number"] = df["Policy_Number"].astype(str)
    return df


def read_tabular_input_as_strings(path: str | Path) -> pd.DataFrame:
    """Read input as strings for raw parse validation."""

    input_path = Path(path)
    suffix = input_path.suffix.lower()
    if suffix not in SUPPORTED_INPUT_SUFFIXES:
        raise ValueError(
            f"Unsupported file type: {suffix or '<none>'}. Supported formats: {sorted(SUPPORTED_INPUT_SUFFIXES)}"
        )
    if suffix == ".csv":
        return pd.read_csv(input_path, dtype=str, keep_default_na=False)
    return pd.read_parquet(input_path).fillna("").astype(str)


def classify_feature_type(df: pd.DataFrame, column: str) -> str:
    """Classify a column as numerical or categorical for profile metadata."""

    if column in REQUIRED_NUMERIC_COLUMNS or column in {"Face_Amount", "Issue_Age", "Age"}:
        return "numerical"
    series = df[column]
    if pd.api.types.is_numeric_dtype(series):
        return "numerical" if series.nunique(dropna=True) > 20 else "categorical"
    return "categorical"


def _format_band_edge(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def build_equal_width_band(
    series: pd.Series,
    *,
    band_count: int = DEFAULT_ISSUE_AGE_BAND_COUNT,
) -> pd.Series:
    """Return deterministic equal-width numeric bands for a source series.

    Args:
        series: Numeric source values to band.
        band_count: Number of equal-width bands to create.

    Returns:
        A string series containing interval labels, with missing values labeled
        separately.

    Raises:
        ValueError: If `band_count` is less than one.
    """

    if band_count < 1:
        raise ValueError("band_count must be at least 1.")

    numeric = pd.to_numeric(series, errors="coerce")
    non_null = numeric.dropna()
    if non_null.empty:
        return pd.Series(["Missing"] * len(series), index=series.index, dtype="string")

    minimum = float(non_null.min())
    maximum = float(non_null.max())
    if minimum == maximum:
        label = f"{_format_band_edge(minimum)} to {_format_band_edge(maximum)}"
        return pd.Series(
            [label if pd.notna(value) else "Missing" for value in numeric],
            index=series.index,
            dtype="string",
        )

    width = (maximum - minimum) / band_count
    edges = [minimum + (width * index) for index in range(band_count)] + [maximum]
    labels = [
        f"{_format_band_edge(edges[index])} to {_format_band_edge(edges[index + 1])}"
        for index in range(band_count)
    ]
    banded = pd.cut(
        numeric,
        bins=edges,
        labels=labels,
        include_lowest=True,
        duplicates="raise",
    )
    return banded.astype("string").fillna("Missing")


def add_default_derived_dimensions(df: pd.DataFrame) -> pd.DataFrame:
    """Add deterministic derived cohort dimensions used by the A/E workflow."""

    prepared = df.copy()
    if "Issue_Age" in prepared.columns and ISSUE_AGE_BAND_COLUMN not in prepared.columns:
        prepared[ISSUE_AGE_BAND_COLUMN] = build_equal_width_band(prepared["Issue_Age"])
    return prepared


def profile_dataset(context: WorkflowContext, data_path: str | Path) -> dict[str, Any]:
    """Profile a source dataset and save the prepared Parquet artifact."""

    source_path = Path(data_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"File not found: {data_path}")
    df = add_default_derived_dimensions(read_tabular_input(source_path))
    context.ensure_dirs()
    prepared_path = context.default_prepared_path
    df.to_parquet(prepared_path, engine="pyarrow", index=False)

    context.source_data_path = source_path
    context.prepared_data_path = prepared_path
    context.artifact_manifest_path = context.default_artifact_manifest_path
    context.methodology_log_path = context.default_methodology_log_path

    data = {
        "total_rows": len(df),
        "columns": list(df.columns),
        "data_types": {column: str(dtype) for column, dtype in df.dtypes.items()},
        "feature_classification": {
            column: classify_feature_type(df, column) for column in df.columns
        },
        "unique_policy_count": (
            int(df["Policy_Number"].nunique()) if "Policy_Number" in df.columns else 0
        ),
        "null_counts": {column: int(df[column].isna().sum()) for column in df.columns},
    }

    append_methodology_event(
        context.default_methodology_log_path,
        MethodologyEvent(
            step_name="Source dataset profiled",
            tool_name="profile",
            input_path=str(source_path),
            output_path=str(prepared_path),
            parameters={"data_path": str(source_path)},
        ),
    )
    upsert_artifact_entry(
        context.default_artifact_manifest_path,
        artifact_type="source_dataset",
        path=source_path,
        generating_tool="profile",
        parameters={"data_path": str(source_path)},
    )
    upsert_artifact_entry(
        context.default_artifact_manifest_path,
        artifact_type="prepared_dataset",
        path=prepared_path,
        generating_tool="profile",
        parameters={"data_path": str(source_path)},
        source_artifacts=source_artifact("source_dataset", source_path),
    )
    context.write()
    return {
        "ok": True,
        "kind": "profile",
        "message": f"Profiled `{source_path}` and saved `{prepared_path}`.",
        "artifacts": {
            "source_data_path": str(source_path),
            "prepared_data_path": str(prepared_path),
        },
        "data": data,
    }


def inspect_schema(context: WorkflowContext, data_path: str | Path | None = None) -> dict[str, Any]:
    """Inspect ordered columns and data types."""

    source_path = Path(data_path).expanduser().resolve() if data_path else context.prepared_data_path
    if source_path is None or not source_path.exists():
        raise FileNotFoundError("No dataset is available. Profile a dataset first or provide --data-path.")
    df = read_tabular_input(source_path)
    data = {
        "source_path": str(source_path),
        "columns": list(df.columns),
        "column_count": len(df.columns),
        "data_types": {column: str(dtype) for column, dtype in df.dtypes.items()},
    }
    context.artifact_manifest_path = context.artifact_manifest_path or context.default_artifact_manifest_path
    context.methodology_log_path = context.methodology_log_path or context.default_methodology_log_path
    append_methodology_event(
        context.default_methodology_log_path,
        MethodologyEvent(
            step_name="Schema inspected",
            tool_name="schema",
            input_path=str(source_path),
            output_path=None,
            parameters={},
        ),
    )
    context.write()
    return {
        "ok": True,
        "kind": "schema",
        "message": f"Inspected schema for `{source_path}`.",
        "artifacts": {},
        "data": data,
    }
