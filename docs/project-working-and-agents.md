# DR Validator - Project Working Guide

## 1. Purpose

DR Validator reviews a Design Requirement (DR) against its Business
Requirement (BR) and related attachments. It checks traceability, UI details,
events, APIs, database mappings, and consistency across the supplied sources.

The review is read-only. Confluence pages and source documents are captured
locally and are never edited.

## 2. Main entry point

The user starts a review through the `dr-reviewer` agent in VS Code Copilot
Chat by providing:

- Function key
- DR URL
- BR URL

Example:

```text
Start a full review.
Function Key: WCRM050105
DR URL: <DR URL>
BR URL: <BR URL>
```

The Python CLI manages capture, validation, merging, verification, and report
creation. The VS Code agents perform the specialist review work.

## 3. Agents and their responsibilities

### `dr-reviewer`

The main orchestrator and only user-facing agent.

Responsibilities:

- Start or resume a review
- Capture the DR, BR, and attachments
- Create the immutable evidence baseline
- Select and invoke the required specialist agents
- Import and validate their findings
- Start independent verification
- Invoke reconciliation when findings conflict or are duplicated
- Generate the final local report
- Return the short completion summary in chat

### `review-traceability`

Reviews DR alignment with the BR.

Checks include:

- Whether every BR requirement is represented in the DR
- Business rules and validations
- Roles and permissions
- Required data and states
- Error and exception behavior
- Conflicts between BR and DR descriptions

### `review-consistency`

Reviews internal consistency within the DR and its attachments.

Checks include:

- Contradictory definitions
- Duplicate fields or endpoints
- Conflicting values across worksheets
- Inconsistent names, types, lengths, and statuses
- Cross-section contradictions

### `review-ui-technical`

Reviews textual UI details and technical mappings.

Checks include:

- UI components and labels
- Events and event-to-API mappings
- API-to-UI mappings
- API methods, paths, parameters, request and response fields
- Field lengths, data types, mandatory rules, and enums
- UI-to-database and API-to-database mappings

### `review-vision`

Reviews image attachments through visual inspection only.

It checks visible UI details such as:

- Labels and controls
- Layout and alignment
- Visible states
- Status indicators
- Visible empty or error states
- Visible overflow or scroll affordances

It does not infer runtime behavior, API execution, database persistence,
permissions, accessibility compliance, keyboard behavior, or responsive
behavior from a static image.

Visual findings are placed in the **UI Components** section.

### `review-verifier`

Independently verifies every submitted finding against the locked evidence.

It confirms:

- The cited text or image observation is present
- The source and location are correct
- The finding is supported by the evidence
- The severity and recommendation are reasonable

Visual findings are independently checked against the cited image region.

### `review-reconciler`

Used only when required.

It resolves:

- Duplicate findings
- Severity conflicts
- Recommendation conflicts
- Differences between specialist findings

It does not invent a resolution when the evidence is insufficient.

## 4. Review flow

```text
User provides DR and BR
          |
          v
dr-reviewer starts a new review round
          |
          v
Capture current DR, BR, and attachments
          |
          v
Create immutable source registry and review brief
          |
          v
Run applicable specialist agents
          |
          +--> review-traceability
          +--> review-consistency
          +--> review-ui-technical
          +--> review-vision (when images exist)
          |
          v
Validate and merge findings
          |
          v
review-verifier independently verifies findings
          |
          v
review-reconciler runs only when conflicts require it
          |
          v
Generate local report and evidence snapshot
          |
          v
Return completion details and section-results table
```

## 5. Review sections

The generated report uses fixed sections:

1. UI Components
2. Event Mapping with API
3. API Mapping with Events and UI Components
4. DR API Coverage
5. Database Mapping with UI Components
6. Database Mapping with API
7. DR Alignment with BR
8. Cross-Section Consistency

Each section contains its findings table. If no verified gap exists, the
section contains a single no-gap row:

```text
No verified gaps found
```

Workbook evidence is simplified for reviewers. The report does not expose
raw Excel cell coordinates or column dumps. It uses meaningful identifiers
such as component IDs, entity IDs, API fields, sheet names, and plain-English
finding descriptions.

## 6. Reruns

When a reviewer requests a rerun for a DR and BR:

- A new review round is created.
- The current DR, BR, and attachments are fetched again.
- The complete review is performed again.
- The process is not limited to version differences.
- Existing findings are reviewed again.
- Newly introduced findings are also reported.

This ensures that a rerun represents the current state of the source
documents.

## 7. Generated files

Each completed review is stored under:

```text
runs\<FunctionKey>\reviews\<ReviewId>\
```

The main deliverables are:

- `review_report.md` - reviewer-facing findings report
- `evidence_snapshot.md` - captured extracted source detail

Additional internal workflow files may include:

- `state.json`
- `manifest.json`
- `findings.json`
- `verifications.json`
- `workbook_evidence.txt`

These internal files support validation and auditability but are not part of
the short completion response shown to the reviewer.

## 8. Read-only and evidence rules

- Confluence remains read-only.
- The DR and BR are never edited.
- No Confluence comments or pages are created.
- No Jira updates are performed.
- Findings must be supported by captured evidence.
- Image findings must identify the image source and visible region.
- Static images cannot prove runtime or backend behavior.
- A review is not marked complete until required findings are verified and
  any required reconciliation is finished.
