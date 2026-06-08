# Experience Study AI Copilot Codex Skill

This repo is a CLI-first deterministic workflow engine plus Codex skill interface for Experience Study A/E analysis. It is not a Streamlit conversion.

Python owns calculations and artifact generation. Codex owns workflow orchestration and interpretation of sanitized aggregate artifacts only.

## Setup

```bash
uv sync
```

## Smoke Test

```bash
uv run experience-study run data/input/synthetic_inforce.csv \
  --output-dir runs/demo \
  --ae-by Gender \
  --ae-by Gender Smoker \
  --measure both \
  --min-claims 1 \
  --top-n 10

uv run experience-study doctor --output-dir runs/demo
```

## CLI

```bash
experience-study profile DATA_PATH --output-dir DIR
experience-study schema --output-dir DIR [--data-path PATH]
experience-study validate --output-dir DIR [--data-path PATH]
experience-study ae --output-dir DIR --measure count|amount|both --group-by COL [COL ...]
experience-study packet --output-dir DIR [--ae-path PATH]
experience-study doctor --output-dir DIR
experience-study run DATA_PATH --output-dir DIR [--ae-by COL [COL ...]]...
```

`ae` performs grouped cohort A/E analysis. It supports one or two grouping columns in MVP. Use `--filters-json` for filters, for example:

```bash
uv run experience-study ae \
  --output-dir runs/demo \
  --measure count \
  --group-by Product_Group Study_Year \
  --filters-json '[{"column":"Study_Year","op":">=","value":2021}]'
```

When `Issue_Age` is present, profiling creates a deterministic categorical `Issue_Age_Band` dimension with four equal-width bands. Use `Issue_Age_Band` for age cohort A/E analysis; raw `Issue_Age` remains ineligible as an A/E grouping dimension.

## Artifacts

Artifacts are written below `--output-dir`:

- `workflow_context.json`
- `artifacts/analysis_inforce.parquet`
- `artifacts/ae/ae_summary_by_<slug>.csv`
- `artifacts/ae/latest.csv`
- `artifacts/ae/latest_1way.csv`
- `artifacts/ae/latest_2way.csv`
- `artifacts/audit/methodology_log.json`
- `artifacts/audit/artifact_manifest.json`
- `artifacts/ai/ai_ae_packet.json`

Canonical A/E summary CSVs contain the full eligible grouped result. `--top-n` only affects CLI display and AI packet selection.

## Privacy Boundary

AI packets are built only from aggregate A/E summary CSVs and audit metadata. They do not read source data or prepared row-level data. Sensitive dimensions and filters are masked before packet serialization.

## Tests

```bash
uv run pytest -q
```
