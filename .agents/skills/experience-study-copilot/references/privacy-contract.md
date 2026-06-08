# Privacy Contract

AI interpretation may use only sanitized aggregate artifacts.

Deterministic Python feature engineering may read and update the prepared row-level dataset. Codex may orchestrate those commands, but interpretation must still use only aggregate artifacts and sanitized packets.

Allowed inputs for interpretation:

- A/E summary CSVs from `artifacts/ae/`
- `artifacts/ai/ai_ae_packet.json`
- audit metadata from `artifacts/audit/`

Do not send raw source data, prepared row-level data, policy-level records, claim-level records, or unapproved columns to an LLM.

Engineered dimension names and aggregate cohort labels may appear in A/E summaries and AI packets after masking checks. Raw row-level source values must not be inspected for interpretation.

Sensitive values and dimensions must be masked before interpretation. Examples include:

- `Policy_Number`
- names
- DOBs
- addresses
- emails
- phone numbers
- SSNs
- applicant/member/certificate/account identifiers

Low-volume cohorts should be masked or flagged before interpretation.
