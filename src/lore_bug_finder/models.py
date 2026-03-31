from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MessageRecord:
    message_id: str
    subject: str
    author_name: str
    author_email: str
    date_utc: str | None
    date_epoch: int | None
    list_name: str
    thread_key: str
    archive_url: str | None
    references: str
    in_reply_to: str
    body_text: str
    source_path: str


@dataclass(slots=True)
class SearchResult:
    message_id: str
    subject: str
    author_name: str
    author_email: str
    date_utc: str | None
    list_name: str
    archive_url: str | None
    body_text: str
    excerpt: str
    source_path: str


@dataclass(slots=True)
class TriageDecision:
    message_id: str
    query: str
    scope: str
    model: str
    relevant: bool
    classification: str
    confidence: str
    exclude_reason: str
    summary: str
    evidence: str
    published_at: str | None
    list_name: str
    report_path: str | None
    raw_response: str
    title: str

