# Privacy Contract

AI interpretation may use only sanitized aggregate artifacts.

Allowed inputs for interpretation:

- A/E summary CSVs from `artifacts/ae/`
- `artifacts/ai/ai_ae_packet.json`
- audit metadata from `artifacts/audit/`

Do not send raw source data, prepared row-level data, policy-level records, claim-level records, or unapproved columns to an LLM.

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
