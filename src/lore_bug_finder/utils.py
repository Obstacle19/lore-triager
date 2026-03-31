from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, time
from email.utils import parsedate_to_datetime


_CI_STATUS_PREFIX_RE = re.compile(
    r"^[✓✗]\s+[A-Za-z0-9_.-]+:\s+(?:success|failure)\s+for\s+",
    re.I,
)


def parse_email_date(value: str | None) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None, None
    if dt is None:
        return None, None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.isoformat(), int(dt.timestamp())


def normalize_message_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"<[^>]+>", value)
    return match.group(0) if match else value.strip()


def extract_list_name(*values: str | None, default: str = "unknown") -> str:
    for value in values:
        if not value:
            continue
        match = re.search(r"<([^>]+)>", value)
        candidate = match.group(1) if match else value.strip()
        candidate = candidate.replace("\n", " ").strip()
        if candidate:
            return candidate
    return default


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_subject_line(value: str) -> str:
    normalized = collapse_whitespace(value)
    while True:
        updated = re.sub(r"^(?:(?:re|fw|fwd|aw)\s*:\s*)+", "", normalized, flags=re.I)
        if updated == normalized:
            break
        normalized = updated
    normalized = re.sub(r"^\[(?:patch[^\]]*|rfc[^\]]*|resend[^\]]*)\]\s*", "", normalized, flags=re.I)
    return collapse_whitespace(normalized)


def is_patchwork_author(author_email: str | None) -> bool:
    if not author_email:
        return False
    lowered = author_email.strip().lower()
    return lowered == "patchwork@emeril.freedesktop.org" or lowered.startswith("patchwork@")


def is_ci_status_subject(subject: str) -> bool:
    return bool(_CI_STATUS_PREFIX_RE.match(collapse_whitespace(subject)))


def extract_patchwork_series_title(body_text: str | None) -> str | None:
    if not body_text:
        return None
    collapsed = collapse_whitespace(body_text)
    match = re.search(r"(?:^| )Series:\s*(.+?)\s+URL\s*:", collapsed, re.I)
    if not match:
        return None
    title = collapse_whitespace(match.group(1))
    return title or None


def canonical_topic_title(
    subject: str,
    *,
    author_email: str | None = None,
    body_text: str | None = None,
) -> str:
    if is_patchwork_author(author_email):
        series_title = extract_patchwork_series_title(body_text)
        if series_title:
            return series_title
    normalized = normalize_subject_line(subject)
    normalized = _CI_STATUS_PREFIX_RE.sub("", normalized)
    return collapse_whitespace(normalized) or collapse_whitespace(subject)


def build_topic_key(
    subject: str,
    thread_key: str | None,
    *,
    author_email: str | None = None,
    body_text: str | None = None,
) -> str:
    title = canonical_topic_title(subject, author_email=author_email, body_text=body_text)
    title = re.sub(r"\s*\(rev\d+\)$", "", title, flags=re.I).casefold()
    base = (thread_key or "").strip().casefold()
    return f"{base}::{title}" if base else title


def representative_sort_key(
    message_id: str,
    thread_key: str | None,
    author_email: str | None,
    subject: str,
    published_at: str | None,
) -> tuple[int, int, int, str, str]:
    return (
        0 if (thread_key or "") == message_id else 1,
        0 if not is_patchwork_author(author_email) else 1,
        0 if not is_ci_status_subject(subject) else 1,
        published_at or "9999-12-31T23:59:59+00:00",
        message_id,
    )


def slugify(value: str, default: str = "report") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug or default


def short_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def coerce_date_boundary(value: str | None, *, upper: bool) -> int | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = datetime.combine(dt.date(), time.max if upper else time.min, tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return int(dt.timestamp())
