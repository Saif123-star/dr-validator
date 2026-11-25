# DR Validator

DR Validator is a read-only Design Requirement (DR) review system. It reviews
a DR against its Business Requirement (BR), attached workbooks, documents, and
UI images. It checks traceability, UI details, events, APIs, database
mappings, and consistency across the supplied sources.

The workflow captures source content locally, creates an immutable evidence
baseline, delegates specialist reviews through VS Code Copilot agents,
independently verifies findings, and generates a local Markdown report.

Confluence and the source documents are never edited. The system does not
create Confluence comments or pages, update Jira, or patch the DR.

For a simple explanation of the complete workflow and all agents, see
[Project working and agents guide](docs/project-working-and-agents.md).

## Requirements

- Python 3.12 or newer
- PyYAML 6.0 or newer
- VS Code with Copilot agent support for the orchestrated review

Install the package from the repository root:

```powershell
python -m pip install -e .
```

The Python CLI provides capture, validation, evidence, and report commands.
The VS Code `dr-reviewer` agent coordinates specialist agents; the CLI alone
does not autonomously launch them.

## Start a full review in VS Code

Select `dr-reviewer` in VS Code Copilot Chat and provide the function key and
the current DR and BR URLs:

```text
Start a full review.
Function Key: WCRM050105
DR URL: <DR URL>
BR URL: <BR URL>
```

The orchestrator:

1. Fetches the current DR, BR, and attachments from Confluence.
2. Creates a new review round and immutable local source snapshots.
3. Builds the source registry and review brief.
4. Runs the applicable specialist agents.
5. Validates and merges their findings.
6. Independently verifies every finding.
7. Reconciles only duplicate or conflicting findings when required.
8. Generates the final report and evidence snapshot.

The completion response in chat contains only:

- Review details
- Review directory
- Generated files
- Section results table

Finding details, evidence details, limitations, and validation information are
provided only when explicitly requested.

## Agents

| Agent | Use |
|---|---|
| `dr-reviewer` | Main orchestrator and only user-facing agent. Manages capture, delegation, validation, verification, reconciliation, and report generation. |
| `review-traceability` | Checks DR alignment with the BR, including business rules, roles, validations, required data, states, and error behavior. |
| `review-consistency` | Finds contradictions, duplicate definitions, inconsistent values, and cross-section or cross-sheet conflicts. |
| `review-ui-technical` | Reviews textual UI details, event mappings, API contracts, field constraints, UI-to-database mappings, and API-to-database mappings. |
| `review-vision` | Visually inspects image attachments. Its findings are reported in the UI Components section. |
| `review-verifier` | Independently verifies each submitted finding against the locked evidence. |
| `review-reconciler` | Resolves duplicate findings or severity/recommendation conflicts when required. |

`review-vision` uses visual inspection only. Static images cannot prove
runtime interaction, API execution, database persistence, permission
enforcement, accessibility compliance, keyboard behavior, or responsive
behavior.

## Review sections

Every report uses the same fixed sections:

1. UI Components
2. Event Mapping with API
3. API Mapping with Events and UI Components
4. DR API Coverage
5. Database Mapping with UI Components
6. Database Mapping with API
7. DR Alignment with BR
8. Cross-Section Consistency

Each section contains its findings table. A section without verified findings
contains a single placeholder row:

| ID | Severity | Finding | Source | BR Requirement | DR Requirement / Cross-Section Value | Review Location | Recommended Action |
|---|---|---|---|---|---|---|---|
| — | — | No verified gaps found | — | — | — | — | — |

There is no separate section summary, checks-performed block, or section
limitations block.

## Reviewer-friendly evidence

The report is designed for business and technical reviewers rather than as a
raw audit log. It uses:

- Plain-English finding descriptions
- Source comparisons
- Exact meaningful review locations
- Recommended actions
- Serial numbers within each section

Workbook evidence is simplified before it is shown in the report. Raw Excel
cell coordinates, column-by-column value dumps, and technical cell assignments
are not displayed. The report uses meaningful references such as:

- Component IDs, for example `CMP_WCRM050105_009`
- Entity IDs, for example `ENT-004`
- API field names
- Database column names
- Sheet names

Original extracted evidence remains available in the local evidence snapshot
for internal validation.

## Rerun behavior

When a reviewer requests a rerun for a DR and BR:

- A new review round is created.
- The current DR, BR, and attachments are fetched again.
- The complete review is performed again.
- The review is not limited to version differences.
- Existing findings are reviewed again.
- Recurring and newly introduced findings are reported.

For example, resubmitting the same function key starts `R002`, `R003`, and so
on; it does not overwrite the previous review round.

## Local review output

Completed reviews are stored under:

```text
runs\<FunctionKey>\reviews\<ReviewId>\
```

Primary generated files:

- `review_report.md` - reviewer-facing section-wise report
- `evidence_snapshot.md` - captured extracted source detail

Supporting workflow files may include:

- `state.json` - review state and provenance
- `manifest.json` - source registry and integrity metadata
- `findings.json` - validated internal findings
- `verifications.json` - independent verification results
- `workbook_evidence.txt` - workbook evidence view used by technical reviewers

SHA-256 values and internal finding IDs are retained for integrity and
workflow validation, but they are not shown as primary reviewer-facing
identifiers.

## Local CLI

The CLI can initialize local-file reviews and manage workflow artifacts:

```powershell
python -m dr_reviewer init `
  --function-key WSMB010104 `
  --dr .\input\published-dr.docx `
  --br .\input\business-requirements.docx `
  --attachments .\input\attachments `
  --runs-dir .\runs
```

Useful commands include:

```powershell
python -m dr_reviewer workbook-evidence `
  .\runs\WSMB010104\reviews\R001

python -m dr_reviewer evidence-snapshot `
  .\runs\WSMB010104\reviews\R001

python -m dr_reviewer report `
  .\runs\WSMB010104\reviews\R001

python -m dr_reviewer status `
  .\runs\WSMB010104\reviews\R001
```

For Confluence capture, configure the required environment values without
printing or committing them:

- `CONFLUENCE_BASE_URL`
- `CONFLUENCE_EMAIL`
- `CONFLUENCE_API_TOKEN`

## Evidence and security rules

- Confluence access is read-only.
- Source snapshots are hash-checked before evidence is accepted.
- Findings must cite captured evidence.
- Visual findings must identify the image source and visible region.
- Images are not OCR-processed.
- Static images cannot establish runtime or backend behavior.
- Missing, invalid, or unverifiable evidence is not silently treated as a
  clean result.
- Secrets in `.env` must never be displayed, committed, or included in
  reports.

## Tests

Run the full test suite from the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path '.\src').Path
python -m unittest discover -s tests -v
```
