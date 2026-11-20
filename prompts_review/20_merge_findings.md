# Merge Findings

Validate all agent outputs against `schemas/review/finding.schema.json` and
against the locked source snapshots. Reject findings without evidence, a
precise affected location, an impact, a recommendation or decision request,
severity, and confidence.

Deduplicate deterministically using normalized rule ID, category, affected
section/control, evidence source and locator, title, and related function-map
identifier. Preserve every distinct evidence citation and originating track.
Use the highest severity provisionally, flag severity conflicts, and preserve
all distinct recommendations for reconciliation. Assign stable IDs only after
the merged groups are fixed. Never invent missing fields to make a finding pass.
