"""Shared deterministic contracts for Experience Study A/E analysis."""

from __future__ import annotations

PACKAGE_VERSION = "0.1.0"

REQUIRED_NUMERIC_COLUMNS: tuple[str, ...] = ("MAC", "MOC", "MEC", "MAF", "MEF")
COUNT_ACTUAL_COL = "MAC"
COUNT_EXPOSURE_COL = "MOC"
COUNT_EXPECTED_COL = "MEC"
AMOUNT_ACTUAL_COL = "MAF"
AMOUNT_EXPECTED_COL = "MEF"

COMMON_MVP_DIMENSIONS: tuple[str, ...] = (
    "Gender",
    "Smoker",
    "Risk_Class",
    "Product_Group",
    "Study_Year",
)

EXCLUDED_DIMENSIONS: set[str] = {
    "Policy_Number",
    "MAC",
    "MOC",
    "MEC",
    "MAF",
    "MEF",
    "COLA",
}

SEMANTIC_NUMERIC_NON_DIMENSIONS: set[str] = {
    "Face_Amount",
    "Issue_Age",
    "Age",
    "Duration",
}

AE_SUMMARY_COLUMNS: list[str] = [
    "Dimensions",
    "Sum_MAC",
    "Sum_MOC",
    "Sum_MEC",
    "Sum_MAF",
    "Sum_MEF",
    "AE_Ratio_Count",
    "AE_Ratio_Amount",
    "AE_Count_CI_Lower",
    "AE_Count_CI_Upper",
    "AE_Amount_CI_Lower",
    "AE_Amount_CI_Upper",
]

VALID_SORT_COLUMNS: set[str] = {
    "AE_Ratio_Count",
    "AE_Ratio_Amount",
    "Sum_MAC",
    "Sum_MOC",
    "Sum_MEC",
    "Sum_MAF",
    "Sum_MEF",
}

VALID_MEASURES: set[str] = {"count", "amount", "both"}
SUPPORTED_INPUT_SUFFIXES: set[str] = {".csv", ".parquet"}
MAX_TOP_N = 20

WORKFLOW_CONTEXT_FILENAME = "workflow_context.json"
PREPARED_DATASET_FILENAME = "analysis_inforce.parquet"
METHODOLOGY_LOG_FILENAME = "methodology_log.json"
ARTIFACT_MANIFEST_FILENAME = "artifact_manifest.json"
AI_PACKET_FILENAME = "ai_ae_packet.json"

METHODOLOGY_LOG_SCHEMA_VERSION = "methodology_log.v1"
ARTIFACT_MANIFEST_SCHEMA_VERSION = "artifact_manifest.v1"
AI_AE_PACKET_SCHEMA_VERSION = "ai_ae_packet.v1"
AE_VISUAL_SPEC_SCHEMA_VERSION = "ae_visual_spec.v1"
