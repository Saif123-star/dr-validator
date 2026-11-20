from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dr_reviewer.publication import (
    PublicationError,
    PublicationPaths,
    ReviewPagePublisher,
    approve_publication,
    build_publication_plan,
    verify_publication,
)
from dr_reviewer.storage import read_json
from dr_reviewer.workflow import (
    import_findings,
    import_verifications,
    initialize_review,
    record_decision,
)

from fakes import FakeConfluence, write_json


class PublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        dr = self.root / "dr.md"
        br = self.root / "br.md"
        dr.write_text("# Rules\n\nThe account number is required.\n", encoding="utf-8")
        br.write_text("# BR\n\nAccount number must be provided.\n", encoding="utf-8")
        self.review_dir = initialize_review(
            "FN001", dr, br, runs_dir=self.root / "runs", dr_page_id="100", dr_version="3"
        )
        self.paths = PublicationPaths.for_review(self.review_dir)
        self.fake = FakeConfluence()
        self.fake.add_page("100", "DR", 3, "<p>DR</p>")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _complete_review(self, decision: str = "accept") -> str:
        finding = {
            "track": "br_traceability",
            "rule_id": "DR-REQ-001",
            "title": "Rule <needs> evidence",
            "severity": "medium",
            "confidence": "high",
            "category": "traceability",
            "must_change": False,
            "summary": "The requirement is not connected to its source.",
            "impact": "Implementation may omit the rule.",
            "recommendation": "Add an explicit BR reference.",
            "evidence": [
                {
                    "source_id": "SRC-DR-PAGE",
                    "locator": "Rules",
                    "quote": "The account number is required.",
                }
            ],
            "related_sources": ["SRC-BR-PAGE"],
            "affected_sections": ["Rules"],
            "requires_human_decision": False,
            "decision_question": None,
        }
        import_findings(self.review_dir, write_json(self.root / "f.json", {"findings": [finding]}))
        finding_id = read_json(self.review_dir / "findings.json")["findings"][0]["finding_id"]
        verification = {"finding_id": finding_id, "verdict": "verified", "rationale": "Present."}
        import_verifications(
            self.review_dir, write_json(self.root / "v.json", {"verifications": [verification]})
        )
        record_decision(self.review_dir, finding_id, decision, "Reviewer")
        return finding_id

    def _approve(self) -> None:
        build_publication_plan(self.review_dir)
        approve_publication(self.review_dir, "Reviewer", "Yes, publish this review page.")

    def _status(self) -> str:
        return read_json(self.review_dir / "state.json")["status"]

    def test_plan_requires_completed_review_with_accepted_finding(self) -> None:
        with self.assertRaisesRegex(PublicationError, "completed review"):
            build_publication_plan(self.review_dir)
        self._complete_review(decision="defer")
        with self.assertRaisesRegex(PublicationError, "nothing to publish"):
            build_publication_plan(self.review_dir)

    def test_plan_escapes_content_and_lists_findings(self) -> None:
        finding_id = self._complete_review()
        plan_md = build_publication_plan(self.review_dir).read_text(encoding="utf-8")
        body = self.paths.body.read_text(encoding="utf-8")
        self.assertIn(finding_id, plan_md)
        self.assertIn("Rule &lt;needs&gt; evidence", body)
        self.assertNotIn("<needs>", body)
        self.assertEqual(self._status(), "publication_planned")

    def test_tampered_body_blocks_approval_and_publish(self) -> None:
        self._complete_review()
        build_publication_plan(self.review_dir)
        original = self.paths.body.read_text(encoding="utf-8")
        self.paths.body.write_text(original + "<p>extra</p>", encoding="utf-8")
        with self.assertRaisesRegex(PublicationError, "preview changed"):
            approve_publication(self.review_dir, "Reviewer", "Approved")
        self.paths.body.write_text(original, encoding="utf-8")
        approve_publication(self.review_dir, "Reviewer", "Approved")
        self.paths.body.write_text(original + "<p>extra</p>", encoding="utf-8")
        with self.assertRaisesRegex(PublicationError, "preview changed"):
            ReviewPagePublisher(self.review_dir, self.fake).publish()
        self.assertEqual(self.fake.created, [])

    def test_publish_requires_approval(self) -> None:
        self._complete_review()
        build_publication_plan(self.review_dir)
        with self.assertRaisesRegex(PublicationError, "approved plan"):
            ReviewPagePublisher(self.review_dir, self.fake).publish()

    def test_preflight_version_mismatch_writes_nothing(self) -> None:
        self._complete_review()
        self._approve()
        self.fake.add_page("100", "DR", 4, "<p>DR changed</p>")
        with self.assertRaisesRegex(PublicationError, "version 4"):
            ReviewPagePublisher(self.review_dir, self.fake).publish()
        self.assertEqual(self.fake.created, [])
        self.assertEqual(self._status(), "publication_failed")

    def test_resume_adopts_page_created_before_failure(self) -> None:
        finding_id = self._complete_review()
        self._approve()
        self.fake.fail_after_create = True
        with self.assertRaisesRegex(PublicationError, "rerun publish"):
            ReviewPagePublisher(self.review_dir, self.fake).publish()
        self.assertEqual(self._status(), "publication_failed")

        result = ReviewPagePublisher(self.review_dir, self.fake).publish()
        self.assertEqual(len(self.fake.created), 1)
        self.assertEqual(result["page_id"], self.fake.created[0].page_id)
        log = read_json(self.paths.log)
        self.assertEqual(log["items"]["1"]["mode"], "adopted")
        self.assertEqual([attempt["result"] for attempt in log["attempts"]], ["failed", "succeeded"])
        self.assertEqual(self._status(), "published")
        self.assertIn(finding_id, self.fake.created[0].body_storage or "")

    def test_refuses_to_overwrite_unrelated_page_with_same_title(self) -> None:
        self._complete_review()
        self._approve()
        title = read_json(self.paths.plan)["items"][0]["title"]
        self.fake.add_page("555", title, 1, "<p>someone else's page</p>", parent_id="100")
        with self.assertRaisesRegex(PublicationError, "will not be overwritten"):
            ReviewPagePublisher(self.review_dir, self.fake).publish()
        self.assertEqual(self.fake.created, [])

    def test_successful_publish_is_verified(self) -> None:
        self._complete_review()
        self._approve()
        result = ReviewPagePublisher(self.review_dir, self.fake).publish()
        created = self.fake.created[0]
        self.assertEqual(created.parent_id, "100")
        self.assertEqual(result["page_url"], created.web_url)
        verification = verify_publication(self.review_dir, self.fake)
        self.assertTrue(verification["verified"])
        self.assertEqual(verification["finding_count"], 1)
        state = read_json(self.review_dir / "state.json")
        self.assertEqual(state["publication"]["page_id"], created.page_id)


if __name__ == "__main__":
    unittest.main()
