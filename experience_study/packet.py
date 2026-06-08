"""Sanitized AI packet construction from aggregate A/E artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

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
from experience_study.contracts import AE_SUMMARY_COLUMNS, AI_AE_PACKET_SCHEMA_VERSION, MAX_TOP_N

MASKED_COHORT_LABEL = "[masked cohort label]"
MASKED_DIMENSION_COLUMN = "[masked dimension]"
MASKED_FILTER_COLUMN = "[masked column]"
MASKED_FILTER_VALUE = "[masked value]"
SENSITIVE_DIMENSION_TERMS = {
    "policy",
    "policy_number",
    "name",
    "dob",
    "birth",
    "ssn",
    "email",
    "phone",
    "address",
    "zip",
    "postal",
    "member",
    "applicant",
    "insured",
    "id",
    "number",
    "account",
    "certificate",
}

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")
_SSN_RE = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")


class AICohortRow(BaseModel):
    """Sanitized aggregate cohort row for AI interpretation."""

    model_config = ConfigDict(extra="forbid")

    evidence_ref: str
    Dimensions: str
    Dimension_Columns: list[str] = Field(default_factory=list)
    Sum_MAC: float
    Sum_MOC: float
    Sum_MEC: float
    Sum_MAF: float
    Sum_MEF: float
    AE_Ratio_Count: float | None = None
    AE_Ratio_Amount: float | None = None
    AE_Count_CI_Lower: float | None = None
    AE_Count_CI_Upper: float | None = None
    AE_Amount_CI_Lower: float | None = None
    AE_Amount_CI_Upper: float | None = None
    low_credibility: bool = False
    masking_reason: str | None = None
    caution_flags: list[str] = Field(default_factory=list)


class AIAEPacket(BaseModel):
    """Sanitized A/E packet derived only from aggregate artifacts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = AI_AE_PACKET_SCHEMA_VERSION
    source_artifact_path: str
    source_content_hash: str
    state_fingerprint: str | None = None
    packet_fingerprint: str | None = None
    group_by: list[str] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    measure: str | None = None
    deterministic_min_claims: int = 0
    ai_masking_min_claims: int = 1
    rows: list[AICohortRow] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


def _dimension_tokens(column: str) -> set[str]:
    expanded = _CAMEL_BOUNDARY_RE.sub("_", column)
    tokens = [token.lower() for token in re.split(r"[^A-Za-z0-9]+", expanded) if token]
    token_set = set(tokens)
    if tokens:
        token_set.add("_".join(tokens))
    return token_set


def dimension_column_is_sensitive(column: str) -> bool:
    return bool(_dimension_tokens(column) & SENSITIVE_DIMENSION_TERMS)


def parse_dimension_label(dimensions: str) -> tuple[list[tuple[str, str]], list[str]]:
    parsed: list[tuple[str, str]] = []
    warnings: list[str] = []
    for part in str(dimensions).split(" | "):
        if "=" not in part:
            warnings.append("dimension_parse_warning")
            continue
        column, value = part.split("=", 1)
        column = column.strip()
        value = value.strip()
        if not column:
            warnings.append("dimension_parse_warning")
            continue
        parsed.append((column, value))
    return parsed, warnings


