from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import (
    PIPELINE_CONFIG,
    REPOSITORY_ROOT,
    SEVERITY_CONFIG,
    SOURCE_AUTHORITY_CONFIG,
)
from .documents import extract_text, normalize_quote
from .storage import load_state as _load_state
from .storage import read_json as _read_json
from .storage import save_state as _save_state
from .storage import sha256_file as _sha256
from .storage import utc_now as _now
from .storage import write_json as _write_json
from .storage import write_text

if TYPE_CHECKING:
    from .sources import FetchedAttachment


TRACKS = tuple(PIPELINE_CONFIG["tracks"])
SEVERITIES = tuple(
    severity
    for severity, _ in sorted(
        SEVERITY_CONFIG["levels"].items(),
        key=lambda item: item[1]["rank"],
    )
)
CONFIDENCE_LEVELS = ("high", "medium", "low")
VERDICTS = (
    "verified",
    "rejected",
    "downgraded",
    "upgraded",
    "duplicate",
    "needs_human_decision",
    "insufficient_evidence",
)
DECISIONS = (
    "accept",
    "reject",
    "defer",
    "already_addressed",
    "needs_clarification",
    "accepted_risk",
)
_FUNCTION_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SEVERITY_RANK = {
    severity: config["rank"]
    for severity, config in SEVERITY_CONFIG["levels"].items()
}
_FINDING_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "schemas" / "review" / "finding.schema.json").read_text(
        encoding="utf-8"
    )
)
_VERIFICATION_SCHEMA = json.loads(
    (
        REPOSITORY_ROOT
        / "schemas"
        / "review"
        / "verification_result.schema.json"
    ).read_text(encoding="utf-8")
)
_DECISION_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "schemas" / "review" / "decision.schema.json").read_text(
        encoding="utf-8"
    )
)
_REVIEW_STATE_SCHEMA = json.loads(
    (REPOSITORY_ROOT / "schemas" / "review" / "review_state.schema.json").read_text(
        encoding="utf-8"
    )
)
_SOURCE_REGISTRY_SCHEMA = json.loads(
    (
        REPOSITORY_ROOT
        / "schemas"
        / "review"
        / "source_registry.schema.json"
    ).read_text(encoding="utf-8")
)


def _require_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path.resolve()


def _next_review_id(reviews_dir: Path) -> str:
    existing_numbers = [
        int(match.group(1))
        for child in reviews_dir.iterdir()
        if (match := re.fullmatch(r"R(\d{3})", child.name))
    ]
    next_number = max(existing_numbers, default=0) + 1
    if next_number > 999:
        raise ValueError("This Function Key already has 999 review rounds")
    return f"R{next_number:03d}"


