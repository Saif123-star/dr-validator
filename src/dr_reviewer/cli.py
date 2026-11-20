from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    initialize_review,
    record_decision,
    render_report,
    validate_findings,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dr-review",
        description="Local-first, read-only design-requirement review workflow.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Snapshot a DR, BR, and optional attachments")
    init.add_argument("--function-key", required=True)
    init.add_argument("--dr", required=True, type=Path)
    init.add_argument("--br", required=True, type=Path)
    init.add_argument("--attachments", type=Path)
    init.add_argument("--runs-dir", type=Path, default=Path("runs"))
    init.add_argument("--scope", choices=("full", "targeted"), default="full")
    init.add_argument("--tracks", nargs="+", choices=TRACKS)
    init.add_argument("--dr-page-id")
    init.add_argument("--dr-version")
    init.add_argument("--dr-url")
    init.add_argument("--br-page-id")
    init.add_argument("--br-version")
    init.add_argument("--br-url")
    init.add_argument("--reviewer")
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
            review_dir = initialize_review(
                function_key=args.function_key,
                dr_path=args.dr,
                br_path=args.br,
                runs_dir=args.runs_dir,
                attachments_dir=args.attachments,
                scope=args.scope,
                tracks=args.tracks,
                dr_page_id=args.dr_page_id,
                dr_version=args.dr_version,
                dr_url=args.dr_url,
                br_page_id=args.br_page_id,
                br_version=args.br_version,
                br_url=args.br_url,
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
        return 0
    except (OSError, ValueError) as exc:
        print(f"dr-review: error: {exc}", file=sys.stderr)
        return 2
