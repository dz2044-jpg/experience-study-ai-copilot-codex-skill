# Current Supported Capabilities

Use this reference as the execution boundary for user-facing Experience Study workflow requests. If current CLI help disagrees with this file, treat CLI help as the source of truth and report the mismatch.

## Supported Workflow Actions

- Profile a CSV or Parquet dataset: `experience-study profile`
- Inspect prepared or source dataset schema: `experience-study schema`
- Run actuarial validation checks: `experience-study validate`
- Create numeric cohort bands: `experience-study band`
- Regroup categorical values into a new cohort dimension: `experience-study regroup`
- Run grouped count, amount, or combined count/amount A/E analysis: `experience-study ae`
- Build a sanitized aggregate AI A/E packet: `experience-study packet`
- Generate deterministic A/E visual exhibits from aggregate A/E summaries: `experience-study visualize`
- Inspect workflow artifact readiness: `experience-study doctor`
- Run the standard profile, validate, A/E, and packet workflow: `experience-study run`

## Unsupported Unless Explicitly Implemented Later

- Interactive dashboards or Streamlit UI actions
- Custom visualization types beyond the current `experience-study visualize` outputs
- Word, PDF, PowerPoint, Google Workspace, or Excel exports
- Direct database querying
- Raw row-level interpretation
- Package-level LLM clients or model-orchestrated calculations
- New CLI commands, artifact contracts, or workflow features not present in current CLI help

For unsupported requests, do not edit source files, tests, docs, or skill files, and do not emulate the missing capability. State that the current Experience Study CLI does not support the requested action, list the closest supported workflow actions, and ask whether the user wants an implementation plan.
