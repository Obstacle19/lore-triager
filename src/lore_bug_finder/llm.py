from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, replace
from urllib import error, request

from lore_bug_finder.config import AppConfig
from lore_bug_finder.models import SearchResult, TriageDecision
from lore_bug_finder.prompts import (
    SYSTEM_PROMPT,
    TRIAGE_CLASSIFICATIONS,
    TRIAGE_RESPONSE_SCHEMA,
    build_triage_prompt,
)
from lore_bug_finder.utils import collapse_whitespace, normalize_subject_line, short_json


SUPPORTED_OUTPUT_MODES = ("auto", "json_schema", "json_object", "plain")
SUPPORTED_CONFIDENCE = {"high", "medium", "low"}
NON_RELEVANT_CLASSIFICATIONS = {"build_or_tooling", "not_rust_bug"}
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
RETRYABLE_HTTP_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class SignalAssessment:
    relevant: bool
    classification: str
    confidence: str
    summary: str
    evidence: str
    exclude_reason: str
    signal_summary: str


class TransientLLMError(RuntimeError):
    pass


def _extract_json_object(text: str) -> dict[str, object]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("model response did not contain a JSON object")
    return json.loads(match.group(0))


def _stringify_message_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            elif isinstance(item, str):
                chunks.append(item)
        return "\n".join(chunks)
    return short_json(content)


def _collect_signal_hits(text: str, markers: list[str]) -> list[str]:
    hits: list[str] = []
    for marker in markers:
        if marker.isascii() and marker.replace("-", "").replace("_", "").isalnum() and len(marker) <= 3:
            if re.search(rf"\b{re.escape(marker)}\b", text):
                hits.append(marker)
            continue
        if marker in text:
            hits.append(marker)
    return hits


def _contains_rust_token(text: str) -> bool:
    return bool(re.search(r"(?:^|[^a-z0-9])rust(?:[^a-z0-9]|$)|rust[:/]", text))


def _render_signal_summary(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines if line)


