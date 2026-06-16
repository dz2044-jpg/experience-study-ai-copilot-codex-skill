"""Deterministic SVG visualization artifacts for aggregate A/E results."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

import pandas as pd

from experience_study.artifacts import (
    MethodologyEvent,
    WorkflowContext,
    append_methodology_event,
    file_sha256,
    normalize_json_value,
    read_artifact_manifest,
    source_artifact,
    upsert_artifact_entry,
)
from experience_study.contracts import (
    AE_SUMMARY_COLUMNS,
    AE_VISUAL_SPEC_SCHEMA_VERSION,
    MAX_TOP_N,
    PACKAGE_VERSION,
)
from experience_study.sanitization import (
    MASKED_COHORT_LABEL,
    MASKED_DIMENSION_COLUMN,
    dimension_column_is_sensitive,
    parse_dimension_label,
)

VALID_VISUAL_METRICS: set[str] = {"count", "amount"}
VALID_VISUAL_FORMATS: set[str] = {"svg"}
VALID_VISUAL_STYLES: set[str] = {"formal", "compact", "presentation"}

MIN_VISUAL_WIDTH = 600
MAX_VISUAL_WIDTH = 2400
MIN_VISUAL_HEIGHT = 400
MAX_VISUAL_HEIGHT = 3200

DEFAULT_VISUAL_WIDTH = 1200
DEFAULT_VISUAL_HEIGHT = 800
FOREST_AXIS_MIN = 0.0
FOREST_AXIS_MAX = 3.0
COLOR_SCALE_MIN = 0.0
COLOR_SCALE_CENTER = 1.0
COLOR_SCALE_MAX = 2.0


@dataclass(frozen=True)
class MetricColumns:
    """Metric-specific aggregate A/E column mapping."""

    label: str
    actual: str
    expected: str
    ratio: str
    ci_lower: str
    ci_upper: str
    treemap_size: str


@dataclass(frozen=True)
class VisualRow:
    """Sanitized visual-ready aggregate row."""

    evidence_ref: str
    source_row_number: int
    sanitized_dimensions: str
    display_label: str
    dimension_columns: list[str]
    hierarchy_parts: list[str]
    masking_reason: str | None
    caution_flags: list[str]
    metric_actual_true: float | None
    metric_expected_true: float | None
    metric_ratio_true: float | None
    metric_ci_lower_true: float | None
    metric_ci_upper_true: float | None
    metric_ratio_display: float | None
    metric_ci_lower_display: float | None
    metric_ci_upper_display: float | None
    metric_ratio_clipped: bool
    metric_ci_lower_clipped: bool
    metric_ci_upper_clipped: bool
    metric_ci_available: bool
    treemap_size_true: float | None
    color_value_display: float | None
    color_value_saturated: bool

    def to_spec_dict(self) -> dict[str, Any]:
        """Return the JSON-safe row representation used by visual specs."""

        return normalize_json_value(
            {
                "evidence_ref": self.evidence_ref,
                "source_row_number": self.source_row_number,
                "sanitized_dimensions": self.sanitized_dimensions,
                "display_label": self.display_label,
                "dimension_columns": self.dimension_columns,
                "masking_reason": self.masking_reason,
                "caution_flags": self.caution_flags,
                "metric_actual_true": self.metric_actual_true,
                "metric_expected_true": self.metric_expected_true,
                "metric_ratio_true": self.metric_ratio_true,
                "metric_ci_lower_true": self.metric_ci_lower_true,
                "metric_ci_upper_true": self.metric_ci_upper_true,
                "metric_ratio_display": self.metric_ratio_display,
                "metric_ci_lower_display": self.metric_ci_lower_display,
                "metric_ci_upper_display": self.metric_ci_upper_display,
                "metric_ratio_clipped": self.metric_ratio_clipped,
                "metric_ci_lower_clipped": self.metric_ci_lower_clipped,
                "metric_ci_upper_clipped": self.metric_ci_upper_clipped,
                "metric_ci_available": self.metric_ci_available,
                "treemap_size_true": self.treemap_size_true,
                "color_value_display": self.color_value_display,
                "color_value_saturated": self.color_value_saturated,
            }
        )


def metric_columns(metric: str) -> MetricColumns:
    """Return aggregate columns for a supported A/E metric."""

    if metric == "count":
        return MetricColumns(
            label="Count",
            actual="Sum_MAC",
            expected="Sum_MEC",
            ratio="AE_Ratio_Count",
            ci_lower="AE_Count_CI_Lower",
            ci_upper="AE_Count_CI_Upper",
            treemap_size="Sum_MEC",
        )
    if metric == "amount":
        return MetricColumns(
            label="Amount",
            actual="Sum_MAF",
            expected="Sum_MEF",
            ratio="AE_Ratio_Amount",
            ci_lower="AE_Amount_CI_Lower",
            ci_upper="AE_Amount_CI_Upper",
            treemap_size="Sum_MEF",
        )
    raise ValueError("metric must be one of: count, amount.")


def validate_visual_dimensions(width: int, height: int) -> None:
    """Validate governed SVG dimensions."""

    if not MIN_VISUAL_WIDTH <= width <= MAX_VISUAL_WIDTH:
        raise ValueError(
            f"width must be between {MIN_VISUAL_WIDTH} and {MAX_VISUAL_WIDTH}."
        )
    if not MIN_VISUAL_HEIGHT <= height <= MAX_VISUAL_HEIGHT:
        raise ValueError(
            f"height must be between {MIN_VISUAL_HEIGHT} and {MAX_VISUAL_HEIGHT}."
        )


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric) or not math.isfinite(numeric):
        return None
    return numeric


def _clip(value: float | None, lower: float, upper: float) -> tuple[float | None, bool]:
    if value is None:
        return None, False
    clipped = min(max(value, lower), upper)
    return clipped, clipped != value


def _format_number(value: Any, *, decimals: int = 2) -> str:
    numeric = _finite_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:,.{decimals}f}"


def _format_ci(lower: Any, upper: Any) -> str:
    if _finite_float(lower) is None or _finite_float(upper) is None:
        return "n/a"
    return f"{_format_number(lower)} to {_format_number(upper)}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return re.sub(r"_+", "_", slug) or "ae"


def _shorten_label(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def _load_source_manifest(context: WorkflowContext, source_path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    manifest = (
        read_artifact_manifest(context.default_artifact_manifest_path)
        if context.default_artifact_manifest_path.exists()
        else {"entries": [], "fingerprint_inputs": {}, "state_fingerprint": None}
    )
    source_resolved = source_path.resolve()
    source_entry: dict[str, Any] | None = None
    for entry in manifest.get("entries", []):
        entry_path = entry.get("path")
        if not entry_path:
            continue
        try:
            if Path(entry_path).resolve() == source_resolved:
                source_entry = entry
                break
        except OSError:
            continue
    return manifest, source_entry


def _prepare_rows(df: pd.DataFrame, metric: str) -> tuple[list[VisualRow], list[dict[str, Any]]]:
    columns = metric_columns(metric)
    rows: list[VisualRow] = []
    warnings: list[dict[str, Any]] = []
    for row_index, row in df.iterrows():
        evidence_ref = f"row_{row_index + 1:04d}"
        parsed_dimensions, parse_warnings = parse_dimension_label(str(row["Dimensions"]))
        dimension_columns = [column for column, _ in parsed_dimensions]
        caution_flags = list(parse_warnings)
        for warning in parse_warnings:
            warnings.append(
                {
                    "code": warning,
                    "message": "Unable to fully parse dimension label.",
                    "evidence_refs": [evidence_ref],
                }
            )

        sensitive_dimension = any(
            dimension_column_is_sensitive(column) for column in dimension_columns
        )
        masking_reason = None
        sanitized_dimensions = str(row["Dimensions"])
        sanitized_dimension_columns = list(dimension_columns)
        hierarchy_parts = [f"{column}={value}" for column, value in parsed_dimensions]
        display_label = sanitized_dimensions

        if sensitive_dimension:
            masking_reason = "sensitive_or_disallowed_dimension"
            sanitized_dimensions = MASKED_COHORT_LABEL
            sanitized_dimension_columns = [MASKED_DIMENSION_COLUMN]
            display_label = evidence_ref
            hierarchy_parts = [evidence_ref]
            caution_flags.append(masking_reason)
            warnings.append(
                {
                    "code": masking_reason,
                    "message": "A sensitive or disallowed dimension was masked.",
                    "evidence_refs": [evidence_ref],
                }
            )
        elif parse_warnings or not parsed_dimensions:
            masking_reason = "dimension_parse_warning"
            sanitized_dimensions = evidence_ref
            sanitized_dimension_columns = []
            display_label = evidence_ref
            hierarchy_parts = [evidence_ref]

        ratio_true = _finite_float(row[columns.ratio])
        ci_lower_true = _finite_float(row[columns.ci_lower])
        ci_upper_true = _finite_float(row[columns.ci_upper])
        ratio_display, ratio_clipped = _clip(ratio_true, FOREST_AXIS_MIN, FOREST_AXIS_MAX)
        ci_lower_display, ci_lower_clipped = _clip(ci_lower_true, FOREST_AXIS_MIN, FOREST_AXIS_MAX)
        ci_upper_display, ci_upper_clipped = _clip(ci_upper_true, FOREST_AXIS_MIN, FOREST_AXIS_MAX)
        color_value_display, color_value_saturated = _clip(
            ratio_true,
            COLOR_SCALE_MIN,
            COLOR_SCALE_MAX,
        )
        rows.append(
            VisualRow(
                evidence_ref=evidence_ref,
                source_row_number=row_index + 1,
                sanitized_dimensions=sanitized_dimensions,
                display_label=display_label,
                dimension_columns=sanitized_dimension_columns,
                hierarchy_parts=hierarchy_parts,
                masking_reason=masking_reason,
                caution_flags=list(dict.fromkeys(caution_flags)),
                metric_actual_true=_finite_float(row[columns.actual]),
                metric_expected_true=_finite_float(row[columns.expected]),
                metric_ratio_true=ratio_true,
                metric_ci_lower_true=ci_lower_true,
                metric_ci_upper_true=ci_upper_true,
                metric_ratio_display=ratio_display,
                metric_ci_lower_display=ci_lower_display,
                metric_ci_upper_display=ci_upper_display,
                metric_ratio_clipped=ratio_clipped,
                metric_ci_lower_clipped=ci_lower_clipped,
                metric_ci_upper_clipped=ci_upper_clipped,
                metric_ci_available=ci_lower_true is not None and ci_upper_true is not None,
                treemap_size_true=_finite_float(row[columns.treemap_size]),
                color_value_display=color_value_display,
                color_value_saturated=color_value_saturated,
            )
        )
    return rows, list({json.dumps(warning, sort_keys=True): warning for warning in warnings}.values())


def _build_review_frame(rows: list[VisualRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "evidence_ref": row.evidence_ref,
                "source_row_number": row.source_row_number,
                "visual_rank": index + 1,
                "sanitized_dimensions": row.sanitized_dimensions,
                "dimension_columns": " | ".join(row.dimension_columns),
                "metric_actual_true": row.metric_actual_true,
                "metric_expected_true": row.metric_expected_true,
                "metric_ratio_true": row.metric_ratio_true,
                "metric_ci_lower_true": row.metric_ci_lower_true,
                "metric_ci_upper_true": row.metric_ci_upper_true,
                "metric_ratio_display": row.metric_ratio_display,
                "metric_ci_lower_display": row.metric_ci_lower_display,
                "metric_ci_upper_display": row.metric_ci_upper_display,
                "metric_ratio_clipped": row.metric_ratio_clipped,
                "metric_ci_lower_clipped": row.metric_ci_lower_clipped,
                "metric_ci_upper_clipped": row.metric_ci_upper_clipped,
                "metric_ci_available": row.metric_ci_available,
                "masking_reason": row.masking_reason,
                "caution_flags": " | ".join(row.caution_flags),
            }
            for index, row in enumerate(rows)
        ]
    )


def _svg_document(title: str, desc: str, width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">\n'
        f"  <title>{escape(title)}</title>\n"
        f"  <desc>{escape(desc)}</desc>\n"
        f"{body}\n"
        "</svg>\n"
    )


def _style_palette(style: str) -> dict[str, str]:
    if style == "compact":
        return {"bg": "#ffffff", "panel": "#ffffff", "text": "#1f2933", "muted": "#64748b", "accent": "#1f4e79"}
    if style == "presentation":
        return {"bg": "#fbfaf7", "panel": "#ffffff", "text": "#172033", "muted": "#536272", "accent": "#174a7c"}
    return {"bg": "#fbfaf7", "panel": "#ffffff", "text": "#1f2933", "muted": "#52616f", "accent": "#1f4e79"}


def _ratio_color(ratio: float | None) -> str:
    if ratio is None:
        return "#d1d5db"
    value, _ = _clip(ratio, COLOR_SCALE_MIN, COLOR_SCALE_MAX)
    assert value is not None
    if value <= COLOR_SCALE_CENTER:
        t = value / COLOR_SCALE_CENTER
        low = (34, 139, 87)
        mid = (245, 245, 220)
        rgb = tuple(round(low[i] + (mid[i] - low[i]) * t) for i in range(3))
    else:
        t = (value - COLOR_SCALE_CENTER) / (COLOR_SCALE_MAX - COLOR_SCALE_CENTER)
        mid = (245, 245, 220)
        high = (188, 75, 81)
        rgb = tuple(round(mid[i] + (high[i] - mid[i]) * t) for i in range(3))
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def render_forest_svg(
    rows: list[VisualRow],
    *,
    metric: str,
    title: str,
    width: int,
    height: int,
    style: str,
) -> str:
    """Render a horizontal forest plot as deterministic SVG."""

    columns = metric_columns(metric)
    palette = _style_palette(style)
    top_margin = 90
    bottom_margin = 64
    left_margin = min(max(230, width // 4), 420)
    right_margin = 170
    plot_width = max(120, width - left_margin - right_margin)
    plot_height = max(80, height - top_margin - bottom_margin)
    row_height = plot_height / max(len(rows), 1)

    def x_scale(value: float) -> float:
        return left_margin + ((value - FOREST_AXIS_MIN) / (FOREST_AXIS_MAX - FOREST_AXIS_MIN)) * plot_width

    parts = [
        f'  <rect width="{width}" height="{height}" fill="{palette["bg"]}" />',
        f'  <text x="32" y="42" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="{palette["text"]}">{escape(title)}</text>',
        f'  <text x="32" y="68" font-family="Arial, sans-serif" font-size="13" fill="{palette["muted"]}">Horizontal forest plot with true labels and clipped geometry when needed.</text>',
        f'  <line x1="{left_margin}" y1="{top_margin + plot_height}" x2="{left_margin + plot_width}" y2="{top_margin + plot_height}" stroke="#334155" stroke-width="1" />',
    ]
    for tick in (0.0, 1.0, 2.0, 3.0):
        x = x_scale(tick)
        parts.append(f'  <line x1="{x:.1f}" y1="{top_margin}" x2="{x:.1f}" y2="{top_margin + plot_height}" stroke="#e2e8f0" stroke-width="1" />')
        parts.append(f'  <text x="{x:.1f}" y="{top_margin + plot_height + 24}" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" fill="{palette["muted"]}">{tick:.1f}</text>')
    expected_x = x_scale(1.0)
    parts.append(f'  <line x1="{expected_x:.1f}" y1="{top_margin}" x2="{expected_x:.1f}" y2="{top_margin + plot_height}" stroke="#b91c1c" stroke-width="2" stroke-dasharray="6 5" />')
    parts.append(f'  <text x="{expected_x + 8:.1f}" y="{top_margin - 12}" font-family="Arial, sans-serif" font-size="12" fill="#b91c1c">A/E = 1.0</text>')

    for index, row in enumerate(rows):
        y = top_margin + row_height * index + row_height / 2
        if index % 2 == 0:
            parts.append(f'  <rect x="20" y="{y - row_height / 2:.1f}" width="{width - 40}" height="{row_height:.1f}" fill="#ffffff" opacity="0.62" />')
        label = escape(_shorten_label(row.display_label, 48))
        parts.append(f'  <text x="{left_margin - 14}" y="{y + 4:.1f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="{palette["text"]}">{label}</text>')
        if row.metric_ci_available and row.metric_ci_lower_display is not None and row.metric_ci_upper_display is not None:
            ci_x1 = x_scale(row.metric_ci_lower_display)
            ci_x2 = x_scale(row.metric_ci_upper_display)
            parts.append(f'  <line x1="{ci_x1:.1f}" y1="{y:.1f}" x2="{ci_x2:.1f}" y2="{y:.1f}" stroke="{palette["accent"]}" stroke-width="2" />')
            parts.append(f'  <line x1="{ci_x1:.1f}" y1="{y - 5:.1f}" x2="{ci_x1:.1f}" y2="{y + 5:.1f}" stroke="{palette["accent"]}" stroke-width="2" />')
            parts.append(f'  <line x1="{ci_x2:.1f}" y1="{y - 5:.1f}" x2="{ci_x2:.1f}" y2="{y + 5:.1f}" stroke="{palette["accent"]}" stroke-width="2" />')
        if row.metric_ratio_display is not None:
            point_x = x_scale(row.metric_ratio_display)
            clipped_text = " clipped" if row.metric_ratio_clipped else ""
            parts.append(f'  <circle cx="{point_x:.1f}" cy="{y:.1f}" r="5.5" fill="{palette["accent"]}" stroke="#ffffff" stroke-width="1.2" />')
            if clipped_text:
                parts.append(f'  <text x="{point_x + 9:.1f}" y="{y - 8:.1f}" font-family="Arial, sans-serif" font-size="10" fill="#92400e">clipped</text>')
        ratio_text = _format_number(row.metric_ratio_true)
        ci_text = _format_ci(row.metric_ci_lower_true, row.metric_ci_upper_true)
        parts.append(f'  <text x="{left_margin + plot_width + 16}" y="{y - 2:.1f}" font-family="Arial, sans-serif" font-size="11" fill="{palette["text"]}">A/E {escape(ratio_text)}</text>')
        parts.append(f'  <text x="{left_margin + plot_width + 16}" y="{y + 13:.1f}" font-family="Arial, sans-serif" font-size="10" fill="{palette["muted"]}">CI {escape(ci_text)}</text>')
    parts.append(f'  <text x="{left_margin + plot_width / 2:.1f}" y="{height - 18}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="{palette["text"]}">A/E Ratio ({columns.label})</text>')
    return _svg_document(
        title,
        f"{columns.label} A/E forest plot with confidence intervals when available.",
        width,
        height,
        "\n".join(parts),
    )


def _tree_node(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "children": {},
        "size": 0.0,
        "actual": 0.0,
        "expected": 0.0,
        "ratio_weight_total": 0.0,
        "ratio_weight": 0.0,
        "ratio_sum": 0.0,
        "ratio_count": 0,
    }


def _add_tree_row(root: dict[str, Any], row: VisualRow) -> None:
    size = max(row.treemap_size_true or 0.0, 0.0)
    actual = row.metric_actual_true or 0.0
    expected = row.metric_expected_true or 0.0
    node = root
    for part in row.hierarchy_parts or [row.evidence_ref]:
        children = node["children"]
        if part not in children:
            children[part] = _tree_node(part)
        node = children[part]
        node["size"] += size
        node["actual"] += actual
        node["expected"] += expected
        if row.metric_ratio_true is not None:
            if size > 0:
                node["ratio_weight_total"] += row.metric_ratio_true * size
                node["ratio_weight"] += size
            node["ratio_sum"] += row.metric_ratio_true
            node["ratio_count"] += 1


def _node_ratio(node: dict[str, Any]) -> float | None:
    expected = _finite_float(node["expected"])
    if expected is not None and expected > 0:
        return (node["actual"] or 0.0) / expected
    if node["ratio_weight"] > 0:
        return node["ratio_weight_total"] / node["ratio_weight"]
    if node["ratio_count"] > 0:
        return node["ratio_sum"] / node["ratio_count"]
    return None


def _layout_leaves(
    node: dict[str, Any],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    depth: int = 0,
) -> list[dict[str, Any]]:
    children = list(node["children"].values())
    if not children:
        return [
            {
                "label": node["label"],
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "size": node["size"],
                "ratio": _node_ratio(node),
            }
        ]
    total = sum(max(child["size"], 0.0) for child in children)
    if total <= 0:
        total = float(len(children))
        weights = [1.0 for _ in children]
    else:
        weights = [max(child["size"], 0.0) for child in children]

    leaves: list[dict[str, Any]] = []
    cursor = x if depth % 2 == 0 else y
    for index, child in enumerate(children):
        fraction = weights[index] / total if total else 0.0
        if depth % 2 == 0:
            child_width = width * fraction
            leaves.extend(
                _layout_leaves(
                    child,
                    x=cursor,
                    y=y,
                    width=child_width,
                    height=height,
                    depth=depth + 1,
                )
            )
            cursor += child_width
        else:
            child_height = height * fraction
            leaves.extend(
                _layout_leaves(
                    child,
                    x=x,
                    y=cursor,
                    width=width,
                    height=child_height,
                    depth=depth + 1,
                )
            )
            cursor += child_height
    return leaves


def render_treemap_svg(
    rows: list[VisualRow],
    *,
    metric: str,
    title: str,
    width: int,
    height: int,
    style: str,
) -> str:
    """Render a deterministic slice-and-dice risk treemap as SVG."""

    columns = metric_columns(metric)
    palette = _style_palette(style)
    root = _tree_node("A/E cohorts")
    for row in rows:
        _add_tree_row(root, row)
    plot_x = 32
    plot_y = 92
    plot_width = width - 64
    plot_height = height - 130
    leaves = _layout_leaves(root, x=plot_x, y=plot_y, width=plot_width, height=plot_height)
    parts = [
        f'  <rect width="{width}" height="{height}" fill="{palette["bg"]}" />',
        f'  <text x="32" y="42" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="{palette["text"]}">{escape(title)}</text>',
        f'  <text x="32" y="68" font-family="Arial, sans-serif" font-size="13" fill="{palette["muted"]}">Size basis: {escape(columns.treemap_size)}. Color basis: A/E ratio centered at 1.0.</text>',
    ]
    for leaf in leaves:
        if leaf["width"] <= 0 or leaf["height"] <= 0:
            continue
        color = _ratio_color(leaf["ratio"])
        label = escape(_shorten_label(str(leaf["label"]), 28))
        parts.append(f'  <rect x="{leaf["x"]:.1f}" y="{leaf["y"]:.1f}" width="{leaf["width"]:.1f}" height="{leaf["height"]:.1f}" fill="{color}" stroke="#ffffff" stroke-width="1" />')
        if leaf["width"] >= 72 and leaf["height"] >= 34:
            parts.append(f'  <text x="{leaf["x"] + 6:.1f}" y="{leaf["y"] + 18:.1f}" font-family="Arial, sans-serif" font-size="11" fill="#172033">{label}</text>')
            parts.append(f'  <text x="{leaf["x"] + 6:.1f}" y="{leaf["y"] + 33:.1f}" font-family="Arial, sans-serif" font-size="10" fill="#334155">A/E {_format_number(leaf["ratio"])}</text>')
    parts.append(f'  <text x="32" y="{height - 24}" font-family="Arial, sans-serif" font-size="11" fill="{palette["muted"]}">Color scale saturates at {COLOR_SCALE_MIN:.1f} and {COLOR_SCALE_MAX:.1f}; true values are preserved in the visual spec.</text>')
    return _svg_document(
        title,
        f"{columns.label} A/E risk treemap sized by {columns.treemap_size}.",
        width,
        height,
        "\n".join(parts),
    )


def render_table_svg(
    rows: list[VisualRow],
    *,
    metric: str,
    title: str,
    width: int,
    height: int,
    style: str,
) -> str:
    """Render a report-ready cohort detail table as SVG."""

    columns = metric_columns(metric)
    palette = _style_palette(style)
    headers = ["Evidence", "Cohort", "Actual", "Expected", "A/E", "CI"]
    col_widths = [110, max(220, width - 730), 115, 125, 90, 170]
    x_positions = [28]
    for col_width in col_widths[:-1]:
        x_positions.append(x_positions[-1] + col_width)
    table_y = 92
    row_height = min(34, max(24, (height - table_y - 36) / max(len(rows) + 1, 1)))
    parts = [
        f'  <rect width="{width}" height="{height}" fill="{palette["bg"]}" />',
        f'  <text x="32" y="42" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="{palette["text"]}">{escape(title)}</text>',
        f'  <text x="32" y="68" font-family="Arial, sans-serif" font-size="13" fill="{palette["muted"]}">Sanitized cohort detail table for {escape(columns.label)} A/E.</text>',
        f'  <rect x="24" y="{table_y - row_height + 4:.1f}" width="{width - 48}" height="{row_height:.1f}" fill="#e7eef5" />',
    ]
    for index, header in enumerate(headers):
        parts.append(f'  <text x="{x_positions[index] + 4:.1f}" y="{table_y - 8:.1f}" font-family="Arial, sans-serif" font-size="12" font-weight="700" fill="{palette["text"]}">{escape(header)}</text>')
    for row_index, row in enumerate(rows):
        y = table_y + row_height * row_index
        if row_index % 2 == 0:
            parts.append(f'  <rect x="24" y="{y - row_height + 4:.1f}" width="{width - 48}" height="{row_height:.1f}" fill="#ffffff" opacity="0.7" />')
        values = [
            row.evidence_ref,
            _shorten_label(row.sanitized_dimensions, 46),
            _format_number(row.metric_actual_true),
            _format_number(row.metric_expected_true),
            _format_number(row.metric_ratio_true),
            _format_ci(row.metric_ci_lower_true, row.metric_ci_upper_true),
        ]
        for col_index, value in enumerate(values):
            parts.append(f'  <text x="{x_positions[col_index] + 4:.1f}" y="{y:.1f}" font-family="Arial, sans-serif" font-size="11" fill="{palette["text"]}">{escape(value)}</text>')
    return _svg_document(
        title,
        f"{columns.label} A/E sanitized cohort detail table.",
        width,
        height,
        "\n".join(parts),
    )


def _visual_hash(parameters: dict[str, Any]) -> str:
    encoded = json.dumps(
        normalize_json_value(parameters),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:10]


def _artifact_paths(
    context: WorkflowContext,
    *,
    source_path: Path,
    metric: str,
    style: str,
    visual_parameter_hash: str,
) -> dict[str, Path]:
    source_stem = _slug(source_path.stem)
    base = f"{source_stem}_{metric}_{style}_{visual_parameter_hash}"
    return {
        "forest_svg": context.visuals_dir / f"ae_forest_{base}.svg",
        "treemap_svg": context.visuals_dir / f"ae_treemap_{base}.svg",
        "table_svg": context.visuals_dir / f"ae_table_{base}.svg",
        "table_csv": context.visuals_dir / f"ae_table_{base}.csv",
        "spec_json": context.visuals_dir / f"ae_visual_spec_{base}.json",
    }


def _required_visual_columns(metric: str) -> list[str]:
    columns = metric_columns(metric)
    return list(
        dict.fromkeys(
            [
                *AE_SUMMARY_COLUMNS,
                columns.actual,
                columns.expected,
                columns.ratio,
                columns.ci_lower,
                columns.ci_upper,
                columns.treemap_size,
            ]
        )
    )


def _build_visual_spec(
    *,
    source_path: Path,
    source_hash: str,
    source_manifest: dict[str, Any],
    source_entry: dict[str, Any] | None,
    metric: str,
    style: str,
    output_format: str,
    title: str,
    width: int,
    height: int,
    top_n: int,
    visual_parameter_hash: str,
    selected_rows: list[VisualRow],
    treemap_rows: list[VisualRow],
    warnings: list[dict[str, Any]],
    artifact_paths: dict[str, Path],
) -> dict[str, Any]:
    source_parameters = source_entry.get("parameters", {}) if source_entry else {}
    return normalize_json_value(
        {
            "schema_version": AE_VISUAL_SPEC_SCHEMA_VERSION,
            "source_ae_path": str(source_path),
            "source_content_hash": source_hash,
            "source_parameters_found": source_entry is not None,
            "source_min_claims": source_parameters.get("min_claims") if source_entry else None,
            "source_sort_by": source_parameters.get("sort_by") if source_entry else None,
            "source_group_by": source_parameters.get("group_by") if source_entry else [],
            "state_fingerprint": source_manifest.get("state_fingerprint"),
            "metric": metric,
            "style": style,
            "format": output_format,
            "title": title,
            "width": width,
            "height": height,
            "top_n": top_n,
            "source_order_preserved": True,
            "source_row_count": len(treemap_rows),
            "selected_top_n_row_count": len(selected_rows),
            "axis": {"min": FOREST_AXIS_MIN, "max": FOREST_AXIS_MAX},
            "color_scale": {
                "min": COLOR_SCALE_MIN,
                "center": COLOR_SCALE_CENTER,
                "max": COLOR_SCALE_MAX,
            },
            "visual_parameter_hash": visual_parameter_hash,
            "forest_table_rows": [row.to_spec_dict() for row in selected_rows],
            "treemap_rows": [row.to_spec_dict() for row in treemap_rows],
            "warnings": warnings,
            "generated_artifacts": {key: str(path) for key, path in artifact_paths.items()},
            "package_version": PACKAGE_VERSION,
        }
    )


def generate_visual_bundle(
    context: WorkflowContext,
    *,
    metric: str,
    ae_path: str | Path | None = None,
    output_format: str = "svg",
    style: str = "formal",
    title: str | None = None,
    width: int = DEFAULT_VISUAL_WIDTH,
    height: int = DEFAULT_VISUAL_HEIGHT,
    top_n: int = MAX_TOP_N,
) -> dict[str, Any]:
    """Generate deterministic visual artifacts from an aggregate A/E CSV."""

    metric_columns(metric)
    if output_format not in VALID_VISUAL_FORMATS:
        raise ValueError("format must be svg.")
    if style not in VALID_VISUAL_STYLES:
        raise ValueError(f"style must be one of {sorted(VALID_VISUAL_STYLES)}.")
    validate_visual_dimensions(width, height)

    source_path = Path(ae_path).expanduser().resolve() if ae_path else context.latest_ae_path
    if source_path is None or not source_path.exists():
        raise FileNotFoundError("No A/E summary artifact exists. Run grouped A/E analysis first.")
    if source_path.suffix.lower() != ".csv":
        raise ValueError(f"A/E summary artifact must be a CSV file, got `{source_path.suffix or '<none>'}`.")

    ae_df = pd.read_csv(source_path)
    missing = [column for column in _required_visual_columns(metric) if column not in ae_df.columns]
    if missing:
        raise ValueError(f"A/E artifact is missing required visual columns: {missing}.")
    if ae_df.empty:
        raise ValueError("A/E artifact has no cohorts available to visualize.")
    ae_df = ae_df.loc[:, AE_SUMMARY_COLUMNS]

    source_manifest, source_entry = _load_source_manifest(context, source_path)
    source_hash = file_sha256(source_path)
    visual_title = title or f"{metric_columns(metric).label} A/E Visual Exhibit"
    selected_limit = min(max(1, top_n), MAX_TOP_N)
    all_rows, warnings = _prepare_rows(ae_df, metric)
    selected_rows = all_rows[:selected_limit]

    parameter_payload = {
        "source_hash": source_hash,
        "metric": metric,
        "style": style,
        "format": output_format,
        "title": visual_title,
        "width": width,
        "height": height,
        "top_n": selected_limit,
    }
    visual_parameter_hash = _visual_hash(parameter_payload)
    artifact_paths = _artifact_paths(
        context,
        source_path=source_path,
        metric=metric,
        style=style,
        visual_parameter_hash=visual_parameter_hash,
    )

    context.ensure_dirs()
    forest_svg = render_forest_svg(
        selected_rows,
        metric=metric,
        title=f"{visual_title} - Forest Plot",
        width=width,
        height=height,
        style=style,
    )
    treemap_svg = render_treemap_svg(
        all_rows,
        metric=metric,
        title=f"{visual_title} - Risk Treemap",
        width=width,
        height=height,
        style=style,
    )
    table_svg = render_table_svg(
        selected_rows,
        metric=metric,
        title=f"{visual_title} - Cohort Detail",
        width=width,
        height=height,
        style=style,
    )
    artifact_paths["forest_svg"].write_text(forest_svg, encoding="utf-8")
    artifact_paths["treemap_svg"].write_text(treemap_svg, encoding="utf-8")
    artifact_paths["table_svg"].write_text(table_svg, encoding="utf-8")
    _build_review_frame(selected_rows).to_csv(artifact_paths["table_csv"], index=False)

    spec = _build_visual_spec(
        source_path=source_path,
        source_hash=source_hash,
        source_manifest=source_manifest,
        source_entry=source_entry,
        metric=metric,
        style=style,
        output_format=output_format,
        title=visual_title,
        width=width,
        height=height,
        top_n=selected_limit,
        visual_parameter_hash=visual_parameter_hash,
        selected_rows=selected_rows,
        treemap_rows=all_rows,
        warnings=warnings,
        artifact_paths=artifact_paths,
    )
    artifact_paths["spec_json"].write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    context.artifact_manifest_path = context.default_artifact_manifest_path
    context.methodology_log_path = context.default_methodology_log_path
    manifest_parameters = {
        "ae_path": str(source_path),
        "metric": metric,
        "style": style,
        "format": output_format,
        "top_n": selected_limit,
        "width": width,
        "height": height,
        "generated_artifact_paths": {key: str(path) for key, path in artifact_paths.items()},
        "visual_parameter_hash": visual_parameter_hash,
    }
    append_methodology_event(
        context.default_methodology_log_path,
        MethodologyEvent(
            step_name="A/E visualization bundle generated",
            tool_name="visualize",
            input_path=str(source_path),
            output_path=str(artifact_paths["spec_json"]),
            parameters=manifest_parameters,
        ),
    )
    artifact_types = {
        "forest_svg": "ae_visual_forest_svg",
        "treemap_svg": "ae_visual_treemap_svg",
        "table_svg": "ae_visual_table_svg",
        "table_csv": "ae_visual_table_csv",
        "spec_json": "ae_visual_spec",
    }
    for key, artifact_type in artifact_types.items():
        upsert_artifact_entry(
            context.default_artifact_manifest_path,
            artifact_type=artifact_type,
            path=artifact_paths[key],
            generating_tool="visualize",
            parameters=manifest_parameters,
            source_artifacts=source_artifact("ae_summary", source_path),
        )
    context.write()
    return {
        "ok": True,
        "kind": "visualization",
        "message": f"Generated A/E visualization bundle at `{context.visuals_dir}`.",
        "artifacts": {key: str(path) for key, path in artifact_paths.items()},
        "data": {
            "metric": metric,
            "style": style,
            "format": output_format,
            "source_row_count": len(all_rows),
            "selected_top_n_row_count": len(selected_rows),
            "visual_parameter_hash": visual_parameter_hash,
        },
    }
