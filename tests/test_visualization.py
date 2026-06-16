from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from experience_study.artifacts import load_context
from experience_study.cli import main
from experience_study.visualization import generate_visual_bundle, metric_columns


def _write_ae_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _base_row(dimensions: str = "Gender=M") -> dict[str, object]:
    return {
        "Dimensions": dimensions,
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
    }


def _load_spec(result: dict[str, object]) -> dict[str, object]:
    artifacts = result["artifacts"]
    assert isinstance(artifacts, dict)
    return json.loads(Path(str(artifacts["spec_json"])).read_text(encoding="utf-8"))


def test_metric_mapping_uses_expected_treemap_size_basis() -> None:
    assert metric_columns("count").treemap_size == "Sum_MEC"
    assert metric_columns("amount").treemap_size == "Sum_MEF"


def test_visualize_latest_writes_manifest_and_no_latest_visual_context(
    tmp_path: Path,
    sample_csv_path: Path,
) -> None:
    output_dir = tmp_path / "visual-latest"
    assert (
        main(
            [
                "run",
                str(sample_csv_path),
                "--output-dir",
                str(output_dir),
                "--ae-by",
                "Gender",
                "--measure",
                "both",
                "--min-claims",
                "1",
            ]
        )
        == 0
    )

    assert (
        main(
            [
                "visualize",
                "--output-dir",
                str(output_dir),
                "--metric",
                "amount",
                "--width",
                "800",
                "--height",
                "600",
                "--top-n",
                "1",
            ]
        )
        == 0
    )

    context_payload = json.loads((output_dir / "workflow_context.json").read_text(encoding="utf-8"))
    assert "latest_visual_path" not in context_payload

    manifest = json.loads(
        (output_dir / "artifacts" / "audit" / "artifact_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    artifact_types = {entry["artifact_type"] for entry in manifest["entries"]}
    assert {
        "ae_visual_forest_svg",
        "ae_visual_treemap_svg",
        "ae_visual_table_svg",
        "ae_visual_table_csv",
        "ae_visual_spec",
    } <= artifact_types

    spec_entry = next(entry for entry in manifest["entries"] if entry["artifact_type"] == "ae_visual_spec")
    spec = json.loads(Path(spec_entry["path"]).read_text(encoding="utf-8"))
    assert spec["source_order_preserved"] is True
    assert spec["source_row_count"] == 2
    assert spec["selected_top_n_row_count"] == 1
    assert spec["source_parameters_found"] is True
    assert spec["source_min_claims"] == 1
    assert spec["source_sort_by"] == "AE_Ratio_Amount"
    assert spec["width"] == 800
    assert spec["height"] == 600

    log = json.loads(
        (output_dir / "artifacts" / "audit" / "methodology_log.json").read_text(
            encoding="utf-8"
        )
    )
    visual_event = log["events"][-1]
    assert visual_event["tool_name"] == "visualize"
    assert visual_event["parameters"]["metric"] == "amount"
    assert visual_event["parameters"]["width"] == 800
    assert visual_event["parameters"]["height"] == 600
    assert visual_event["parameters"]["visual_parameter_hash"]
    assert "spec_json" in visual_event["parameters"]["generated_artifact_paths"]


def test_visualize_requires_metric_and_validates_dimensions(tmp_path: Path) -> None:
    context = load_context(tmp_path / "bounds")
    context.ensure_dirs()
    ae_path = _write_ae_csv(context.latest_ae_alias_path, [_base_row()])
    context.latest_ae_path = ae_path
    context.write()

    with pytest.raises(SystemExit):
        main(["visualize", "--output-dir", str(context.output_dir)])

    assert (
        main(
            [
                "visualize",
                "--output-dir",
                str(context.output_dir),
                "--metric",
                "count",
                "--width",
                "599",
            ]
        )
        == 1
    )


def test_visualization_sanitizes_sensitive_labels_in_all_outputs(tmp_path: Path) -> None:
    context = load_context(tmp_path / "sensitive")
    context.ensure_dirs()
    ae_path = _write_ae_csv(
        context.latest_ae_alias_path,
        [_base_row("Policy_Number=P001 | Gender=M")],
    )
    context.latest_ae_path = ae_path

    result = generate_visual_bundle(context, metric="count", top_n=10)
    artifacts = result["artifacts"]
    assert isinstance(artifacts, dict)

    combined_output = "\n".join(
        Path(str(path)).read_text(encoding="utf-8") for path in artifacts.values()
    )
    for forbidden in ("Policy_Number", "P001"):
        assert forbidden not in combined_output

    spec = _load_spec(result)
    row = spec["forest_table_rows"][0]
    assert row["sanitized_dimensions"] == "[masked cohort label]"
    assert row["display_label"] == "row_0001"
    assert row["masking_reason"] == "sensitive_or_disallowed_dimension"


def test_visualization_records_missing_ci_and_ratio_clipping(tmp_path: Path) -> None:
    context = load_context(tmp_path / "clipping")
    context.ensure_dirs()
    row = _base_row("Segment=High")
    row["AE_Ratio_Count"] = 4.2
    row["AE_Count_CI_Lower"] = None
    row["AE_Count_CI_Upper"] = None
    ae_path = _write_ae_csv(context.latest_ae_alias_path, [row])
    context.latest_ae_path = ae_path

    result = generate_visual_bundle(context, metric="count")

    spec = _load_spec(result)
    visual_row = spec["forest_table_rows"][0]
    assert visual_row["metric_ratio_true"] == 4.2
    assert visual_row["metric_ratio_display"] == 3.0
    assert visual_row["metric_ratio_clipped"] is True
    assert visual_row["metric_ci_available"] is False

    forest_svg = Path(str(result["artifacts"]["forest_svg"])).read_text(encoding="utf-8")
    assert "clipped" in forest_svg
    assert "A/E 4.20" in forest_svg
    assert "CI n/a" in forest_svg


def test_external_ae_path_without_manifest_lineage_and_parse_warning(tmp_path: Path) -> None:
    context = load_context(tmp_path / "external")
    external_path = _write_ae_csv(tmp_path / "external_ae.csv", [_base_row("malformed label")])

    result = generate_visual_bundle(
        context,
        metric="amount",
        ae_path=external_path,
        title="External Amount A/E",
    )

    spec = _load_spec(result)
    assert spec["source_parameters_found"] is False
    assert spec["source_min_claims"] is None
    assert spec["source_sort_by"] is None
    assert spec["forest_table_rows"][0]["display_label"] == "row_0001"
    assert spec["forest_table_rows"][0]["masking_reason"] == "dimension_parse_warning"
    assert any(warning["code"] == "dimension_parse_warning" for warning in spec["warnings"])
    assert spec["treemap_rows"][0]["treemap_size_true"] == 80000.0


def test_treemap_uses_all_rows_while_forest_and_table_use_top_n(tmp_path: Path) -> None:
    context = load_context(tmp_path / "top-n-visual")
    context.ensure_dirs()
    rows = [
        _base_row("Segment=A"),
        {**_base_row("Segment=B"), "Sum_MEC": 3.0, "AE_Ratio_Count": 1.4},
        {**_base_row("Segment=C"), "Sum_MEC": 5.0, "AE_Ratio_Count": 0.8},
    ]
    ae_path = _write_ae_csv(context.latest_ae_alias_path, rows)
    context.latest_ae_path = ae_path

    result = generate_visual_bundle(context, metric="count", top_n=2)
    spec = _load_spec(result)

    assert spec["selected_top_n_row_count"] == 2
    assert spec["source_row_count"] == 3
    assert len(spec["forest_table_rows"]) == 2
    assert len(spec["treemap_rows"]) == 3
    assert [row["sanitized_dimensions"] for row in spec["forest_table_rows"]] == [
        "Segment=A",
        "Segment=B",
    ]
    assert [row["treemap_size_true"] for row in spec["treemap_rows"]] == [1.0, 3.0, 5.0]
