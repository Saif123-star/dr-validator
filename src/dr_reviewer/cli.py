from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .confluence import ConfluenceClient, ConfluenceSettings
from .publication import (
    ReviewPagePublisher,
    approve_publication,
    build_publication_plan,
    verify_publication,
)
from .sources import PageSource, initialize_review_from_sources
from .workflow import (
    DECISIONS,
    TRACKS,
    create_brief,
    get_status,
    build_source_registry,
    import_findings,
    import_function_map,
    import_reconciliations,
    import_verifications,
    record_decision,
    render_report,
    validate_findings,
)


def _confluence_client(env_file: Path | None) -> ConfluenceClient:
    return ConfluenceClient(ConfluenceSettings.from_environment(env_file))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dr-review",
        description=(
            "Design-requirement review workflow: read-only review, then an optional, "
            "human-approved Confluence review page."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser(
        "init",
        help="Snapshot a DR, BR, and attachments from local files or Confluence (read-only)",
    )
    init.add_argument("--function-key", required=True)
    init.add_argument("--dr", type=Path, help="Local DR file; omit to fetch --dr-page-id")
    init.add_argument("--br", type=Path, help="Local BR file; omit to fetch --br-page-id")
    init.add_argument("--attachments", type=Path)
    init.add_argument("--runs-dir", type=Path, default=Path("runs"))
    init.add_argument("--scope", choices=("full", "targeted"), default="full")
    init.add_argument("--tracks", nargs="+", choices=TRACKS)
    init.add_argument("--dr-page-id")
    init.add_argument(
        "--dr-version",
        help="DR version; required with a local --dr, optional pin for a fetched DR",
    )
    init.add_argument("--dr-url")
    init.add_argument("--br-page-id")
    init.add_argument("--br-version")
    init.add_argument("--br-url")
    init.add_argument("--reviewer")
    init.add_argument("--env-file", type=Path, help="Confluence settings file (default: .env)")
    init.add_argument(
        "--context-source",
        action="append",
        default=[],
        metavar="TYPE=PATH",
        help="Add local context: workshop_decision, figma_export, or comment_export",
    )

    brief = commands.add_parser("brief", help="Regenerate the locked review brief")
    brief.add_argument("review_dir", type=Path)

    findings = commands.add_parser("findings-import", help="Validate and merge findings JSON")
    findings.add_argument("review_dir", type=Path)
    findings.add_argument("findings_file", type=Path)

    validate = commands.add_parser(
        "findings-validate",
        help="Validate findings against the review scope and source snapshots",
    )
    validate.add_argument("review_dir", type=Path)
    validate.add_argument("findings_file", type=Path)

    registry = commands.add_parser(
        "source-registry",
        help="Verify source snapshots and rebuild the source registry",
    )
    registry.add_argument("review_dir", type=Path)
    registry.add_argument("--output", type=Path)

    verifications = commands.add_parser(
        "verifications-import",
        help="Import independent verification results",
    )
    verifications.add_argument("review_dir", type=Path)
    verifications.add_argument("verification_file", type=Path)

    reconciliations = commands.add_parser(
        "reconciliations-import",
        help="Import resolutions for verified finding conflicts",
    )
    reconciliations.add_argument("review_dir", type=Path)
    reconciliations.add_argument("reconciliation_file", type=Path)

    function_map = commands.add_parser(
        "function-map-import",
        help="Import a structured function map",
    )
    function_map.add_argument("review_dir", type=Path)
    function_map.add_argument("function_map_file", type=Path)

    decide = commands.add_parser("decide", help="Record a human disposition")
    decide.add_argument("review_dir", type=Path)
    decide.add_argument("finding_id")
    decide.add_argument("--decision", required=True, choices=DECISIONS)
    decide.add_argument("--owner", required=True)
    decide.add_argument("--rationale", default="")
    decide.add_argument("--action", default="")

    report = commands.add_parser("report", help="Render the review report")
    report.add_argument("review_dir", type=Path)
    report.add_argument("--output", type=Path)

    status = commands.add_parser("status", help="Show the review state")
    status.add_argument("review_dir", type=Path)

    plan = commands.add_parser(
        "publish-plan",
        help="Build the publication plan and page preview (writes nothing to Confluence)",
    )
    plan.add_argument("review_dir", type=Path)

    approve = commands.add_parser(
        "publish-approve",
        help="Record a human approval that locks the publication plan hash",
    )
    approve.add_argument("review_dir", type=Path)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument(
        "--statement",
        required=True,
        help="The approver's own words authorizing publication",
    )

    publish = commands.add_parser(
        "publish",
        help="Create the approved Confluence review page; rerun to resume after a failure",
    )
    publish.add_argument("review_dir", type=Path)
    publish.add_argument("--env-file", type=Path)

    publish_verify = commands.add_parser(
        "publish-verify",
        help="Re-read the published review page and confirm it matches the plan",
    )
    publish_verify.add_argument("review_dir", type=Path)
    publish_verify.add_argument("--env-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            context_sources = []
            for value in args.context_source:
                source_type, separator, source_path = value.partition("=")
                if not separator or not source_type or not source_path:
                    raise ValueError(
                        "--context-source must use TYPE=PATH, for example "
                        "workshop_decision=decisions.md"
                    )
                context_sources.append((source_type, Path(source_path)))
            review_dir = initialize_review_from_sources(
                args.function_key,
                PageSource(args.dr, args.dr_page_id, args.dr_version, args.dr_url),
                PageSource(args.br, args.br_page_id, args.br_version, args.br_url),
                env_file=args.env_file,
                runs_dir=args.runs_dir,
                attachments_dir=args.attachments,
                scope=args.scope,
                tracks=args.tracks,
                reviewer=args.reviewer,
                context_sources=context_sources,
            )
            print(review_dir)
        elif args.command == "brief":
            print(create_brief(args.review_dir))
        elif args.command == "findings-import":
            count = import_findings(args.review_dir, args.findings_file)
            print(f"Imported {count} merged finding(s).")
        elif args.command == "findings-validate":
            count = validate_findings(args.review_dir, args.findings_file)
            print(f"Validated {count} finding(s); no review state was changed.")
        elif args.command == "source-registry":
            print(build_source_registry(args.review_dir, args.output))
        elif args.command == "verifications-import":
            count = import_verifications(args.review_dir, args.verification_file)
            print(f"Imported {count} verification result(s).")
        elif args.command == "reconciliations-import":
            count = import_reconciliations(args.review_dir, args.reconciliation_file)
            print(f"Imported {count} reconciliation result(s).")
        elif args.command == "function-map-import":
            count = import_function_map(args.review_dir, args.function_map_file)
            print(f"Imported {count} function-map entry(ies).")
        elif args.command == "decide":
            record_decision(
                args.review_dir,
                args.finding_id,
                args.decision,
                args.owner,
                args.rationale,
                args.action,
            )
            print(f"Recorded decision for {args.finding_id}.")
        elif args.command == "report":
            print(render_report(args.review_dir, args.output))
        elif args.command == "status":
            print(json.dumps(get_status(args.review_dir), ensure_ascii=False, indent=2))
        elif args.command == "publish-plan":
            print(build_publication_plan(args.review_dir))
        elif args.command == "publish-approve":
            print(approve_publication(args.review_dir, args.approved_by, args.statement))
        elif args.command == "publish":
            publisher = ReviewPagePublisher(args.review_dir, _confluence_client(args.env_file))
            print(json.dumps(publisher.publish(), ensure_ascii=False, indent=2))
        elif args.command == "publish-verify":
            result = verify_publication(args.review_dir, _confluence_client(args.env_file))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"dr-review: error: {exc}", file=sys.stderr)
        return 2
