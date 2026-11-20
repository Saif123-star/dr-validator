---
name: dr-review
description: Start or resume a DR review, and optionally publish one approved Confluence review page.
agent: dr-reviewer
---

Coordinate a DR review using the repository's configured workflow.

Review directory or Function Key: ${input:review}
Requested scope (full or targeted): ${input:scope}
Additional context: ${input:context}

Follow `prompts_review/00_master.md`. Review work is read-only: DR, BR, and
attachments come only from the captured snapshot in
`runs/<FunctionKey>/reviews`. If no snapshot exists, explain that a human must
create it with `scripts/review/init_dr_review.py`, from local files or from
Confluence page IDs; do not silently create or modify source documents.

The only permitted external write is one new Confluence review page, created
through `prompts_review/50_publication_plan.md` after the user approves the
publication plan in their own words.
