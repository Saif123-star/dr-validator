from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from dr_reviewer.confluence import (
    ConfluenceAttachment,
    ConfluenceClient,
    ConfluenceError,
    ConfluenceSettings,
    normalize_base_url,
    page_id_from_url,
)
from dr_reviewer.sources import PageSource, initialize_review_from_sources, safe_filename
from dr_reviewer.storage import read_json

from fakes import FakeConfluence


class _RecordingOpener:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.requests: list[object] = []

    def open(self, outgoing, timeout):  # type: ignore[no-untyped-def]
        _ = timeout
        self.requests.append(outgoing)
        return io.BytesIO(json.dumps(self.responses.pop(0)).encode("utf-8"))


class ConfluenceSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.env_file = Path(self.temporary.name) / ".env"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_rejects_placeholder_values_from_env_file(self) -> None:
        self.env_file.write_text(
            "CONFLUENCE_BASE_URL=https://your-domain.atlassian.net\n"
            "CONFLUENCE_EMAIL=your.name@example.com\n"
            "CONFLUENCE_API_TOKEN=replace-with-your-confluence-api-token\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ConfluenceError, "placeholder"):
            ConfluenceSettings.from_environment(self.env_file, environ={})

    def test_environment_overrides_env_file_and_hides_token(self) -> None:
        self.env_file.write_text(
            'CONFLUENCE_BASE_URL="https://acme.atlassian.net/wiki/"\n'
            "CONFLUENCE_EMAIL=old@acme.test\nCONFLUENCE_API_TOKEN=secret-token\n",
            encoding="utf-8",
        )
        settings = ConfluenceSettings.from_environment(
            self.env_file, environ={"CONFLUENCE_EMAIL": "new@acme.test"}
        )
        self.assertEqual(settings.base_url, "https://acme.atlassian.net")
        self.assertEqual(settings.email, "new@acme.test")
        self.assertNotIn("secret-token", repr(settings))

    def test_base_url_must_be_https_site_root(self) -> None:
        for value in ("http://acme.atlassian.net", "https://acme.atlassian.net/other",
                      "https://user@acme.atlassian.net"):
            with self.subTest(value=value), self.assertRaises(ConfluenceError):
                normalize_base_url(value)

    def test_extracts_page_id_only_from_expected_site_and_page_urls(self) -> None:
        base_url = "https://acme.atlassian.net"
        self.assertEqual(
            page_id_from_url(
                "https://acme.atlassian.net/wiki/spaces/ABC/pages/12345/Page+Title",
                base_url,
            ),
            "12345",
        )
        self.assertEqual(
            page_id_from_url(
                "https://acme.atlassian.net/wiki/pages/viewpage.action?pageId=456",
                base_url,
            ),
            "456",
        )
        for value in (
            "http://acme.atlassian.net/wiki/spaces/ABC/pages/12345",
            "https://evil.test/wiki/spaces/ABC/pages/12345",
            "https://acme.atlassian.net/wiki/spaces/ABC/pages/not-an-id",
        ):
            with self.subTest(value=value), self.assertRaises(ConfluenceError):
                page_id_from_url(value, base_url)


class ConfluenceClientTests(unittest.TestCase):
    def test_follows_attachment_pagination_within_site(self) -> None:
        opener = _RecordingOpener(
            [
                {
                    "results": [{"id": "att1", "title": "a.png", "downloadLink": "/download/a"}],
                    "_links": {"next": "/wiki/api/v2/pages/100/attachments?cursor=abc"},
                },
                {"results": [{"id": "att2", "title": "b.png", "downloadLink": "/download/b"}]},
            ]
        )
        client = ConfluenceClient(
            ConfluenceSettings("https://acme.atlassian.net", "me@acme.test", "token"),
            opener=opener,
        )
        attachments = client.list_attachments("100")
        self.assertEqual([item.attachment_id for item in attachments], ["att1", "att2"])
        urls = [outgoing.full_url for outgoing in opener.requests]  # type: ignore[attr-defined]
        self.assertTrue(urls[0].startswith("https://acme.atlassian.net/wiki/api/v2/pages/100/"))
        self.assertEqual(urls[1], "https://acme.atlassian.net/wiki/api/v2/pages/100/attachments?cursor=abc")
        self.assertTrue(opener.requests[0].get_header("Authorization").startswith("Basic "))  # type: ignore[attr-defined]

    def test_rejects_non_numeric_page_id_and_foreign_links(self) -> None:
        client = ConfluenceClient(
            ConfluenceSettings("https://acme.atlassian.net", "me@acme.test", "token"),
            opener=_RecordingOpener([]),
        )
        with self.assertRaises(ConfluenceError):
            client.get_page("../spaces")
        with self.assertRaisesRegex(ConfluenceError, "outside"):
            client._url("https://evil.test/wiki/api/v2/pages")


class RemoteSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fake = FakeConfluence()
        self.fake.add_page(
            "100",
            "DR",
            3,
            '<p>The account number is required.</p><ac:image><ri:attachment ri:filename="screen:1.png" /></ac:image>',
        )
        self.fake.add_page("200", "BR", 8, "<p>Account number must be provided.</p>")
        self.fake.attachments["100"] = [
            (ConfluenceAttachment("att1", "screen:1.png", "/download/att1", version=2), b"png"),
            (ConfluenceAttachment("old1", "old-screen.png", "/download/old1", version=1), b"old"),
        ]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_captures_confluence_pages_and_dr_attachments(self) -> None:
        review_dir = initialize_review_from_sources(
            "FN001",
            PageSource(page_id="100"),
            PageSource(page_id="200"),
            client=self.fake,
            runs_dir=self.root / "runs",
        )
        state = read_json(review_dir / "state.json")
        self.assertEqual((state["dr_version"], state["br_version"]), ("3", "8"))
        sources = {source["source_id"]: source for source in state["sources"]}
        self.assertEqual(sources["SRC-DR-PAGE"]["origin"], "confluence")
        self.assertEqual(sources["SRC-ATT-0001"]["attachment_id"], "att1")
        self.assertEqual(sources["SRC-ATT-0001"]["filename"], "screen_1.png")
        self.assertEqual(sources["SRC-DR-PAGE"]["text_extraction"], "extracted")
        self.assertEqual(
            {source["attachment_id"] for source in sources.values() if "attachment_id" in source},
            {"att1"},
        )

    def test_captures_referenced_attachments_from_both_pages(self) -> None:
        self.fake.add_page(
            "200",
            "BR",
            8,
            '<p>Account number must be provided.</p><a href="/download/attachments/200/terms%20and%20conditions.pdf?version=2">Terms</a>',
        )
        self.fake.attachments["200"] = [
            (
                ConfluenceAttachment(
                    "br1", "terms and conditions.pdf", "/download/br1", version=2
                ),
                b"terms",
            ),
            (ConfluenceAttachment("old2", "old-terms.pdf", "/download/old2"), b"old"),
        ]
        review_dir = initialize_review_from_sources(
            "FN001",
            PageSource(page_id="100"),
            PageSource(page_id="200"),
            client=self.fake,
            runs_dir=self.root / "runs",
        )
        state = read_json(review_dir / "state.json")
        attachment_ids = {
            source["attachment_id"]
            for source in state["sources"]
            if "attachment_id" in source
        }
        self.assertEqual(attachment_ids, {"att1", "br1"})

    def test_fails_when_page_references_an_unattached_file(self) -> None:
        self.fake.add_page(
            "100",
            "DR",
            3,
            '<ri:attachment ri:filename="missing.png" />',
        )
        with self.assertRaisesRegex(ConfluenceError, "missing.png"):
            initialize_review_from_sources(
                "FN001",
                PageSource(page_id="100"),
                PageSource(page_id="200"),
                client=self.fake,
                runs_dir=self.root / "runs",
            )
        self.assertFalse((self.root / "runs" / "FN001" / "reviews" / "R001").exists())

    def test_rejects_version_mismatch(self) -> None:
        with self.assertRaisesRegex(ConfluenceError, "version 3"):
            initialize_review_from_sources(
                "FN001",
                PageSource(page_id="100", version="2"),
                PageSource(page_id="200"),
                client=self.fake,
                runs_dir=self.root / "runs",
            )
        self.assertFalse((self.root / "runs" / "FN001" / "reviews" / "R001").exists())

    def test_safe_filename_handles_reserved_names(self) -> None:
        self.assertEqual(safe_filename("CON.txt"), "_CON.txt")
        self.assertEqual(safe_filename('a<b>"c.docx'), "a_b__c.docx")


if __name__ == "__main__":
    unittest.main()
