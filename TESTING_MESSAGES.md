# Experience Study Testing Messages

Use these messages to test the end-to-end Experience Study workflow, deterministic calculation path, feature-engineering path, audit artifacts, and fallback/error behavior.

Each section includes:

- **Testing message**: paste this into Codex.
- **Suggested response**: the kind of response Codex should provide if the workflow behaves correctly.

## 1. Happy Path End-To-End Workflow

**Testing message**

```text
Use data/input/synthetic_inforce.csv. Run an end-to-end Experience Study A/E workflow in runs/test_e2e_gender: profile, validate, run count and amount A/E by Gender, build the sanitized AI packet, then summarize which CLI commands were used and which artifacts were produced.
```

**Suggested response**

```text
Completed the end-to-end deterministic Experience Study workflow in runs/test_e2e_gender.

Commands run:
- uv run experience-study profile data/input/synthetic_inforce.csv --output-dir runs/test_e2e_gender
- uv run experience-study validate --output-dir runs/test_e2e_gender
- uv run experience-study ae --output-dir runs/test_e2e_gender --measure both --group-by Gender
- uv run experience-study packet --output-dir runs/test_e2e_gender

Deterministic calculations were performed by Python through the Experience Study CLI, not by Codex manually.

Key artifacts:
- runs/test_e2e_gender/workflow_context.json
- runs/test_e2e_gender/artifacts/analysis_inforce.parquet
- runs/test_e2e_gender/artifacts/ae/latest.csv
- runs/test_e2e_gender/artifacts/ae/ae_summary_by_gender.csv
- runs/test_e2e_gender/artifacts/audit/methodology_log.json
- runs/test_e2e_gender/artifacts/audit/artifact_manifest.json
- runs/test_e2e_gender/artifacts/ai/ai_ae_packet.json
```

## 2. Feature Engineering Then A/E

**Testing message**

```text
Use data/input/synthetic_inforce.csv and output dir runs/test_face_amount_bands. Profile and validate the dataset. Create 4 equal-frequency Face_Amount_Band cohorts from Face_Amount, then run amount A/E grouped by Face_Amount_Band, build the sanitized packet, and tell me where the deterministic calculation happened.
```

**Suggested response**

```text
Completed Face_Amount_Band feature engineering and amount A/E by the engineered cohort.

Calculation path:
- Feature engineering happened in deterministic Python through experience-study band, backed by experience_study.feature_engineering.run_band.
- A/E aggregation happened in deterministic Python through experience-study ae, backed by experience_study.analysis.run_ae_analysis.
- The AI packet was built only from aggregate A/E output, not row-level records.

Expected commands:
- uv run experience-study profile data/input/synthetic_inforce.csv --output-dir runs/test_face_amount_bands
- uv run experience-study validate --output-dir runs/test_face_amount_bands
- uv run experience-study band --output-dir runs/test_face_amount_bands --source-column Face_Amount --new-column Face_Amount_Band --strategy quantile --bins 4
- uv run experience-study ae --output-dir runs/test_face_amount_bands --measure amount --group-by Face_Amount_Band
- uv run experience-study packet --output-dir runs/test_face_amount_bands
```

## 3. Custom Banding

**Testing message**

```text
Use data/input/synthetic_inforce.csv and output dir runs/test_custom_face_amount. Create custom Face_Amount_Band groups with bins [0,250000,500000,1000000,null] and labels ["0-250K","250K-500K","500K-1M","1M+"]. Then run amount A/E by Face_Amount_Band and show the artifact paths.
```

**Suggested response**

```text
Created custom Face_Amount_Band cohorts and ran amount A/E by the engineered dimension.

The custom banding used deterministic Python through experience-study band with --strategy custom. The final null in the bin list created an open-ended upper bin.

Expected artifacts:
- runs/test_custom_face_amount/artifacts/analysis_inforce.parquet
- runs/test_custom_face_amount/artifacts/ae/ae_summary_by_face_amount_band.csv
- runs/test_custom_face_amount/artifacts/ae/latest.csv
- runs/test_custom_face_amount/artifacts/audit/methodology_log.json
- runs/test_custom_face_amount/artifacts/audit/artifact_manifest.json

The methodology log should include a band event with source_column Face_Amount, new_column Face_Amount_Band, strategy custom, custom_bins, and labels.
```

