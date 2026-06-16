# Visualization Reference

Use `experience-study visualize` to generate deterministic A/E visual exhibits from aggregate A/E summary artifacts.

## Routing

- If workflow state is unclear, run `uv run experience-study doctor --output-dir <DIR>`.
- If no latest A/E artifact exists, run grouped A/E analysis before visualization.
- If the user does not specify count or amount, ask which metric they want.
- Do not inspect raw source rows or prepared row-level data for visualization interpretation.

## Commands

Count A/E visuals:

```bash
uv run experience-study visualize --output-dir <DIR> --metric count
```

Amount A/E visuals:

```bash
uv run experience-study visualize --output-dir <DIR> --metric amount
```

Explicit A/E artifact:

```bash
uv run experience-study visualize --output-dir <DIR> --metric amount --ae-path <CSV>
```

## Outputs

Visualization writes a bundle under `artifacts/visuals/`:

- horizontal forest plot SVG
- risk treemap SVG
- cohort detail table SVG
- review table CSV
- canonical visual spec JSON

Report generated artifact paths directly. For visual results, mention that forest/table preserve source A/E artifact order and that the treemap uses all source cohorts.
