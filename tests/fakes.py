from __future__ import annotations

import json
from pathlib import Path

from dr_reviewer.confluence import ConfluenceAttachment, ConfluenceError, ConfluencePage

SITE = "https://acme.atlassian.net"


class FakeConfluence:
    """In-memory ConfluenceGateway used instead of the network."""

    def __init__(self) -> None:
        self.pages: dict[str, ConfluencePage] = {}
        self.attachments: dict[str, list[tuple[ConfluenceAttachment, bytes]]] = {}
        self.created: list[ConfluencePage] = []
        self.fail_after_create = False
        self._next_id = 9000

    def add_page(
        self, page_id: str, title: str, version: int, body: str, parent_id: str | None = None
    ) -> None:
        self.pages[page_id] = ConfluencePage(
            page_id, title, "77", parent_id, version, body, f"{SITE}/wiki/pages/{page_id}"
        )

    def get_page(self, page_id: str, *, include_body: bool = True) -> ConfluencePage:
        if page_id not in self.pages:
            raise ConfluenceError(f"Page {page_id} not found", status=404)
        return self.pages[page_id]

    def list_attachments(self, page_id: str) -> list[ConfluenceAttachment]:
        return [attachment for attachment, _ in self.attachments.get(page_id, [])]

    def download_attachment(self, attachment: ConfluenceAttachment, destination: Path) -> str:
        for page_attachments in self.attachments.values():
            for candidate, content in page_attachments:
                if candidate.attachment_id == attachment.attachment_id:
                    destination.write_bytes(content)
                    return SITE + "/wiki" + attachment.download_link
        raise ConfluenceError("Attachment not found", status=404)

    def find_pages_by_title(self, space_id: str, title: str) -> list[ConfluencePage]:
        return [page for page in self.pages.values() if page.title == title]

    def create_page(
        self, *, space_id: str, parent_id: str, title: str, storage_body: str
    ) -> ConfluencePage:
        self._next_id += 1
        page_id = str(self._next_id)
        self.add_page(page_id, title, 1, storage_body, parent_id)
        self.created.append(self.pages[page_id])
        if self.fail_after_create:
            self.fail_after_create = False
            raise ConfluenceError("Connection reset after the page was created")
        return self.pages[page_id]


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
