# Artifact Reference

Workflow state:

- `workflow_context.json`

Prepared data:

- `artifacts/analysis_inforce.parquet`
- `band` and `regroup` update this prepared dataset in place and refresh its manifest content hash.

A/E summaries:

- `artifacts/ae/ae_summary_by_<slug>.csv`
- `artifacts/ae/latest.csv`
- `artifacts/ae/latest_1way.csv`
- `artifacts/ae/latest_2way.csv`

Audit:

- `artifacts/audit/methodology_log.json`
- `artifacts/audit/artifact_manifest.json`

AI packet:

- `artifacts/ai/ai_ae_packet.json`

Slug rules: lowercase column names, replace non-alphanumeric characters with `_`, collapse repeated `_`, trim leading/trailing `_`, and preserve column order.

Canonical A/E summaries contain the full eligible grouped result. `--top-n` affects display and packet selection only.

Feature engineering clears stale latest A/E and packet pointers in `workflow_context.json`, but historical A/E and packet files remain on disk for auditability. Rerun `ae` after feature engineering before building a new packet.
