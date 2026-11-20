# DR Review Workflow

## Mission

Produce a traceable, repeatable, local review of an existing DR against its BR
and supplied attachments. The orchestrator coordinates specialist work; it
does not perform the review. The workflow is read-only with respect to source
documents and external systems.

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

1. **Initialize:** snapshot local DR, BR, and optional attachments; record page
   IDs/versions only when the user supplies them.
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
8. **Report:** render a local review report. Do not publish or edit the DR.

## Completion

Do not describe a review as complete if required tracks, verification,
reconciliation, or decisions remain pending. A review with no findings may be
completed after the selected checks finish and the empty result is recorded.

## First-release limits

This phase supports local files and manual user-provided metadata only. It does
not fetch Confluence, retrieve design files, invoke an external service,
publish comments/pages, patch a DR, or run delta reviews. Report missing
capabilities instead of implying they were checked.
