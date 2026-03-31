from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from lore_bug_finder.config import AppConfig
from lore_bug_finder.db import connect, get_related_messages, initialize_database, search_messages, upsert_triage_result
from lore_bug_finder.ingest import ingest_eml_tree, ingest_maildir, ingest_mbox
from lore_bug_finder.llm import classify_candidate
from lore_bug_finder.reporting import rebuild_docs_index, write_report
from lore_bug_finder.utils import coerce_date_boundary


def _parse_scope(scope_value: str | None) -> list[str] | None:
    if scope_value is None:
        return None
    if not scope_value.strip():
        return None
    if scope_value.strip().lower() == "all":
        return None
    scopes = [part.strip() for part in scope_value.split(",") if part.strip()]
    return scopes or None


def _display_query(query_text: str) -> str:
    return query_text.strip() or "(entire imported dataset)"


def _display_scope(scope_text: str | None) -> str:
    if not scope_text or not scope_text.strip() or scope_text.strip().lower() == "all":
        return "all imported messages"
    return scope_text.strip()


def _open_db(config: AppConfig):
    config.ensure_runtime_dirs()
    connection = connect(config.database_path)
    initialize_database(connection)
    return connection


def cmd_init(config: AppConfig, _args: argparse.Namespace) -> int:
    with _open_db(config) as connection:
        connection.commit()
    print(f"Initialized database at {config.database_path}")
    print(f"Docs directory: {config.docs_dir}")
    return 0


def cmd_ingest_mbox(config: AppConfig, args: argparse.Namespace) -> int:
    total = 0
    with _open_db(config) as connection:
        for raw_path in args.paths:
            total += ingest_mbox(connection, Path(raw_path), args.list_name)
    print(f"Ingested {total} messages from {len(args.paths)} mbox file(s)")
    return 0


def cmd_ingest_maildir(config: AppConfig, args: argparse.Namespace) -> int:
    total = 0
    with _open_db(config) as connection:
        for raw_path in args.paths:
            total += ingest_maildir(connection, Path(raw_path), args.list_name)
    print(f"Ingested {total} messages from {len(args.paths)} maildir path(s)")
    return 0


def cmd_ingest_eml(config: AppConfig, args: argparse.Namespace) -> int:
    total = 0
    with _open_db(config) as connection:
        for raw_path in args.paths:
            total += ingest_eml_tree(connection, Path(raw_path), args.list_name)
    print(f"Ingested {total} messages from {len(args.paths)} eml tree(s)")
    return 0


