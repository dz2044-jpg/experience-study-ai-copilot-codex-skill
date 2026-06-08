from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

import pandas as pd
import pytest

from experience_study.ae_math import compute_ae_ci, compute_ae_ci_amount
from experience_study.analysis import run_ae_analysis
from experience_study.artifacts import load_context, stable_slug, timestamped_output_dir
from experience_study.cli import main
from experience_study.contracts import AE_SUMMARY_COLUMNS
from experience_study.io import ISSUE_AGE_BAND_COLUMN, profile_dataset
from experience_study.packet import build_ai_packet
from experience_study.validation import run_validation


def test_stable_slug_rules_preserve_order_and_clean_names() -> None:
    assert stable_slug(["Risk Class", "Issue_Age_Band", "Smoker?"]) == "risk_class_issue_age_band_smoker"
    assert stable_slug(["Smoker?", "Risk Class"]) == "smoker_risk_class"


def test_timestamped_output_dir_prefixes_name_and_avoids_collisions(tmp_path: Path) -> None:
    requested = tmp_path / "runs" / "risk-regroup"
    now = datetime(2026, 6, 8, 14, 5)

    first_candidate = timestamped_output_dir(requested, now=now)
    first_candidate.mkdir(parents=True)
    second_candidate = timestamped_output_dir(requested, now=now)

    assert first_candidate == tmp_path / "runs" / "202606081405_risk-regroup"
    assert second_candidate == tmp_path / "runs" / "202606081405_risk-regroup_02"


def test_ci_math_preserves_reference_behavior() -> None:
    lower, upper = compute_ae_ci(mac=5, moc=1000, mec=4)
    assert lower is not None
    assert upper is not None
    assert lower < upper

    amount_lower, amount_upper = compute_ae_ci_amount(
        mac=0,
        moc=1000,
        mec=4,
        actual_amount=0,
        expected_amount=400000,
    )
    assert amount_lower is not None
    assert amount_upper is not None
    assert amount_upper > 0


def test_profile_validate_and_gender_ae_exact_values(tmp_path: Path, sample_csv_path: Path) -> None:
    context = load_context(tmp_path / "run")
    profile = profile_dataset(context, sample_csv_path)
    validation = run_validation(context)
    result = run_ae_analysis(
        context,
        measure="both",
        group_by=["Gender"],
        min_claims=0,
        top_n=1,
    )

    assert profile["ok"] is True
    assert validation["data"]["status"] == "PASS"
    assert result["data"]["row_count"] == 2
    assert len(result["data"]["results"]) == 1

    latest_path = tmp_path / "run" / "artifacts" / "ae" / "latest.csv"
    latest_df = pd.read_csv(latest_path)
    assert list(latest_df.columns) == AE_SUMMARY_COLUMNS
    assert len(latest_df) == 2

    by_dimension = latest_df.set_index("Dimensions")
    assert by_dimension.loc["Gender=M", "Sum_MAC"] == 2
    assert by_dimension.loc["Gender=F", "Sum_MAC"] == 1
    assert by_dimension.loc["Gender=M", "AE_Ratio_Count"] == pytest.approx(2.5316455696202533)
    assert by_dimension.loc["Gender=M", "AE_Ratio_Amount"] == pytest.approx(0.8517350157728707)
    assert by_dimension.loc["Gender=F", "AE_Ratio_Count"] == pytest.approx(1.5873015873015872)
    assert by_dimension.loc["Gender=F", "AE_Ratio_Amount"] == pytest.approx(0.39215686274509803)


def test_profile_creates_issue_age_band_and_one_way_ae_artifacts(
    tmp_path: Path,
    sample_csv_path: Path,
) -> None:
    output_dir = tmp_path / "issue-age-band-run"
    exit_code = main(
        [
            "run",
            str(sample_csv_path),
            "--output-dir",
            str(output_dir),
            "--ae-by",
            "Gender",
            "--ae-by",
            ISSUE_AGE_BAND_COLUMN,
            "--measure",
            "count",
        ]
    )

    assert exit_code == 0
    prepared_df = pd.read_parquet(output_dir / "artifacts" / "analysis_inforce.parquet")
    assert ISSUE_AGE_BAND_COLUMN in prepared_df.columns
    assert prepared_df[ISSUE_AGE_BAND_COLUMN].nunique() == 4

    issue_age_path = output_dir / "artifacts" / "ae" / "ae_summary_by_issue_age_band.csv"
    gender_path = output_dir / "artifacts" / "ae" / "ae_summary_by_gender.csv"
    assert issue_age_path.exists()
    assert gender_path.exists()

    issue_age_df = pd.read_csv(issue_age_path)
    gender_df = pd.read_csv(gender_path)
    assert issue_age_df["Dimensions"].str.startswith(f"{ISSUE_AGE_BAND_COLUMN}=").all()
    assert gender_df["Dimensions"].str.startswith("Gender=").all()
    assert issue_age_df["Sum_MAC"].sum() == gender_df["Sum_MAC"].sum()


