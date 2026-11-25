"""Read-only capture of DR/BR pages and DR attachments from Confluence."""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .confluence import (
    ConfluenceClient,
    ConfluenceError,
    ConfluenceGateway,
    ConfluenceSettings,
    page_id_from_url,
    require_numeric_id,
)
from .storage import write_text
from .workflow import initialize_review

_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_MAX_FILENAME = 120


class _AttachmentReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.filenames: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        filename = attributes.get("ri:filename")
        if filename:
            self.filenames.add(unquote(filename))

        href = attributes.get("href")
        if href:
            path = urlsplit(href).path
            marker = "/download/attachments/"
            if marker in path:
                filename = path.split(marker, 1)[1].rsplit("/", 1)[-1]
                if filename:
                    self.filenames.add(unquote(filename))


def _referenced_attachment_filenames(body_storage: str) -> set[str]:
    parser = _AttachmentReferenceParser()
    parser.feed(body_storage)
    parser.close()
    return parser.filenames


@dataclass(frozen=True)
class PageSource:
    """A DR or BR source: either a local file or a Confluence page ID."""

    path: Path | None = None
    page_id: str | None = None
    version: str | None = None
    url: str | None = None

    @property
    def is_remote(self) -> bool:
        return self.path is None

    def validate(self, label: str) -> None:
        if self.path is None and not self.page_id and not self.url:
            raise ValueError(
                f"Provide a local --{label} file, --{label}-page-id, or --{label}-url"
            )


@dataclass(frozen=True)
class FetchedAttachment:
    path: Path
    attachment_id: str
    version: str | None
    url: str
    parent_page_id: str


def safe_filename(name: str, fallback: str = "attachment") -> str:
    cleaned = _INVALID_FILENAME.sub("_", name).strip(" .") or fallback
    stem, dot, suffix = cleaned.rpartition(".")
    if not dot:
        stem, suffix = cleaned, ""
    if stem.casefold() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    suffix = f".{suffix}" if suffix else ""
    if len(stem) + len(suffix) > _MAX_FILENAME:
        suffix = suffix[:20]
        stem = stem[: _MAX_FILENAME - len(suffix)]
    return f"{stem}{suffix}"


class ConfluenceSourceFetcher:
    """Downloads page storage bodies and attachments into a workspace directory."""

    def __init__(self, client: ConfluenceGateway, workspace: Path) -> None:
        self._client = client
        self._workspace = workspace

    def fetch_page(
        self, page_id: str, label: str, expected_version: str | None = None
    ) -> tuple[Path, str, str | None]:
        """Return the snapshot path, captured version, and web URL for a page."""
        page = self._client.get_page(require_numeric_id(page_id, f"{label} page ID"))
        if expected_version is not None and str(page.version) != str(expected_version).strip():
            raise ConfluenceError(
                f"{label} page {page_id} is at version {page.version}, "
                f"but version {expected_version} was requested"
            )
        if page.body_storage is None:
            raise ConfluenceError(f"{label} page {page_id} returned no storage body")
        snapshot = self._workspace / f"{label.lower()}-{page.page_id}-v{page.version}.html"
        write_text(snapshot, page.body_storage)
        return snapshot, str(page.version), page.web_url

    def fetch_attachments(self, page_id: str, body_storage: str) -> list[FetchedAttachment]:
        page_id = require_numeric_id(page_id, "Confluence page ID")
        referenced_filenames = _referenced_attachment_filenames(body_storage)
        if not referenced_filenames:
            return []

        attachments = self._client.list_attachments(page_id)
        selected = [
            attachment
            for attachment in attachments
            if attachment.title in referenced_filenames
        ]
        missing = referenced_filenames - {attachment.title for attachment in selected}
        if missing:
            names = ", ".join(sorted(missing))
            raise ConfluenceError(
                f"Page {page_id} references attachment(s) not found on that page: {names}"
            )

        fetched: list[FetchedAttachment] = []
        for attachment in selected:
            attachment_id = re.sub(r"[^A-Za-z0-9_-]", "_", attachment.attachment_id)
            directory = self._workspace / "attachments" / attachment_id
            directory.mkdir(parents=True, exist_ok=False)
            destination = directory / safe_filename(attachment.title)
            url = self._client.download_attachment(attachment, destination)
            fetched.append(
                FetchedAttachment(
                    path=destination,
                    attachment_id=attachment.attachment_id,
                    version=None if attachment.version is None else str(attachment.version),
                    url=url,
                    parent_page_id=page_id,
                )
            )
        return fetched


def initialize_review_from_sources(
    function_key: str,
    dr: PageSource,
    br: PageSource,
    *,
    client: ConfluenceGateway | None = None,
    env_file: Path | None = None,
    **review_options: Any,
) -> Path:
    """Initialize a review, capturing any Confluence-hosted DR/BR read-only."""
    dr.validate("dr")
    br.validate("br")
    if not dr.is_remote and not br.is_remote:
        return initialize_review(
            function_key,
            dr.path,  # type: ignore[arg-type]
            br.path,  # type: ignore[arg-type]
            dr_page_id=dr.page_id,
            dr_version=dr.version,
            dr_url=dr.url,
            br_page_id=br.page_id,
            br_version=br.version,
            br_url=br.url,
            **review_options,
        )

    if client is None:
        settings = ConfluenceSettings.from_environment(env_file)
        gateway: ConfluenceGateway = ConfluenceClient(settings)
    else:
        settings = None
        gateway = client
    page_ids: dict[str, str | None] = {}
    for label, source in (("DR", dr), ("BR", br)):
        page_id = source.page_id
        if source.is_remote and source.url:
            if settings is None:
                raise ValueError(
                    f"Resolving a {label} URL with an injected client requires an explicit page ID"
                )
            url_page_id = page_id_from_url(source.url, settings.base_url)
            if page_id and require_numeric_id(page_id, f"{label} page ID") != url_page_id:
                raise ConfluenceError(f"{label} page ID does not match its URL")
            page_id = url_page_id
        page_ids[label] = page_id

    workspace = Path(tempfile.mkdtemp(prefix="dr-review-confluence-"))
    try:
        fetcher = ConfluenceSourceFetcher(gateway, workspace)
        resolved: dict[str, tuple[Path, str | None, str | None, str]] = {}
        page_bodies: dict[str, str] = {}
        for label, source in (("DR", dr), ("BR", br)):
            if source.is_remote:
                path, version, url = fetcher.fetch_page(
                    page_ids[label] or "", label, source.version
                )
                resolved[label] = (path, version, source.url or url, "confluence")
                page_bodies[label] = path.read_text(encoding="utf-8")
            else:
                resolved[label] = (source.path, source.version, source.url, "local")  # type: ignore[assignment]
        attachments: list[FetchedAttachment] = []
        for label, source in (("DR", dr), ("BR", br)):
            if source.is_remote:
                attachments.extend(
                    fetcher.fetch_attachments(page_ids[label] or "", page_bodies[label])
                )
        dr_path, dr_version, dr_url, dr_origin = resolved["DR"]
        br_path, br_version, br_url, br_origin = resolved["BR"]
        return initialize_review(
            function_key,
            dr_path,
            br_path,
            dr_page_id=page_ids["DR"],
            dr_version=dr_version,
            dr_url=dr_url,
            br_page_id=page_ids["BR"],
            br_version=br_version,
            br_url=br_url,
            dr_origin=dr_origin,
            br_origin=br_origin,
            confluence_attachments=attachments,
            **review_options,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
