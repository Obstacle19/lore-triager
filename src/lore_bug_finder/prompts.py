from __future__ import annotations

from lore_bug_finder.models import SearchResult


TRIAGE_CLASSIFICATIONS = [
    "rust_logic_bug",
    "rust_unsafe_bug",
    "rust_memory_safety_bug",
    "rust_api_misuse",
    "build_or_tooling",
    "not_rust_bug",
    "uncertain",
]

TRIAGE_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "relevant": {"type": "boolean"},
        "classification": {
            "type": "string",
            "enum": TRIAGE_CLASSIFICATIONS,
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "exclude_reason": {"type": "string"},
        "summary": {"type": "string"},
        "evidence": {"type": "string"},
        "title": {"type": "string"},
    },
    "required": [
        "relevant",
        "classification",
        "confidence",
        "exclude_reason",
        "summary",
        "evidence",
        "title",
    ],
}


SYSTEM_PROMPT = """
You are a precise Linux kernel mailing list analyst.

Your job is to decide whether a search result is a real Rust bug report or discussion about a Rust bug in kernel logic, unsafe usage, memory safety, or soundness.

Some inputs are follow-up replies, apply/merge acknowledgements, or short patch-thread messages that do not restate the full bug details. In those cases, infer from:
- the patch title or quoted subject
- explicit null/non-null, unsafe, UB, soundness, ownership, lifetime, or memory-safety signals
- related thread context if provided

Exclude noisy hits where:
- the email merely contains the words "rust" and "bug" without discussing an actual Rust-related defect
- the message is primarily about mailing list process, tooling chatter, release notes, or unrelated subsystems
- the message is not about a defect, regression, crash, soundness issue, unsafe misuse, race, panic, UB, memory corruption, or similar bug
- the email is a meeting agenda, template, process note, weekly summary, or tracking thread rather than a concrete defect discussion

Decision rules:
- Set "relevant": true only for real Rust bug discussions worth keeping in docs/.
- Set "relevant": false for build_or_tooling, not_rust_bug, or process noise.
- If the subject clearly describes a Rust nullness, unsafe, UB, soundness, or memory-safety fix, keep it even if the current email is only an acknowledgement or short reply.
- Use "uncertain" only when the available text lacks enough evidence either way.
- Keep evidence short and quote or paraphrase the specific signal that supports the decision.

Return only valid JSON that matches the requested schema.
""".strip()


def _excerpt_body(body_text: str, max_body_chars: int) -> str:
    if len(body_text) <= max_body_chars:
        return body_text
    head = max_body_chars // 2
    tail = max_body_chars - head
    return f"{body_text[:head]}\n\n[... snip ...]\n\n{body_text[-tail:]}"


def build_triage_prompt(
    candidate: SearchResult,
    query: str,
    max_body_chars: int,
    *,
    related_messages: list[SearchResult] | None = None,
    signal_summary: str | None = None,
) -> str:
    body_excerpt = _excerpt_body(candidate.body_text, max_body_chars)
    related_messages = related_messages or []
    related_section = ""
    if related_messages:
        rendered = []
        for message in related_messages[:3]:
            rendered.append(
                "\n".join(
                    [
                        f"- message_id: {message.message_id}",
                        f"  subject: {message.subject}",
                        f"  date_utc: {message.date_utc}",
                        f"  body_excerpt: {_excerpt_body(message.body_text, max(1200, max_body_chars // 3))}",
                    ]
                )
            )
        related_section = "Related thread context:\n" + "\n\n".join(rendered)
    signal_section = f"Observed bug signals:\n{signal_summary}" if signal_summary else ""
    sections = [f"""
Search query: {query}

Message metadata:
- message_id: {candidate.message_id}
- subject: {candidate.subject}
- author: {candidate.author_name} <{candidate.author_email}>
- date_utc: {candidate.date_utc}
- list_name: {candidate.list_name}
- archive_url: {candidate.archive_url}

Body excerpt:
{body_excerpt}

Decide whether this should be kept as a real Rust bug entry in docs/.
""".strip()]
    if signal_section:
        sections.append(signal_section)
    if related_section:
        sections.append(related_section)
    return "\n\n".join(section for section in sections if section)
