# Natural Language Examples

## A/E By One Dimension

User:
"Show A/E by Gender."

Interpretation:

- measure = both
- group_by = `Gender`
- filters = none

CLI:

```bash
uv run experience-study ae --output-dir <DIR> --measure both --group-by Gender
```

## Count A/E By Study Year Since 2021

User:
"Give me A/E by count by study year for each year since 2021."

Interpretation:

- measure = count
- group_by = `Study_Year`
- filters = `Study_Year >= 2021`

CLI:

```bash
uv run experience-study ae --output-dir <DIR> --measure count --group-by Study_Year --filters-json '[{"column":"Study_Year","op":">=","value":2021}]'
```

## Count A/E For A Product Group By Study Year

User:
"Give me A/E by count for Term product group by study year for each year since 2021."

Interpretation:

- measure = count
- group_by = `Study_Year`
- filters = `Product_Group == "Term"` and `Study_Year >= 2021`

CLI:

```bash
uv run experience-study ae --output-dir <DIR> --measure count --group-by Study_Year --filters-json '[{"column":"Product_Group","op":"==","value":"Term"},{"column":"Study_Year","op":">=","value":2021}]'
```

## A/E By Product Group And Study Year

User:
"Give me A/E by count by product group and study year since 2021."

Interpretation:

- measure = count
- group_by = `Product_Group`, `Study_Year`
- filters = `Study_Year >= 2021`

CLI:

```bash
uv run experience-study ae --output-dir <DIR> --measure count --group-by Product_Group Study_Year --filters-json '[{"column":"Study_Year","op":">=","value":2021}]'
```

## Amount A/E By Face Amount Percentile Bands

User:
"Create 4 percentile bands for face amount and show amount A/E by the new band."

Interpretation:

- feature engineering = quantile banding
- source_column = `Face_Amount`
- new_column = `Face_Amount_Band`
- bins = 4
- measure = amount
- group_by = `Face_Amount_Band`

CLI:

```bash
uv run experience-study band --output-dir <DIR> --source-column Face_Amount --new-column Face_Amount_Band --strategy quantile --bins 4
uv run experience-study ae --output-dir <DIR> --measure amount --group-by Face_Amount_Band
uv run experience-study packet --output-dir <DIR>
```

## Count A/E By Regrouped Risk Class

User:
"Regroup risk class into Preferred, Standard, and Substandard, then show count A/E."

Interpretation:

- feature engineering = categorical regroup
- source_column = `Risk_Class`
- new_column = `Risk_Class_Group`
- measure = count
- group_by = `Risk_Class_Group`

CLI:

```bash
uv run experience-study regroup \
  --output-dir <DIR> \
  --source-column Risk_Class \
  --new-column Risk_Class_Group \
  --mapping-json '{"Preferred":["Preferred Plus","Preferred"],"Standard":["Standard Plus","Standard"],"Substandard":["Table A","Table B","Table C"]}'

uv run experience-study ae --output-dir <DIR> --measure count --group-by Risk_Class_Group
uv run experience-study packet --output-dir <DIR>
```
