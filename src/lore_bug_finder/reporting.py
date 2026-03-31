from __future__ import annotations

import json
from pathlib import Path

from lore_bug_finder.config import AppConfig
from lore_bug_finder.db import list_relevant_triage_results
from lore_bug_finder.models import SearchResult, TriageDecision
from lore_bug_finder.utils import slugify


def _display_path(config: AppConfig, path: Path) -> str:
    try:
        return str(path.relative_to(config.project_root))
    except ValueError:
        return str(path)


def write_report(config: AppConfig, candidate: SearchResult, decision: TriageDecision) -> str:
    config.docs_dir.mkdir(parents=True, exist_ok=True)
    date_prefix = (decision.published_at or "undated").split("T")[0]
    slug = slugify(decision.title or candidate.subject, default="bug-report")
    filename = f"{date_prefix}-{slug}.md"
    path = config.docs_dir / filename
    lines = [
        f"# {decision.title or candidate.subject}",
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
    entries = []
    for row in list_relevant_triage_results(connection):
        entries.append(
            {
                "message_id": row["message_id"],
                "title": row["title"],
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
