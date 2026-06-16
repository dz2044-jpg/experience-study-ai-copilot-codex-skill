---
name: experience-study-copilot
description: "Use this skill for deterministic Experience Study A/E workflows: profiling CSV/Parquet files, validation, grouped count/amount A/E analysis, audit artifacts, sanitized aggregate packets, and A/E visualization exhibits such as plots, charts, forest plots, treemaps, tables, or visual reports. Use the CLI; never calculate A/E manually."
---

# Experience Study Copilot

Use this skill when the user asks for Experience Study, actual-to-expected, A/E, mortality experience, count A/E, amount A/E, grouped cohort analysis, feature engineering, banding, bucketing, regrouping, breakouts by actuarial dimensions, or deterministic A/E visual exhibits.

## Execution vs Development Mode

Default to Execution Mode. This skill is primarily for using the existing Experience Study CLI, not for implementing missing capabilities.

Before taking action:

1. Decide whether the request is Execution Mode or Development Mode.
2. If Execution Mode, use only existing CLI commands and artifacts.
3. If the requested capability is unsupported, do not edit files; give an unsupported-capability response.
4. If mode is ambiguous, ask whether the user wants to use existing functionality or change the repo.

Execution Mode includes tool-use wording such as "run", "show", "plot", "visualize", "create bands", "create a regrouped dimension", "generate the AI packet", and "generate amount A/E visuals". Plain "create" or "generate" must not trigger Development Mode by itself.

Development Mode requires explicit repo/code/implementation intent, such as "implement a new feature", "add support for", "modify the repo", "fix the code", "refactor the module", "edit files", "update the CLI implementation", or "create a PR".

For "Can you make the tool support X?" or similar phrasing, ask for confirmation before editing unless the user clearly requests implementation.

## Core Rules

- Python owns all calculations. Never calculate A/E ratios, confidence intervals, aggregations, or exposures manually.
- Use `uv run experience-study ...` commands from the repo root.
- Use current CLI help and `references/capabilities.md` as the capability boundary before deciding whether a user request can be fulfilled.
- Run `experience-study doctor --output-dir <DIR>` first when workflow state is unclear.
- Use only aggregate A/E artifacts and sanitized packets for interpretation.
- Do not inspect raw source rows or prepared row-level data for AI interpretation.
- Do not add or call package-level LLM clients.
- Prefer actuarial wording: A/E analysis, count A/E, amount A/E, grouped by, breakout, cohort, dimension, study year.
- Avoid saying "sweep" unless the user says it first.
- For visual requests, use `experience-study visualize`; never manually draw or invent A/E visual values.

## Workflow

1. Confirm or choose an `--output-dir`.
2. Profile the dataset if no prepared dataset exists.
3. Validate before A/E analysis.
4. Run deterministic feature engineering with `experience-study band` or `experience-study regroup` when the requested dimension does not already exist as an eligible categorical cohort dimension.
5. Run grouped A/E analysis with `experience-study ae`.
6. Build `artifacts/ai/ai_ae_packet.json` before any interpretation.
7. Interpret only the sanitized packet and aggregate CSV outputs.

Read references as needed:

- `references/workflow.md` for command sequences.
- `references/capabilities.md` for supported and unsupported user-facing capabilities.
- `references/calculation-contract.md` for required columns and output fields.
- `references/privacy-contract.md` for AI packet boundaries.
- `references/artifacts.md` for artifact locations and meaning.
- `references/visualization.md` for forest plot, treemap, and visual exhibit routing.
- `references/examples.md` for natural-language translation examples.

## Natural Language Mapping

- "A/E by count" means `--measure count`.
- "A/E by amount" means `--measure amount`.
- Unspecified measure means `--measure both`.
- "A/E by X" means `--group-by X`.
- "A/E by X and Y" is ambiguous unless the user explicitly says `1-way`, `2-way`, `pairwise`, `combined`, `interaction`, `separate`, `individually`, `each`, or `all pairs`; ask whether they want separate 1D breakouts or one combined multi-column cohort breakout.
- "Since 2021" for study year means filter `Study_Year >= 2021`.
- "For product group X" means filter `Product_Group == X`.
- "By product group" means group by `Product_Group`.
- "At least N claims" or "at least N deaths" means `--min-claims N`.
- "Band", "bucket", "bin", "turn numeric variable into bands", or "create categorical feature" means use `experience-study band` before A/E analysis.
- "Equal-width bands" means `experience-study band --strategy equal-width --bins N`.
- "Percentile", "quantile", "equal-frequency", or "roughly equal-sized groups" means `experience-study band --strategy quantile --bins N`.
- "Custom cut points" means `experience-study band --strategy custom --custom-bins JSON --labels JSON`.
- "Regroup", "collapse", "combine categories", or "map categories" means use `experience-study regroup` before A/E analysis.
- After `band` or `regroup`, rerun `experience-study ae` before `experience-study packet`; feature engineering clears stale latest A/E and packet pointers.
- "Plot count A/E", "show count A/E visuals", or "count forest plot" means `experience-study visualize --metric count`.
- "Plot amount A/E", "show amount A/E visuals", or "amount treemap" means `experience-study visualize --metric amount`.
- "Plot A/E", "visualize A/E", or "show charts" without count or amount is ambiguous; ask whether the user wants count A/E visuals or amount A/E visuals.
- If filtering versus grouping is ambiguous, ask a concise clarification before running.