def value_looks_sensitive(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return bool(_EMAIL_RE.match(stripped) or _PHONE_RE.match(stripped) or _SSN_RE.match(stripped))


def sanitize_filters(filters: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sanitized: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for filter_spec in filters or []:
        column = str(filter_spec.get("column", ""))
        value = filter_spec.get("value")
        operator = filter_spec.get("operator", filter_spec.get("op"))
        if dimension_column_is_sensitive(column) or value_looks_sensitive(value):
            sanitized.append({"column": MASKED_FILTER_COLUMN, "operator": operator, "value": MASKED_FILTER_VALUE})
            warnings.append({"code": "sensitive_filter_masked", "message": "A sensitive or disallowed filter was masked."})
        else:
            sanitized.append({"column": column, "operator": operator, "value": value})
    return sanitized, warnings


def _numeric_or_none(value: Any) -> float | None:
    if pd.isna(value):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return numeric


def _packet_fingerprint(packet: AIAEPacket) -> str:
    payload = packet.model_dump(mode="json", exclude={"packet_fingerprint"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_ai_packet(
    context: WorkflowContext,
    *,
    ae_path: str | Path | None = None,
    top_n: int = MAX_TOP_N,
    masking_min_claims: int | None = None,
) -> dict[str, Any]:
    """Build and persist a sanitized aggregate A/E packet."""

    source_path = Path(ae_path).expanduser().resolve() if ae_path else context.latest_ae_path
    if source_path is None or not source_path.exists():
        raise FileNotFoundError("No A/E summary artifact exists. Run grouped A/E analysis first.")

    ae_df = pd.read_csv(source_path)
    missing = [column for column in AE_SUMMARY_COLUMNS if column not in ae_df.columns]
    if missing:
        raise ValueError(f"A/E artifact is missing required packet columns: {missing}.")
    ae_df = ae_df.loc[:, AE_SUMMARY_COLUMNS]

    manifest = (
        read_artifact_manifest(context.default_artifact_manifest_path)
        if context.default_artifact_manifest_path.exists()
        else {"fingerprint_inputs": {}, "state_fingerprint": None}
    )
    fingerprint_inputs = manifest.get("fingerprint_inputs") or {}
    group_by = list(fingerprint_inputs.get("group_by") or [])
    filters, filter_warnings = sanitize_filters(fingerprint_inputs.get("filters") or [])
    deterministic_min_claims = int(fingerprint_inputs.get("min_claims") or 0)
    ai_masking_min_claims = (
        int(masking_min_claims)
        if masking_min_claims is not None
        else max(1, deterministic_min_claims)
    )

    rows: list[AICohortRow] = []
    warnings = list(filter_warnings)
    packet_limit = min(max(1, top_n), MAX_TOP_N)
    for row_index, row in ae_df.head(packet_limit).iterrows():
        evidence_ref = f"row_{row_index + 1:04d}"
        parsed_dimensions, parse_warnings = parse_dimension_label(str(row["Dimensions"]))
        dimension_columns = [column for column, _ in parsed_dimensions]
        caution_flags = list(parse_warnings)
        for warning in parse_warnings:
            warnings.append({"code": warning, "message": "Unable to fully parse dimension label.", "evidence_refs": [evidence_ref]})

        sum_mac = _numeric_or_none(row["Sum_MAC"])
        if sum_mac is None:
            raise ValueError("Invalid numeric value in required A/E column `Sum_MAC`.")
        dimensions = str(row["Dimensions"])
        sanitized_dimension_columns = list(dimension_columns)
        low_credibility = False
        masking_reason = None

        if any(dimension_column_is_sensitive(column) for column in dimension_columns):
            dimensions = MASKED_COHORT_LABEL
            sanitized_dimension_columns = [MASKED_DIMENSION_COLUMN]
            low_credibility = True
            masking_reason = "sensitive_or_disallowed_dimension"
            caution_flags.append(masking_reason)
            warnings.append({"code": masking_reason, "message": "A sensitive or disallowed dimension was masked.", "evidence_refs": [evidence_ref]})
        elif sum_mac < ai_masking_min_claims:
            dimensions = MASKED_COHORT_LABEL
            low_credibility = True
            masking_reason = "low_volume"
            caution_flags.append("low_volume")

        values = {column: _numeric_or_none(row[column]) for column in AE_SUMMARY_COLUMNS if column != "Dimensions"}
        rows.append(
            AICohortRow(
                evidence_ref=evidence_ref,
                Dimensions=dimensions,
                Dimension_Columns=sanitized_dimension_columns,
                Sum_MAC=float(values["Sum_MAC"] or 0.0),
                Sum_MOC=float(values["Sum_MOC"] or 0.0),
                Sum_MEC=float(values["Sum_MEC"] or 0.0),
                Sum_MAF=float(values["Sum_MAF"] or 0.0),
                Sum_MEF=float(values["Sum_MEF"] or 0.0),
                AE_Ratio_Count=values["AE_Ratio_Count"],
                AE_Ratio_Amount=values["AE_Ratio_Amount"],
                AE_Count_CI_Lower=values["AE_Count_CI_Lower"],
                AE_Count_CI_Upper=values["AE_Count_CI_Upper"],
                AE_Amount_CI_Lower=values["AE_Amount_CI_Lower"],
                AE_Amount_CI_Upper=values["AE_Amount_CI_Upper"],
                low_credibility=low_credibility,
                masking_reason=masking_reason,
                caution_flags=list(dict.fromkeys(caution_flags)),
            )
        )

    packet = AIAEPacket(
        source_artifact_path=str(source_path),
        source_content_hash=file_sha256(source_path),
        state_fingerprint=manifest.get("state_fingerprint"),
        group_by=group_by,
        filters=normalize_json_value(filters),
        measure=fingerprint_inputs.get("measure"),
        deterministic_min_claims=deterministic_min_claims,
        ai_masking_min_claims=ai_masking_min_claims,
        rows=rows,
        warnings=list({json.dumps(warning, sort_keys=True): warning for warning in warnings}.values()),
    )
    packet.packet_fingerprint = _packet_fingerprint(packet)

    context.ensure_dirs()
    packet_path = context.default_packet_path
    packet_path.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
    context.latest_packet_path = packet_path
    context.artifact_manifest_path = context.default_artifact_manifest_path
    context.methodology_log_path = context.default_methodology_log_path

    append_methodology_event(
        context.default_methodology_log_path,
        MethodologyEvent(
            step_name="Sanitized AI A/E packet built",
            tool_name="packet",
            input_path=str(source_path),
            output_path=str(packet_path),
            parameters={"top_n": packet_limit, "masking_min_claims": ai_masking_min_claims},
        ),
    )
    upsert_artifact_entry(
        context.default_artifact_manifest_path,
        artifact_type="ai_ae_packet",
        path=packet_path,
        generating_tool="packet",
        parameters={"top_n": packet_limit, "masking_min_claims": ai_masking_min_claims},
        source_artifacts=source_artifact("latest_ae_summary", source_path),
    )
    context.write()
    return {
        "ok": True,
        "kind": "packet",
        "message": f"Built sanitized AI A/E packet at `{packet_path}`.",
        "artifacts": {"ai_ae_packet_path": str(packet_path)},
        "data": {"row_count": len(packet.rows), "packet_fingerprint": packet.packet_fingerprint},
    }
