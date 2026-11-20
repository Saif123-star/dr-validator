# DR Reviewer

DR Reviewer is a local-first, read-only implementation of the first release in
the implementation plan. It creates an immutable evidence snapshot for a DR,
its BR, and optional attachments; produces a shared review brief; validates and
merges evidence-backed findings; imports independent verification results;
records human decisions; and renders a review report.

This workspace contains no existing source pipeline or external service
connector. The CLI handles local snapshots, deterministic validation/merging,
verification-result import, reconciliation-result import, decisions, and
reporting. The `.github/agents` and `prompts_review` files define specialist
instructions for VS Code; the CLI does not autonomously launch agents.
Semantic verification remains independent human or agent work. Nothing is
published or written back to source systems.

## Requirements

- Python 3.12 or newer
- PyYAML 6.0 or newer (installed from `pyproject.toml`)

Install with `python -m pip install -e .`. Then run `python -m dr_reviewer` or
use the `dr-review` command from any directory.

## Phase 1 layout

- `.github/agents/` — orchestrator and five specialist/verification agent
  definitions, restricted to read/search tools
- `.github/prompts/dr-review.prompt.md` — VS Code prompt to start a local DR
  review
- `config/review/` — phase pipeline, severity policy, and evidence authority
- `prompts_review/` — shared workflow, track prompts, merge, verify, reconcile,
  and decision-package instructions
- `schemas/review/` — JSON Schemas for state, sources, findings, verification,
  and decisions
- `scripts/review/` — command-line entry points for the Phase 1 workflow
- `src/dr_reviewer/` — package implementation behind both scripts and CLI

Open `.github/prompts/dr-review.prompt.md` in VS Code to start the
`dr-reviewer` coordination workflow. The prompt requires an existing local
snapshot; use the initialization script below to create it first.

## Start a review

```powershell
python scripts/review/init_dr_review.py `
  --function-key WSMB010104 `
  --dr .\input\published-dr.docx `
  --br .\input\business-requirements.docx `
  --attachments .\input\attachments `
  --context-source workshop_decision=.\input\workshop-decisions.md `
  --context-source figma_export=.\input\figma-export.pdf `
  --context-source comment_export=.\input\comments.html `
  --dr-page-id 1819377813 --dr-version 4 `
  --br-page-id 1818689539 --br-version 11 `
  --reviewer "Reviewer Name" `
  --runs-dir .\runs
```

`fetch_review_sources.py` uses the same local-only capture arguments: source
acquisition is part of initialization so the baseline is created atomically.
The installed equivalent is `python -m dr_reviewer init`.

Page IDs, versions, URLs, and reviewer identity are optional for local-only
sources and are stored as review provenance when supplied.
Repeat `--context-source TYPE=PATH` to register local workshop-decision,
design-export, or comment-export files under their configured authority. These
are imported local evidence; the reviewer does not retrieve them remotely.

The command creates `runs/<FunctionKey>/reviews/R001/` with:

- `state.json` and `manifest.json` for review state and source provenance
- `sources/` containing copies of all supplied files
- `review_brief.md`, `agent_findings.template.json`, and the applicable schemas
- `verification.template.json`, `decision.template.json`,
  `reconciliation.template.json`, `findings.json`, and `function_map.json`

The review stores source filenames, content hashes, capture timestamps, source
types, and text-extraction status. It does not store the original absolute input
paths. Source snapshots are hash-checked before evidence is accepted.
The authority and severity settings are loaded from `config/review/`.

Supported text extraction includes DOCX, XLSX, UTF-8 text, Markdown, CSV, HTML,
XML, JSON, YAML, and common text formats. Images are retained as evidence but
not OCR-processed. PDF and legacy Office files are retained but marked as
unsupported for text extraction.

For targeted reviews, supply at least one track:

```powershell
python -m dr_reviewer init --function-key WSMB010104 `
  --dr .\input\published-dr.docx --br .\input\business-requirements.docx `
  --scope targeted --tracks br_traceability technical_mapping
```

Available tracks: `document_integrity`, `br_traceability`,
`internal_consistency`, `ui_ux_context`, and `technical_mapping`.

## Findings and decisions

Have the specialist reviewers fill `agent_findings.template.json`. Validate it
without changing review state, then merge it:

```powershell
python scripts/review/validate_findings.py .\runs\WSMB010104\reviews\R001 `
  .\reviewer-findings.json
python scripts/review/merge_findings.py .\runs\WSMB010104\reviews\R001 `
  .\reviewer-findings.json
```

Every finding must conform to `finding.schema.json` and cite at least one exact
quote from a captured, text-extractable source. Duplicate findings are merged
deterministically and receive stable IDs. To re-check the snapshot manifest,
run `python scripts/review/build_source_registry.py <review_dir>`.

An independent verifier supplies a file shaped like:

```json
{
  "verifications": [
    {
      "finding_id": "DRV-WSMB010104-R001-0123456789",
      "verdict": "verified",
      "rationale": "The evidence is present and the surrounding section confirms it."
    }
  ]
}
```

Import it, record a human disposition, and render the report:

```powershell
python -m dr_reviewer verifications-import .\runs\WSMB010104\reviews\R001 `
  .\verification-results.json
python scripts/review/reconcile_findings.py .\runs\WSMB010104\reviews\R001 `
  .\reconciliation-results.json
python -m dr_reviewer decide .\runs\WSMB010104\reviews\R001 `
  DRV-WSMB010104-R001-0123456789 --decision accept --owner "Reviewer"
python -m dr_reviewer report .\runs\WSMB010104\reviews\R001
python -m dr_reviewer status .\runs\WSMB010104\reviews\R001
```

Decision values: `accept`, `reject`, `defer`, `already_addressed`,
`needs_clarification`, and `accepted_risk`. The `--action` option records
intended follow-up as text only; it never performs that action.

Verification must cover the whole finding set before decisions can be recorded.
If merge or verification exposes conflicting severity or recommendations, use
`reconciliation.template.json` as the input shape for
`python -m dr_reviewer reconciliations-import <review_dir> <results.json>`.

An optional structured function map can be imported with
`python scripts/review/build_function_map.py <review_dir> <function-map.json>`.
Each entry can contain `business_function`,
`screen_or_chapter`, `ui_component`, `ui_event`, `validation`, `api`,
`request_response_field`, `db_mapping`, and `testable_outcome`.

The pipeline records the selected review scope and track set. It rejects
findings outside that scope, findings without in-snapshot quotes, and human
decisions until every finding has been independently verified and all flagged
conflicts have been reconciled.

## Current boundary

This first release intentionally stops at a local review report. It does not
implement remote source acquisition, automatic agent invocation, publishing,
re-review deltas, or controlled DR patching. These require the existing
application pipeline and external integration details, neither of which are
present in this workspace. Evidence citation checks are deterministic; they
do not replace semantic verification.

## Tests

```powershell
python -m unittest discover -s tests -v
```
