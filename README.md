# DR Reviewer

DR Reviewer is a local-first, read-only implementation of the first release in
the implementation plan. It creates an immutable evidence snapshot for a DR,
its BR, and optional attachments; produces a shared review brief; validates and
merges evidence-backed findings; imports independent verification results;
records human decisions; and renders a review report.

The workspace did not contain an existing application, source pipeline, or
agent runtime, so this is a standalone Python package. It does not execute
review agents or call external services. Findings and verification results are
provided as JSON, and semantic judgment remains with the reviewer. Nothing is
published or written back to source systems.

## Requirements

- Python 3.12 or newer
- No third-party runtime packages

Install the local package once with `python -m pip install -e .`. Then run
`python -m dr_reviewer` or use the `dr-review` command from any directory.

## Start a review

```powershell
python -m dr_reviewer init `
  --function-key WSMB010104 `
  --dr .\input\published-dr.docx `
  --br .\input\business-requirements.docx `
  --attachments .\input\attachments `
  --dr-page-id 1819377813 --dr-version 4 `
  --br-page-id 1818689539 --br-version 11 `
  --reviewer "Reviewer Name" `
  --runs-dir .\runs
```

Page IDs, versions, URLs, and reviewer identity are optional for local-only
sources and are stored as review provenance when supplied.

The command creates `runs/<FunctionKey>/reviews/R001/` with:

- `state.json` and `manifest.json` for review state and source provenance
- `sources/` containing copies of all supplied files
- `review_brief.md`, `agent_findings.template.json`, and `finding.schema.json`
- `verification.template.json`, `findings.json`, and `function_map.json`

The review stores source filenames, content hashes, capture timestamps, source
types, and text-extraction status. It does not store the original absolute input
paths. Source snapshots are hash-checked before evidence is accepted.

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

Have the specialist reviewers fill `agent_findings.template.json` and import
it:

```powershell
python -m dr_reviewer findings-import .\runs\WSMB010104\reviews\R001 `
  .\reviewer-findings.json
```

Every finding must conform to `finding.schema.json` and cite at least one exact
quote from a captured, text-extractable source. Duplicate findings are merged
deterministically and receive stable IDs.

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
python -m dr_reviewer decide .\runs\WSMB010104\reviews\R001 `
  DRV-WSMB010104-R001-0123456789 --decision accept --owner "Reviewer"
python -m dr_reviewer report .\runs\WSMB010104\reviews\R001
python -m dr_reviewer status .\runs\WSMB010104\reviews\R001
```

Decision values: `accept`, `reject`, `defer`, `already_addressed`,
`needs_clarification`, and `accepted_risk`. The `--action` option records
intended follow-up as text only; it never performs that action.

An optional structured function map can be imported with
`function-map-import`. Each entry can contain `business_function`,
`screen_or_chapter`, `ui_component`, `ui_event`, `validation`, `api`,
`request_response_field`, `db_mapping`, and `testable_outcome`.

## Current boundary

This first release intentionally stops at a local review report. It does not
implement remote source acquisition, agent execution, publishing, re-review
deltas, or controlled DR patching. These require the existing application
pipeline and external integration details, neither of which are present in
this workspace. Evidence citation checks are deterministic; they do not
replace semantic verification.

## Tests

```powershell
python -m unittest discover -s tests -v
```
