"""Phase 2: plan, approve, publish, and verify one Confluence review page.

Publication is the only external write the reviewer performs. It is gated by an
explicit human approval that locks the SHA-256 of the plan and the page body.
"""

from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CONFLUENCE_CONFIG, PIPELINE_CONFIG, SEVERITY_CONFIG
from .confluence import ConfluenceError, ConfluenceGateway, ConfluencePage
from .storage import (
    canonical_sha256,
    load_state,
    read_json,
    save_state,
    sha256_file,
    utc_now,
    write_json,
    write_text,
)

PLAN_SCHEMA_VERSION = 1
CREATE_REVIEW_PAGE = "create_review_page"
MARKER_PREFIX = "dr-review-publication-id:"
_PLANNABLE = {"completed", "publication_planned", "publication_approved"}
_PUBLISHABLE = {"publication_approved", "publication_failed", "publishing"}
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_MAX_TITLE_LENGTH = 255
_SEVERITY_RANK = {
    name: level["rank"] for name, level in SEVERITY_CONFIG["levels"].items()
}


class PublicationError(ValueError):
    """Publication cannot proceed safely."""


@dataclass(frozen=True)
class PublicationPaths:
    root: Path

    @classmethod
    def for_review(cls, review_dir: Path) -> PublicationPaths:
        return cls(review_dir / "publication")

    @property
    def plan(self) -> Path:
        return self.root / "plan.json"

    @property
    def plan_markdown(self) -> Path:
        return self.root / "plan.md"

    @property
    def body(self) -> Path:
        return self.root / "review_page.storage.html"

    @property
    def approval(self) -> Path:
        return self.root / "approved.json"

    @property
    def log(self) -> Path:
        return self.root / "publication_log.json"


def _transition(state: dict[str, Any], target: str) -> None:
    current = state["status"]
    if target not in PIPELINE_CONFIG["stages"].get(current, []):
        raise PublicationError(f"Review status '{current}' cannot move to '{target}'")
    state["status"] = target


def _included_decisions() -> list[str]:
    return [str(value).casefold() for value in CONFLUENCE_CONFIG["review_page"]["include_decisions"]]


def _page_title(state: dict[str, Any]) -> str:
    template = CONFLUENCE_CONFIG["review_page"]["title_template"]
    try:
        title = template.format(function_key=state["function_key"], review_id=state["review_id"])
    except (KeyError, IndexError, ValueError) as exc:
        raise PublicationError(f"Invalid review_page.title_template: {exc}") from exc
    title = _clean(title).strip()
    if not title or len(title) > _MAX_TITLE_LENGTH:
        raise PublicationError(f"Review page title must be 1-{_MAX_TITLE_LENGTH} characters")
    return title


def _clean(value: Any) -> str:
    return _CONTROL_CHARACTERS.sub("", "" if value is None else str(value))


def _text(value: Any) -> str:
    return html.escape(_clean(value), quote=True)


def _paragraphs(value: Any) -> str:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", _clean(value)) if block.strip()]
    if not blocks:
        return "<p><em>None provided.</em></p>"
    return "".join(
        "<p>" + "<br />".join(_text(line) for line in block.splitlines()) + "</p>"
        for block in blocks
    )


def _sort_key(finding: dict[str, Any]) -> tuple[int, str]:
    return (_SEVERITY_RANK.get(finding.get("severity"), len(_SEVERITY_RANK)), finding["finding_id"])


