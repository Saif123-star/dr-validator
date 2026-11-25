# Reconcile Findings

Reconcile only merged findings marked `reconciliation_required`. Focus on
must-change findings and resolve overlapping root causes, duplicate findings,
contradictory recommendations, and severity conflicts.

Return a proposal per finding: finding ID, selected recommendation, selected
severity when disputed, rationale, and unresolved questions. Preserve the
alternatives and their evidence in the audit record. Do not conceal a
disagreement or make a business decision for the user.