def _assess_candidate_signals(
    candidate: SearchResult,
    related_messages: list[SearchResult] | None = None,
) -> SignalAssessment:
    related_messages = related_messages or []
    normalized_subject = normalize_subject_line(candidate.subject)
    headline_text = "\n".join(
        part
        for part in (
            candidate.subject,
            normalized_subject,
            candidate.excerpt,
            candidate.body_text[:800],
        )
        if part
    )
    related_headline_text = "\n".join(
        part
        for message in related_messages
        for part in (
            message.subject,
            normalize_subject_line(message.subject),
            message.excerpt,
        )
        if part
    )
    text_parts = [
        candidate.subject,
        normalized_subject,
        candidate.body_text,
        candidate.excerpt,
    ]
    for message in related_messages:
        text_parts.extend(
            [
                message.subject,
                normalize_subject_line(message.subject),
                message.body_text,
                message.excerpt,
            ]
        )
    text = "\n".join(part for part in text_parts if part)
    lowered = text.casefold()
    subject_lower = collapse_whitespace(candidate.subject).casefold()
    headline_lower = headline_text.casefold()
    related_headline_lower = related_headline_text.casefold()

    rust_context_markers = [
        "rust bug",
        "rust code",
        "rust driver",
        "rust abstraction",
        "rust binding",
        "rust wrapper",
        "rust helper",
        "rust module",
        "rust implementation",
        "rust logic",
        "rust-side",
        "rust side",
        "safe rust",
        "unsafe rust",
        "written in rust",
    ]
    noise_markers = [
        "meeting agenda",
        "agenda item",
        "weekly summary",
        "tracking thread",
        "template",
        "mailing list process",
        "submission guide",
        "status update",
        "report template",
        "conference",
        "summit",
        "no specific defect",
        "not describing an actual kernel bug",
        "process note",
    ]
    hard_noise_markers = [
        "only collects agenda items",
        "not a real defect",
        "not describing an actual kernel bug",
        "no specific defect",
        "this is just a process template",
        "triage meeting agenda",
    ]
    tooling_markers = [
        "rustc",
        "cargo",
        "clippy",
        "bindgen",
        "toolchain",
        "compile error",
        "linker error",
        "build failure",
        "ci failure",
    ]
    unsafe_markers = [
        "unsafe",
        "undefined behavior",
        "soundness",
        "nonnull::new_unchecked",
        "new_unchecked",
        "nonnull",
        "raw pointer",
        "dangling pointer",
        "aliasing",
        "lifetime",
        "invariant",
        "ub",
    ]
    memory_markers = [
        "memory corruption",
        "memory safety",
        "use-after-free",
        "uaf",
        "out-of-bounds",
        "oob",
        "double free",
        "null pointer",
        "returns non-null",
        "return non-null",
        "non-null",
        "may be null",
        "possibly null",
        "returns null",
        "uninitialized",
        "dangling",
        "dereference",
    ]
    logic_markers = [
        "logic bug",
        "wrong branch",
        "stale state",
        "wrong state",
        "regression",
        "refcount",
        "reference count",
        "race",
        "panic",
        "oops",
        "crash",
        "drops a reference",
        "reopen path",
    ]
    api_misuse_markers = [
        "do not assume",
        "assume that",
        "misuse",
        "incorrect use",
        "wrong ownership",
        "ownership",
        "violates",
        "violate",
        "invariant",
        "contract",
    ]
    bug_markers = [
        "bug",
        "fix",
        "bug fix",
        "regression",
        "panic",
        "crash",
        "oops",
        "defect",
        "issue",
    ]
    ack_markers = [
        "applied to",
        "thanks!",
        "[1/1]",
        "it will be integrated into the linux-next tree",
    ]

    rust_hits = []
    if _contains_rust_token(lowered):
        rust_hits.append("rust")
    subject_rust = _contains_rust_token(subject_lower)
    related_subject_rust = _contains_rust_token(related_headline_lower)
    body_rust_context_hits = _collect_signal_hits(headline_lower, rust_context_markers)
    rust_anchor = subject_rust or related_subject_rust or bool(body_rust_context_hits)
    noise_hits = _collect_signal_hits(lowered, noise_markers)
    hard_noise_hits = _collect_signal_hits(lowered, hard_noise_markers)
    tooling_hits = _collect_signal_hits(lowered, tooling_markers)
    unsafe_hits = _collect_signal_hits(lowered, unsafe_markers)
    memory_hits = _collect_signal_hits(lowered, memory_markers)
    logic_hits = _collect_signal_hits(lowered, logic_markers)
    api_hits = _collect_signal_hits(lowered, api_misuse_markers)
    bug_hits = _collect_signal_hits(lowered, bug_markers)
    ack_hits = _collect_signal_hits(lowered, ack_markers)

    is_patch_subject = "[patch" in subject_lower
    rust_present = bool(rust_hits)
    strong_bug_signal = bool(unsafe_hits or memory_hits or logic_hits or api_hits)
    noise_only = bool(noise_hits) and not strong_bug_signal
    tooling_only = bool(tooling_hits) and not strong_bug_signal

    summary_lines: list[str] = []
    if rust_present:
        summary_lines.append("Rust is mentioned somewhere in the message or related context.")
    if subject_rust:
        summary_lines.append("Rust is explicitly mentioned in the subject.")
    if related_subject_rust:
        summary_lines.append("Rust is explicitly mentioned in a related message subject.")
    if body_rust_context_hits:
        summary_lines.append(f"Rust appears as a primary topic in the message body: {', '.join(sorted(set(body_rust_context_hits)))}")
    if rust_present and not rust_anchor:
        summary_lines.append("Rust appears only incidentally, not as the primary subject of the message.")
    if unsafe_hits:
        summary_lines.append(f"Unsafe/soundness signals: {', '.join(sorted(set(unsafe_hits)))}")
    if memory_hits:
        summary_lines.append(f"Memory/nullness signals: {', '.join(sorted(set(memory_hits)))}")
    if logic_hits:
        summary_lines.append(f"Logic/regression signals: {', '.join(sorted(set(logic_hits)))}")
    if api_hits:
        summary_lines.append(f"API misuse/contract signals: {', '.join(sorted(set(api_hits)))}")
    if hard_noise_hits:
        summary_lines.append(f"Explicit noise/process markers: {', '.join(sorted(set(hard_noise_hits)))}")
    if ack_hits:
        summary_lines.append("Current mail looks like a patch acknowledgement or follow-up reply.")
    if related_messages:
        summary_lines.append(f"Related thread messages supplied: {len(related_messages)}")

    relevant = False
    classification = "uncertain"
    confidence = "low"
    exclude_reason = ""
    summary = "Signals were too weak to confidently keep this as a Rust bug."
    evidence = collapse_whitespace(candidate.excerpt)

    if not rust_anchor:
        classification = "not_rust_bug"
        confidence = "high" if rust_present else "medium"
        exclude_reason = "Rust is not the primary subject of this message."
        summary = "The message may mention Rust incidentally, but it is not primarily about a Rust code bug."
        evidence = collapse_whitespace("No Rust-specific anchor was found in the subject or opening context.")
        if tooling_hits and not rust_present:
            classification = "build_or_tooling"
            exclude_reason = "This is tooling or build chatter without a Rust-code bug as the primary subject."
            summary = "The message is tooling/build chatter rather than a Rust code bug."
    elif rust_present and hard_noise_hits:
        classification = "not_rust_bug"
        confidence = "high"
        exclude_reason = "This message explicitly says it is process chatter rather than a concrete defect."
        summary = "The message explicitly says it is a template, agenda, or other non-bug process note."
        evidence = collapse_whitespace(
            f"Explicit noise markers include {', '.join(sorted(set(hard_noise_hits))[:6])}."
        )
    elif rust_anchor and not noise_only and not tooling_only:
        if unsafe_hits and (memory_hits or api_hits or bug_hits or is_patch_subject):
            relevant = True
            classification = "rust_unsafe_bug"
            confidence = "high" if {"undefined behavior", "soundness", "nonnull::new_unchecked", "new_unchecked"} & set(unsafe_hits) else "medium"
            summary = "The message points to a Rust unsafe/soundness bug."
            evidence = collapse_whitespace(
                f"Subject/body signals include {', '.join(sorted(set(unsafe_hits + memory_hits + api_hits))[:6])}."
            )
        elif memory_hits and (bug_hits or api_hits or is_patch_subject or ack_hits):
            relevant = True
            classification = "rust_memory_safety_bug"
            confidence = "high" if {"null pointer", "memory corruption", "use-after-free", "double free"} & set(memory_hits) else "medium"
            summary = "The message points to a Rust memory-safety or nullness bug."
            evidence = collapse_whitespace(
                f"Subject/body signals include {', '.join(sorted(set(memory_hits + api_hits))[:6])}."
            )
        elif logic_hits and (bug_hits or is_patch_subject):
            relevant = True
            classification = "rust_logic_bug"
            confidence = "medium"
            summary = "The message describes a Rust logic or state-management bug."
            evidence = collapse_whitespace(
                f"Subject/body signals include {', '.join(sorted(set(logic_hits + bug_hits))[:6])}."
            )
        elif api_hits and (bug_hits or is_patch_subject):
            relevant = True
            classification = "rust_api_misuse"
            confidence = "medium"
            summary = "The message appears to describe a Rust API/contract misuse bug."
            evidence = collapse_whitespace(
                f"Subject/body signals include {', '.join(sorted(set(api_hits + bug_hits))[:6])}."
            )
        elif tooling_hits:
            classification = "build_or_tooling"
            confidence = "medium"
            exclude_reason = "This looks like Rust tooling/build chatter rather than a runtime bug."
            summary = "The message is primarily about Rust tooling or build failures."
        elif noise_hits:
            classification = "not_rust_bug"
            confidence = "medium"
            exclude_reason = "This looks like process or mailing-list noise rather than a concrete bug."
            summary = "The message is process chatter rather than a concrete Rust kernel bug."
    elif rust_anchor and tooling_only:
        classification = "build_or_tooling"
        confidence = "medium"
        exclude_reason = "This looks like Rust tooling/build chatter rather than a runtime bug."
        summary = "The message is primarily about Rust tooling or build failures."
    elif rust_anchor and noise_only:
        classification = "not_rust_bug"
        confidence = "medium"
        exclude_reason = "This looks like process or mailing-list noise rather than a concrete bug."
        summary = "The message is process chatter rather than a concrete Rust kernel bug."
    elif not rust_present and (tooling_hits or noise_hits):
        classification = "not_rust_bug"
        confidence = "medium"
        exclude_reason = "No meaningful Rust bug context was found."
        summary = "The message does not look like a Rust bug."

    if not relevant and not exclude_reason:
        exclude_reason = "Local signal analysis did not find enough evidence for a real Rust bug."

    signal_summary = _render_signal_summary(summary_lines)
    return SignalAssessment(
        relevant=relevant,
        classification=classification,
        confidence=confidence,
        summary=summary,
        evidence=evidence,
        exclude_reason=exclude_reason,
        signal_summary=signal_summary,
    )