def render_review_page(
    state: dict[str, Any], findings: list[dict[str, Any]], publication_id: str
) -> str:
    """Render accepted findings as Confluence storage-format XHTML."""
    parts = [
        "<p>Automated design-requirement review for "
        f"<strong>{_text(state['function_key'])}</strong>, review "
        f"<strong>{_text(state['review_id'])}</strong>.</p>",
        "<p>Reviewed DR page ID "
        f"<code>{_text(state.get('dr_page_id'))}</code> at version "
        f"<code>{_text(state.get('dr_version'))}</code>. "
        f"Baseline captured {_text(state.get('baseline_timestamp'))}. "
        f"This page lists {len(findings)} accepted finding(s); "
        "the DR page itself was not modified.</p>",
        "<h2>Summary</h2>",
        "<table><tbody><tr><th>Finding ID</th><th>Severity</th><th>Title</th>"
        "<th>Must change</th><th>Decision owner</th></tr>",
    ]
    for finding in findings:
        decision = finding["decision"]
        parts.append(
            f"<tr><td><code>{_text(finding['finding_id'])}</code></td>"
            f"<td>{_text(finding['severity'])}</td><td>{_text(finding['title'])}</td>"
            f"<td>{'Yes' if finding.get('must_change') else 'No'}</td>"
            f"<td>{_text(decision['owner'])}</td></tr>"
        )
    parts.append("</tbody></table>")
    for finding in findings:
        decision = finding["decision"]
        tracks = ", ".join(finding.get("originating_tracks") or [finding["track"]])
        parts.extend(
            [
                f"<h2>{_text(finding['finding_id'])}: {_text(finding['title'])}</h2>",
                f"<p><strong>Severity:</strong> {_text(finding['severity'])}<br />"
                f"<strong>Category:</strong> {_text(finding.get('category'))}<br />"
                f"<strong>Track(s):</strong> {_text(tracks)}<br />"
                f"<strong>Affected sections:</strong> "
                f"{_text(', '.join(finding.get('affected_sections') or []) or 'Not specified')}</p>",
                "<h3>Summary</h3>",
                _paragraphs(finding.get("summary")),
                "<h3>Impact</h3>",
                _paragraphs(finding.get("impact")),
                "<h3>Recommendation</h3>",
                _paragraphs(finding.get("recommendation")),
                "<h3>Evidence</h3>",
                "<ul>",
            ]
        )
        for reference in finding.get("evidence") or []:
            parts.append(
                f"<li><code>{_text(reference.get('source_id'))}</code> &#8212; "
                f"{_text(reference.get('locator'))}: <em>&#8220;"
                f"{_text(reference.get('quote'))}&#8221;</em></li>"
            )
        parts.extend(
            [
                "</ul>",
                "<h3>Decision</h3>",
                f"<p><strong>Decision:</strong> {_text(decision['decision'])}<br />"
                f"<strong>Owner:</strong> {_text(decision['owner'])}<br />"
                f"<strong>Recorded:</strong> {_text(decision.get('timestamp'))}</p>",
                "<p><strong>Rationale:</strong></p>",
                _paragraphs(decision.get("rationale")),
                "<p><strong>Intended action:</strong></p>",
                _paragraphs(decision.get("intended_action")),
            ]
        )
    parts.append(f"<p><sub>{MARKER_PREFIX} {_text(publication_id)}</sub></p>")
    return "\n".join(parts) + "\n"


