# DR Reviewer

DR Reviewer implements an orchestrated design-requirement review. It creates an
immutable evidence snapshot for a DR, its BR, and attachments (from local files
or read-only from Confluence Cloud); produces a shared review brief; validates
and merges evidence-backed findings; imports independent verification results;
and automatically writes a reviewer-friendly, action-oriented local report.

The CLI handles snapshots, deterministic validation/merging,
verification-result import, reconciliation-result import, decisions,
and local report generation. The `.github/agents` and `prompts_review`
files define specialist instructions for VS Code; the CLI does not
autonomously launch agents. Semantic verification remains independent human
or agent work. Confluence is read-only: the DR is never edited and review
results are never written back to Confluence.

## Requirements

- Python 3.12 or newer
- PyYAML 6.0 or newer (installed from `pyproject.toml`)

Install with `python -m pip install -e .`. Then run `python -m dr_reviewer` or
use the `dr-review` command from any directory.

## Layout

- `.github/agents/` — the `dr-reviewer` orchestrator (which may delegate and
  run the workflow scripts) and five read-only specialist/verification agents
- `.github/prompts/dr-review.prompt.md` — VS Code prompt to start a DR review
- `config/review/` — pipeline stages, severity policy, evidence authority, and
  Confluence settings (`confluence.yaml`)
- `prompts_review/` — shared workflow, track prompts, merge, verify, reconcile,
  decision-package, and local review-comments instructions
- `schemas/review/` — JSON Schemas for state, sources, findings, verification,
  and decisions
- `scripts/review/` — command-line entry points for the workflow
- `src/dr_reviewer/` — package implementation behind both scripts and CLI

### Start or resume in VS Code

Select **`dr-reviewer`** in the agent picker in VS Code Copilot Chat and send
one message:

```text
Start a full review. Function Key: WSMB010104; DR URL: <DR URL>; BR URL: <BR URL>
```

For an existing snapshot, send `Resume .\runs\WSMB010104\reviews\R001`.
The orchestrator uses the saved status to resume without re-fetching the pages.
It invokes the applicable specialists, validates and merges their findings,
invokes the verifier and (only when needed) reconciler, and saves their outputs.
You do not run the individual prompts, agents, or import commands yourself.
Full reviews check the DR against the BR and audit the DR itself: declared
field lengths for the same field, references to every Item Description
component, API contracts across worksheets, and cross-section contradictions.
The orchestrator prepares a hash-checked `.xlsx` evidence view for the
reviewers and reports any coverage limits. For a targeted review, select
`technical_mapping` and `internal_consistency` to include these checks.
After verification and any required reconciliation, the orchestrator creates
`review_report.md` and `evidence_snapshot.md` in the review folder and presents
the findings directly. The report uses readable finding IDs, source comparison
tables, exact review locations, business impacts, suggested owners, testing
guidance, and a development-readiness assessment. No user acceptance step is
required. VS Code may prompt you to allow workflow tool calls.

If you use VS Code's Local harness, the `/dr-review` prompt also accepts
the same inputs directly in chat. The Python CLI alone does not invoke agents.

## Manual CLI reference

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

`fetch_review_sources.py` uses the same capture arguments: source
acquisition is part of initialization so the baseline is created atomically.
The installed equivalent is `python -m dr_reviewer init`.

Page IDs, versions, URLs, and reviewer identity are optional for local-only
sources and are stored as review provenance when supplied.

### Capture from Confluence (read-only)

Copy `.env.example` to `.env` and set `CONFLUENCE_BASE_URL`
(`https://<site>.atlassian.net`), `CONFLUENCE_EMAIL`, and
`CONFLUENCE_API_TOKEN`. Environment variables override `.env`; `--env-file`
selects another file. Placeholder values are rejected before any request.
Then omit `--dr`/`--br` and pass page IDs:

```powershell
python scripts/review/init_dr_review.py --function-key WSMB010104 `
  --dr-page-id 1819377813 --br-page-id 1818689539 --reviewer "Reviewer Name"
```

The storage-format body of each page is saved as an HTML snapshot with its
current version. Only attachments linked or embedded in those captured page
bodies are downloaded as attachment sources; older, unreferenced attachments
are excluded. Pass `--dr-version`/`--br-version` to pin a version; capture
fails if the page has moved on. Local and Confluence sources can be mixed, for
example a Confluence DR with a local `--br` file. Review tracks only read the
snapshot.

You can also pass the full Confluence page URLs:

```powershell
python scripts/review/init_dr_review.py --function-key WSMB010104 `
  --dr-url "https://<site>.atlassian.net/wiki/spaces/ABC/pages/1819377813/Design+Requirements" `
  --br-url "https://<site>.atlassian.net/wiki/spaces/ABC/pages/1818689539/Business+Requirements"
```

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
paths. Source snapshots are hash-checked before evidence is accepted. The
original extracted source detail is rendered to `evidence_snapshot.md`; hashes
remain integrity metadata in `manifest.json`.
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

## Findings and reports

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
deterministically and retain an internal stable key; the report assigns
readable IDs such as `WSMB010114-TRC-001` or `WSMB010114-API-001`. After
independent verification and any required reconciliation, the workflow directly
creates `review_report.md` and `evidence_snapshot.md`; no user acceptance step
is required. To re-check the snapshot manifest, run
`python scripts/review/build_source_registry.py <review_dir>`.

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

Import it and render the report:

```powershell
python -m dr_reviewer verifications-import .\runs\WSMB010104\reviews\R001 `
  .\verification-results.json
python scripts/review/reconcile_findings.py .\runs\WSMB010104\reviews\R001 `
  .\reconciliation-results.json
python -m dr_reviewer report .\runs\WSMB010104\reviews\R001
python -m dr_reviewer status .\runs\WSMB010104\reviews\R001
```

If merge or verification exposes conflicting severity or recommendations, use
`reconciliation.template.json` as the input shape for
`python -m dr_reviewer reconciliations-import <review_dir> <results.json>`.

An optional structured function map can be imported with
`python scripts/review/build_function_map.py <review_dir> <function-map.json>`.
Each entry can contain `business_function`,
`screen_or_chapter`, `ui_component`, `ui_event`, `validation`, `api`,
`request_response_field`, `db_mapping`, and `testable_outcome`.

The pipeline records the selected review scope and track set. It rejects
findings outside that scope and findings without in-snapshot quotes. The report
is generated after every finding is independently verified and all flagged
conflicts have been reconciled.

## Local review deliverables

When the review reaches `completed`, the orchestrator automatically generates:

- `review_report.md` — the reviewer-facing report with an executive summary,
  readable finding IDs, source comparisons, exact locations, impacts, owners,
  testing scenarios, statuses, and development readiness.
- `evidence_snapshot.md` — original extracted source detail for reviewers.

Both files remain under `runs/<FunctionKey>/reviews/<ReviewId>/`.

```powershell
python -m dr_reviewer review-comments .\runs\WSMB010104\reviews\R001
```

Confluence is read-only and used only to capture source pages and attachments.
The workflow never creates Confluence pages or comments and never edits the DR.
Evidence citation checks are deterministic; they do not replace semantic
verification.

## Tests

```powershell
python -m unittest discover -s tests -v
```
