from __future__ import annotations

import json
from pathlib import Path

from lore_bug_finder.config import AppConfig
from lore_bug_finder.db import list_relevant_triage_results
from lore_bug_finder.models import SearchResult, TriageDecision
from lore_bug_finder.utils import build_topic_key, canonical_topic_title, representative_sort_key, slugify


def _display_path(config: AppConfig, path: Path) -> str:
    try:
        return str(path.relative_to(config.project_root))
    except ValueError:
        return str(path)


def _report_title(candidate: SearchResult, decision: TriageDecision) -> str:
    return canonical_topic_title(
        decision.title or candidate.subject,
        author_email=candidate.author_email,
        body_text=candidate.body_text,
    )


def _row_topic_key(row) -> str:
    return build_topic_key(
        row["subject"] or row["title"],
        row["thread_key"],
        author_email=row["author_email"],
        body_text=row["body_text"],
    )


def _row_rank(row) -> tuple[int, int, int, str, str]:
    return representative_sort_key(
        row["message_id"],
        row["thread_key"],
        row["author_email"],
        row["subject"] or row["title"],
        row["published_at"],
    )


def _dedupe_relevant_rows(rows):
    groups = {}
    for row in rows:
        key = _row_topic_key(row)
        best = groups.get(key)
        if best is None or _row_rank(row) < _row_rank(best):
            groups[key] = row
    return sorted(
        groups.values(),
        key=lambda row: (row["published_at"] or "", row["message_id"]),
        reverse=True,
    )


def _cleanup_superseded_reports(config: AppConfig, all_rows, selected_rows) -> None:
    selected_paths = {row["report_path"] for row in selected_rows if row["report_path"]}
    stale_paths = {
        row["report_path"]
        for row in all_rows
        if row["report_path"] and row["report_path"] not in selected_paths
    }
    for relative_path in stale_paths:
        path = (config.project_root / relative_path).resolve()
        try:
            path.relative_to(config.docs_dir.resolve())
        except ValueError:
            continue
        if path.exists() and path.is_file():
            path.unlink()


def write_report(config: AppConfig, candidate: SearchResult, decision: TriageDecision) -> str:
    config.docs_dir.mkdir(parents=True, exist_ok=True)
    date_prefix = (decision.published_at or "undated").split("T")[0]
    report_title = _report_title(candidate, decision)
    slug = slugify(report_title, default="bug-report")
    filename = f"{date_prefix}-{slug}.md"
    path = config.docs_dir / filename
    lines = [
        f"# {report_title}",
        "",
        f"- Message-ID: `{candidate.message_id}`",
        f"- Classification: `{decision.classification}`",
        f"- Confidence: `{decision.confidence}`",
        f"- Mailing list: `{candidate.list_name}`",
        f"- Published at: `{decision.published_at or 'unknown'}`",
        f"- Author: `{candidate.author_name} <{candidate.author_email}>`",
        f"- Archive URL: {candidate.archive_url or 'not recorded'}",
        f"- Source path: `{candidate.source_path}`",
        "",
        "## Summary",
        "",
        decision.summary,
        "",
        "## Evidence",
        "",
        decision.evidence,
        "",
        "## Original Subject",
        "",
        candidate.subject,
        "",
        "## Body Excerpt",
        "",
        "```text",
        candidate.body_text[:4000].strip(),
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return _display_path(config, path)


def rebuild_docs_index(config: AppConfig, connection) -> Path:
    config.docs_dir.mkdir(parents=True, exist_ok=True)
    all_rows = list_relevant_triage_results(connection)
    rows = _dedupe_relevant_rows(all_rows)
    _cleanup_superseded_reports(config, all_rows, rows)
    entries = []
    for row in rows:
        entries.append(
            {
                "message_id": row["message_id"],
                "title": canonical_topic_title(
                    row["subject"] or row["title"],
                    author_email=row["author_email"],
                    body_text=row["body_text"],
                ),
                "subject": row["subject"],
                "classification": row["classification"],
                "confidence": row["confidence"],
                "summary": row["summary"],
                "evidence": row["evidence"],
                "published_at": row["published_at"],
                "list_name": row["list_name"],
                "author_name": row["author_name"],
                "author_email": row["author_email"],
                "archive_url": row["archive_url"],
                "report_path": row["report_path"],
            }
        )
    output_path = config.docs_dir / "index.json"
    output_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
