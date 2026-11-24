# Independent Finding Verification

For each assigned finding, independently reopen the cited snapshot source.
Confirm the quote and locator, inspect surrounding context, check the rest of
the DR for resolving language, and compare the BR where relevant.

For a cross-sheet finding, check both cited worksheet locations in the
hash-checked workbook evidence view. Confirm the declarations refer to the
same field, component, or endpoint in context, and check for documented
exceptions or mappings that explain the difference. For an omission, confirm
that the target sheet is expected to contain the entry.

For `visual_observation` evidence, reopen the cited image and independently
confirm the described visual observation and region. Do not convert a static
image observation into a claim about runtime behavior.

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
