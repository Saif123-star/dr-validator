---
name: dr-review
description: Start or resume a local, read-only design-requirement review.
agent: dr-reviewer
---

Coordinate a Phase 1 DR review using the repository's configured workflow.

Review directory or Function Key: ${input:review}
Requested scope (full or targeted): ${input:scope}
Additional context: ${input:context}

Follow `prompts_review/00_master.md`. Confirm that the review is local and
read-only, that no live external evidence source is available, and that no
external write is allowed. Use the existing `runs/<FunctionKey>/reviews`
snapshot when a review directory is supplied. If no snapshot exists, explain
that a human must create it with `scripts/review/init_dr_review.py`; do not
silently create or modify source documents.