## 4. Categorical Regroup

**Testing message**

```text
Use data/input/synthetic_inforce.csv and output dir runs/test_risk_regroup. Regroup Risk_Class into Risk_Class_Group with Preferred = Preferred Plus and Preferred, Standard = Standard Plus and Standard, Substandard = Table A and Table B. Then run count A/E by Risk_Class_Group and build the packet.
```

**Suggested response**

```text
Created Risk_Class_Group with deterministic categorical regrouping, then ran count A/E by Risk_Class_Group and built the sanitized AI packet.

Calculation path:
- Regrouping happened through experience-study regroup.
- Count A/E aggregation happened through experience-study ae.
- Packet generation used the aggregate A/E CSV only.

Expected artifacts:
- runs/test_risk_regroup/artifacts/analysis_inforce.parquet
- runs/test_risk_regroup/artifacts/ae/ae_summary_by_risk_class_group.csv
- runs/test_risk_regroup/artifacts/ai/ai_ae_packet.json
- runs/test_risk_regroup/artifacts/audit/methodology_log.json
- runs/test_risk_regroup/artifacts/audit/artifact_manifest.json
```

## 5. State And Readiness Check

**Testing message**

```text
Use output dir runs/test_face_amount_bands. Before running any new analysis, inspect workflow readiness with doctor and tell me whether prepared data, latest A/E, and packet artifacts are available.
```

**Suggested response**

```text
Inspected workflow readiness with doctor.

Report:
- prepared_data: true or false
- latest_ae: true or false
- latest_packet: true or false
- artifact_manifest: true or false
- methodology_log: true or false

If latest A/E or latest packet is missing, the fallback is to rerun experience-study ae and then experience-study packet after confirming the prepared dataset exists.
```

## 6. Stale Packet Guardrail

**Testing message**

```text
Use output dir runs/test_stale_packet. Profile data/input/synthetic_inforce.csv, validate, run A/E by Gender, and build a packet. Then create a new Face_Amount_Band feature. After that, try to build a packet without rerunning A/E and explain why it fails or what fallback action is needed.
```

**Suggested response**

```text
The packet build after feature engineering should fail because feature engineering clears stale latest A/E and packet pointers in workflow_context.json.

This is expected behavior. The prepared dataset changed, so the prior A/E summary no longer represents the current prepared data.

Fallback action:
- Rerun grouped A/E using the intended current dimension.
- Then rebuild the packet.

Example:
- uv run experience-study ae --output-dir runs/test_stale_packet --measure amount --group-by Face_Amount_Band
- uv run experience-study packet --output-dir runs/test_stale_packet
```

## 7. Raw Numeric Dimension Rejection

**Testing message**

```text
Use data/input/synthetic_inforce.csv and output dir runs/test_raw_numeric_reject. Profile and validate, then try to run A/E grouped directly by Face_Amount. Explain why this is rejected and what deterministic feature-engineering command should be used instead.
```

**Suggested response**

```text
Running A/E grouped directly by Face_Amount should be rejected because raw numeric fields are not eligible A/E grouping dimensions.

The correct deterministic fallback is to create a categorical cohort dimension first.

Example:
- uv run experience-study band --output-dir runs/test_raw_numeric_reject --source-column Face_Amount --new-column Face_Amount_Band --strategy quantile --bins 4
- uv run experience-study ae --output-dir runs/test_raw_numeric_reject --measure both --group-by Face_Amount_Band

The calculation remains in Python. Codex should not manually calculate A/E ratios.
```

## 8. Missing Column Error

**Testing message**