def _source_record(
    stage: Path,
    source_id: str,
    source_type: str,
    source_path: Path,
    authoritative_for: list[str],
    tracks: list[str],
    page_id: str | None = None,
    version: str | None = None,
    url: str | None = None,
    origin: str = "local",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_dir = stage / "sources" / source_id
    source_dir.mkdir(parents=True)
    snapshot = source_dir / source_path.name
    shutil.copy2(source_path, snapshot)
    _, extraction_status = extract_text(snapshot)
    authority = SOURCE_AUTHORITY_CONFIG["source_types"].get(source_type, {})
    return {
        "source_id": source_id,
        "type": source_type,
        "origin": origin,
        "filename": source_path.name,
        "snapshot_path": snapshot.relative_to(stage).as_posix(),
        "sha256": _sha256(snapshot),
        "captured_at": _now(),
        "size_bytes": snapshot.stat().st_size,
        "availability": "available",
        "text_extraction": extraction_status,
        "page_id": page_id,
        "version": version,
        "url": url,
        "authoritative_for": authority.get("authoritative_for", authoritative_for),
        "applicable_tracks": authority.get("applicable_tracks", tracks),
        **(extra or {}),
    }


def initialize_review(
    function_key: str,
    dr_path: Path,
    br_path: Path,
    runs_dir: Path = Path("runs"),
    attachments_dir: Path | None = None,
    scope: str = "full",
    tracks: list[str] | None = None,
    dr_page_id: str | None = None,
    dr_version: str | None = None,
    dr_url: str | None = None,
    br_page_id: str | None = None,
    br_version: str | None = None,
    br_url: str | None = None,
    reviewer: str | None = None,
    context_sources: list[tuple[str, Path]] | None = None,
    dr_origin: str = "local",
    br_origin: str = "local",
    confluence_attachments: Sequence[FetchedAttachment] = (),
) -> Path:
    if not _FUNCTION_KEY.fullmatch(function_key):
        raise ValueError("Function Key must be 1-64 letters, digits, underscores, or hyphens")
    if scope not in {"full", "targeted"}:
        raise ValueError("Scope must be 'full' or 'targeted'")
    selected_tracks = list(dict.fromkeys(tracks or []))
    unknown_tracks = sorted(set(selected_tracks) - set(TRACKS))
    if unknown_tracks:
        raise ValueError(f"Unknown review track(s): {', '.join(unknown_tracks)}")
    if scope == "targeted" and not selected_tracks:
        raise ValueError("Targeted reviews require at least one --tracks value")
    if scope == "full":
        selected_tracks = list(TRACKS)
    if bool(dr_page_id) != bool(dr_version):
        raise ValueError("Provide both --dr-page-id and --dr-version, or neither")
    if bool(br_page_id) != bool(br_version):
        raise ValueError("Provide both --br-page-id and --br-version, or neither")
    if reviewer is not None and not reviewer.strip():
        raise ValueError("Reviewer must be non-empty when provided")

    dr_path = _require_file(dr_path, "DR")
    br_path = _require_file(br_path, "BR")
    attachment_files: list[Path] = []
    if attachments_dir is not None:
        if attachments_dir.is_symlink() or not attachments_dir.is_dir():
            raise ValueError(f"Attachments path must be a directory: {attachments_dir}")
        for item in sorted(attachments_dir.rglob("*")):
            if item.is_symlink():
                raise ValueError(f"Symbolic links are not allowed in attachments: {item}")
            if item.is_file():
                attachment_files.append(item.resolve())
    remote_attachments = [
        (_require_file(attachment.path, "Confluence attachment"), attachment)
        for attachment in confluence_attachments
    ]
    validated_context: list[tuple[str, Path]] = []
    for source_type, source_path in context_sources or []:
        if source_type not in SOURCE_AUTHORITY_CONFIG["source_types"]:
            raise ValueError(f"Unknown local context source type: {source_type}")
        validated_context.append(
            (source_type, _require_file(source_path, f"{source_type} source"))
        )

    function_dir = runs_dir / function_key
    reviews_dir = function_dir / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    review_id = _next_review_id(reviews_dir)
    review_dir = reviews_dir / review_id
    stage = Path(tempfile.mkdtemp(prefix=f".{review_id}-", dir=reviews_dir))
    try:
        all_tracks = list(TRACKS)
        sources = [
            _source_record(
                stage,
                "SRC-DR-PAGE",
                "dr_page",
                dr_path,
                ["dr_content"],
                all_tracks,
                page_id=dr_page_id,
                version=dr_version,
                url=dr_url,
                origin=dr_origin,
            ),
            _source_record(
                stage,
                "SRC-BR-PAGE",
                "br_page",
                br_path,
                ["business_requirements"],
                ["br_traceability", "technical_mapping"],
                page_id=br_page_id,
                version=br_version,
                url=br_url,
                origin=br_origin,
            ),
        ]
        for index, source_path in enumerate(attachment_files, start=1):
            sources.append(
                _source_record(
                    stage,
                    f"SRC-ATT-{index:04d}",
                    "attachment",
                    source_path,
                    ["attachment_content"],
                    ["document_integrity", "ui_ux_context", "technical_mapping"],
                )
            )
        for index, (source_path, attachment) in enumerate(
            remote_attachments, start=len(attachment_files) + 1
        ):
            sources.append(
                _source_record(
                    stage,
                    f"SRC-ATT-{index:04d}",
                    "attachment",
                    source_path,
                    ["attachment_content"],
                    ["document_integrity", "ui_ux_context", "technical_mapping"],
                    page_id=attachment.parent_page_id,
                    version=attachment.version,
                    url=attachment.url,
                    origin="confluence",
                    extra={"attachment_id": attachment.attachment_id},
                )
            )
        for index, (source_type, source_path) in enumerate(validated_context, start=1):
            sources.append(
                _source_record(
                    stage,
                    f"SRC-CONTEXT-{index:04d}",
                    source_type,
                    source_path,
                    [],
                    [],
                )
            )

        created_at = _now()
        state = {
            "schema_version": 1,
            "function_key": function_key,
            "review_id": review_id,
            "status": "sources_ready",
            "scope": scope,
            "tracks": selected_tracks,
            "created_at": created_at,
            "baseline_timestamp": created_at,
            "updated_at": created_at,
            "reviewer": reviewer.strip() if reviewer else None,
            "dr_page_id": dr_page_id,
            "dr_version": dr_version,
            "br_page_id": br_page_id,
            "br_version": br_version,
            "sources": sources,
            "finding_count": 0,
            "decision_count": 0,
        }
        _write_json(stage / "state.json", state)
        _write_json(stage / "manifest.json", {"sources": sources})
        _write_json(stage / "findings.json", {"findings": []})
        _write_json(stage / "function_map.json", {"entries": []})
        _write_json(stage / "agent_findings.template.json", {"findings": []})
        _write_json(stage / "finding.schema.json", _FINDING_SCHEMA)
        _write_json(stage / "verification.template.json", {"verifications": []})
        _write_json(stage / "verification_result.schema.json", _VERIFICATION_SCHEMA)
        _write_json(stage / "decision.schema.json", _DECISION_SCHEMA)
        _write_json(stage / "review_state.schema.json", _REVIEW_STATE_SCHEMA)
        _write_json(stage / "source_registry.schema.json", _SOURCE_REGISTRY_SCHEMA)
        _write_json(stage / "decision.template.json", {"decisions": []})
        _write_json(stage / "reconciliation.template.json", {"reconciliations": []})
        _write_brief(stage / "review_brief.md", state)
        stage.rename(review_dir)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return review_dir


def _source_text(review_dir: Path, source: dict[str, Any]) -> str:
    relative = Path(source["snapshot_path"])
    snapshot = (review_dir / relative).resolve()
    if not snapshot.is_relative_to(review_dir.resolve()):
        raise ValueError(f"Invalid source snapshot path: {relative}")
    if not snapshot.is_file() or _sha256(snapshot) != source["sha256"]:
        raise ValueError(f"Source snapshot changed or is missing: {source['source_id']}")
    text, _ = extract_text(snapshot)
    return text


def _write_brief(path: Path, state: dict[str, Any]) -> None:
    source_lines = [
        f"- `{source['source_id']}` ({source['type']}): {source['filename']} "
        f"— SHA-256 `{source['sha256']}`, extraction `{source['text_extraction']}`"
        for source in state["sources"]
    ]
    body = [
        f"# Review brief: {state['function_key']} / {state['review_id']}",
        "",
        f"- Scope: **{state['scope']}**",
        f"- Tracks: {', '.join(state['tracks'])}",
        f"- Baseline captured: {state['created_at']}",
        f"- Reviewer: {state.get('reviewer') or 'Not specified'}",
        f"- DR page: {state.get('dr_page_id') or 'Local source'} "
        f"(version {state.get('dr_version') or 'not supplied'})",
        f"- BR page: {state.get('br_page_id') or 'Local source'} "
        f"(version {state.get('br_version') or 'not supplied'})",
        "- This is a read-only local snapshot. Do not modify source files.",
        "",
        "## Evidence sources",
        *source_lines,
        "",
        "## Specialist review instructions",
        "Return only evidence-backed findings in `agent_findings.template.json`.",
        "Use `finding.schema.json` for the required fields and allowed values.",
        "Use `verification.template.json` with `verification_result.schema.json`",
        "for independent verification results.",
        "Every finding must cite one or more source IDs with a locator and an exact quote.",
        "Do not invent APIs, database mappings, requirements, or missing evidence.",
        "Use the declared track names and severity levels shown in the template.",
        "Default source precedence: "
        + " > ".join(SOURCE_AUTHORITY_CONFIG["precedence"]),
        "The workflow checks citation text and merges duplicates; it does not perform",
        "semantic review or automatically launch specialist agents.",
        "",
    ]
    path.write_text("\n".join(body), encoding="utf-8")


def create_brief(review_dir: Path) -> Path:
    state = _load_state(review_dir)
    path = review_dir / "review_brief.md"
    _write_brief(path, state)
    return path


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "possibly empty " if allow_empty else ""
        raise ValueError(f"{label} must be a {qualifier}list of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must contain only non-empty strings")
    return list(dict.fromkeys(item.strip() for item in value))


def _finding_key(finding: dict[str, Any]) -> str:
    evidence_refs = "|".join(
        sorted(
            f"{item['source_id']}:{normalize_quote(item['locator'])}"
            for item in finding["evidence"]
        )
    )
    sections = "|".join(sorted(normalize_quote(item) for item in finding["affected_sections"]))
    return "|".join(
        (
            normalize_quote(finding["rule_id"]),
            normalize_quote(finding["category"]),
            evidence_refs,
            sections,
        )
    )


def _validate_finding(
    value: Any,
    sources_by_id: dict[str, dict[str, Any]],
    text_by_source: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Each finding must be a JSON object")
    required_strings = (
        "track",
        "rule_id",
        "title",
        "severity",
        "confidence",
        "category",
        "summary",
        "impact",
        "recommendation",
    )
    finding = {key: _string(value.get(key), f"finding.{key}") for key in required_strings}
    if finding["track"] not in TRACKS:
        raise ValueError(f"Unknown finding track: {finding['track']}")
    if finding["severity"].casefold() not in SEVERITIES:
        raise ValueError(f"Unknown finding severity: {finding['severity']}")
    if finding["confidence"].casefold() not in CONFIDENCE_LEVELS:
        raise ValueError(f"Unknown confidence level: {finding['confidence']}")
    finding["severity"] = finding["severity"].casefold()
    finding["confidence"] = finding["confidence"].casefold()

    if not isinstance(value.get("must_change"), bool):
        raise ValueError("finding.must_change must be a boolean")
    if (
        SEVERITY_CONFIG["levels"][finding["severity"]]["must_change_default"]
        and not value["must_change"]
    ):
        raise ValueError(
            f"Severity '{finding['severity']}' requires must_change=true"
        )
    if not isinstance(value.get("requires_human_decision"), bool):
        raise ValueError("finding.requires_human_decision must be a boolean")
    finding["must_change"] = value["must_change"]
    finding["requires_human_decision"] = value["requires_human_decision"]
    finding["decision_question"] = value.get("decision_question")
    if finding["decision_question"] is not None and not isinstance(
        finding["decision_question"], str
    ):
        raise ValueError("finding.decision_question must be a string or null")

    finding["affected_sections"] = _string_list(
        value.get("affected_sections"), "finding.affected_sections"
    )
    finding["related_sources"] = _string_list(
        value.get("related_sources", []), "finding.related_sources", allow_empty=True
    )
    unknown_related_sources = sorted(set(finding["related_sources"]) - set(sources_by_id))
    if unknown_related_sources:
        raise ValueError(
            "Finding refers to unknown related source(s): "
            + ", ".join(unknown_related_sources)
        )
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("Every finding requires at least one evidence reference")
    checked_evidence: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("Each evidence reference must be a JSON object")
        source_id = _string(item.get("source_id"), "evidence.source_id")
        if source_id not in sources_by_id:
            raise ValueError(f"Evidence refers to unknown source: {source_id}")
        locator = _string(item.get("locator"), "evidence.locator")
        quote = _string(item.get("quote"), "evidence.quote")
        source_text = text_by_source.get(source_id, "")
        if not source_text or normalize_quote(quote) not in normalize_quote(source_text):
            raise ValueError(
                f"Evidence quote was not found in source {source_id} at {locator!r}"
            )
        checked_evidence.append(
            {"source_id": source_id, "locator": locator, "quote": quote}
        )
    finding["evidence"] = checked_evidence
    finding["reconciliation_required"] = False
    finding["verification"] = {
        "evidence_citations": "passed",
        "verdict": None,
        "rationale": None,
    }
    finding["decision"] = None
    return finding


def _merge_group(items: list[dict[str, Any]], function_key: str, review_id: str) -> dict[str, Any]:
    items = sorted(items, key=lambda item: (item["track"], item["title"].casefold()))
    first = items[0]
    key = _finding_key(first)
    stable_suffix = hashlib.sha256(
        f"{function_key}|{review_id}|{key}".encode("utf-8")
    ).hexdigest()[:10]
    recommendations = list(dict.fromkeys(item["recommendation"] for item in items))
    summaries = list(dict.fromkeys(item["summary"] for item in items))
    impacts = list(dict.fromkeys(item["impact"] for item in items))
    evidence: list[dict[str, str]] = []
    seen_evidence: set[tuple[str, str, str]] = set()
    for item in items:
        for reference in item["evidence"]:
            signature = (
                reference["source_id"],
                normalize_quote(reference["locator"]),
                normalize_quote(reference["quote"]),
            )
            if signature not in seen_evidence:
                evidence.append(reference)
                seen_evidence.add(signature)
    severity_values = {item["severity"] for item in items}
    severity_conflict = len(severity_values) > 1
    severity = min(severity_values, key=_SEVERITY_RANK.get)
    tracks = sorted({item["track"] for item in items})
    return {
        "finding_id": f"DRV-{function_key}-{review_id}-{stable_suffix}",
        "track": tracks[0],
        "originating_tracks": tracks,
        "rule_id": first["rule_id"],
        "title": first["title"],
        "severity": severity,
        "confidence": max(
            (item["confidence"] for item in items),
            key=CONFIDENCE_LEVELS.index,
        ),
        "category": first["category"],
        "must_change": any(item["must_change"] for item in items),
        "summary": "\n\n".join(summaries),
        "impact": "\n\n".join(impacts),
        "recommendation": "\n\n".join(recommendations),
        "evidence": evidence,
        "related_sources": sorted(
            {source for item in items for source in item["related_sources"]}
        ),
        "affected_sections": sorted(
            {section for item in items for section in item["affected_sections"]}
        ),
        "requires_human_decision": any(
            item["requires_human_decision"] for item in items
        ),
        "decision_question": next(
            (item["decision_question"] for item in items if item["decision_question"]),
            None,
        ),
        "severity_conflict": severity_conflict,
        "reconciliation_required": len(recommendations) > 1 or severity_conflict,
        "verification": first["verification"],
        "decision": None,
    }


def import_findings(review_dir: Path, findings_path: Path) -> int:
    return merge_findings(review_dir, findings_path)


def _read_findings_input(
    review_dir: Path,
    findings_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = _load_state(review_dir)
    payload = _read_json(findings_path)
    values = payload.get("findings") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ValueError("Findings input must be a list or an object with a findings list")

    sources_by_id = {source["source_id"]: source for source in state["sources"]}
    text_by_source = {
        source_id: _source_text(review_dir, source)
        for source_id, source in sources_by_id.items()
    }
    validated = [
        _validate_finding(value, sources_by_id, text_by_source) for value in values
    ]
    for finding in validated:
        if finding["track"] not in state["tracks"]:
            raise ValueError(
                f"Finding track {finding['track']} is outside the confirmed review scope"
            )
    return state, validated


def validate_findings(review_dir: Path, findings_path: Path) -> int:
    _, validated = _read_findings_input(review_dir, findings_path)
    return len(validated)


def merge_findings(review_dir: Path, findings_path: Path) -> int:
    state = _load_state(review_dir)
    if state["status"] not in {"sources_ready", "reviewing"}:
        raise ValueError("Findings can only be imported before verification and decisions")
    existing = _read_json(review_dir / "findings.json").get("findings", [])
    if existing:
        raise ValueError("Findings already exist; do not overwrite a reviewed finding set")
    _, validated = _read_findings_input(review_dir, findings_path)
    groups: dict[str, list[dict[str, Any]]] = {}
    for finding in validated:
        groups.setdefault(_finding_key(finding), []).append(finding)
    merged = [
        _merge_group(groups[key], state["function_key"], state["review_id"])
        for key in sorted(groups)
    ]
    _write_json(review_dir / "findings.json", {"findings": merged})
    state["status"] = "verifying" if merged else "completed"
    state["finding_count"] = len(merged)
    _save_state(review_dir, state)
    if state["status"] == "completed":
        render_review_comments(review_dir)
    return len(merged)


def build_source_registry(review_dir: Path, output_path: Path | None = None) -> Path:
    state = _load_state(review_dir)
    for source in state["sources"]:
        _source_text(review_dir, source)
    registry = {"sources": state["sources"]}
    registry_path = output_path or review_dir / "manifest.json"
    _write_json(registry_path, registry)
    return registry_path


def export_workbook_evidence(review_dir: Path) -> Path:
    """Write a read-only text view of captured DR workbooks for review agents."""
    state = _load_state(review_dir)
    workbooks: list[str] = []
    for source in state["sources"]:
        if source["type"] not in {"dr_page", "attachment"}:
            continue
        if Path(source["snapshot_path"]).suffix.casefold() != ".xlsx":
            continue
        text = _source_text(review_dir, source)
        workbooks.append(f"Source: {source['source_id']} ({source['filename']})\n{text}")
    output = review_dir / "workbook_evidence.txt"
    content = (
        "\n\n".join(workbooks) + "\n"
        if workbooks
        else "No captured DR .xlsx workbooks. Check the manifest for unavailable formats.\n"
    )
    write_text(output, content)
    return output


def _advance_after_verification(
    state: dict[str, Any], findings: list[dict[str, Any]]
) -> None:
    if any(finding["verification"].get("verdict") is None for finding in findings):
        state["status"] = "verifying"
        return
    terminal_verdicts = {"rejected", "duplicate", "insufficient_evidence"}
    for finding in findings:
        if finding["verification"].get("verdict") in terminal_verdicts:
            finding["reconciliation_required"] = False
    actionable = [
        finding
        for finding in findings
        if finding["verification"].get("verdict") not in terminal_verdicts
    ]
    if not actionable:
        state["status"] = "completed"
    elif any(finding.get("reconciliation_required") for finding in actionable):
        state["status"] = "reconciling"
    else:
        state["status"] = "awaiting_decisions"


def import_verifications(review_dir: Path, verification_path: Path) -> int:
    state = _load_state(review_dir)
    findings_payload = _read_json(review_dir / "findings.json")
    findings = findings_payload.get("findings", [])
    if not findings:
        raise ValueError("There are no findings to verify")
    if any(item.get("decision") for item in findings):
        raise ValueError("Verification cannot be changed after decisions are recorded")
    payload = _read_json(verification_path)
    values = payload.get("verifications") if isinstance(payload, dict) else payload
    if not isinstance(values, list) or not values:
        raise ValueError("Verification input must contain at least one verification")
    findings_by_id = {item["finding_id"]: item for item in findings}
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Each verification must be a JSON object")
        finding_id = _string(value.get("finding_id"), "verification.finding_id")
        if finding_id not in findings_by_id:
            raise ValueError(f"Verification refers to unknown finding: {finding_id}")
        if finding_id in seen:
            raise ValueError(f"Duplicate verification for finding: {finding_id}")
        seen.add(finding_id)
        verdict = _string(value.get("verdict"), "verification.verdict").casefold()
        if verdict not in VERDICTS:
            raise ValueError(f"Unknown verification verdict: {verdict}")
        rationale = _string(value.get("rationale"), "verification.rationale")
        finding = findings_by_id[finding_id]
        if finding["verification"].get("verdict") is not None:
            raise ValueError(f"Finding already has a verification: {finding_id}")
        severity = value.get("severity")
        severity_changed = False
        if severity is not None:
            if not isinstance(severity, str) or severity.casefold() not in SEVERITIES:
                raise ValueError(f"Unknown verification severity: {severity}")
            severity = severity.casefold()
            if severity != finding["severity"]:
                finding["severity"] = severity
                finding["reconciliation_required"] = True
                severity_changed = True
        elif verdict in {"downgraded", "upgraded"}:
            raise ValueError(f"Verification verdict '{verdict}' requires a severity")
        finding["verification"]["verdict"] = verdict
        finding["verification"]["rationale"] = rationale
        finding["verification"]["severity"] = severity
        finding["verification"]["severity_changed"] = severity_changed
        if value.get("duplicate_of") is not None:
            finding["verification"]["duplicate_of"] = _string(
                value["duplicate_of"], "verification.duplicate_of"
            )

    _advance_after_verification(state, findings)
    _write_json(review_dir / "findings.json", findings_payload)
    _save_state(review_dir, state)
    if state["status"] == "completed":
        render_review_comments(review_dir)
    return len(values)


def import_reconciliations(review_dir: Path, reconciliation_path: Path) -> int:
    state = _load_state(review_dir)
    payload = _read_json(review_dir / "findings.json")
    findings = payload.get("findings", [])
    if not findings:
        raise ValueError("There are no findings to reconcile")
    if any(finding["verification"].get("verdict") is None for finding in findings):
        raise ValueError("Every finding must be independently verified before reconciliation")

    reconciliation_payload = _read_json(reconciliation_path)
    values = (
        reconciliation_payload.get("reconciliations")
        if isinstance(reconciliation_payload, dict)
        else None
    )
    if not isinstance(values, list) or not values:
        raise ValueError("Reconciliation input must contain a reconciliations list")
    findings_by_id = {finding["finding_id"]: finding for finding in findings}
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Each reconciliation must be a JSON object")
        finding_id = _string(value.get("finding_id"), "reconciliation.finding_id")
        if finding_id not in findings_by_id:
            raise ValueError(f"Reconciliation refers to unknown finding: {finding_id}")
        if finding_id in seen:
            raise ValueError(f"Duplicate reconciliation for finding: {finding_id}")
        seen.add(finding_id)
        finding = findings_by_id[finding_id]
        if not finding.get("reconciliation_required"):
            raise ValueError(f"Finding does not require reconciliation: {finding_id}")
        rationale = _string(value.get("rationale"), "reconciliation.rationale")
        recommendation = value.get("recommendation")
        severity = value.get("severity")
        if severity is not None:
            if not isinstance(severity, str) or severity.casefold() not in SEVERITIES:
                raise ValueError(f"Unknown reconciliation severity: {severity}")
            severity = severity.casefold()
        if len(finding["recommendation"].split("\n\n")) > 1:
            recommendation = _string(
                recommendation, "reconciliation.recommendation"
            )
            options = finding["recommendation"].split("\n\n")
            if recommendation not in options:
                raise ValueError(
                    "Reconciliation recommendation must select one of the merged recommendations"
                )
            finding["recommendation"] = recommendation
        if (
            finding.get("severity_conflict")
            or finding["verification"].get("severity_changed")
        ):
            if severity is None:
                raise ValueError(
                    "A severity is required to resolve the finding's severity conflict"
                )
        if severity is not None:
            finding["severity"] = severity
        finding["reconciliation"] = {
            "rationale": rationale,
            "recommendation": finding["recommendation"],
            "severity": finding["severity"],
            "timestamp": _now(),
        }
        finding["reconciliation_required"] = False

    _advance_after_verification(state, findings)
    _write_json(review_dir / "findings.json", payload)
    _save_state(review_dir, state)
    if state["status"] == "completed":
        render_review_comments(review_dir)
    return len(values)


def _refresh_completion(state: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    terminal_verdicts = {"rejected", "duplicate", "insufficient_evidence"}
    resolved = all(
        finding.get("decision") is not None
        or finding.get("verification", {}).get("verdict") in terminal_verdicts
        for finding in findings
    )
    state["status"] = "completed" if resolved else "awaiting_decisions"
    state["decision_count"] = sum(finding.get("decision") is not None for finding in findings)


def record_decision(
    review_dir: Path,
    finding_id: str,
    decision: str,
    owner: str,
    rationale: str = "",
    intended_action: str = "",
) -> None:
    if decision not in DECISIONS:
        raise ValueError(f"Decision must be one of: {', '.join(DECISIONS)}")
    owner = _string(owner, "decision owner")
    findings_payload = _read_json(review_dir / "findings.json")
    findings = findings_payload.get("findings", [])
    if any(item.get("verification", {}).get("verdict") is None for item in findings):
        raise ValueError("All findings must be independently verified before decisions")
    if any(item.get("reconciliation_required") for item in findings):
        raise ValueError("All finding conflicts must be reconciled before decisions")
    finding = next(
        (item for item in findings if item.get("finding_id") == finding_id),
        None,
    )
    if finding is None:
        raise ValueError(f"Unknown finding ID: {finding_id}")
    if finding.get("decision") is not None:
        raise ValueError(f"A decision is already recorded for finding: {finding_id}")
    verdict = finding.get("verification", {}).get("verdict")
    if verdict is None:
        raise ValueError("A finding needs independent verification before a decision")
    if verdict in {"rejected", "duplicate", "insufficient_evidence"}:
        raise ValueError(f"A finding with verdict '{verdict}' cannot receive a decision")
    if finding.get("reconciliation_required"):
        raise ValueError("A finding needs reconciliation before a human decision")
    finding["decision"] = {
        "finding_id": finding_id,
        "decision": decision,
        "owner": owner,
        "timestamp": _now(),
        "rationale": rationale.strip(),
        "intended_action": intended_action.strip(),
    }
    _write_json(review_dir / "findings.json", findings_payload)
    state = _load_state(review_dir)
    _refresh_completion(state, findings)
    _save_state(review_dir, state)
    if state["status"] == "completed":
        render_review_comments(review_dir)


def import_function_map(review_dir: Path, function_map_path: Path) -> int:
    state = _load_state(review_dir)
    payload = _read_json(function_map_path)
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("Function map must be an object with an entries list")
    required_fields = (
        "business_function",
        "screen_or_chapter",
        "ui_component",
        "ui_event",
        "validation",
        "api",
        "request_response_field",
        "db_mapping",
        "testable_outcome",
    )
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Function-map entry {index + 1} must be an object")
        for field in required_fields:
            value = entry.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"Function-map entry {index + 1} field '{field}' must be text or null"
                )
        if not entry.get("business_function"):
            raise ValueError(
                f"Function-map entry {index + 1} requires business_function"
            )
    _write_json(review_dir / "function_map.json", {"entries": entries})
    state["function_map_count"] = len(entries)
    _save_state(review_dir, state)
    return len(entries)


def render_report(review_dir: Path, output_path: Path | None = None) -> Path:
    state = _load_state(review_dir)
    findings = _read_json(review_dir / "findings.json").get("findings", [])
    function_map = _read_json(review_dir / "function_map.json").get("entries", [])
    report_path = output_path or review_dir / "review_report.md"
    lines = [
        f"# DR review report: {state['function_key']} / {state['review_id']}",
        "",
        f"- Status: **{state['status']}**",
        f"- Scope: {state['scope']}",
        f"- Baseline: {state['created_at']}",
        f"- Reviewer: {state.get('reviewer') or 'Not specified'}",
        f"- DR page/version: {state.get('dr_page_id') or 'local'} / "
        f"{state.get('dr_version') or 'not supplied'}",
        f"- BR page/version: {state.get('br_page_id') or 'local'} / "
        f"{state.get('br_version') or 'not supplied'}",
        f"- Findings: {len(findings)}",
        f"- Function-map entries: {len(function_map)}",
        "",
        "## Evidence snapshot",
        "",
        "| Source | Type | File | SHA-256 | Text extraction |",
        "|---|---|---|---|---|",
    ]
    for source in state["sources"]:
        lines.append(
            f"| `{source['source_id']}` | {source['type']} | {source['filename']} "
            f"| `{source['sha256']}` | {source['text_extraction']} |"
        )
    if function_map:
        lines.extend(["", "## Function map", ""])
        map_fields = (
            "business_function",
            "screen_or_chapter",
            "ui_component",
            "ui_event",
            "validation",
            "api",
            "request_response_field",
            "db_mapping",
            "testable_outcome",
        )
        for entry in function_map:
            values = {field: entry.get(field) or "Not specified" for field in map_fields}
            lines.append(
                "- **{business_function}** → {screen_or_chapter} → {ui_component} "
                "→ {ui_event} → {validation} → {api} → {request_response_field} "
                "→ {db_mapping} → {testable_outcome}".format(**values)
            )
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("No findings have been imported.")
    for finding in findings:
        verdict = finding["verification"].get("verdict") or "awaiting independent review"
        lines.extend(
            [
                f"### {finding['finding_id']}: {finding['title']}",
                "",
                f"- Severity: {finding['severity']} "
                f"({'must change' if finding['must_change'] else 'advisory'})",
                f"- Tracks: {', '.join(finding['originating_tracks'])}",
                f"- Verification: {verdict}",
                f"- Severity conflict: "
                f"{'yes' if finding['severity_conflict'] else 'no'}",
                f"- Reconciliation required: "
                f"{'yes' if finding['reconciliation_required'] else 'no'}",
                f"- Decision: "
                f"{finding['decision']['decision'] if finding['decision'] else 'not recorded'}",
                "",
                finding["summary"],
                "",
                f"**Impact:** {finding['impact']}",
                "",
                f"**Recommendation:** {finding['recommendation']}",
                "",
                "**Evidence:**",
            ]
        )
        for evidence in finding["evidence"]:
            quote = evidence["quote"].replace("\n", " ")
            lines.append(
                f"- `{evidence['source_id']}` — {evidence['locator']}: > {quote}"
            )
        if finding["verification"].get("rationale"):
            lines.extend(
                [
                    "",
                    f"**Verification rationale:** {finding['verification']['rationale']}",
                ]
            )
        reconciliation = finding.get("reconciliation")
        if reconciliation:
            lines.extend(
                [
                    "",
                    f"**Reconciliation rationale:** {reconciliation['rationale']}",
                ]
            )
        if finding["decision"]:
            decision = finding["decision"]
            lines.extend(
                [
                    "",
                    f"**Decision owner:** {decision['owner']}",
                    f"**Decision rationale:** {decision['rationale'] or 'Not provided'}",
                    f"**Intended action:** {decision['intended_action'] or 'Not specified'}",
                ]
            )
        lines.append("")
    lines.extend(
        [
            "---",
            "This report reflects a local, read-only workflow. Evidence citations are checked",
            "against the captured snapshots; semantic verification remains an independent",
            "reviewer or human responsibility.",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def render_review_comments(review_dir: Path, output_path: Path | None = None) -> Path:
    """Write accepted findings as a local Markdown deliverable after completion."""
    state = _load_state(review_dir)
    if state["status"] != "completed":
        raise ValueError(
            "Review comments can only be generated after the review is completed"
        )

    findings = _read_json(review_dir / "findings.json").get("findings", [])
    accepted = [
        finding
        for finding in findings
        if (finding.get("decision") or {}).get("decision") == "accept"
    ]
    report_path = output_path or review_dir / "review_comments.md"
    lines = [
        f"# Accepted DR review comments: {state['function_key']} / {state['review_id']}",
        "",
        f"- Scope: {state['scope']}",
        f"- Tracks: {', '.join(state['tracks'])}",
        f"- DR page/version: {state.get('dr_page_id') or 'local'} / "
        f"{state.get('dr_version') or 'not supplied'}",
        f"- BR page/version: {state.get('br_page_id') or 'local'} / "
        f"{state.get('br_version') or 'not supplied'}",
        f"- Completed: {state['updated_at']}",
        f"- Accepted comments: {len(accepted)}",
        "",
        "This local file contains only findings explicitly accepted by the "
        "review decision-maker. It does not modify or publish to Confluence.",
        "",
    ]
    if not accepted:
        lines.append("No findings were accepted for the review.")

    for finding in accepted:
        decision = finding["decision"]
        verification = finding.get("verification") or {}
        lines.extend(
            [
                f"## {finding['finding_id']}: {finding['title']}",
                "",
                f"- Severity: {finding['severity']}",
                f"- Track(s): {', '.join(finding.get('originating_tracks') or [finding['track']])}",
                f"- Verification: {verification.get('verdict') or 'not recorded'}",
                f"- Decision owner: {decision['owner']}",
                f"- Decision recorded: {decision['timestamp']}",
                "",
                "### Finding",
                "",
                finding["summary"],
                "",
                "### Impact",
                "",
                finding["impact"],
                "",
                "### Recommended DR change",
                "",
                finding["recommendation"],
                "",
                "### Evidence",
                "",
            ]
        )
        for evidence in finding["evidence"]:
            quote_lines = evidence["quote"].splitlines() or [""]
            lines.append(
                f"- Source `{evidence['source_id']}`, {evidence['locator']}:"
            )
            lines.extend(f"  > {line}" for line in quote_lines)
        if verification.get("rationale"):
            lines.extend(
                ["", "### Independent verification", "", verification["rationale"]]
            )
        reconciliation = finding.get("reconciliation")
        if reconciliation:
            lines.extend(
                [
                    "",
                    "### Reconciliation",
                    "",
                    reconciliation.get("rationale") or "Resolved; no rationale recorded.",
                ]
            )
        if decision.get("rationale"):
            lines.extend(["", "### Decision rationale", "", decision["rationale"]])
        if decision.get("intended_action"):
            lines.extend(
                ["", "### Intended follow-up", "", decision["intended_action"]]
            )
        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return report_path


def get_status(review_dir: Path) -> dict[str, Any]:
    state = _load_state(review_dir)
    findings = _read_json(review_dir / "findings.json").get("findings", [])
    return {
        "function_key": state["function_key"],
        "review_id": state["review_id"],
        "status": state["status"],
        "scope": state["scope"],
        "tracks": state["tracks"],
        "sources": len(state["sources"]),
        "findings": len(findings),
        "decisions": sum(finding.get("decision") is not None for finding in findings),
        "unverified": sum(
            finding.get("verification", {}).get("verdict") is None
            for finding in findings
        ),
        "needs_reconciliation": sum(
            finding.get("reconciliation_required", False) for finding in findings
        ),
        "review_comments": str((review_dir / "review_comments.md").resolve())
        if (review_dir / "review_comments.md").is_file()
        else None,
        "review_dir": str(review_dir.resolve()),
    }
