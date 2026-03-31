from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, time
from email.utils import parsedate_to_datetime


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