def _render_plan_markdown(plan: dict[str, Any], plan_sha256: str, review_dir: Path) -> str:
    item = plan["items"][0]
    lines = [
        f"# Publication plan - {plan['function_key']} {plan['review_id']}",
        "",
        "Nothing has been written to Confluence. Review this plan and the page preview",
        f"(`{item['body_file']}`), then approve it in your own words.",
        "",
        f"- Publication ID: `{plan['publication_id']}`",
        f"- Plan SHA-256: `{plan_sha256}`",
        f"- DR baseline: page `{plan['baseline']['dr_page_id']}` version "
        f"`{plan['baseline']['dr_version']}` (checked again before writing)",
        f"- Included decisions: {', '.join(plan['included_decisions'])}",
        "",
        "## Planned actions",
        "",
        "| # | Action | Parent page | Title | Findings | Body SHA-256 |",
        "| ---: | --- | --- | --- | ---: | --- |",
    ]
    for planned in plan["items"]:
        lines.append(
            f"| {planned['sequence']} | {planned['action']} | `{planned['parent_page_id']}` "
            f"| {planned['title']} | {len(planned['finding_ids'])} | `{planned['body_sha256']}` |"
        )
    lines.extend(["", "## Findings to publish", ""])
    lines.extend(f"- `{finding_id}`" for finding_id in item["finding_ids"])
    lines.extend(["", "## Findings not published", ""])
    if plan["excluded_findings"]:
        lines.extend(
            f"- `{excluded['finding_id']}` - {excluded['reason']}"
            for excluded in plan["excluded_findings"]
        )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Approve",
            "",
            "```text",
            f'python scripts/review/approve_publish_plan.py "{review_dir}" '
            '--approved-by "<name>" --statement "<approval in your own words>"',
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def build_publication_plan(review_dir: Path) -> Path:
    """Write plan.json, plan.md, and the page preview; returns the plan.md path."""
    state = load_state(review_dir)
    if state["status"] not in _PLANNABLE:
        raise PublicationError(
            "A publication plan requires a completed review "
            f"(current status: {state['status']})"
        )
    if not state.get("dr_page_id") or not state.get("dr_version"):
        raise PublicationError(
            "Publishing requires the DR Confluence page ID and version captured at init"
        )
    included = _included_decisions()
    findings = read_json(review_dir / "findings.json").get("findings", [])
    publish: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for finding in findings:
        decision = finding.get("decision")
        if decision and decision.get("decision") in included:
            publish.append(finding)
        elif decision:
            excluded.append(
                {"finding_id": finding["finding_id"], "reason": f"decision: {decision['decision']}"}
            )
        else:
            verdict = (finding.get("verification") or {}).get("verdict")
            excluded.append(
                {"finding_id": finding["finding_id"], "reason": f"verification verdict: {verdict}"}
            )
    if not publish:
        raise PublicationError(
            f"No findings have a publishable decision ({', '.join(included)}); nothing to publish"
        )
    publish.sort(key=_sort_key)

    paths = PublicationPaths.for_review(review_dir)
    publication_id = str(uuid.uuid4())
    write_text(paths.body, render_review_page(state, publish, publication_id))
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "publication_id": publication_id,
        "function_key": state["function_key"],
        "review_id": state["review_id"],
        "created_at": utc_now(),
        "baseline": {"dr_page_id": state["dr_page_id"], "dr_version": str(state["dr_version"])},
        "findings_sha256": sha256_file(review_dir / "findings.json"),
        "included_decisions": included,
        "items": [
            {
                "sequence": 1,
                "action": CREATE_REVIEW_PAGE,
                "parent_page_id": state["dr_page_id"],
                "title": _page_title(state),
                "body_file": paths.body.name,
                "body_sha256": sha256_file(paths.body),
                "finding_ids": [finding["finding_id"] for finding in publish],
            }
        ],
        "excluded_findings": excluded,
    }
    plan_sha256 = canonical_sha256(plan)
    write_json(paths.plan, plan)
    write_text(paths.plan_markdown, _render_plan_markdown(plan, plan_sha256, review_dir))
    paths.approval.unlink(missing_ok=True)
    paths.log.unlink(missing_ok=True)

    _transition(state, "publication_planned")
    state["publication"] = {
        "publication_id": publication_id,
        "plan_sha256": plan_sha256,
        "planned_at": plan["created_at"],
        "approved_by": None,
        "approved_at": None,
        "page_id": None,
        "page_url": None,
        "published_at": None,
        "last_error": None,
    }
    save_state(review_dir, state)
    return paths.plan_markdown


