from __future__ import annotations

from pathlib import Path

from dr_reviewer.confluence import ConfluenceAttachment, ConfluenceError, ConfluencePage

SITE = "https://acme.atlassian.net"


class FakeConfluence:
    """In-memory ConfluenceGateway used instead of the network."""

    def __init__(self) -> None:
        self.pages: dict[str, ConfluencePage] = {}
        self.attachments: dict[str, list[tuple[ConfluenceAttachment, bytes]]] = {}

    def add_page(
        self, page_id: str, title: str, version: int, body: str, parent_id: str | None = None
    ) -> None:
        self.pages[page_id] = ConfluencePage(
            page_id, title, "77", parent_id, version, body, f"{SITE}/wiki/pages/{page_id}"
        )

    def get_page(self, page_id: str, *, include_body: bool = True) -> ConfluencePage:
        _ = include_body
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
