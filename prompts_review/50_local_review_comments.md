# Local Review Comments

The orchestrator generates `review_comments.md` automatically when the review
reaches `completed`. Do not publish this report to Confluence.

The file includes only findings whose recorded human decision is `accept`.
For every accepted finding, include its stable ID, severity, title, summary,
impact, recommendation, verification result and rationale, reconciliation
result when applicable, decision owner and timestamp, and exact snapshot
citations (source ID, locator, and quote). Include the DR/BR page IDs and
versions, review scope, selected tracks, and completion time.

If no findings are accepted, write an explicit statement that no findings
were accepted. Do not silently omit this case or turn an incomplete review
into an empty result.

Keep the full finding set, including rejected, deferred, and unresolved items,
in `review_report.md`; `review_comments.md` is specifically the accepted
comments deliverable.
