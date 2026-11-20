---
name: dr-review
description: Start or resume a DR review and create a local Markdown file of accepted findings.
agent: dr-reviewer
argument-hint: "Function Key, DR URL, BR URL; or an existing review directory"
---

Use the inputs supplied in the chat message to start or resume the review.
For a new review, take the Function Key and both Confluence page URLs. For an
existing review, take its directory and resume from its saved status without
capturing the pages again. Ask only for missing required inputs.

Follow the `dr-reviewer` orchestration instructions: invoke the applicable
subagents and run the review commands yourself. Do not hand stage execution or
JSON handling back to the user. Pause for finding decisions. On completion,
automatically create `review_comments.md` containing only findings the user
accepted. Keep Confluence read-only and never write review results there.
