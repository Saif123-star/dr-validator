"""Read-only Confluence Cloud REST v2 client for source capture."""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib import error, parse, request

from .config import CONFLUENCE_CONFIG, REPOSITORY_ROOT, load_env_file


DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env"
_PLACEHOLDER_MARKERS = ("your-domain", "replace-with", "example.com")
_NUMERIC_ID = re.compile(r"^[0-9]{1,20}$")


class ConfluenceError(ValueError):
    """A Confluence request failed or returned an unusable response."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def normalize_base_url(value: str) -> str:
    """Return the HTTPS site root, accepting an optional trailing ``/wiki``."""
    parsed = parse.urlsplit(value.strip())
    path = parsed.path.rstrip("/")
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or "@" in parsed.netloc
        or parsed.query
        or parsed.fragment
        or path.casefold() not in {"", "/wiki"}
    ):
        raise ConfluenceError(
            "CONFLUENCE_BASE_URL must be an https site root such as "
            "https://your-site.atlassian.net"
        )
    return f"https://{parsed.netloc}"


def page_id_from_url(value: str, base_url: str) -> str:
    """Extract a numeric page ID from a URL on the configured Confluence site."""
    parsed = parse.urlsplit(value.strip())
    site = parse.urlsplit(normalize_base_url(base_url))
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != site.netloc.casefold()
        or parsed.username
        or parsed.password
        or not parsed.path.casefold().startswith("/wiki/")
        or parsed.fragment
    ):
        raise ConfluenceError(
            "Page URL must be an HTTPS Confluence page URL on the configured site"
        )

    match = re.match(
        r"^/wiki/(?:spaces/[^/]+/pages|pages)/([0-9]+)(?:/|$)",
        parsed.path,
        flags=re.IGNORECASE,
    )
    if match:
        return require_numeric_id(match.group(1), "Page ID")

    query = parse.parse_qs(parsed.query)
    page_ids = query.get("pageId", [])
    if parsed.path.casefold().endswith("/viewpage.action") and len(page_ids) == 1:
        return require_numeric_id(page_ids[0], "Page ID")
    raise ConfluenceError(
        "Could not find a page ID in the Confluence URL; expected "
        "/wiki/spaces/<space>/pages/<id>/... or /wiki/pages/viewpage.action?pageId=<id>"
    )


@dataclass(frozen=True)
class ConfluenceSettings:
    base_url: str
    email: str
    api_token: str = field(repr=False)

    @property
    def wiki_url(self) -> str:
        return f"{self.base_url}/wiki"

    @classmethod
    def from_environment(
        cls,
        env_file: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> ConfluenceSettings:
        """Read settings from the environment, falling back to a dotenv file."""
        path = env_file or DEFAULT_ENV_FILE
        file_values = load_env_file(path)
        environment = os.environ if environ is None else environ

        def setting(name: str) -> str:
            return (environment.get(name) or file_values.get(name) or "").strip()

        values = {
            name: setting(name)
            for name in ("CONFLUENCE_BASE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN")
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfluenceError(
                f"Missing Confluence setting(s): {', '.join(missing)}. "
                f"Set them in the environment or in {path}"
            )
        if any(
            marker in value.casefold()
            for value in values.values()
            for marker in _PLACEHOLDER_MARKERS
        ):
            raise ConfluenceError(
                f"Confluence settings still contain placeholder values; update {path}"
            )
        return cls(
            base_url=normalize_base_url(values["CONFLUENCE_BASE_URL"]),
            email=values["CONFLUENCE_EMAIL"],
            api_token=values["CONFLUENCE_API_TOKEN"],
        )


@dataclass(frozen=True)
class ConfluencePage:
    page_id: str
    title: str
    space_id: str
    parent_id: str | None
    version: int
    body_storage: str | None = None
    web_url: str | None = None


@dataclass(frozen=True)
class ConfluenceAttachment:
    attachment_id: str
    title: str
    download_link: str
    media_type: str | None = None
    file_size: int | None = None
    version: int | None = None


class ConfluenceGateway(Protocol):
    """Read-only operations required for Confluence source capture."""

    def get_page(self, page_id: str, *, include_body: bool = True) -> ConfluencePage: ...

    def list_attachments(self, page_id: str) -> list[ConfluenceAttachment]: ...

    def download_attachment(self, attachment: ConfluenceAttachment, destination: Path) -> str: ...


class _SafeRedirectHandler(request.HTTPRedirectHandler):
    """Refuse HTTPS downgrades and never forward credentials to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        target = parse.urlsplit(newurl)
        if target.scheme != "https":
            raise ConfluenceError("Confluence redirected to a non-HTTPS URL; request refused")
        if target.netloc.casefold() != parse.urlsplit(req.full_url).netloc.casefold():
            redirected.remove_header("Authorization")
        return redirected


def require_numeric_id(value: str, label: str) -> str:
    value = str(value).strip()
    if not _NUMERIC_ID.fullmatch(value):
        raise ConfluenceError(f"{label} must be a numeric Confluence ID: {value!r}")
    return value


