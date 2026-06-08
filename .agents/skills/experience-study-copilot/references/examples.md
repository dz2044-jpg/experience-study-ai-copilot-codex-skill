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
