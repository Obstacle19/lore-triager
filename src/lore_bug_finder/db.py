from __future__ import annotations

import sqlite3
from pathlib import Path

from lore_bug_finder.models import MessageRecord, SearchResult, TriageDecision
from lore_bug_finder.utils import normalize_subject_line


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    subject TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_email TEXT NOT NULL,
    date_utc TEXT,
    date_epoch INTEGER,
    list_name TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    archive_url TEXT,
    references_header TEXT NOT NULL,
    in_reply_to TEXT NOT NULL,
    body_text TEXT NOT NULL,
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_date_epoch ON messages(date_epoch);
CREATE INDEX IF NOT EXISTS idx_messages_list_name ON messages(list_name);

CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    subject,
    body_text,
    author_name,
    list_name,
    message_id UNINDEXED,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS triage_results (
    message_id TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    scope TEXT NOT NULL,
    model TEXT NOT NULL,
    relevant INTEGER NOT NULL,
    classification TEXT NOT NULL,
    confidence TEXT NOT NULL,
    exclude_reason TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence TEXT NOT NULL,
    published_at TEXT,
    list_name TEXT NOT NULL,
    report_path TEXT,
    raw_response TEXT NOT NULL,
    title TEXT NOT NULL,
    triaged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(message_id) REFERENCES messages(message_id)
);
"""


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def upsert_message(connection: sqlite3.Connection, record: MessageRecord) -> int:
    connection.execute(
        """
        INSERT INTO messages (
            message_id,
            subject,
            author_name,
            author_email,
            date_utc,
            date_epoch,
            list_name,
            thread_key,
            archive_url,
            references_header,
            in_reply_to,
            body_text,
            source_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            subject=excluded.subject,
            author_name=excluded.author_name,
            author_email=excluded.author_email,
            date_utc=excluded.date_utc,
            date_epoch=excluded.date_epoch,
            list_name=excluded.list_name,
            thread_key=excluded.thread_key,
            archive_url=excluded.archive_url,
            references_header=excluded.references_header,
            in_reply_to=excluded.in_reply_to,
            body_text=excluded.body_text,
            source_path=excluded.source_path
        """,
        (
            record.message_id,
            record.subject,
            record.author_name,
            record.author_email,
            record.date_utc,
            record.date_epoch,
            record.list_name,
            record.thread_key,
            record.archive_url,
            record.references,
            record.in_reply_to,
            record.body_text,
            record.source_path,
        ),
    )
    row = connection.execute(
        "SELECT id FROM messages WHERE message_id = ?",
        (record.message_id,),
    ).fetchone()
    assert row is not None
    row_id = int(row["id"])
    connection.execute("DELETE FROM message_fts WHERE rowid = ?", (row_id,))
    connection.execute(
        """
        INSERT INTO message_fts(rowid, subject, body_text, author_name, list_name, message_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            row_id,
            record.subject,
            record.body_text,
            record.author_name,
            record.list_name,
            record.message_id,
        ),
    )
    return row_id


def _normalize_query(query_text: str) -> str | None:
    stripped = query_text.strip()
    if not stripped:
        return None
    parts = [part for part in stripped.split() if part]
    if not parts:
        return None
    return " AND ".join(f'"{part.replace(chr(34), "")}"' for part in parts)


