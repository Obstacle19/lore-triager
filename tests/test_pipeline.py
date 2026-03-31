from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest import mock
from urllib import error

from lore_bug_finder.config import AppConfig
from lore_bug_finder.db import connect, get_related_messages, initialize_database, search_messages, upsert_triage_result
from lore_bug_finder.ingest import ingest_eml_tree, ingest_mbox
from lore_bug_finder.llm import classify_candidate
from lore_bug_finder.models import SearchResult, TriageDecision
from lore_bug_finder.reporting import rebuild_docs_index, write_report


SAMPLE_EML = """From: Alice Example <alice@example.com>
Date: Tue, 11 Feb 2025 09:15:00 +0000
Subject: [PATCH] rust: fix unsafe pointer bug in foo
Message-ID: <sample-message-1@example.com>
List-Id: <linux-rust.vger.kernel.org>
Content-Type: text/plain; charset="utf-8"

This patch fixes a Rust bug caused by unsafe pointer dereference.
The issue could trigger a panic and memory corruption.
"""

BAD_CHARSET_EML = """From: Broken Charset <broken@example.com>
Date: Sat, 15 Feb 2025 11:00:00 +0000
Subject: rust: malformed charset header still contains bug details
Message-ID: <bad-charset-message@example.com>
List-Id: <rust-for-linux.vger.kernel.org>
Content-Type: text/plain; charset=yes

This message has a broken charset header but still talks about a Rust bug.
"""

MIXED_MBOX = """From alice@example.com Tue Feb 11 09:15:00 2025
From: Alice Example <alice@example.com>
Date: Tue, 11 Feb 2025 09:15:00 +0000
Subject: [PATCH] rust: fix unsafe pointer bug in foo
Message-ID: <mixed-message-1@example.com>
List-Id: <linux-rust.vger.kernel.org>
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

This patch fixes a Rust bug caused by unsafe pointer dereference.
The issue could trigger a panic and memory corruption in the driver path.

From bob@example.com Wed Feb 12 10:20:00 2025
From: Bob Example <bob@example.com>
Date: Wed, 12 Feb 2025 10:20:00 +0000
Subject: rust: fix refcount logic bug in net helper
Message-ID: <mixed-message-2@example.com>
List-Id: <linux-rust.vger.kernel.org>
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

The Rust helper drops a reference in the wrong branch.
That logic bug leaves stale state behind and breaks the reopen path after recovery.

From carol@example.com Thu Feb 13 08:00:00 2025
From: Carol Process <carol@example.com>
Date: Thu, 13 Feb 2025 08:00:00 +0000
Subject: Re: rust bug triage meeting agenda for next week
Message-ID: <mixed-message-3@example.com>
List-Id: <linux-rust.vger.kernel.org>
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

This thread only collects agenda items for the rust bug triage meeting.
No specific defect or regression is being discussed in this email.

From dave@example.com Fri Feb 14 07:30:00 2025
From: Dave Docs <dave@example.com>
Date: Fri, 14 Feb 2025 07:30:00 +0000
Subject: Rust bug report template for mailing list submissions
Message-ID: <mixed-message-4@example.com>
List-Id: <linux-rust.vger.kernel.org>
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

This is just a process template for writing a good rust bug report.
It is not describing an actual kernel bug, crash, or unsafe issue.
"""


