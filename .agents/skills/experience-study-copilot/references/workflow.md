# Workflow Reference

## State Check

Use doctor when the output directory may already contain artifacts:

```bash
uv run experience-study doctor --output-dir <DIR>
```

## Standard File-Based Workflow

```bash
uv run experience-study profile <DATA_PATH> --output-dir <DIR>
uv run experience-study validate --output-dir <DIR>
uv run experience-study band --output-dir <DIR> --source-column Face_Amount --new-column Face_Amount_Band --strategy quantile --bins 4
uv run experience-study ae --output-dir <DIR> --measure both --group-by Gender
uv run experience-study packet --output-dir <DIR>
```

Feature engineering is optional. Use `band` for numeric-to-categorical dimensions and `regroup` for categorical-to-regrouped dimensions before grouped A/E analysis.

After `band` or `regroup`, rerun grouped A/E analysis before building a packet. Feature engineering updates the prepared dataset and clears stale latest A/E and packet pointers in workflow context.

## One-Shot Workflow

```bash
uv run experience-study run <DATA_PATH> \
  --output-dir <DIR> \
  --ae-by Gender \
  --ae-by Gender Smoker \
  --measure both \
  --min-claims 1 \
  --top-n 10
```

The `run` command stops before A/E analysis if validation returns `FAIL`.

The `run` command does not perform custom feature engineering. For feature-engineered dimensions, use the standard file-based workflow.