def _heuristic_classification(
    candidate: SearchResult,
    query: str,
    scope: str,
    related_messages: list[SearchResult] | None = None,
) -> TriageDecision:
    signals = _assess_candidate_signals(candidate, related_messages)
    return TriageDecision(
        message_id=candidate.message_id,
        query=query,
        scope=scope,
        model="heuristic",
        relevant=signals.relevant,
        classification=signals.classification,
        confidence=signals.confidence,
        exclude_reason="" if signals.relevant else signals.exclude_reason,
        summary=signals.summary,
        evidence=signals.evidence or collapse_whitespace(candidate.excerpt),
        published_at=candidate.date_utc,
        list_name=candidate.list_name,
        report_path=None,
        raw_response=signals.signal_summary or "heuristic-fallback",
        title=candidate.subject,
    )


def _should_override_with_signals(decision: TriageDecision, signals: SignalAssessment) -> bool:
    signal_rank = CONFIDENCE_RANK.get(signals.confidence, 0)
    decision_rank = CONFIDENCE_RANK.get(decision.confidence, 0)
    if signals.relevant:
        if decision.classification == "uncertain":
            return True
        if not decision.relevant:
            return True
        return signal_rank > decision_rank
    if signals.classification in NON_RELEVANT_CLASSIFICATIONS:
        if decision.relevant:
            return signal_rank >= decision_rank
        if decision.classification == "uncertain" and signal_rank > decision_rank:
            return True
    return False