def test_cli_run_can_create_timestamped_output_dir(
    tmp_path: Path,
    sample_csv_path: Path,
) -> None:
    requested_output_dir = tmp_path / "runs" / "gender-count"

    exit_code = main(
        [
            "run",
            str(sample_csv_path),
            "--output-dir",
            str(requested_output_dir),
            "--timestamp-output-dir",
            "--ae-by",
            "Gender",
            "--measure",
            "count",
        ]
    )

    assert exit_code == 0
    assert not requested_output_dir.exists()

    created_dirs = list((tmp_path / "runs").iterdir())
    assert len(created_dirs) == 1
    actual_output_dir = created_dirs[0]
    assert re.fullmatch(r"\d{12}_gender-count", actual_output_dir.name)
    assert (actual_output_dir / "artifacts" / "ae" / "latest.csv").exists()
    assert (actual_output_dir / "artifacts" / "ai" / "ai_ae_packet.json").exists()


def test_cli_ae_prints_measure_specific_presentation_tables(
    tmp_path: Path,
    sample_csv_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "presentation-table"
    assert main(["profile", str(sample_csv_path), "--output-dir", str(output_dir)]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "ae",
                "--output-dir",
                str(output_dir),
                "--measure",
                "count",
                "--group-by",
                "Gender",
            ]
        )
        == 0
    )
    count_output = capsys.readouterr().out
    assert "Summary of A/E Results" not in count_output
    assert "Count A/E Results" in count_output
    assert "| Cohort | Actual Deaths | Expected Deaths | Count A/E | Count A/E CI |" in count_output
    assert "| Gender=" in count_output

    assert (
        main(
            [
                "ae",
                "--output-dir",
                str(output_dir),
                "--measure",
                "amount",
                "--group-by",
                "Gender",
            ]
        )
        == 0
    )
    amount_output = capsys.readouterr().out
    assert "Amount A/E Results" in amount_output
    assert "| Cohort | Actual Amount | Expected Amount | Amount A/E | Amount A/E CI |" in amount_output
    assert "| Gender=" in amount_output

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
    both_output = capsys.readouterr().out
    assert "Count A/E Results" in both_output
    assert "Amount A/E Results" in both_output


def test_cli_golden_run_writes_manifest_log_context_and_packet(
    tmp_path: Path,
    sample_csv_path: Path,
) -> None:
    output_dir = tmp_path / "golden"
    exit_code = main(
        [
            "run",
            str(sample_csv_path),
            "--output-dir",
            str(output_dir),
            "--ae-by",
            "Gender",
            "--ae-by",
            "Gender",
            "Smoker",
            "--measure",
            "both",
            "--min-claims",
            "1",
            "--top-n",
            "1",
        ]
    )

    assert exit_code == 0
    context_path = output_dir / "workflow_context.json"
    latest_path = output_dir / "artifacts" / "ae" / "latest.csv"
    latest_1way = output_dir / "artifacts" / "ae" / "latest_1way.csv"
    latest_2way = output_dir / "artifacts" / "ae" / "latest_2way.csv"
    packet_path = output_dir / "artifacts" / "ai" / "ai_ae_packet.json"
    log_path = output_dir / "artifacts" / "audit" / "methodology_log.json"
    manifest_path = output_dir / "artifacts" / "audit" / "artifact_manifest.json"

    for path in (context_path, latest_path, latest_1way, latest_2way, packet_path, log_path, manifest_path):
        assert path.exists()

    assert (output_dir / "artifacts" / "ae" / "ae_summary_by_gender.csv").exists()
    assert (output_dir / "artifacts" / "ae" / "ae_summary_by_gender_smoker.csv").exists()

    latest_df = pd.read_csv(latest_path)
    assert list(latest_df.columns) == AE_SUMMARY_COLUMNS
    assert len(latest_df) > 1

    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert packet["schema_version"] == "ai_ae_packet.v1"
    assert len(packet["rows"]) == 1
    assert packet["packet_fingerprint"]

    methodology_log = json.loads(log_path.read_text(encoding="utf-8"))
    assert [event["step_name"] for event in methodology_log["events"]] == [
        "Source dataset profiled",
        "Validation checks run",
        "Grouped A/E analysis run",
        "Grouped A/E analysis run",
        "Sanitized AI A/E packet built",
    ]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_types = {entry["artifact_type"] for entry in manifest["entries"]}
    assert {
        "source_dataset",
        "prepared_dataset",
        "ae_summary",
        "latest_ae_summary",
        "latest_ae_summary_by_way",
        "ai_ae_packet",
    } <= artifact_types
    assert manifest["fingerprint_inputs"]["group_by"] == ["Gender", "Smoker"]
    assert manifest["fingerprint_inputs"]["min_claims"] == 1


