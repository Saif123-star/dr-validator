# Publication Plan and Approval

Publication creates exactly one new Confluence page: a child of the reviewed
DR page that lists the findings whose human decision is `accept`. It never
edits the DR, never adds comments, and never touches other systems.

## Preconditions

- Review status is `completed` (every finding verified, reconciled, and
  decided).
- The review was initialized with the DR page ID and version.
- `.env` (or the environment) holds real `CONFLUENCE_BASE_URL`,
  `CONFLUENCE_EMAIL`, and `CONFLUENCE_API_TOKEN` values.

## Steps

1. **Plan:** run `scripts/review/build_publish_plan.py <review_dir>`. This
   writes `publication/plan.md`, `plan.json`, and the page preview
   `review_page.storage.html`, and writes nothing to Confluence.
2. **Present:** give the user an itemized summary of `plan.md`: action, parent
   page, title, included findings, excluded findings with reasons, DR baseline
   version, and plan hash. Offer the preview file for inspection.
3. **Approve:** wait for the user to approve in their own words. Record it
   verbatim with
   `scripts/review/approve_publish_plan.py <review_dir> --approved-by "<name>" --statement "<words>"`.
   The approval locks the plan hash in `publication/approved.json`. Never
   fabricate, paraphrase, or assume approval. If the user asks for changes,
   change the review data, rebuild the plan, and ask again.
4. **Publish:** run `scripts/review/publish_dr_review.py <review_dir>`.
   - Preflight: the DR must still be at the reviewed version; nothing is
     written otherwise.
   - Publish gate, before each item: the plan, page body, findings, and
     approval hashes must match, and earlier items must have succeeded.
   - Each item is written, read back, and its page ID recorded in
     `publication/publication_log.json`. The first failure stops the run.
5. **Retry:** after a failure, report the error. Only when the user asks to
   retry, rerun the same command. It checks Confluence for a page it already
   created (by title, parent, and publication marker), adopts it instead of
   creating a duplicate, and resumes.
6. **Verify:** run `scripts/review/check_review_publication.py <review_dir>`
   and report the page URL and result.