def _apply_signal_override(
    decision: TriageDecision,
    candidate: SearchResult,
    signals: SignalAssessment,
) -> TriageDecision:
    if not _should_override_with_signals(decision, signals):
        return decision
    raw_response = decision.raw_response
    override_note = f"\n[local-signal-override]\n{signals.signal_summary}" if signals.signal_summary else "\n[local-signal-override]"
    if override_note.strip() not in raw_response:
        raw_response = f"{raw_response}{override_note}" if raw_response else override_note.strip()
    return replace(
        decision,
        relevant=signals.relevant,
        classification=signals.classification,
        confidence=signals.confidence,
        exclude_reason="" if signals.relevant else signals.exclude_reason,
        summary=signals.summary,
        evidence=signals.evidence or collapse_whitespace(candidate.excerpt),
        raw_response=raw_response,
        title=candidate.subject,
    )


def _heuristic_fallback_after_transport_error(
    candidate: SearchResult,
    query: str,
    scope: str,
    related_messages: list[SearchResult] | None,
    exc: Exception,
) -> TriageDecision:
    fallback = _heuristic_classification(candidate, query, scope, related_messages)
    detail = collapse_whitespace(str(exc))
    note = f"LLM transport failed; used heuristic fallback. {detail}".strip()
    raw_response = f"{note}\n{fallback.raw_response}" if fallback.raw_response else note
    return replace(
        fallback,
        model="heuristic [llm_transport_error]",
        summary=f"{fallback.summary} {note}".strip(),
        raw_response=raw_response,
    )


