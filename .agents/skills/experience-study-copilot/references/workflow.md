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
uv run experience-study ae --output-dir <DIR> --measure both --group-by Gender
uv run experience-study packet --output-dir <DIR>
```

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
