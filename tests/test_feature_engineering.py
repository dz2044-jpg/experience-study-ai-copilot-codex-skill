from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from experience_study.cli import main
from experience_study.feature_engineering import (
    MISSING_LABEL,
    OUT_OF_RANGE_LABEL,
    build_custom_band,
    build_equal_width_band,
    build_quantile_band,
    regroup_categorical,
)


def _manifest(output_dir: Path) -> dict:
    return json.loads(
        (output_dir / "artifacts" / "audit" / "artifact_manifest.json").read_text(
            encoding="utf-8"
        )
    )


def _prepared_entry(output_dir: Path) -> dict:
    manifest = _manifest(output_dir)
    return next(entry for entry in manifest["entries"] if entry["artifact_type"] == "prepared_dataset")


def test_equal_width_band_labels_and_missing_values() -> None:
    result = build_equal_width_band(
        pd.Series([0, 5, 10, None]),
        band_count=2,
        source_column="Face_Amount",
    )

    assert list(result) == ["0 to 5", "0 to 5", "5 to 10", MISSING_LABEL]


def test_quantile_band_creates_equal_frequency_groups() -> None:
    result = build_quantile_band(
        pd.Series([1, 2, 3, 4, 5, 6, 7, 8]),
        band_count=4,
        source_column="Face_Amount",
    )

    assert result.nunique() == 4
    assert sorted(result.value_counts().tolist()) == [2, 2, 2, 2]


def test_custom_band_supports_open_ended_bins_and_out_of_range_values() -> None:
    result = build_custom_band(
        pd.Series([0, 250000, 750000, 1200000, -1, None]),
        custom_bins=[0, 250000, 500000, 1000000, None],
        labels=["0-250K", "250K-500K", "500K-1M", "1M+"],
        source_column="Face_Amount",
    )

    assert list(result) == [
        "0-250K",
        "0-250K",
        "500K-1M",
        "1M+",
        OUT_OF_RANGE_LABEL,
        MISSING_LABEL,
    ]


def test_band_validation_rejects_invalid_bins_duplicate_labels_and_non_numeric_values() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        build_custom_band(
            pd.Series([1, 2]),
            custom_bins=[0, 2, 1],
            labels=["A", "B"],
            source_column="Face_Amount",
        )

    with pytest.raises(ValueError, match="unique"):
        build_custom_band(
            pd.Series([1, 2]),
            custom_bins=[0, 1, 2],
            labels=["A", "A"],
            source_column="Face_Amount",
        )

    with pytest.raises(ValueError, match="numeric"):
        build_equal_width_band(pd.Series(["F", "M"]), band_count=2, source_column="Gender")


def test_regroup_mapping_defaults_unmapped_and_can_keep_unmapped_values() -> None:
    series = pd.Series(["Preferred", "Standard Plus", "Other Product", None])
    mapping = {
        "Preferred": ["Preferred", "Preferred Plus"],
        "Standard": ["Standard", "Standard Plus"],
    }

    defaulted = regroup_categorical(series, mapping=mapping, source_column="Risk_Class")
    kept = regroup_categorical(
        series,
        mapping=mapping,
        source_column="Risk_Class",
        keep_unmapped=True,
    )

    assert list(defaulted) == ["Preferred", "Standard", "Other", MISSING_LABEL]
    assert list(kept) == ["Preferred", "Standard", "Other Product", MISSING_LABEL]


def test_regroup_rejects_duplicate_source_category_assignments() -> None:
    with pytest.raises(ValueError, match="assigned to more than one"):
        regroup_categorical(
            pd.Series(["Preferred"]),
            mapping={"A": ["Preferred"], "B": ["Preferred"]},
            source_column="Risk_Class",
        )


def test_cli_band_validation_errors_and_overwrite_behavior(
    tmp_path: Path,
    sample_csv_path: Path,
) -> None:
    output_dir = tmp_path / "band-errors"
    assert main(["profile", str(sample_csv_path), "--output-dir", str(output_dir)]) == 0

    assert (
        main(
            [
                "band",
                "--output-dir",
                str(output_dir),
                "--source-column",
                "Missing_Column",
                "--new-column",
                "Missing_Band",
                "--strategy",
                "equal-width",
                "--bins",
                "2",
            ]
        )
        == 1
    )
    assert (
        main(
            [
                "band",
                "--output-dir",
                str(output_dir),
                "--source-column",
                "Gender",
                "--new-column",
                "Gender_Band",
                "--strategy",
                "equal-width",
                "--bins",
                "2",
            ]
        )
        == 1
    )
    assert (
        main(
            [
                "band",
                "--output-dir",
                str(output_dir),
                "--source-column",
                "Face_Amount",
                "--new-column",
                "Issue_Age_Band",
                "--strategy",
                "equal-width",
                "--bins",
                "2",
            ]
        )
        == 1
    )
    assert (
        main(
            [
                "band",
                "--output-dir",
                str(output_dir),
                "--source-column",
                "Face_Amount",
                "--new-column",
                "Issue_Age_Band",
                "--strategy",
                "equal-width",
                "--bins",
                "2",
                "--overwrite",
            ]
        )
        == 0
    )


