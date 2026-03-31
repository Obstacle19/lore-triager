from __future__ import annotations

import codecs
import mailbox
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path

from lore_bug_finder.db import upsert_message
from lore_bug_finder.models import MessageRecord
from lore_bug_finder.utils import (
    collapse_whitespace,
    extract_list_name,
    normalize_message_id,
    parse_email_date,
    sha256_text,
)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    return collapse_whitespace(parser.text())


def _normalize_charset(charset: str | None) -> str | None:
    if not charset:
        return None
    candidate = charset.strip().strip('"').strip("'").lower()
    if not candidate:
        return None
    if candidate in {
        "yes",
        "no",
        "unknown",
        "unknown-8bit",
        "8bit",
        "7bit",
        "binary",
        "text",
        "plain",
    }:
        return None
    try:
        codecs.lookup(candidate)
    except LookupError:
        return None
    return candidate


def _decode_bytes(payload: bytes, charset: str | None) -> str:
    candidates: list[str] = []
    normalized = _normalize_charset(charset)
    if normalized:
        candidates.append(normalized)
    candidates.extend(["utf-8", "latin-1", "gb18030"])
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return payload.decode(candidate, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def _extract_part_payload(part: Message) -> str | None:
    try:
        payload = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            return _decode_bytes(payload, part.get_content_charset())
        if isinstance(payload, str):
            return payload
        return None
    if isinstance(payload, bytes):
        return _decode_bytes(payload, part.get_content_charset())
    if isinstance(payload, str):
        return payload
    return None


def _extract_text_body(message: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disposition = part.get_content_disposition()
            if disposition == "attachment":
                continue
            content_type = part.get_content_type()
            payload = _extract_part_payload(part)
            if not isinstance(payload, str):
                continue
            if content_type == "text/plain":
                plain_parts.append(payload)
            elif content_type == "text/html":
                html_parts.append(payload)
    else:
        payload = _extract_part_payload(message)
        if isinstance(payload, str):
            if message.get_content_type() == "text/html":
                html_parts.append(payload)
            else:
                plain_parts.append(payload)
    if plain_parts:
        return collapse_whitespace("\n\n".join(plain_parts))
    if html_parts:
        return _html_to_text("\n\n".join(html_parts))
    return ""


def _parse_message(raw_bytes: bytes, source_path: str, list_name_override: str | None) -> MessageRecord:
    message: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    author_name, author_email = parseaddr(message.get("From", ""))
    message_id = normalize_message_id(message.get("Message-ID"))
    if not message_id:
        digest = sha256_text(raw_bytes.decode("utf-8", errors="replace"))
        message_id = f"<generated-{digest[:24]}@local>"
    references = " ".join(filter(None, message.get_all("References", [])))
    in_reply_to = normalize_message_id(message.get("In-Reply-To")) or ""
    thread_key = normalize_message_id(references.split()[0] if references else None) or in_reply_to or message_id
    list_name = list_name_override or extract_list_name(
        message.get("List-Id"),
        message.get("X-Mailing-List"),
        message.get("Mailing-List"),
        default="unknown",
    )
    date_utc, date_epoch = parse_email_date(message.get("Date"))
    subject = collapse_whitespace(message.get("Subject", "(no subject)")) or "(no subject)"
    body_text = _extract_text_body(message)
    return MessageRecord(
        message_id=message_id,
        subject=subject,
        author_name=author_name or "",
        author_email=author_email or "",
        date_utc=date_utc,
        date_epoch=date_epoch,
        list_name=list_name,
        thread_key=thread_key,
        archive_url=None,
        references=references,
        in_reply_to=in_reply_to,
        body_text=body_text,
        source_path=source_path,
    )


def ingest_mbox(connection, path: Path, list_name_override: str | None = None) -> int:
    if not path.exists():
        raise FileNotFoundError(
            f"mbox file not found: {path}. Replace the README placeholder with a real .mbox file path."
        )
    if not path.is_file():
        raise ValueError(f"mbox path is not a file: {path}")
    if path.suffix == ".gz":
        raise ValueError(
            f"gzipped archive not supported directly: {path}. Please decompress it first, for example with "
            f"'gzip -dc {path} > {path.with_suffix('')}'."
        )
    imported = 0
    mbox = mailbox.mbox(path, create=False)
    try:
        for key in mbox.iterkeys():
            raw_bytes = mbox.get_bytes(key)
            record = _parse_message(raw_bytes, f"{path}::{key}", list_name_override)
            upsert_message(connection, record)
            imported += 1
    finally:
        mbox.close()
    connection.commit()
    return imported


def ingest_maildir(connection, path: Path, list_name_override: str | None = None) -> int:
    if not path.exists():
        raise FileNotFoundError(f"maildir path not found: {path}")
    if not path.is_dir():
        raise ValueError(f"maildir path is not a directory: {path}")
    imported = 0
    maildir = mailbox.Maildir(path, factory=None)
    for key in maildir.iterkeys():
        raw_bytes = maildir.get_bytes(key)
        record = _parse_message(raw_bytes, f"{path}::{key}", list_name_override)
        upsert_message(connection, record)
        imported += 1
    connection.commit()
    return imported


def ingest_eml_tree(connection, path: Path, list_name_override: str | None = None) -> int:
    if not path.exists():
        raise FileNotFoundError(f"eml tree path not found: {path}")
    if not path.is_dir():
        raise ValueError(f"eml tree path is not a directory: {path}")
    imported = 0
    for eml_file in sorted(path.rglob("*.eml")):
        raw_bytes = eml_file.read_bytes()
        record = _parse_message(raw_bytes, str(eml_file), list_name_override)
        upsert_message(connection, record)
        imported += 1
    connection.commit()
    return imported
