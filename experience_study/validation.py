"""Deterministic actuarial validation checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from experience_study.artifacts import MethodologyEvent, WorkflowContext, append_methodology_event
from experience_study.contracts import REQUIRED_NUMERIC_COLUMNS
from experience_study.io import classify_feature_type, read_tabular_input, read_tabular_input_as_strings

RAW_MISSING_TOKENS = {"", "na", "nan", "null", "none", "n/a"}


def _find_raw_non_numeric_values(data_path: str | Path) -> list[str]:
    raw_df = read_tabular_input_as_strings(data_path)
    issues: list[str] = []
    for column in REQUIRED_NUMERIC_COLUMNS:
        if column not in raw_df.columns:
            continue
        raw_values = raw_df[column].fillna("").astype(str).str.strip()
        missing_mask = raw_values.str.lower().isin(RAW_MISSING_TOKENS)
        parsed_values = pd.to_numeric(raw_values.where(~missing_mask, pd.NA), errors="coerce")
        invalid_count = int((~missing_mask & parsed_values.isna()).sum())
        if invalid_count:
            issues.append(
                f"{column} contains {invalid_count} non-numeric raw value(s) that cannot be parsed."
            )
    return issues


def run_validation(context: WorkflowContext, data_path: str | Path | None = None) -> dict[str, Any]:
    """Run deterministic actuarial data checks."""

    source_path = Path(data_path).expanduser().resolve() if data_path else context.prepared_data_path
    if source_path is None or not source_path.exists():
        raise FileNotFoundError("No dataset is available. Profile a dataset first or provide --data-path.")

    issues = _find_raw_non_numeric_values(source_path)
    df = read_tabular_input(source_path)
    missing_core_columns = [column for column in REQUIRED_NUMERIC_COLUMNS if column not in df.columns]
    issues.extend(f"Missing required actuarial column: {column}." for column in missing_core_columns)

    for column in REQUIRED_NUMERIC_COLUMNS:
        if column in df.columns and not pd.api.types.is_numeric_dtype(df[column]):
            issues.append(f"{column} must be numeric.")

    for column in ("Duration", "Issue_Age", "Age", "Face_Amount", "Study_Year"):
        if column not in df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(df[column]):
            issues.append(f"{column} must be numeric.")
            continue
        non_null = df[column].dropna()
        if column != "Face_Amount" and not (non_null == non_null.astype(int)).all():
            issues.append(f"{column} must contain integer values.")

    if "MAC" in df.columns:
        invalid_mac = df[~df["MAC"].isin([0, 1])].dropna(subset=["MAC"])
        if not invalid_mac.empty:
            issues.append(f"MAC must be 0 or 1. Found {len(invalid_mac)} invalid rows.")

    if "MEC" in df.columns:
        invalid_mec = df[~((df["MEC"] > 0) & (df["MEC"] < 1))].dropna(subset=["MEC"])
        if not invalid_mec.empty:
            issues.append(f"MEC must be strictly between 0 and 1. Found {len(invalid_mec)} invalid rows.")

    if "MOC" in df.columns:
        invalid_moc = df[~((df["MOC"] > 0) & (df["MOC"] <= 1.0))].dropna(subset=["MOC"])
        if not invalid_moc.empty:
            issues.append(
                f"MOC must be strictly greater than 0 and less than or equal to 1.0. Found {len(invalid_moc)} invalid rows."
            )

    if "Face_Amount" in df.columns:
        invalid_face = df[df["Face_Amount"] <= 0]
        if not invalid_face.empty:
            issues.append(f"Face_Amount must be greater than 0. Found {len(invalid_face)} invalid rows.")

    age_column = "Issue_Age" if "Issue_Age" in df.columns else "Age" if "Age" in df.columns else None
    if age_column:
        invalid_age = df[df[age_column] <= 0]
        if not invalid_age.empty:
            issues.append(f"{age_column} must be greater than 0. Found {len(invalid_age)} invalid rows.")

    if "Policy_Number" in df.columns and "Duration" in df.columns:
        duplicates = df[df.duplicated(subset=["Policy_Number", "Duration"], keep=False)]
        if not duplicates.empty:
            issues.append(
                f"Duplicate Policy_Number + Duration combinations found: {duplicates.groupby(['Policy_Number', 'Duration']).ngroups} unique pairs."
            )

    if "MAC" in df.columns and "COLA" in df.columns:
        mac0_cola_not_null = df[(df["MAC"] == 0) & (df["COLA"].notna()) & (df["COLA"] != "")]
        if not mac0_cola_not_null.empty:
            issues.append(f"COLA must be null when MAC=0. Found {len(mac0_cola_not_null)} invalid rows.")
        mac1_cola_null = df[(df["MAC"] == 1) & (df["COLA"].isna() | (df["COLA"] == ""))]
        if not mac1_cola_null.empty:
            issues.append(f"COLA must not be null when MAC=1. Found {len(mac1_cola_null)} invalid rows.")

    if "MAC" in df.columns and "MOC" in df.columns:
        moc_not_one = df[(df["MAC"] == 1) & ((df["MOC"] - 1.0).abs() > 1e-9)]
        if not moc_not_one.empty:
            issues.append(f"MOC must be exactly 1.0 when MAC=1. Found {len(moc_not_one)} invalid rows.")

    if "Policy_Number" in df.columns and "Duration" in df.columns and "MAC" in df.columns:
        death_rows = df.loc[df["MAC"] == 1, ["Policy_Number", "Duration"]].dropna()
        exposure_rows = df[["Policy_Number", "Duration"]].dropna()
        merged_exposure = death_rows.merge(
            exposure_rows,
            on="Policy_Number",
            suffixes=("_death", "_later"),
        )
        violations = int((merged_exposure["Duration_later"] > merged_exposure["Duration_death"]).sum())
        if violations:
            issues.append(f"Death exposure logic violated by {violations} rows after the death duration.")

    status = "PASS" if not issues else "FAIL"
    context.artifact_manifest_path = context.artifact_manifest_path or context.default_artifact_manifest_path
    context.methodology_log_path = context.methodology_log_path or context.default_methodology_log_path
    append_methodology_event(
        context.default_methodology_log_path,
        MethodologyEvent(
            step_name="Validation checks run",
            tool_name="validate",
            input_path=str(source_path),
            output_path=None,
            parameters={"status": status, "issue_count": len(issues)},
        ),
    )
    context.write()
    return {
        "ok": True,
        "kind": "validation",
        "message": f"Actuarial validation completed for `{source_path}` with status `{status}`.",
        "artifacts": {},
        "data": {
            "status": status,
            "issues": issues,
            "feature_classification": {
                column: classify_feature_type(df, column) for column in df.columns
            },
        },
    }