class ConfluenceClient:
    """Confluence Cloud REST v2 client authenticated with an email and API token."""

    def __init__(
        self,
        settings: ConfluenceSettings,
        *,
        opener: Any | None = None,
        timeout: float | None = None,
        max_response_bytes: int | None = None,
        max_attachment_bytes: int | None = None,
    ) -> None:
        self._settings = settings
        self._opener = opener or request.build_opener(_SafeRedirectHandler())
        self._timeout = timeout or CONFLUENCE_CONFIG["request_timeout_seconds"]
        self._max_response_bytes = max_response_bytes or CONFLUENCE_CONFIG["max_response_bytes"]
        self._max_attachment_bytes = (
            max_attachment_bytes or CONFLUENCE_CONFIG["max_attachment_bytes"]
        )
        credentials = f"{settings.email}:{settings.api_token}".encode("utf-8")
        self._authorization = "Basic " + base64.b64encode(credentials).decode("ascii")

    def get_page(self, page_id: str, *, include_body: bool = True) -> ConfluencePage:
        page_id = require_numeric_id(page_id, "Page ID")
        query = {"body-format": "storage"} if include_body else None
        return self._page(self._request_json(self._url(f"/api/v2/pages/{page_id}", query)))

    def list_attachments(self, page_id: str) -> list[ConfluenceAttachment]:
        page_id = require_numeric_id(page_id, "Page ID")
        url: str | None = self._url(f"/api/v2/pages/{page_id}/attachments", {"limit": "250"})
        visited: set[str] = set()
        attachments: list[ConfluenceAttachment] = []
        while url:
            if url in visited:
                raise ConfluenceError("Confluence attachment pagination repeated a page")
            visited.add(url)
            payload = self._request_json(url)
            attachments.extend(self._attachment(item) for item in payload.get("results", []))
            next_link = (payload.get("_links") or {}).get("next")
            url = self._url(next_link) if isinstance(next_link, str) and next_link else None
        return attachments

    def download_attachment(self, attachment: ConfluenceAttachment, destination: Path) -> str:
        limit = self._max_attachment_bytes
        if attachment.file_size is not None and attachment.file_size > limit:
            raise ConfluenceError(
                f"Attachment {attachment.title!r} exceeds the {limit}-byte download limit"
            )
        url = self._url(attachment.download_link)
        written = 0
        with self._open(url, accept="*/*") as response, destination.open("xb") as handle:
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise ConfluenceError(
                        f"Attachment {attachment.title!r} exceeds the {limit}-byte download limit"
                    )
                handle.write(chunk)
        return url

    def _url(self, link: str, query: Mapping[str, str] | None = None) -> str:
        site = parse.urlsplit(self._settings.base_url)
        if link.startswith(("https://", "http://")):
            target = parse.urlsplit(link)
            if target.scheme != "https" or target.netloc.casefold() != site.netloc.casefold():
                raise ConfluenceError("Confluence returned a link outside the configured site")
            url = link
        elif link.startswith("/wiki/"):
            url = self._settings.base_url + link
        elif link.startswith("/"):
            url = self._settings.wiki_url + link
        else:
            raise ConfluenceError(f"Unexpected Confluence link: {link!r}")
        if query:
            url = f"{url}{'&' if '?' in url else '?'}{parse.urlencode(query)}"
        return url

    def _open(self, url: str, accept: str = "application/json") -> Any:
        headers = {"Authorization": self._authorization, "Accept": accept}
        outgoing = request.Request(url, headers=headers)
        location = parse.urlsplit(url).path
        try:
            return self._opener.open(outgoing, timeout=self._timeout)
        except error.HTTPError as exc:
            raise ConfluenceError(
                f"Confluence GET {location} failed with HTTP {exc.code}: "
                f"{_error_detail(exc)}",
                status=exc.code,
            ) from exc
        except OSError as exc:
            reason = getattr(exc, "reason", exc)
            raise ConfluenceError(
                f"Unable to reach Confluence for GET {location}: {reason}"
            ) from exc

    def _request_json(self, url: str) -> dict[str, Any]:
        with self._open(url) as response:
            raw = response.read(self._max_response_bytes + 1)
        if len(raw) > self._max_response_bytes:
            raise ConfluenceError("Confluence response exceeded the configured size limit")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfluenceError("Confluence returned a response that is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ConfluenceError("Confluence returned an unexpected JSON response")
        return data

    def _page(self, data: Mapping[str, Any]) -> ConfluencePage:
        try:
            page_id = str(data["id"])
            title = str(data["title"])
            space_id = str(data["spaceId"])
            version = int(data["version"]["number"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfluenceError("Confluence returned an incomplete page record") from exc
        body = ((data.get("body") or {}).get("storage") or {}).get("value")
        webui = (data.get("_links") or {}).get("webui")
        parent_id = data.get("parentId")
        return ConfluencePage(
            page_id=page_id,
            title=title,
            space_id=space_id,
            parent_id=str(parent_id) if parent_id else None,
            version=version,
            body_storage=body if isinstance(body, str) else None,
            web_url=self._url(webui) if isinstance(webui, str) and webui.startswith("/") else None,
        )

    def _attachment(self, data: Mapping[str, Any]) -> ConfluenceAttachment:
        links = data.get("_links") or {}
        download_link = data.get("downloadLink") or links.get("download")
        if not isinstance(download_link, str) or not data.get("id") or not data.get("title"):
            raise ConfluenceError("Confluence returned an incomplete attachment record")
        version = (data.get("version") or {}).get("number")
        file_size = data.get("fileSize")
        return ConfluenceAttachment(
            attachment_id=str(data["id"]),
            title=str(data["title"]),
            download_link=download_link,
            media_type=data.get("mediaType"),
            file_size=file_size if isinstance(file_size, int) else None,
            version=version if isinstance(version, int) else None,
        )


def _error_detail(exc: error.HTTPError) -> str:
    try:
        raw = exc.read(4096).decode("utf-8", errors="replace")
    except OSError:
        return exc.reason or "no details"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()[:300] or str(exc.reason)
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        detail = errors[0].get("title") or errors[0].get("detail")
    else:
        detail = payload.get("message") if isinstance(payload, dict) else None
    return str(detail or exc.reason)[:300]
