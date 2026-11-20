# Track E — Technical Mapping and Function Map

Review API endpoint completeness, request/response consistency, required
fields, query/path parameters, error responses, UI-to-API and API-to-database
mapping, data types, required/optional mismatches, database entities/columns,
and workbook cross-consistency.

## Required cross-sheet checks

Use the orchestrator's workbook evidence export to inventory all DR worksheets,
including worksheets with no applicable records. Check each declared field,
each component in Item Description, and each API endpoint in the DR workbook
or DR page. Review all sheets for relevant references, not just the first
match or a sample.

- **Field lengths:** Match the same logical field using the component, endpoint,
  entity, or explicit mapping as context. Compare declared maximum lengths
  and their units across UI, API, and data definitions. Do not compare Excel
  display widths, column counts, or populated rows. A blank is not a zero;
  different units or an explicitly documented layer-specific restriction are
  not automatically contradictions. Flag an unaddressed incompatibility, such
  as one layer accepting values that the next layer cannot store.
- **Components:** Start with every Item Description entry. Match by component
  ID or by name plus screen/context when the ID is unavailable. Compare labels,
  types, visibility, states, events, validation, and UI/API/data mappings
  wherever they are specified. Flag contradictory references and missing
  mappings only where that sheet is expected to cover the component.
- **API endpoints:** Inventory each HTTP method and path, plus documented
  aliases. Compare references, methods, routes, triggers, parameters,
  request/response fields, status/error behavior, and mappings. Do not merge
  different methods on the same path or guess that similar routes are aliases.
  If the method or path is unclear, record the ambiguity rather than inventing it.

Return a short coverage summary alongside (not inside) the findings payload:
worksheet names and source IDs checked, field/component/endpoint counts
compared, and anything not assessed and why (including a missing or ambiguous
Item Description sheet or endpoints with no comparable references). Cite both
locations for a mismatch: use original source IDs, worksheet names and cell
references, plus exact quotes from the extracted rows. For an omission, cite
the evidence that establishes the expectation and the location checked; do not
invent a quote for a missing entry.

Produce function-map edges connecting business function, chapter/screen,
component, event, validation, API, request/response field, database mapping,
and testable outcome where evidence exists. Mark missing technical decisions
explicitly. Never invent an endpoint, field, database mapping, or contract.