def _verified_plan(review_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Return the plan only if it, its body, and the findings are unchanged."""
    publication = state.get("publication") or {}
    paths = PublicationPaths.for_review(review_dir)
    plan = read_json(paths.plan)
    if not isinstance(plan, dict) or plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise PublicationError("publication/plan.json is missing or unsupported")
    if canonical_sha256(plan) != publication.get("plan_sha256"):
        raise PublicationError("publication/plan.json changed after it was built; rebuild the plan")
    if plan.get("publication_id") != publication.get("publication_id"):
        raise PublicationError("Publication ID does not match the review state")
    if sha256_file(review_dir / "findings.json") != plan["findings_sha256"]:
        raise PublicationError("findings.json changed after the plan was built; rebuild the plan")
    for item in plan["items"]:
        if item["body_file"] != paths.body.name or sha256_file(paths.body) != item["body_sha256"]:
            raise PublicationError("The review page preview changed after planning; rebuild the plan")
    return plan


def approve_publication(review_dir: Path, approved_by: str, statement: str) -> Path:
    """Lock the current plan hash with a named human approval."""
    approved_by = approved_by.strip()
    statement = statement.strip()
    if not approved_by:
        raise PublicationError("--approved-by must name the approving person")
    if not statement:
        raise PublicationError("--statement must record the approval in the approver's own words")
    state = load_state(review_dir)
    if state["status"] != "publication_planned":
        raise PublicationError(
            f"Only a planned publication can be approved (current status: {state['status']})"
        )
    plan = _verified_plan(review_dir, state)
    approved_at = utc_now()
    paths = PublicationPaths.for_review(review_dir)
    write_json(
        paths.approval,
        {
            "publication_id": plan["publication_id"],
            "plan_sha256": state["publication"]["plan_sha256"],
            "approved_by": approved_by,
            "statement": statement,
            "approved_at": approved_at,
        },
    )
    _transition(state, "publication_approved")
    state["publication"].update({"approved_by": approved_by, "approved_at": approved_at})
    save_state(review_dir, state)
    return paths.approval


def _verify_page(
    client: ConfluenceGateway, page_id: str, item: dict[str, Any], publication_id: str
) -> ConfluencePage:
    page = client.get_page(page_id)
    body = page.body_storage or ""
    problems = []
    if page.title != item["title"]:
        problems.append(f"title is {page.title!r}")
    if page.parent_id != item["parent_page_id"]:
        problems.append(f"parent is {page.parent_id!r}")
    if publication_id not in body:
        problems.append("publication marker is missing")
    missing = [finding_id for finding_id in item["finding_ids"] if finding_id not in body]
    if missing:
        problems.append(f"{len(missing)} finding ID(s) missing: {', '.join(missing[:5])}")
    if problems:
        raise PublicationError(f"Review page {page_id} failed verification: {'; '.join(problems)}")
    return page


class ReviewPagePublisher:
    """Executes an approved plan through the publish gate, resumably."""

    def __init__(self, review_dir: Path, client: ConfluenceGateway) -> None:
        self._review_dir = review_dir
        self._client = client
        self._paths = PublicationPaths.for_review(review_dir)

    def publish(self) -> dict[str, Any]:
        state = load_state(self._review_dir)
        if state["status"] not in _PUBLISHABLE:
            raise PublicationError(
                "Publishing requires an approved plan "
                f"(current status: {state['status']})"
            )
        plan = self._gate(state)
        log = self._load_log(plan)
        attempt: dict[str, Any] = {"started_at": utc_now(), "result": "running"}
        log["attempts"].append(attempt)
        self._save_log(log)
        try:
            space_id = self._preflight(plan)
            if state["status"] != "publishing":
                _transition(state, "publishing")
                save_state(self._review_dir, state)
            page: ConfluencePage | None = None
            for item in sorted(plan["items"], key=lambda value: value["sequence"]):
                self._gate(state, log, item["sequence"])
                record = log["items"].get(str(item["sequence"]))
                if record and record.get("status") == "succeeded":
                    page_id = record["page_id"]
                else:
                    page_id, mode = self._execute(item, space_id, plan["publication_id"])
                    log["items"][str(item["sequence"])] = {
                        "status": "succeeded",
                        "action": item["action"],
                        "page_id": page_id,
                        "mode": mode,
                        "completed_at": utc_now(),
                    }
                    self._save_log(log)
                page = _verify_page(self._client, page_id, item, plan["publication_id"])
        except (ConfluenceError, PublicationError, OSError) as exc:
            attempt.update({"result": "failed", "error": str(exc), "finished_at": utc_now()})
            self._save_log(log)
            state = load_state(self._review_dir)
            if state["status"] != "publication_failed":
                _transition(state, "publication_failed")
            state["publication"]["last_error"] = str(exc)
            save_state(self._review_dir, state)
            raise PublicationError(
                f"Publication stopped: {exc}. Completed actions are recorded in "
                f"{self._paths.log}; rerun publish to check Confluence and resume."
            ) from exc

        if page is None:
            raise PublicationError("The publication plan contains no items")
        attempt.update({"result": "succeeded", "finished_at": utc_now()})
        self._save_log(log)
        _transition(state, "published")
        state["publication"].update(
            {
                "page_id": page.page_id,
                "page_url": page.web_url,
                "published_at": utc_now(),
                "last_error": None,
            }
        )
        save_state(self._review_dir, state)
        return {"page_id": page.page_id, "page_url": page.web_url, "title": page.title}

    def _gate(
        self,
        state: dict[str, Any],
        log: dict[str, Any] | None = None,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        """Re-check plan, body, findings, and approval hashes, plus item order."""
        plan = _verified_plan(self._review_dir, state)
        approval = read_json(self._paths.approval) if self._paths.approval.is_file() else None
        if (
            not isinstance(approval, dict)
            or approval.get("plan_sha256") != state["publication"]["plan_sha256"]
            or approval.get("publication_id") != plan["publication_id"]
            or not approval.get("approved_by")
            or not approval.get("statement")
        ):
            raise PublicationError("No valid approval matches the current plan hash")
        if log is not None and sequence is not None:
            for item in plan["items"]:
                prior = log["items"].get(str(item["sequence"]), {})
                if item["sequence"] < sequence and prior.get("status") != "succeeded":
                    raise PublicationError(
                        f"Item {sequence} cannot run before item {item['sequence']} succeeds"
                    )
        return plan

    def _preflight(self, plan: dict[str, Any]) -> str:
        """Confirm the DR is still at the reviewed version; returns its space ID."""
        baseline = plan["baseline"]
        dr_page = self._client.get_page(baseline["dr_page_id"], include_body=False)
        if str(dr_page.version) != baseline["dr_version"]:
            raise PublicationError(
                f"DR page {dr_page.page_id} is now version {dr_page.version}, but the review "
                f"baseline is version {baseline['dr_version']}; start a new review round"
            )
        return dr_page.space_id

    def _execute(self, item: dict[str, Any], space_id: str, publication_id: str) -> tuple[str, str]:
        if item["action"] != CREATE_REVIEW_PAGE:
            raise PublicationError(f"Unsupported publication action: {item['action']}")
        for candidate in self._client.find_pages_by_title(space_id, item["title"]):
            if candidate.title != item["title"]:
                continue
            existing = self._client.get_page(candidate.page_id)
            if (
                existing.parent_id == item["parent_page_id"]
                and publication_id in (existing.body_storage or "")
            ):
                return existing.page_id, "adopted"
            raise PublicationError(
                f"A different page titled {item['title']!r} already exists "
                f"(page {existing.page_id}); it will not be overwritten"
            )
        created = self._client.create_page(
            space_id=space_id,
            parent_id=item["parent_page_id"],
            title=item["title"],
            storage_body=self._paths.body.read_text(encoding="utf-8"),
        )
        return created.page_id, "created"

    def _load_log(self, plan: dict[str, Any]) -> dict[str, Any]:
        if self._paths.log.is_file():
            log = read_json(self._paths.log)
            if isinstance(log, dict) and log.get("publication_id") == plan["publication_id"]:
                return log
            raise PublicationError("publication_log.json belongs to a different plan")
        return {"publication_id": plan["publication_id"], "attempts": [], "items": {}}

    def _save_log(self, log: dict[str, Any]) -> None:
        write_json(self._paths.log, log)


def verify_publication(review_dir: Path, client: ConfluenceGateway) -> dict[str, Any]:
    """Re-read the published page and confirm it still matches the approved plan."""
    state = load_state(review_dir)
    if state["status"] != "published":
        raise PublicationError(f"The review is not published (current status: {state['status']})")
    plan = _verified_plan(review_dir, state)
    item = plan["items"][0]
    page = _verify_page(client, state["publication"]["page_id"], item, plan["publication_id"])
    return {
        "verified": True,
        "page_id": page.page_id,
        "page_url": page.web_url,
        "version": page.version,
        "finding_count": len(item["finding_ids"]),
    }