def _normalize_output_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in SUPPORTED_OUTPUT_MODES:
        raise ValueError(
            f"unsupported OPENAI_OUTPUT_MODE '{mode}'. Expected one of: {', '.join(SUPPORTED_OUTPUT_MODES)}"
        )
    return normalized


def _iter_output_modes(mode: str) -> tuple[str, ...]:
    normalized = _normalize_output_mode(mode)
    if normalized == "auto":
        return ("json_schema", "json_object", "plain")
    return (normalized,)


def _build_payload(model: str, user_prompt: str, output_mode: str) -> dict[str, object]:
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    if output_mode == "json_schema":
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "rust_bug_triage",
                "strict": True,
                "schema": TRIAGE_RESPONSE_SCHEMA,
            },
        }
    elif output_mode == "json_object":
        payload["response_format"] = {"type": "json_object"}
    return payload


def _unsupported_response_format(details: str) -> bool:
    lowered = details.lower()
    return any(
        marker in lowered
        for marker in (
            "response_format",
            "json_schema",
            "json_object",
            "structured outputs",
            "unsupported parameter",
        )
    )


def _format_attempt_suffix(attempt: int, total_attempts: int) -> str:
    return f" (attempt {attempt}/{total_attempts})" if total_attempts > 1 else ""


def _sleep_before_retry(config: AppConfig, attempt: int) -> None:
    delay = max(config.http_retry_delay, 0.0) * attempt
    if delay > 0:
        time.sleep(delay)


def _request_payload(config: AppConfig, payload: dict[str, object], output_mode: str) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    endpoint = f"{config.base_url}/chat/completions"
    req = request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
    )
    total_attempts = max(config.http_max_retries, 0) + 1
    last_error: Exception | None = None
    for attempt in range(1, total_attempts + 1):
        try:
            with request.urlopen(req, timeout=config.http_timeout) as response:
                response_text = response.read().decode("utf-8")
            return json.loads(response_text)
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400 and output_mode != "plain" and _unsupported_response_format(details):
                raise ValueError(f"provider does not support output mode '{output_mode}': {details}") from exc
            if exc.code in RETRYABLE_HTTP_CODES and attempt < total_attempts:
                last_error = exc
                _sleep_before_retry(config, attempt)
                continue
            if exc.code in RETRYABLE_HTTP_CODES:
                raise TransientLLMError(
                    f"chat completion failed with HTTP {exc.code}{_format_attempt_suffix(attempt, total_attempts)}: {details}"
                ) from exc
            raise RuntimeError(f"chat completion failed with HTTP {exc.code}: {details}") from exc
        except error.URLError as exc:
            if attempt < total_attempts:
                last_error = exc
                _sleep_before_retry(config, attempt)
                continue
            raise TransientLLMError(
                f"chat completion request failed{_format_attempt_suffix(attempt, total_attempts)}: {exc}"
            ) from exc
    raise TransientLLMError(f"chat completion request failed after retries: {last_error}")


