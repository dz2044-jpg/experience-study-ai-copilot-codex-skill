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

Visual exhibits:

- `artifacts/visuals/ae_forest_<source>_<metric>_<style>_<hash>.svg`
- `artifacts/visuals/ae_treemap_<source>_<metric>_<style>_<hash>.svg`
- `artifacts/visuals/ae_table_<source>_<metric>_<style>_<hash>.svg`
- `artifacts/visuals/ae_table_<source>_<metric>_<style>_<hash>.csv`
- `artifacts/visuals/ae_visual_spec_<source>_<metric>_<style>_<hash>.json`

Slug rules: lowercase column names, replace non-alphanumeric characters with `_`, collapse repeated `_`, trim leading/trailing `_`, and preserve column order.

Canonical A/E summaries contain the full eligible grouped result. `--top-n` affects display, packet selection, and forest/table visual selection only. Treemap visuals use all source A/E rows.

Feature engineering clears stale latest A/E and packet pointers in `workflow_context.json`, but historical A/E and packet files remain on disk for auditability. Rerun `ae` after feature engineering before building a new packet.