def test_band_updates_prepared_dataset_audit_state_and_packet_boundary(
    tmp_path: Path,
    sample_csv_path: Path,
) -> None:
    output_dir = tmp_path / "band-workflow"
    assert main(["profile", str(sample_csv_path), "--output-dir", str(output_dir)]) == 0
    assert main(["validate", "--output-dir", str(output_dir)]) == 0
    assert (
        main(
            [
                "ae",
                "--output-dir",
                str(output_dir),
                "--measure",
                "both",
                "--group-by",
                "Gender",
            ]
        )
        == 0
    )
    assert main(["packet", "--output-dir", str(output_dir)]) == 0

    old_prepared_hash = _prepared_entry(output_dir)["content_hash"]
    old_latest_path = output_dir / "artifacts" / "ae" / "latest.csv"
    assert old_latest_path.exists()

    assert (
        main(
            [
                "band",
                "--output-dir",
                str(output_dir),
                "--source-column",
                "Face_Amount",
                "--new-column",
                "Face_Amount_Band",
                "--strategy",
                "quantile",
                "--bins",
                "4",
            ]
        )
        == 0
    )

    prepared_df = pd.read_parquet(output_dir / "artifacts" / "analysis_inforce.parquet")
    assert "Face_Amount_Band" in prepared_df.columns
    assert prepared_df["Face_Amount_Band"].nunique() == 4
    assert old_latest_path.exists()

    context = json.loads((output_dir / "workflow_context.json").read_text(encoding="utf-8"))
    assert context["latest_ae_path"] is None
    assert context["latest_packet_path"] is None
    assert context["latest_ae_paths_by_way"] == {}

    manifest = _manifest(output_dir)
    assert "state_fingerprint" not in manifest
    assert "fingerprint_inputs" not in manifest
    prepared_entry = _prepared_entry(output_dir)
    assert prepared_entry["content_hash"] != old_prepared_hash
    assert prepared_entry["generating_tool"] == "band"
    assert prepared_entry["parameters"]["source_column"] == "Face_Amount"

    log = json.loads(
        (output_dir / "artifacts" / "audit" / "methodology_log.json").read_text(
            encoding="utf-8"
        )
    )
    assert [event["tool_name"] for event in log["events"]][-1] == "band"

    assert main(["packet", "--output-dir", str(output_dir)]) == 1
    assert (
        main(
            [
                "ae",
                "--output-dir",
                str(output_dir),
                "--measure",
                "amount",
                "--group-by",
                "Face_Amount_Band",
            ]
        )
        == 0
    )
    assert main(["packet", "--output-dir", str(output_dir)]) == 0

    packet_json = (output_dir / "artifacts" / "ai" / "ai_ae_packet.json").read_text(
        encoding="utf-8"
    )
    packet = json.loads(packet_json)
    assert packet["group_by"] == ["Face_Amount_Band"]
    assert packet["rows"][0]["Dimension_Columns"] == ["Face_Amount_Band"]
    for forbidden in ("Policy_Number", "P001", "P002"):
        assert forbidden not in packet_json


def test_regroup_engineered_dimension_can_drive_count_ae(
    tmp_path: Path,
    sample_csv_path: Path,
) -> None:
    output_dir = tmp_path / "regroup-workflow"
    assert main(["profile", str(sample_csv_path), "--output-dir", str(output_dir)]) == 0
    mapping_json = json.dumps(
        {
            "Preferred": ["Preferred", "Preferred Plus"],
            "Standard": ["Standard", "Standard Plus"],
            "Substandard": ["Table A", "Table B"],
        }
    )
    assert (
        main(
            [
                "regroup",
                "--output-dir",
                str(output_dir),
                "--source-column",
                "Risk_Class",
                "--new-column",
                "Risk_Class_Group",
                "--mapping-json",
                mapping_json,
            ]
        )
        == 0
    )

    prepared_df = pd.read_parquet(output_dir / "artifacts" / "analysis_inforce.parquet")
    assert set(prepared_df["Risk_Class_Group"]) == {"Preferred", "Standard"}

    assert (
        main(
            [
                "ae",
                "--output-dir",
                str(output_dir),
                "--measure",
                "count",
                "--group-by",
                "Risk_Class_Group",
            ]
        )
        == 0
    )

    latest_df = pd.read_csv(output_dir / "artifacts" / "ae" / "latest.csv")
    assert latest_df["Dimensions"].str.startswith("Risk_Class_Group=").all()
