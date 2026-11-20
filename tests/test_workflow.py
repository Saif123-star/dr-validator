from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dr_reviewer.workflow import (
    build_source_registry,
    import_findings,
    import_reconciliations,
    import_verifications,
    initialize_review,
    record_decision,
    render_report,
)


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dr = self.root / "dr.md"
        self.br = self.root / "br.md"
        self.dr.write_text(
            "# Validation Rules\n\nThe account number is required.\n",
            encoding="utf-8",
        )
        self.br.write_text(
            "# Business Requirements\n\nAccount number must be provided.\n",
            encoding="utf-8",
        )
        self.review_dir = initialize_review(
            function_key="FN001",
            dr_path=self.dr,
            br_path=self.br,
            runs_dir=self.root / "runs",
        )
        self.assertTrue((self.review_dir / "finding.schema.json").is_file())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _finding(self, track: str, severity: str = "medium") -> dict[str, object]:
        return {
            "track": track,
            "rule_id": "DR-REQ-001",
            "title": "Account-number rule needs evidence",
            "severity": severity,
            "confidence": "high",
            "category": "traceability",
            "must_change": severity in {"critical", "high"},
            "summary": "The requirement is not connected to its source.",
            "impact": "Implementation may omit the business rule.",
            "recommendation": "Add an explicit BR reference.",
            "evidence": [
                {
                    "source_id": "SRC-DR-PAGE",
                    "locator": "Validation Rules",
                    "quote": "The account number is required.",
                }
            ],
            "related_sources": ["SRC-BR-PAGE"],
            "affected_sections": ["Validation Rules"],
            "requires_human_decision": False,
            "decision_question": None,
        }

    def _write_json(self, filename: str, payload: object) -> Path:
        path = self.root / filename
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_import_merges_duplicates_and_requires_verification_for_decisions(self) -> None:
        findings_path = self._write_json(
            "findings.json",
            {
                "findings": [
                    self._finding("br_traceability", "medium"),
                    self._finding("internal_consistency", "high"),
                ]
            },
        )
        self.assertEqual(import_findings(self.review_dir, findings_path), 1)
        findings = json.loads((self.review_dir / "findings.json").read_text())
        finding = findings["findings"][0]
        self.assertEqual(finding["severity"], "high")
        self.assertTrue(finding["severity_conflict"])
        self.assertTrue(finding["reconciliation_required"])
        self.assertEqual(
            finding["originating_tracks"],
            ["br_traceability", "internal_consistency"],
        )
        with self.assertRaisesRegex(ValueError, "independently verified"):
            record_decision(
                self.review_dir,
                finding["finding_id"],
                "accept",
                "Reviewer",
            )

        verification_path = self._write_json(
            "verifications.json",
            {
                "verifications": [
                    {
                        "finding_id": finding["finding_id"],
                        "verdict": "verified",
                        "rationale": "The quoted text exists in the captured DR.",
                    }
                ]
            },
        )
        self.assertEqual(import_verifications(self.review_dir, verification_path), 1)
        with self.assertRaisesRegex(ValueError, "reconciled"):
            record_decision(
                self.review_dir,
                finding["finding_id"],
                "accept",
                "Reviewer",
            )
        reconciliation_path = self._write_json(
            "reconciliations.json",
            {
                "reconciliations": [
                    {
                        "finding_id": finding["finding_id"],
                        "severity": "high",
                        "rationale": "Use the higher reported severity pending user review.",
                    }
                ]
            },
        )
        self.assertEqual(
            import_reconciliations(self.review_dir, reconciliation_path),
            1,
        )
        record_decision(
            self.review_dir,
            finding["finding_id"],
            "accept",
            "Reviewer",
            rationale="Agreed with the recommendation.",
        )
        report = render_report(self.review_dir).read_text(encoding="utf-8")
        self.assertIn("Status: **completed**", report)
        self.assertIn("The account number is required.", report)

    def test_rejects_quote_not_present_in_snapshot(self) -> None:
        finding = self._finding("br_traceability")
        finding["evidence"][0]["quote"] = "This text is not in the DR."
        findings_path = self._write_json("bad-findings.json", {"findings": [finding]})

        with self.assertRaisesRegex(ValueError, "quote was not found"):
            import_findings(self.review_dir, findings_path)

    def test_rejects_modified_snapshot(self) -> None:
        dr_source = self.review_dir / "sources" / "SRC-DR-PAGE" / "dr.md"
        dr_source.write_text("changed after capture", encoding="utf-8")
        findings_path = self._write_json(
            "findings.json",
            {"findings": [self._finding("br_traceability")]},
        )

        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            import_findings(self.review_dir, findings_path)

    def test_targeted_review_requires_a_track(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one --tracks"):
            initialize_review(
                function_key="FN002",
                dr_path=self.dr,
                br_path=self.br,
                runs_dir=self.root / "runs",
                scope="targeted",
            )

    def test_rejects_findings_outside_targeted_scope(self) -> None:
        review_dir = initialize_review(
            function_key="FN006",
            dr_path=self.dr,
            br_path=self.br,
            runs_dir=self.root / "runs",
            scope="targeted",
            tracks=["br_traceability"],
        )
        findings_path = self._write_json(
            "out-of-scope.json",
            {"findings": [self._finding("internal_consistency")]},
        )
        with self.assertRaisesRegex(ValueError, "outside the confirmed review scope"):
            import_findings(review_dir, findings_path)

    def test_records_optional_page_provenance(self) -> None:
        review_dir = initialize_review(
            function_key="FN003",
            dr_path=self.dr,
            br_path=self.br,
            runs_dir=self.root / "runs",
            dr_page_id="DR-123",
            dr_version="4",
            dr_url="https://example.invalid/dr",
            br_page_id="BR-456",
            br_version="11",
            reviewer="Reviewer",
        )
        state = json.loads((review_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["dr_page_id"], "DR-123")
        self.assertEqual(state["dr_version"], "4")
        self.assertEqual(state["reviewer"], "Reviewer")

    def test_builds_source_registry_from_unchanged_snapshot(self) -> None:
        registry_path = build_source_registry(self.review_dir)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [source["source_id"] for source in registry["sources"]],
            ["SRC-DR-PAGE", "SRC-BR-PAGE"],
        )

    def test_records_local_workshop_context_with_configured_authority(self) -> None:
        context = self.root / "workshop.md"
        context.write_text("Approved decision: retain the account number.", encoding="utf-8")
        review_dir = initialize_review(
            function_key="FN004",
            dr_path=self.dr,
            br_path=self.br,
            runs_dir=self.root / "runs",
            context_sources=[("workshop_decision", context)],
        )
        registry = json.loads(
            (review_dir / "manifest.json").read_text(encoding="utf-8")
        )
        source = registry["sources"][-1]
        self.assertEqual(source["type"], "workshop_decision")
        self.assertEqual(source["authoritative_for"], ["approved_decision"])

    def test_rejects_context_source_with_unconfigured_type(self) -> None:
        context = self.root / "misc.md"
        context.write_text("Context.", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unknown local context source type"):
            initialize_review(
                function_key="FN005",
                dr_path=self.dr,
                br_path=self.br,
                runs_dir=self.root / "runs",
                context_sources=[("unknown_context", context)],
            )

    def test_completes_review_when_no_findings_are_reported(self) -> None:
        findings_path = self._write_json("empty-findings.json", {"findings": []})
        self.assertEqual(import_findings(self.review_dir, findings_path), 0)
        report = render_report(self.review_dir).read_text(encoding="utf-8")
        self.assertIn("Status: **completed**", report)
        self.assertIn("No findings have been imported.", report)

    def test_requires_must_change_for_high_severity(self) -> None:
        finding = self._finding("br_traceability", "high")
        finding["must_change"] = False
        findings_path = self._write_json("bad-severity.json", {"findings": [finding]})

        with self.assertRaisesRegex(ValueError, "must_change=true"):
            import_findings(self.review_dir, findings_path)


if __name__ == "__main__":
    unittest.main()
