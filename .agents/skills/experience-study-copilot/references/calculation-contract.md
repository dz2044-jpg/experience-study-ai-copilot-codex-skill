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
