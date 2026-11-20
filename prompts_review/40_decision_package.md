# Human Decision Package

Present the function key and review baseline, evidence availability and
limitations, coverage by track, function map, verified/reconciled must-change
findings, findings awaiting a human decision, and optional observations.

For every finding, include its stable ID, severity, confidence, impact,
evidence and locators, recommendation, verification verdict, reconciliation
status, and proposed disposition. Offer `accept`, `reject`, `defer`,
`already_addressed`, `needs_clarification`, or `accepted_risk`.

Record decision owner, timestamp, optional rationale, and intended follow-up.
Only after all required findings are verified, reconciled, and decided, render
`review_comments.md` with findings whose decision is `accept`. This local
deliverable is generated automatically; it is not published to Confluence.
DR edits are never performed.