def cmd_search(config: AppConfig, args: argparse.Namespace) -> int:
    scopes = _parse_scope(args.scope)
    after_epoch = coerce_date_boundary(args.after, upper=False)
    before_epoch = coerce_date_boundary(args.before, upper=True)
    with _open_db(config) as connection:
        results = search_messages(
            connection,
            query_text=args.query,
            scopes=scopes,
            limit=args.limit,
            after_epoch=after_epoch,
            before_epoch=before_epoch,
        )
    if args.json:
        payload = [
            {
                "message_id": result.message_id,
                "subject": result.subject,
                "author_name": result.author_name,
                "author_email": result.author_email,
                "date_utc": result.date_utc,
                "list_name": result.list_name,
                "archive_url": result.archive_url,
                "excerpt": result.excerpt,
                "source_path": result.source_path,
            }
            for result in results
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not results:
        print("No matching messages found.")
        return 0
    print(f"Query filter: {_display_query(args.query)}")
    print(f"Scope filter: {_display_scope(args.scope)}")
    for index, result in enumerate(results, start=1):
        print(f"[{index}] {result.subject}")
        print(f"    message_id: {result.message_id}")
        print(f"    list: {result.list_name}")
        print(f"    date: {result.date_utc}")
        print(f"    author: {result.author_name} <{result.author_email}>")
        print(f"    source: {result.source_path}")
        print(f"    excerpt: {result.excerpt}")
    return 0


def cmd_triage(config: AppConfig, args: argparse.Namespace) -> int:
    scopes = _parse_scope(args.scope)
    after_epoch = coerce_date_boundary(args.after, upper=False)
    before_epoch = coerce_date_boundary(args.before, upper=True)
    query_label = _display_query(args.query)
    scope_label = _display_scope(args.scope)
    relevant_count = 0
    excluded_count = 0
    with _open_db(config) as connection:
        candidates = search_messages(
            connection,
            query_text=args.query,
            scopes=scopes,
            limit=args.limit,
            after_epoch=after_epoch,
            before_epoch=before_epoch,
        )
        if not candidates:
            print("No matching messages found for triage.")
            return 0
        print(f"Triage query filter: {query_label}")
        print(f"Triage scope filter: {scope_label}")
        for candidate in candidates:
            related_messages = get_related_messages(connection, candidate.message_id, limit=3)
            decision = classify_candidate(
                config,
                candidate,
                query=query_label,
                scope=scope_label,
                related_messages=related_messages,
                model_override=args.model,
            )
            if decision.model == "heuristic [llm_transport_error]":
                print(
                    f"Warning: LLM request failed for {candidate.message_id}; used heuristic fallback instead.",
                    file=sys.stderr,
                )
            if decision.relevant:
                relevant_count += 1
            else:
                excluded_count += 1
            if decision.relevant and args.write_docs:
                report_path = write_report(config, candidate, decision)
                decision = replace(decision, report_path=report_path)
            upsert_triage_result(connection, decision)
            print(f"{candidate.message_id} -> {decision.classification} ({decision.confidence})")
        connection.commit()
        index_path = rebuild_docs_index(config, connection)
    print(f"Relevant: {relevant_count}")
    print(f"Excluded or undecided: {excluded_count}")
    print(f"Docs index: {index_path}")
    return 0


def cmd_export_index(config: AppConfig, _args: argparse.Namespace) -> int:
    with _open_db(config) as connection:
        index_path = rebuild_docs_index(config, connection)
    print(f"Rebuilt docs index: {index_path}")
    return 0


def cmd_doctor(config: AppConfig, _args: argparse.Namespace) -> int:
    payload = {
        "project_root": str(config.project_root),
        "env_file_path": str(config.env_file_path),
        "database_path": str(config.database_path),
        "docs_dir": str(config.docs_dir),
        "data_dir": str(config.data_dir),
        "openai_base_url": config.base_url,
        "openai_model": config.model,
        "openai_output_mode": config.output_mode,
        "api_key_configured": bool(config.api_key),
        "http_timeout": config.http_timeout,
        "http_max_retries": config.http_max_retries,
        "http_retry_delay": config.http_retry_delay,
        "max_body_chars": config.max_body_chars,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mbox-triage",
        description="Offline triage for manually downloaded lore/public-inbox mbox archives.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize the database and docs directories")
    init_parser.set_defaults(func=cmd_init)

    for name, func, help_text in [
        ("ingest-mbox", cmd_ingest_mbox, "Ingest one or more manually decompressed .mbox files"),
        ("ingest-maildir", cmd_ingest_maildir, "Ingest one or more maildir directories"),
        ("ingest-eml", cmd_ingest_eml, "Ingest one or more directories containing .eml files"),
    ]:
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("paths", nargs="+")
        sub.add_argument(
            "--list-name",
            default=None,
            help="Optional override for list_name when the imported file does not contain a useful List-Id",
        )
        sub.set_defaults(func=func)

    search_parser = subparsers.add_parser("search", help="Inspect imported messages with optional local filters")
    search_parser.add_argument(
        "--query",
        default="",
        help="Optional local full-text filter. Omit it to list the newest imported messages.",
    )
    search_parser.add_argument(
        "--scope",
        default="",
        help="Optional local list_name filter. Omit it to search everything in the current database.",
    )
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument("--after", default=None, help="Lower date bound in ISO format, for example 2025-01-01")
    search_parser.add_argument("--before", default=None, help="Upper date bound in ISO format, for example 2025-12-31")
    search_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    search_parser.set_defaults(func=cmd_search)

    triage_parser = subparsers.add_parser(
        "triage",
        help="Classify imported messages and write Markdown reports. Query/scope are optional local filters.",
    )
    triage_parser.add_argument(
        "--query",
        default="",
        help="Optional local full-text filter before triage. Omit it to analyze imported messages directly.",
    )
    triage_parser.add_argument(
        "--scope",
        default="",
        help="Optional local list_name filter before triage. Omit it to analyze everything in the current database.",
    )
    triage_parser.add_argument("--limit", type=int, default=20)
    triage_parser.add_argument("--after", default=None, help="Lower date bound in ISO format")
    triage_parser.add_argument("--before", default=None, help="Upper date bound in ISO format")
    triage_parser.add_argument("--model", default=None, help="Override OPENAI_MODEL for this run")
    triage_parser.add_argument(
        "--write-docs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write Markdown reports for relevant findings",
    )
    triage_parser.set_defaults(func=cmd_triage)

    export_parser = subparsers.add_parser("export-index", help="Rebuild docs/index.json from triage results")
    export_parser.set_defaults(func=cmd_export_index)

    doctor_parser = subparsers.add_parser("doctor", help="Show current runtime configuration")
    doctor_parser.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = AppConfig.load()
    try:
        return args.func(config, args)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
