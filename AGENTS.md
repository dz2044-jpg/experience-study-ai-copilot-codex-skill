# AGENTS.md

## Repository Purpose

This repo is a CLI-first deterministic workflow engine plus Codex skill interface for Experience Study A/E analysis.

## Rules

- Python owns all calculations, aggregations, A/E ratios, confidence intervals, validation, and artifacts.
- Codex may orchestrate workflows and interpret aggregate artifacts only.
- Do not add package-level LLM clients.
- Do not port Streamlit UI, chat UI, sidebar code, session state, or UI workflow status from `../experience-study-ai-copilot`.
- Do not modify `../experience-study-ai-copilot`; it is read-only reference material.
- Preserve public CLI behavior and artifact contracts unless the user explicitly changes them.
- Use actuarial wording in user-facing text: A/E analysis, count A/E, amount A/E, grouped by, breakout, cohort, dimension, and study year.
- When reporting A/E results in a chat response, include the presentation-style cohort table directly in the message, not only artifact paths. Use count columns for count A/E, amount columns for amount A/E, and separate count and amount tables when both measures are shown.
- Avoid exposing raw row-level data to AI packet or interpretation flows.
- Run `uv run pytest -q` before considering implementation work complete.
