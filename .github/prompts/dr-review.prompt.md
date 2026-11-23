---
name: dr-review
description: Start or resume a DR review and create a local Markdown report with verified findings.
agent: dr-reviewer
argument-hint: "Function Key, DR URL, BR URL; or an existing review directory"
---

Use the inputs supplied in the chat message to start or resume the review.
For a new review, take the Function Key and both Confluence page URLs. For an
existing review, take its directory and resume from its saved status without
capturing the pages again. Ask only for missing required inputs.

Follow the `dr-reviewer` orchestration instructions: invoke the applicable
subagents and run the review commands yourself. Do not hand stage execution or
JSON handling back to the user. Do not pause for finding decisions. On
completion, automatically create `review_report.md` and an evidence snapshot
containing the original extracted source detail. Keep Confluence read-only and
never write review results there.
