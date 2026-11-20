# DR Review Workflow

## Mission

Produce a traceable, repeatable review of an existing DR against its BR and
supplied attachments. The orchestrator coordinates specialist work; it does
not perform the review. Review work is read-only with respect to source
documents and external systems. The only external write is one new
local Markdown file of human-accepted review comments.

## Baseline and evidence

1. Use one review directory under
   `runs/<FunctionKey>/reviews/<ReviewId>/`.
2. Read `state.json`, `manifest.json`, and `review_brief.md`.
3. Confirm each captured source exists and its SHA-256 matches the manifest.
   If a source is missing or changed, stop and report a stale or invalid
   baseline. Never switch to a newer file mid-review.
4. Use only the selected tracks in the review state. Do not infer the contents
   of images or unavailable attachments.
5. Do not retrieve or import evidence from sources outside the captured local
   snapshot.

## Phase gates

1. **Initialize:** snapshot the DR, BR, and attachments from local files or,
   read-only, from Confluence page IDs (page versions are recorded
   automatically). Record local page IDs/versions only when the user supplies
   them.
2. **Scope:** confirm full or targeted review and selected tracks. Keep a
   record of excluded areas.
3. **Review:** run structural checks and delegate semantic work to the matching
   specialist agent. Every finding needs exact evidence.
4. **Merge:** validate finding contracts and deterministically merge likely
   duplicates. Preserve track provenance, evidence, and conflicts.
5. **Verify:** use an independent verifier for each finding. A citation match
   alone is not semantic verification.
6. **Reconcile:** resolve flagged recommendation/severity conflicts as
   proposals. Keep unresolved issues visible.
7. **Decide:** present findings and options to the human. Decisions require
   owner, timestamp, and rationale when provided.
8. **Report:** render a local review report. Never edit the DR.
9. **Deliver:** automatically render `review_comments.md` in the review
   directory after completion. Include only findings whose recorded human
   decision is `accept`; preserve source citations and verification results.

## Completion

Do not describe a review as complete if required tracks, verification,
reconciliation, or decisions remain pending. A review with no findings may be
completed after the selected checks finish and the empty result is recorded.
Do not describe a review as complete until its local reports have been written.

## Limits

Confluence pages are fetched once at initialization into the snapshot; review
tracks never read live pages. Confluence remains read-only. The workflow does
not add comments or pages, edit the DR, touch Jira, retrieve design files, or
run delta reviews. Report missing capabilities instead of implying they were
checked.