def _extract_text_from_payload(payload: dict[str, object]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("chat completion returned no choices")
    message = choices[0].get("message", {})
    refusal = message.get("refusal")
    if isinstance(refusal, str) and refusal.strip():
        raise RuntimeError(f"model refused the request: {refusal.strip()}")
    return _stringify_message_content(message.get("content", ""))


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return bool(value)


def _normalize_decision_payload(parsed: dict[str, object], candidate: SearchResult) -> dict[str, object]:
    classification = str(parsed.get("classification", "uncertain")).strip()
    if classification not in TRIAGE_CLASSIFICATIONS:
        classification = "uncertain"
    confidence = str(parsed.get("confidence", "low")).strip().lower()
    if confidence not in SUPPORTED_CONFIDENCE:
        confidence = "low"
    relevant = _coerce_bool(parsed.get("relevant", False))
    if classification in NON_RELEVANT_CLASSIFICATIONS:
        relevant = False
    exclude_reason = collapse_whitespace(str(parsed.get("exclude_reason", "")))
    if not relevant and not exclude_reason:
        exclude_reason = "Model judged this message not worth keeping as a Rust bug entry."
    summary = collapse_whitespace(str(parsed.get("summary", ""))) or "Model returned no summary."
    evidence = collapse_whitespace(str(parsed.get("evidence", ""))) or collapse_whitespace(candidate.excerpt)
    title = collapse_whitespace(str(parsed.get("title", candidate.subject))) or candidate.subject
    return {
        "relevant": relevant,
        "classification": classification,
        "confidence": confidence,
        "exclude_reason": exclude_reason,
        "summary": summary,
        "evidence": evidence,
        "title": title,
    }


def _call_chat_completions(
    config: AppConfig,
    user_prompt: str,
    model: str,
    output_mode: str,
) -> tuple[str, dict[str, object], str]:
    last_error: Exception | None = None
    for current_mode in _iter_output_modes(output_mode):
        payload = _build_payload(model, user_prompt, current_mode)
        try:
            response_payload = _request_payload(config, payload, current_mode)
            raw_response = _extract_text_from_payload(response_payload)
            parsed = _extract_json_object(raw_response)
            return raw_response, parsed, current_mode
        except ValueError as exc:
            last_error = exc
            if "provider does not support output mode" in str(exc):
                continue
            if current_mode != "plain":
                continue
            raise RuntimeError(f"failed to parse JSON response in mode '{current_mode}': {exc}") from exc
    raise RuntimeError(f"all output modes failed: {last_error}")


def classify_candidate(
    config: AppConfig,
    candidate: SearchResult,
    *,
    query: str,
    scope: str,
    related_messages: list[SearchResult] | None = None,
    model_override: str | None = None,
) -> TriageDecision:
    model = model_override or config.model
    signals = _assess_candidate_signals(candidate, related_messages)
    if not config.api_key or not model:
        return _heuristic_classification(candidate, query, scope, related_messages)
    user_prompt = build_triage_prompt(
        candidate,
        query,
        config.max_body_chars,
        related_messages=related_messages,
        signal_summary=signals.signal_summary,
    )
    try:
        raw_response, parsed, used_mode = _call_chat_completions(
            config,
            user_prompt,
            model,
            config.output_mode,
        )
    except TransientLLMError as exc:
        return _heuristic_fallback_after_transport_error(candidate, query, scope, related_messages, exc)
    normalized = _normalize_decision_payload(parsed, candidate)
    decision = TriageDecision(
        message_id=candidate.message_id,
        query=query,
        scope=scope,
        model=f"{model} [{used_mode}]",
        relevant=bool(normalized["relevant"]),
        classification=str(normalized["classification"]),
        confidence=str(normalized["confidence"]),
        exclude_reason=str(normalized["exclude_reason"]),
        summary=str(normalized["summary"]),
        evidence=str(normalized["evidence"]),
        published_at=candidate.date_utc,
        list_name=candidate.list_name,
        report_path=None,
        raw_response=raw_response,
        title=str(normalized["title"]),
    )
    return _apply_signal_override(decision, candidate, signals)