def build_config(root: Path, *, api_key: str | None = None, model: str | None = None) -> AppConfig:
    return AppConfig(
        project_root=root,
        env_file_path=root / ".env",
        database_path=root / "data.db",
        docs_dir=root / "docs",
        data_dir=root / "data",
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        model=model,
        output_mode="auto",
        http_timeout=30,
        max_body_chars=8000,
        http_max_retries=3,
        http_retry_delay=0.0,
    )


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class PipelineTests(unittest.TestCase):
    def test_ingest_search_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            eml_dir = root / "eml"
            eml_dir.mkdir()
            (eml_dir / "sample.eml").write_text(SAMPLE_EML, encoding="utf-8")
            config = build_config(root)
            config.ensure_runtime_dirs()
            with connect(config.database_path) as connection:
                initialize_database(connection)
                imported = ingest_eml_tree(connection, eml_dir)
                self.assertEqual(imported, 1)
                results = search_messages(connection, query_text="rust bug", scopes=None, limit=10)
                self.assertEqual(len(results), 1)
                candidate = results[0]
                self.assertEqual(candidate.list_name, "linux-rust.vger.kernel.org")
                decision = TriageDecision(
                    message_id=candidate.message_id,
                    query="rust bug",
                    scope="all",
                    model="heuristic",
                    relevant=True,
                    classification="rust_unsafe_bug",
                    confidence="medium",
                    exclude_reason="",
                    summary="Unsafe pointer dereference in Rust code can corrupt memory.",
                    evidence="The email explicitly mentions unsafe pointer dereference and memory corruption.",
                    published_at=candidate.date_utc,
                    list_name=candidate.list_name,
                    report_path=None,
                    raw_response="test",
                    title="Unsafe pointer bug in Rust foo",
                )
                report_path = write_report(config, candidate, decision)
                self.assertTrue((root / report_path).exists())
                upsert_triage_result(connection, replace(decision, report_path=report_path))
                connection.commit()
                index_path = rebuild_docs_index(config, connection)
                self.assertTrue(index_path.exists())
                self.assertIn("Unsafe pointer bug in Rust foo", index_path.read_text(encoding="utf-8"))

    def test_ingest_bad_charset_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            eml_dir = root / "eml"
            eml_dir.mkdir()
            (eml_dir / "bad.eml").write_text(BAD_CHARSET_EML, encoding="utf-8")
            config = build_config(root)
            config.ensure_runtime_dirs()
            with connect(config.database_path) as connection:
                initialize_database(connection)
                imported = ingest_eml_tree(connection, eml_dir)
                self.assertEqual(imported, 1)
                results = search_messages(connection, query_text="rust bug", scopes=None, limit=10)
                self.assertEqual(len(results), 1)
                self.assertIn("broken charset header", results[0].body_text.lower())

    def test_ingest_gzipped_mbox_requires_manual_decompression(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = build_config(root)
            config.ensure_runtime_dirs()
            gz_path = root / "mixed.mbox.gz"
            gz_path.write_text("placeholder", encoding="utf-8")
            with connect(config.database_path) as connection:
                initialize_database(connection)
                with self.assertRaisesRegex(ValueError, "Please decompress it first"):
                    ingest_mbox(connection, gz_path, "linux-rust")

    def test_mixed_mbox_filters_noise_with_heuristics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = build_config(root)
            config.ensure_runtime_dirs()
            mbox_path = root / "mixed.mbox"
            mbox_path.write_text(MIXED_MBOX, encoding="utf-8")
            with connect(config.database_path) as connection:
                initialize_database(connection)
                imported = ingest_mbox(connection, mbox_path, "linux-rust")
                self.assertEqual(imported, 4)
                results = search_messages(connection, query_text="", scopes=None, limit=10)
                self.assertEqual(len(results), 4)
                decisions = [
                    classify_candidate(
                        config,
                        result,
                        query="(entire imported dataset)",
                        scope="all imported messages",
                        related_messages=get_related_messages(connection, result.message_id),
                    )
                    for result in results
                ]
            relevant = [decision for decision in decisions if decision.relevant]
            excluded = [decision for decision in decisions if not decision.relevant]
            self.assertEqual(len(relevant), 2)
            self.assertEqual(len(excluded), 2)
            self.assertTrue(any(decision.classification == "rust_unsafe_bug" for decision in relevant))
            self.assertTrue(any(decision.classification == "rust_logic_bug" for decision in relevant))
            self.assertTrue(all(decision.classification in {"not_rust_bug", "uncertain"} for decision in excluded))

    def test_llm_falls_back_from_json_schema_to_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = build_config(root, api_key="test-key", model="test-model")
            candidate = SearchResult(
                message_id="<fallback-message@example.com>",
                subject="rust bug triage process update",
                author_name="Carol",
                author_email="carol@example.com",
                date_utc="2025-02-13T08:00:00+00:00",
                list_name="linux-rust",
                archive_url=None,
                body_text="This is only a rust bug triage meeting agenda and not a real defect.",
                excerpt="This is only a rust bug triage meeting agenda and not a real defect.",
                source_path="memory",
            )
            unsupported = error.HTTPError(
                url=f"{config.base_url}/chat/completions",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=BytesIO(b'{"error":{"message":"Unsupported response_format json_schema"}}'),
            )
            final_payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "relevant": False,
                                    "classification": "not_rust_bug",
                                    "confidence": "high",
                                    "exclude_reason": "This is a process note, not a concrete defect.",
                                    "summary": "The email is about triage process rather than a real Rust bug.",
                                    "evidence": "It explicitly says it is only a meeting agenda.",
                                    "title": "Process note, not a Rust bug",
                                }
                            )
                        }
                    }
                ]
            }
            with mock.patch(
                "lore_bug_finder.llm.request.urlopen",
                side_effect=[unsupported, FakeHTTPResponse(final_payload)],
            ) as mocked_urlopen:
                decision = classify_candidate(config, candidate, query="rust bug", scope="all")
            self.assertFalse(decision.relevant)
            self.assertEqual(decision.classification, "not_rust_bug")
            self.assertEqual(decision.confidence, "high")
            self.assertIn("[json_object]", decision.model)
            self.assertEqual(mocked_urlopen.call_count, 2)

    def test_patch_ack_with_nullness_subject_is_not_left_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = build_config(root)
            candidate = SearchResult(
                message_id="<177435771478.81121.14256327316446596627.b4-ty@b4>",
                subject="Re: [PATCH] rust: regulator: do not assume that regulator_get() returns non-null",
                author_name="Mark Brown",
                author_email="broonie@kernel.org",
                date_utc="2026-03-24T13:08:34+00:00",
                list_name="rust-for-linux.vger.kernel.org",
                archive_url=None,
                body_text=(
                    "On Tue, 24 Mar 2026 10:49:59 +0000, Alice Ryhl wrote:\n"
                    "> rust: regulator: do not assume that regulator_get() returns non-null\n\n"
                    "Applied to https://git.kernel.org/... for-7.0\n"
                    "Thanks!\n"
                ),
                excerpt="Applied to ... rust: regulator: do not assume that regulator_get() returns non-null",
                source_path="memory",
            )
            decision = classify_candidate(config, candidate, query="(entire imported dataset)", scope="all")
            self.assertTrue(decision.relevant)
            self.assertEqual(decision.classification, "rust_memory_safety_bug")
            self.assertEqual(decision.confidence, "medium")

    def test_llm_uncertain_result_can_be_overridden_by_strong_local_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = build_config(root, api_key="test-key", model="test-model")
            candidate = SearchResult(
                message_id="<177435771478.81121.14256327316446596627.b4-ty@b4>",
                subject="Re: [PATCH] rust: regulator: do not assume that regulator_get() returns non-null",
                author_name="Mark Brown",
                author_email="broonie@kernel.org",
                date_utc="2026-03-24T13:08:34+00:00",
                list_name="rust-for-linux.vger.kernel.org",
                archive_url=None,
                body_text=(
                    "On Tue, 24 Mar 2026 10:49:59 +0000, Alice Ryhl wrote:\n"
                    "> rust: regulator: do not assume that regulator_get() returns non-null\n\n"
                    "Applied to https://git.kernel.org/... for-7.0\n"
                    "Thanks!\n"
                ),
                excerpt="Applied to ... rust: regulator: do not assume that regulator_get() returns non-null",
                source_path="memory",
            )
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "relevant": False,
                                    "classification": "uncertain",
                                    "confidence": "low",
                                    "exclude_reason": "Not enough detail in this reply alone.",
                                    "summary": "The reply is short and does not restate the bug details.",
                                    "evidence": "This looks like an applied reply.",
                                    "title": candidate.subject,
                                }
                            )
                        }
                    }
                ]
            }
            with mock.patch("lore_bug_finder.llm.request.urlopen", return_value=FakeHTTPResponse(payload)):
                decision = classify_candidate(config, candidate, query="(entire imported dataset)", scope="all")
            self.assertTrue(decision.relevant)
            self.assertEqual(decision.classification, "rust_memory_safety_bug")
            self.assertEqual(decision.confidence, "medium")
            self.assertIn("local-signal-override", decision.raw_response)

    def test_llm_transient_network_error_retries_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = build_config(root, api_key="test-key", model="test-model")
            candidate = SearchResult(
                message_id="<retry-message@example.com>",
                subject="[PATCH] rust: fix unsafe pointer bug in foo",
                author_name="Alice",
                author_email="alice@example.com",
                date_utc="2025-02-11T09:15:00+00:00",
                list_name="linux-rust",
                archive_url=None,
                body_text="This patch fixes a Rust bug caused by unsafe pointer dereference.",
                excerpt="unsafe pointer dereference",
                source_path="memory",
            )
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "relevant": True,
                                    "classification": "rust_unsafe_bug",
                                    "confidence": "high",
                                    "exclude_reason": "",
                                    "summary": "Unsafe pointer misuse in Rust code.",
                                    "evidence": "The mail explicitly says unsafe pointer dereference.",
                                    "title": candidate.subject,
                                }
                            )
                        }
                    }
                ]
            }
            with mock.patch(
                "lore_bug_finder.llm.request.urlopen",
                side_effect=[error.URLError("EOF occurred in violation of protocol"), FakeHTTPResponse(payload)],
            ) as mocked_urlopen:
                decision = classify_candidate(config, candidate, query="rust bug", scope="all")
            self.assertTrue(decision.relevant)
            self.assertEqual(decision.classification, "rust_unsafe_bug")
            self.assertEqual(decision.confidence, "high")
            self.assertEqual(mocked_urlopen.call_count, 2)

    def test_llm_transient_network_error_falls_back_to_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = build_config(root, api_key="test-key", model="test-model")
            candidate = SearchResult(
                message_id="<transport-fallback-message@example.com>",
                subject="Re: [PATCH] rust: regulator: do not assume that regulator_get() returns non-null",
                author_name="Mark Brown",
                author_email="broonie@kernel.org",
                date_utc="2026-03-24T13:08:34+00:00",
                list_name="rust-for-linux.vger.kernel.org",
                archive_url=None,
                body_text="Applied to https://git.kernel.org/... for-7.0 Thanks!",
                excerpt="Applied to ... rust: regulator: do not assume that regulator_get() returns non-null",
                source_path="memory",
            )
            with mock.patch(
                "lore_bug_finder.llm.request.urlopen",
                side_effect=error.URLError("EOF occurred in violation of protocol"),
            ):
                decision = classify_candidate(config, candidate, query="rust bug", scope="all")
            self.assertTrue(decision.relevant)
            self.assertEqual(decision.model, "heuristic [llm_transport_error]")
            self.assertIn("LLM transport failed; used heuristic fallback", decision.summary)

    def test_incidental_rust_mentions_do_not_make_release_notes_a_rust_bug(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = build_config(root)
            candidate = SearchResult(
                message_id="<release-notes@example.com>",
                subject="Linux 7.0-rc6",
                author_name="Linus Torvalds",
                author_email="torvalds@linux-foundation.org",
                date_utc="2026-03-29T23:05:58+00:00",
                list_name="linux-kernel.vger.kernel.org",
                archive_url=None,
                body_text=(
                    "This release has a lot of fixes across filesystems and networking. "
                    "Later in the changelog it lists: rust: regulator: do not assume that regulator_get() returns non-null. "
                    "It also lists some null pointer and use-after-free fixes in unrelated C subsystems."
                ),
                excerpt="This release has a lot of fixes across filesystems and networking.",
                source_path="memory",
            )
            decision = classify_candidate(config, candidate, query="rust bug", scope="all")
            self.assertFalse(decision.relevant)
            self.assertEqual(decision.classification, "not_rust_bug")

    def test_c_patch_mentioning_rust_path_is_not_a_rust_bug(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = build_config(root)
            candidate = SearchResult(
                message_id="<c-patch-with-rust-reference@example.com>",
                subject="Re: [PATCH] hpet: fix bounds check for s->timer[]",
                author_name="Zhao Liu",
                author_email="zhao1.liu@intel.com",
                date_utc="2026-03-30T14:47:06+00:00",
                list_name="qemu-devel.nongnu.org",
                archive_url=None,
                body_text=(
                    "Fix an off-by-one issue in QEMU's HPET handlers. "
                    "Commit 869b0afa4fa (\"rust/hpet: Drop BqlCell wrapper for num_timers\") "
                    "silently fixed the same bug in rust/hw/timer/hpet/src/device.rs."
                ),
                excerpt="Fix an off-by-one issue in QEMU's HPET handlers.",
                source_path="memory",
            )
            decision = classify_candidate(config, candidate, query="rust bug", scope="all")
            self.assertFalse(decision.relevant)
            self.assertEqual(decision.classification, "not_rust_bug")


if __name__ == "__main__":
    unittest.main()
