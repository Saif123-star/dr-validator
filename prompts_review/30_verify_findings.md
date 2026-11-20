# Independent Finding Verification

For each assigned finding, independently reopen the cited snapshot source.
Confirm the quote and locator, inspect surrounding context, check the rest of
the DR for resolving language, and compare the BR where relevant.

Return exactly one result per assigned finding using
`schemas/review/verification_result.schema.json`:

- `verified`
- `rejected`
- `downgraded`
- `upgraded`
- `duplicate`
- `needs_human_decision`
- `insufficient_evidence`

Provide a concise rationale. Use `duplicate_of` for duplicates and `severity`
for a justified changed severity. Do not make the human disposition.
