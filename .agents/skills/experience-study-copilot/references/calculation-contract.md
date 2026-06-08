# Calculation Contract

Python owns all deterministic calculations.

Required MVP columns:

- `MAC`
- `MOC`
- `MEC`
- `MAF`
- `MEF`

Common MVP dimensions:

- `Gender`
- `Smoker`
- `Risk_Class`
- `Product_Group`
- `Study_Year`

Raw numeric fields are not eligible grouping dimensions in MVP:

- `Issue_Age`
- `Age`
- `Duration`
- `Face_Amount`

Engineered categorical dimensions created by deterministic feature engineering are eligible grouping dimensions. Examples include:

- `Issue_Age_Band`
- `Face_Amount_Band`
- `Duration_Band`
- `Risk_Class_Group`

Use `experience-study band` before A/E analysis to create categorical bands from numeric fields. Use `experience-study regroup` before A/E analysis to collapse categorical values into new cohort dimensions.

A/E output columns:

- `Dimensions`
- `Sum_MAC`
- `Sum_MOC`
- `Sum_MEC`
- `Sum_MAF`
- `Sum_MEF`
- `AE_Ratio_Count`
- `AE_Ratio_Amount`
- `AE_Count_CI_Lower`
- `AE_Count_CI_Upper`
- `AE_Amount_CI_Lower`
- `AE_Amount_CI_Upper`

Filters are applied before aggregation. `--min-claims` is applied after aggregation as `Sum_MAC >= N`.