def test_two_way_risk_class_filters_and_min_claims(tmp_path: Path, sample_csv_path: Path) -> None:
    context = load_context(tmp_path / "filtered")
    profile_dataset(context, sample_csv_path)
    run_validation(context)

    result = run_ae_analysis(
        context,
        measure="count",
        group_by=["Gender", "Risk_Class"],
        filters=[{"column": "Product_Group", "operator": "=", "value": "Term"}],
        min_claims=1,
    )

    latest_df = pd.read_csv(result["artifacts"]["latest_ae_path"])
    assert not latest_df.empty
    assert latest_df["Sum_MAC"].ge(1).all()
    assert latest_df["Dimensions"].str.contains("Risk_Class=").all()


def test_cli_rejects_raw_numeric_dimension(tmp_path: Path, sample_csv_path: Path) -> None:
    output_dir = tmp_path / "bad-dimension"
    assert main(["profile", str(sample_csv_path), "--output-dir", str(output_dir)]) == 0

    exit_code = main(
        [
            "ae",
            "--output-dir",
            str(output_dir),
            "--measure",
            "both",
            "--group-by",
            "Issue_Age",
        ]
    )

    assert exit_code == 1


def test_run_stops_before_ae_when_validation_fails(tmp_path: Path, sample_csv_path: Path) -> None:
    invalid_path = tmp_path / "invalid.csv"
    df = pd.read_csv(sample_csv_path)
    df.loc[0, "MAC"] = 2
    df.to_csv(invalid_path, index=False)
    output_dir = tmp_path / "invalid-run"

    exit_code = main(
        [
            "run",
            str(invalid_path),
            "--output-dir",
            str(output_dir),
            "--ae-by",
            "Gender",
        ]
    )

    assert exit_code == 1
    assert not (output_dir / "artifacts" / "ae" / "latest.csv").exists()
    log = json.loads((output_dir / "artifacts" / "audit" / "methodology_log.json").read_text(encoding="utf-8"))
    assert [event["tool_name"] for event in log["events"]] == ["profile", "validate"]


def test_context_reconstructs_from_manifest_when_context_file_is_missing(
    tmp_path: Path,
    sample_csv_path: Path,
) -> None:
    output_dir = tmp_path / "recover"
    assert main(["run", str(sample_csv_path), "--output-dir", str(output_dir), "--ae-by", "Gender"]) == 0
    (output_dir / "workflow_context.json").unlink()

    context = load_context(output_dir)

    assert context.prepared_data_path is not None
    assert context.prepared_data_path.exists()
    assert context.latest_ae_path is not None
    assert context.latest_ae_path.exists()
    assert context.latest_packet_path is not None
    assert context.latest_packet_path.exists()


def test_packet_masks_sensitive_dimensions_and_ignores_unknown_columns(tmp_path: Path) -> None:
    context = load_context(tmp_path / "packet")
    context.ensure_dirs()
    ae_path = context.latest_ae_alias_path
    pd.DataFrame(
        [
            {
                "Dimensions": "Policy_Number=P001 | Gender=M",
                "Sum_MAC": 2,
                "Sum_MOC": 10.0,
                "Sum_MEC": 1.0,
                "Sum_MAF": 100000.0,
                "Sum_MEF": 80000.0,
                "AE_Ratio_Count": 2.0,
                "AE_Ratio_Amount": 1.25,
                "AE_Count_CI_Lower": 0.25,
                "AE_Count_CI_Upper": 3.5,
                "AE_Amount_CI_Lower": 0.30,
                "AE_Amount_CI_Upper": 3.75,
                "Unexpected_Name": "Alice Example",
            }
        ]
    ).to_csv(ae_path, index=False)
    context.latest_ae_path = ae_path
    context.prepared_data_path = tmp_path / "missing_row_level.parquet"

    result = build_ai_packet(context, top_n=10)

    packet_json = Path(result["artifacts"]["ai_ae_packet_path"]).read_text(encoding="utf-8")
    for forbidden in ("Policy_Number", "P001", "Alice Example", "Unexpected_Name"):
        assert forbidden not in packet_json
    packet = json.loads(packet_json)
    assert packet["rows"][0]["Dimensions"] == "[masked cohort label]"
    assert packet["rows"][0]["Dimension_Columns"] == ["[masked dimension]"]
    assert packet["rows"][0]["masking_reason"] == "sensitive_or_disallowed_dimension"


def test_packet_top_n_does_not_truncate_canonical_ae_summary(
    tmp_path: Path,
    sample_csv_path: Path,
) -> None:
    context = load_context(tmp_path / "top-n")
    profile_dataset(context, sample_csv_path)
    run_validation(context)
    run_ae_analysis(context, measure="both", group_by=["Gender"], top_n=1)
    build_ai_packet(context, top_n=1)

    latest_df = pd.read_csv(context.latest_ae_path)
    packet = json.loads(context.latest_packet_path.read_text(encoding="utf-8"))

    assert len(latest_df) == 2
    assert len(packet["rows"]) == 1