def search_messages(
    connection: sqlite3.Connection,
    *,
    query_text: str,
    scopes: list[str] | None,
    limit: int,
    after_epoch: int | None = None,
    before_epoch: int | None = None,
) -> list[SearchResult]:
    normalized_query = _normalize_query(query_text)
    where = ["1 = 1"]
    params: list[object] = []
    if scopes:
        placeholders = ", ".join("?" for _ in scopes)
        where.append(f"m.list_name IN ({placeholders})")
        params.extend(scopes)
    if after_epoch is not None:
        where.append("m.date_epoch >= ?")
        params.append(after_epoch)
    if before_epoch is not None:
        where.append("m.date_epoch <= ?")
        params.append(before_epoch)
    try:
        if normalized_query:
            rows = connection.execute(
                f"""
                SELECT
                    m.message_id,
                    m.subject,
                    m.author_name,
                    m.author_email,
                    m.date_utc,
                    m.list_name,
                    m.archive_url,
                    m.body_text,
                    m.source_path,
                    snippet(message_fts, 1, '[', ']', ' ... ', 18) AS excerpt
                FROM message_fts
                JOIN messages AS m ON m.id = message_fts.rowid
                WHERE message_fts MATCH ?
                  AND {" AND ".join(where)}
                ORDER BY COALESCE(m.date_epoch, 0) DESC, m.message_id DESC
                LIMIT ?
                """,
                [normalized_query, *params, limit],
            ).fetchall()
        else:
            rows = connection.execute(
                f"""
                SELECT
                    m.message_id,
                    m.subject,
                    m.author_name,
                    m.author_email,
                    m.date_utc,
                    m.list_name,
                    m.archive_url,
                    m.body_text,
                    m.source_path,
                    substr(m.body_text, 1, 240) AS excerpt
                FROM messages AS m
                WHERE {" AND ".join(where)}
                ORDER BY COALESCE(m.date_epoch, 0) DESC, m.message_id DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
    except sqlite3.OperationalError:
        like_params: list[object] = []
        like_where = ["1 = 1"]
        if query_text.strip():
            for term in [part for part in query_text.split() if part]:
                like_where.append("(m.subject LIKE ? OR m.body_text LIKE ?)")
                like_fragment = f"%{term}%"
                like_params.extend([like_fragment, like_fragment])
        if scopes:
            placeholders = ", ".join("?" for _ in scopes)
            like_where.append(f"m.list_name IN ({placeholders})")
            like_params.extend(scopes)
        if after_epoch is not None:
            like_where.append("m.date_epoch >= ?")
            like_params.append(after_epoch)
        if before_epoch is not None:
            like_where.append("m.date_epoch <= ?")
            like_params.append(before_epoch)
        like_params.append(limit)
        rows = connection.execute(
            f"""
            SELECT
                m.message_id,
                m.subject,
                m.author_name,
                m.author_email,
                m.date_utc,
                m.list_name,
                m.archive_url,
                m.body_text,
                m.source_path,
                substr(m.body_text, 1, 240) AS excerpt
            FROM messages AS m
            WHERE {" AND ".join(like_where)}
            ORDER BY COALESCE(m.date_epoch, 0) DESC, m.message_id DESC
            LIMIT ?
            """,
            like_params,
        ).fetchall()
    return [
        SearchResult(
            message_id=row["message_id"],
            subject=row["subject"],
            author_name=row["author_name"],
            author_email=row["author_email"],
            date_utc=row["date_utc"],
            list_name=row["list_name"],
            archive_url=row["archive_url"],
            body_text=row["body_text"],
            excerpt=row["excerpt"] or "",
            source_path=row["source_path"],
        )
        for row in rows
    ]


def get_message_by_id(connection: sqlite3.Connection, message_id: str) -> SearchResult | None:
    row = connection.execute(
        """
        SELECT
            message_id,
            subject,
            author_name,
            author_email,
            date_utc,
            list_name,
            archive_url,
            body_text,
            source_path,
            substr(body_text, 1, 240) AS excerpt
        FROM messages
        WHERE message_id = ?
        """,
        (message_id,),
    ).fetchone()
    if row is None:
        return None
    return SearchResult(
        message_id=row["message_id"],
        subject=row["subject"],
        author_name=row["author_name"],
        author_email=row["author_email"],
        date_utc=row["date_utc"],
        list_name=row["list_name"],
        archive_url=row["archive_url"],
        body_text=row["body_text"],
        excerpt=row["excerpt"] or "",
        source_path=row["source_path"],
    )


def get_related_messages(
    connection: sqlite3.Connection,
    message_id: str,
    *,
    limit: int = 3,
) -> list[SearchResult]:
    base = connection.execute(
        """
        SELECT
            message_id,
            subject,
            list_name,
            thread_key,
            in_reply_to,
            date_epoch
        FROM messages
        WHERE message_id = ?
        """,
        (message_id,),
    ).fetchone()
    if base is None:
        return []

    rows = connection.execute(
        """
        SELECT
            m.message_id,
            m.subject,
            m.author_name,
            m.author_email,
            m.date_utc,
            m.list_name,
            m.archive_url,
            m.body_text,
            m.source_path,
            substr(m.body_text, 1, 240) AS excerpt
        FROM messages AS m
        WHERE m.message_id != ?
          AND (
            (? != '' AND m.thread_key = ?)
            OR (? != '' AND m.in_reply_to = ?)
            OR (? != '' AND m.message_id = ?)
          )
        ORDER BY COALESCE(m.date_epoch, 0) ASC, m.message_id ASC
        LIMIT ?
        """,
        (
            base["message_id"],
            base["thread_key"],
            base["thread_key"],
            base["message_id"],
            base["message_id"],
            base["in_reply_to"],
            base["in_reply_to"],
            limit,
        ),
    ).fetchall()
    if rows:
        return [
            SearchResult(
                message_id=row["message_id"],
                subject=row["subject"],
                author_name=row["author_name"],
                author_email=row["author_email"],
                date_utc=row["date_utc"],
                list_name=row["list_name"],
                archive_url=row["archive_url"],
                body_text=row["body_text"],
                excerpt=row["excerpt"] or "",
                source_path=row["source_path"],
            )
            for row in rows
        ]

    normalized_subject = normalize_subject_line(str(base["subject"] or "")).casefold()
    if not normalized_subject:
        return []
    subject_rows = connection.execute(
        """
        SELECT
            m.message_id,
            m.subject,
            m.author_name,
            m.author_email,
            m.date_utc,
            m.list_name,
            m.archive_url,
            m.body_text,
            m.source_path,
            substr(m.body_text, 1, 240) AS excerpt
        FROM messages AS m
        WHERE m.message_id != ?
          AND m.list_name = ?
        ORDER BY ABS(COALESCE(m.date_epoch, 0) - COALESCE(?, 0)) ASC, m.message_id ASC
        LIMIT 64
        """,
        (
            base["message_id"],
            base["list_name"],
            base["date_epoch"],
        ),
    ).fetchall()
    related: list[SearchResult] = []
    for row in subject_rows:
        if normalize_subject_line(str(row["subject"] or "")).casefold() != normalized_subject:
            continue
        related.append(
            SearchResult(
                message_id=row["message_id"],
                subject=row["subject"],
                author_name=row["author_name"],
                author_email=row["author_email"],
                date_utc=row["date_utc"],
                list_name=row["list_name"],
                archive_url=row["archive_url"],
                body_text=row["body_text"],
                excerpt=row["excerpt"] or "",
                source_path=row["source_path"],
            )
        )
        if len(related) >= limit:
            break
    return related


def upsert_triage_result(connection: sqlite3.Connection, decision: TriageDecision) -> None:
    connection.execute(
        """
        INSERT INTO triage_results (
            message_id,
            query_text,
            scope,
            model,
            relevant,
            classification,
            confidence,
            exclude_reason,
            summary,
            evidence,
            published_at,
            list_name,
            report_path,
            raw_response,
            title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            query_text=excluded.query_text,
            scope=excluded.scope,
            model=excluded.model,
            relevant=excluded.relevant,
            classification=excluded.classification,
            confidence=excluded.confidence,
            exclude_reason=excluded.exclude_reason,
            summary=excluded.summary,
            evidence=excluded.evidence,
            published_at=excluded.published_at,
            list_name=excluded.list_name,
            report_path=excluded.report_path,
            raw_response=excluded.raw_response,
            title=excluded.title,
            triaged_at=CURRENT_TIMESTAMP
        """,
        (
            decision.message_id,
            decision.query,
            decision.scope,
            decision.model,
            int(decision.relevant),
            decision.classification,
            decision.confidence,
            decision.exclude_reason,
            decision.summary,
            decision.evidence,
            decision.published_at,
            decision.list_name,
            decision.report_path,
            decision.raw_response,
            decision.title,
        ),
    )


def list_relevant_triage_results(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            t.message_id,
            t.classification,
            t.confidence,
            t.summary,
            t.evidence,
            t.published_at,
            t.list_name,
            t.report_path,
            t.title,
            m.subject,
            m.author_name,
            m.author_email,
            m.archive_url
        FROM triage_results AS t
        JOIN messages AS m ON m.message_id = t.message_id
        WHERE t.relevant = 1 AND t.report_path IS NOT NULL
        ORDER BY COALESCE(m.date_epoch, 0) DESC, t.message_id DESC
        """
    ).fetchall()