```text
Use data/input/synthetic_inforce.csv and output dir runs/test_missing_column. Profile the dataset, then try to create bands from a source column named Not_A_Real_Column. Report the exact failure and the fallback next step.
```

**Suggested response**

```text
The banding command should fail because Not_A_Real_Column is not present in the prepared dataset.

Expected failure:
- Column `Not_A_Real_Column` was not found in the prepared dataset.

Fallback action:
- Run experience-study schema or doctor to inspect available columns.
- Choose an existing numeric source column such as Face_Amount, Issue_Age, Age, or Duration.
- Retry experience-study band with the correct column name.
```

## 9. Validation Failure Stops A/E

**Testing message**

```text
Use output dir runs/test_validation_failure. Create or use an invalid dataset where MAC has a value other than 0 or 1, then run the standard workflow. Confirm that validation stops the workflow before A/E analysis and identify the audit artifact that records it.
```

**Suggested response**

```text
Validation should fail before A/E analysis because MAC must be 0 or 1.

Expected behavior:
- profile succeeds.
- validate returns FAIL.
- A/E analysis is not run.
- No latest A/E summary should be created for this failed run.

Audit artifact:
- runs/test_validation_failure/artifacts/audit/methodology_log.json

The methodology log should include profile and validate events, with validation parameters showing status FAIL and a nonzero issue_count.
```

## 10. Ambiguous User Request

**Testing message**

```text
Use data/input/synthetic_inforce.csv. I want A/E for Term by study year. If this is ambiguous between filtering for Term versus grouping by Product_Group, ask me the clarification you need before running the calculation.
```

**Suggested response**

```text
I need one clarification before running this: should "for Term" mean filter the analysis to Product_Group = Term and group by Study_Year, or should I group by both Product_Group and Study_Year?
```

## 11. Audit Trail Inspection

**Testing message**

```text
Use output dir runs/test_face_amount_bands. Inspect the methodology log and artifact manifest. Tell me which steps happened, which tool created Face_Amount_Band, and whether the prepared dataset hash changed after feature engineering.
```

**Suggested response**

```text
The audit trail should show the workflow sequence in artifacts/audit/methodology_log.json.

Expected steps:
- Source dataset profiled
- Validation checks run
- Feature engineering band created
- Grouped A/E analysis run
- Sanitized AI A/E packet built

Face_Amount_Band should be created by tool_name band.

The artifact manifest should show the prepared_dataset entry generated by band after feature engineering, with a content_hash different from the original prepared dataset hash recorded before the band step.
```

## 12. Privacy Boundary Inspection

**Testing message**

```text
Use output dir runs/test_face_amount_bands. Inspect the sanitized AI packet and confirm whether it contains engineered dimension names but not raw policy-level values. Explain what data Codex is allowed to interpret.
```

**Suggested response**

```text
The sanitized AI packet may contain engineered aggregate dimension names such as Face_Amount_Band and aggregate cohort labels.

It should not contain raw policy-level values such as Policy_Number values or row-level records.

Codex is allowed to interpret:
- aggregate A/E summary CSVs
- artifacts/ai/ai_ae_packet.json
- audit metadata

Codex should not interpret raw source rows or prepared row-level data.
```

## Quick Coverage Map

| Test | Exercises |
| --- | --- |
| Happy path | profile, validate, A/E, packet, artifacts |
| Feature engineering then A/E | quantile banding, amount A/E, privacy boundary |
| Custom banding | custom bins, labels, open-ended upper bound |
| Categorical regroup | regroup mapping, count A/E |
| State/readiness check | doctor, fallback readiness |
| Stale packet guardrail | context clearing after feature engineering |
| Raw numeric rejection | invalid grouping dimension fallback |
| Missing column error | source-column validation |
| Validation failure | validation stops before A/E |
| Ambiguous request | clarification before calculation |
| Audit trail inspection | methodology log and manifest behavior |
| Privacy boundary inspection | packet-only interpretation |
