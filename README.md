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

Feature engineering example:

```bash
uv run experience-study band \
  --output-dir runs/demo \
  --source-column Face_Amount \
  --new-column Face_Amount_Band \
  --strategy quantile \
  --bins 4

uv run experience-study ae \
  --output-dir runs/demo \
  --measure amount \
  --group-by Face_Amount_Band
```

## CLI

```bash
experience-study profile DATA_PATH --output-dir DIR
experience-study schema --output-dir DIR [--data-path PATH]
experience-study validate --output-dir DIR [--data-path PATH]
experience-study band --output-dir DIR --source-column COL --new-column COL --strategy equal-width|quantile|custom
experience-study regroup --output-dir DIR --source-column COL --new-column COL --mapping-json JSON
experience-study ae --output-dir DIR --measure count|amount|both --group-by COL [COL ...]
experience-study packet --output-dir DIR [--ae-path PATH]
experience-study doctor --output-dir DIR
experience-study run DATA_PATH --output-dir DIR [--ae-by COL [COL ...]]...
```

`band` and `regroup` perform deterministic feature engineering on the prepared dataset created by `profile`. They update `artifacts/analysis_inforce.parquet`, refresh the prepared dataset entry in the artifact manifest, and clear stale latest A/E and packet pointers. Historical A/E files remain on disk for auditability, but rerun `ae` before building a new packet.

Use `band` to turn numeric fields into categorical cohort dimensions:

```bash
uv run experience-study band \
  --output-dir runs/demo \
  --source-column Face_Amount \
  --new-column Face_Amount_Band \
  --strategy custom \
  --custom-bins '[0,250000,500000,1000000,null]' \
  --labels '["0-250K","250K-500K","500K-1M","1M+"]'
```

Use `regroup` to collapse existing categorical values:

```bash
uv run experience-study regroup \
  --output-dir runs/demo \
  --source-column Risk_Class \
  --new-column Risk_Class_Group \
  --mapping-json '{"Preferred":["Preferred Plus","Preferred"],"Standard":["Standard Plus","Standard"],"Substandard":["Table A","Table B"]}'
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

Raw numeric fields such as `Issue_Age`, `Duration`, and `Face_Amount` remain ineligible as A/E grouping dimensions. Create engineered categorical dimensions first, then run grouped A/E analysis on those new columns.

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
