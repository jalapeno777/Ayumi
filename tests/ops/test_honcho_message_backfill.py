#!/usr/bin/env python3
"""Tests for scripts/ops/honcho_message_backfill.py (HR37 Honcho backfill).

Covers:
  - Gap detection (HR37 §5.2 + §3 watermark corruption logic)
  - Transcript parsing (filters non-message events, drops empty content)
  - Honcho session lookup (metadata.oc_session_id matching)
  - Dry-run safety gate (writes_attempted == 0)
  - --apply env-var gate (HONCHO_BACKFILL_LIVE=1 required)
  - Apply path mocked (writes_attempted == gap_size chunks)
  - 0-message session filtered (per spec edge case "filter_edge_case")
  - Watermark-corrupted cross-check (no false gap detection)
  - find_session_files mtime window + Codex CLI rollout exclusion

Test layout:
  - Synthetic JSONL transcripts written to a tmp dir.
  - HonchoClient stubbed via monkey-patching in run_backfill's client param.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make scripts/ops importable as `honcho_message_backfill` for tests.
# pytest.ini already adds scripts to pythonpath, so we add scripts/ops
# so the module name matches its filename.
_HERE = Path(__file__).resolve().parent
_OPS_DIR = _HERE.parent.parent / "scripts" / "ops"
if str(_OPS_DIR) not in sys.path:
    sys.path.insert(0, str(_OPS_DIR))

import honcho_message_backfill as hmb  # noqa: E402
from honcho_message_backfill import (  # noqa: E402
    LIVE_ENV_VALUE,
    LIVE_ENV_VAR,
    HonchoAPIError,
    ScanStats,
    detect_gap,
    extract_text_content,
    find_session_files,
    read_transcript_messages,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_msg_event_dict(
    seq: int,
    role: str = "user",
    content: str = "hello",
    timestamp: str = "2026-08-15T20:00:00.000Z",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "message",
        "id": idempotency_key or f"event-{seq}",
        "parentId": None,
        "timestamp": timestamp,
        "message": {
            "role": role,
            "content": content,
            "idempotencyKey": idempotency_key or f"event-{seq}:{role}",
        },
    }


def write_transcript(path: Path, messages: list[dict]) -> None:
    """Write a JSONL transcript with a session_meta header + messages."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        # OpenClaw session transcripts start with a `session` event header.
        f.write(
            json.dumps(
                {
                    "type": "session",
                    "version": 3,
                    "id": path.stem,
                    "timestamp": "2026-08-15T19:55:00.000Z",
                }
            )
            + "\n"
        )
        for m in messages:
            f.write(json.dumps(m) + "\n")


# ---------------------------------------------------------------------------
# Gap detection tests (HR37 §5.2 + §3 watermark corruption)
# ---------------------------------------------------------------------------


class TestDetectGap(unittest.TestCase):
    """Pure-function tests for the gap-detection algorithm."""

    def test_empty_transcript_yields_zero_gap(self):
        gap = detect_gap(last_saved_index=10, transcript_length=0, current_count=8)
        self.assertEqual(gap.gap_size, 0)
        self.assertEqual(gap.status, "watermark_intact")

    def test_watermark_at_or_past_transcript_end_is_intact(self):
        # Watermark at exact transcript length -> nothing to backfill.
        gap = detect_gap(last_saved_index=10, transcript_length=10, current_count=8)
        self.assertEqual(gap.gap_size, 0)
        self.assertEqual(gap.status, "watermark_intact")
        # Watermark beyond transcript length -> also nothing to backfill.
        gap = detect_gap(last_saved_index=15, transcript_length=10, current_count=8)
        self.assertEqual(gap.gap_size, 0)
        self.assertEqual(gap.status, "watermark_intact")

    def test_count_equals_last_saved_index_is_intact(self):
        # HR37 §3 cross-check: count >= lastSavedIndex -> watermark INTACT.
        gap = detect_gap(last_saved_index=5, transcript_length=10, current_count=5)
        self.assertEqual(gap.gap_size, 0)
        self.assertEqual(gap.status, "watermark_intact")

    def test_count_exceeds_last_saved_index_is_intact_conservative(self):
        # Spec: even when there are messages beyond the watermark, if count >=
        # lastSavedIndex we skip conservatively.
        gap = detect_gap(last_saved_index=5, transcript_length=10, current_count=8)
        self.assertEqual(gap.gap_size, 0)
        self.assertEqual(gap.status, "watermark_intact")

    def test_count_below_last_saved_index_is_corrupted(self):
        # HR37 §3 caveat: watermark may be corrupted (claims N saved but only
        # count < N actually landed).
        gap = detect_gap(last_saved_index=5, transcript_length=10, current_count=3)
        self.assertEqual(gap.gap_size, 5)  # gap = transcript_length - lastSavedIndex
        self.assertEqual(gap.status, "watermark_corrupted")

    def test_count_zero_with_positive_watermark_is_corrupted(self):
        # Edge case: no messages landed but watermark says 5.
        gap = detect_gap(last_saved_index=5, transcript_length=10, current_count=0)
        self.assertEqual(gap.gap_size, 5)
        self.assertEqual(gap.status, "watermark_corrupted")

    def test_count_below_last_saved_index_with_no_messages_beyond(self):
        # count < lastSavedIndex but lastSavedIndex >= transcript_length ->
        # skip (nothing to backfill beyond watermark).
        gap = detect_gap(last_saved_index=10, transcript_length=8, current_count=3)
        self.assertEqual(gap.gap_size, 0)
        self.assertEqual(gap.status, "watermark_intact")

    def test_negative_inputs_clamped_to_zero(self):
        # Defensive: negative inputs are clamped to 0.
        gap = detect_gap(last_saved_index=-5, transcript_length=10, current_count=2)
        # With clamped lsi=0, count(2) >= 0 -> INTACT.
        self.assertEqual(gap.gap_size, 0)
        self.assertEqual(gap.status, "watermark_intact")

    def test_lsi_zero_with_messages_and_no_honcho_save_is_corrupted(self):
        # Edge case: lsi=0, count=0, transcript has messages — watermark was
        # never initialised. Matches plugin semantics where lsi=0 means
        # "nothing saved yet". Treat as full gap.
        gap = detect_gap(last_saved_index=0, transcript_length=250, current_count=0)
        self.assertEqual(gap.gap_size, 250)
        self.assertEqual(gap.status, "watermark_corrupted")


# ---------------------------------------------------------------------------
# Transcript parsing tests
# ---------------------------------------------------------------------------


class TestReadTranscript(unittest.TestCase):
    """Verify transcript parser matches openclaw-honcho/extractMessages semantics."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="honcho-bf-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parses_user_and_assistant_messages(self):
        # Mimic production layout: <tmp>/agents/<agent>/sessions/<file>.jsonl
        path = Path(self.tmp) / "agents" / "main" / "sessions" / "abc.jsonl"
        write_transcript(
            path,
            [
                make_msg_event_dict(0, role="user", content="hi"),
                make_msg_event_dict(1, role="assistant", content="hello!"),
                make_msg_event_dict(2, role="user", content="how are you?"),
            ],
        )
        events = read_transcript_messages(path)
        self.assertEqual(len(events), 3)
        self.assertEqual([e.role for e in events], ["user", "assistant", "user"])
        self.assertEqual([e.content for e in events], ["hi", "hello!", "how are you?"])
        # seq is 0-based and contiguous.
        self.assertEqual([e.seq for e in events], [0, 1, 2])
        # agent_id derived from path: agents/<x>/sessions/...
        self.assertEqual(events[0].agent_id, "main")

    def test_filters_out_tool_result_messages(self):
        # openclaw-honcho/extractMessages skips toolResult; we must too.
        path = Path(self.tmp) / "agents" / "main" / "sessions" / "abc.jsonl"
        write_transcript(
            path,
            [
                make_msg_event_dict(0, role="user", content="hi"),
                {
                    "type": "message",
                    "id": "tool-1",
                    "timestamp": "2026-08-15T20:00:01.000Z",
                    "message": {
                        "role": "toolResult",
                        "content": [],
                        "toolCallId": "call-1",
                        "toolName": "exec",
                    },
                },
                make_msg_event_dict(2, role="assistant", content="done"),
            ],
        )
        events = read_transcript_messages(path)
        self.assertEqual(len(events), 2)
        # seq is reassigned contiguously after filter.
        self.assertEqual([e.seq for e in events], [0, 1])

    def test_drops_empty_content(self):
        path = Path(self.tmp) / "agents" / "main" / "sessions" / "abc.jsonl"
        write_transcript(
            path,
            [
                make_msg_event_dict(0, role="user", content="hi"),
                make_msg_event_dict(1, role="assistant", content="   "),  # whitespace-only
                make_msg_event_dict(2, role="assistant", content=""),  # empty
                make_msg_event_dict(3, role="assistant", content="real answer"),
            ],
        )
        events = read_transcript_messages(path)
        self.assertEqual(len(events), 2)
        self.assertEqual([e.content for e in events], ["hi", "real answer"])

    def test_handles_list_content_blocks(self):
        path = Path(self.tmp) / "agents" / "main" / "sessions" / "abc.jsonl"
        write_transcript(
            path,
            [
                {
                    "type": "message",
                    "id": "evt-1",
                    "timestamp": "2026-08-15T20:00:00.000Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "internal monologue"},
                            {"type": "text", "text": "visible answer"},
                            {"type": "text", "text": "second paragraph"},
                        ],
                    },
                },
            ],
        )
        events = read_transcript_messages(path)
        self.assertEqual(len(events), 1)
        # thinking blocks are skipped (per spec mirroring openclaw-honcho).
        self.assertEqual(events[0].content, "visible answer\nsecond paragraph")

    def test_empty_transcript_returns_empty_list(self):
        path = Path(self.tmp) / "agents" / "main" / "sessions" / "empty.jsonl"
        write_transcript(path, [])
        events = read_transcript_messages(path)
        self.assertEqual(events, [])

    def test_skips_malformed_jsonl_lines(self):
        path = Path(self.tmp) / "agents" / "main" / "sessions" / "abc.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "session", "id": "abc"}) + "\n")
            f.write("not-json-line\n")  # malformed
            f.write(json.dumps(make_msg_event_dict(0, role="user", content="hi")) + "\n")
            f.write("\n")  # blank
        events = read_transcript_messages(path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].content, "hi")


# ---------------------------------------------------------------------------
# Content extraction tests
# ---------------------------------------------------------------------------


class TestExtractTextContent(unittest.TestCase):
    def test_plain_string(self):
        self.assertEqual(extract_text_content("hello"), "hello")

    def test_string_with_whitespace_stripped(self):
        self.assertEqual(extract_text_content("  hello  \n"), "hello")

    def test_list_of_text_blocks(self):
        content = [
            {"type": "text", "text": "part1"},
            {"type": "text", "text": "part2"},
        ]
        self.assertEqual(extract_text_content(content), "part1\npart2")

    def test_list_with_thinking_block_skipped(self):
        content = [
            {"type": "thinking", "thinking": "hidden"},
            {"type": "text", "text": "visible"},
        ]
        self.assertEqual(extract_text_content(content), "visible")

    def test_list_with_string_blocks(self):
        content = ["line1", "line2"]
        self.assertEqual(extract_text_content(content), "line1\nline2")

    def test_empty_list_returns_empty_string(self):
        self.assertEqual(extract_text_content([]), "")

    def test_other_types_coerced_to_string(self):
        self.assertEqual(extract_text_content(42), "42")


# ---------------------------------------------------------------------------
# find_session_files tests (mtime window + Codex exclusion)
# ---------------------------------------------------------------------------


class TestFindSessionFiles(unittest.TestCase):
    """Verify file scanning rules (mtime filter + Codex rollout exclusion)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="honcho-bf-find-")
        self.agents = Path(self.tmp) / "agents"
        self.agents.mkdir()
        # Window covers the middle of the real outage.
        self.start = datetime(2026, 8, 15, 19, 30, 0, tzinfo=timezone.utc)
        self.end = datetime(2026, 8, 15, 22, 10, 0, tzinfo=timezone.utc)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, path: Path, mtime_iso: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n")
        ts = datetime.fromisoformat(mtime_iso).timestamp()
        os.utime(path, (ts, ts))

    def test_finds_files_in_window(self):
        # Main session at 20:00 UTC.
        f1 = self.agents / "main" / "sessions" / "abc.jsonl"
        self._touch(f1, "2026-08-15T20:00:00+00:00")
        # Sub-agent session at 21:30 UTC.
        f2 = self.agents / "reina" / "sessions" / "xyz.jsonl"
        self._touch(f2, "2026-08-15T21:30:00+00:00")
        results = find_session_files(self.agents, self.start, self.end)
        self.assertEqual({p.name for p in results}, {"abc.jsonl", "xyz.jsonl"})

    def test_excludes_files_outside_window(self):
        f1 = self.agents / "main" / "sessions" / "before.jsonl"
        self._touch(f1, "2026-08-15T19:29:00+00:00")  # 1 min before start
        f2 = self.agents / "main" / "sessions" / "after.jsonl"
        self._touch(f2, "2026-08-15T22:11:00+00:00")  # 1 min after end
        results = find_session_files(self.agents, self.start, self.end)
        self.assertEqual(results, [])

    def test_excludes_trajectory_sidecars(self):
        # Per spec edge case: ".trajectory.jsonl" duplicates — must skip.
        f1 = self.agents / "main" / "sessions" / "abc.jsonl"
        self._touch(f1, "2026-08-15T20:00:00+00:00")
        f2 = self.agents / "main" / "sessions" / "abc.trajectory.jsonl"
        self._touch(f2, "2026-08-15T20:00:00+00:00")
        results = find_session_files(self.agents, self.start, self.end)
        self.assertEqual([p.name for p in results], ["abc.jsonl"])

    def test_excludes_codex_cli_rollouts(self):
        # Codex rollouts live under agents/<x>/agent/codex-home/sessions/...
        f1 = self.agents / "main" / "sessions" / "regular.jsonl"
        self._touch(f1, "2026-08-15T20:00:00+00:00")
        f2 = self.agents / "rin" / "agent" / "codex-home" / "sessions" / "2026" / "08" / "15" / "rollout-test.jsonl"
        self._touch(f2, "2026-08-15T20:00:00+00:00")
        results = find_session_files(self.agents, self.start, self.end)
        # Only the regular session is included.
        self.assertEqual([p.name for p in results], ["regular.jsonl"])

    def test_excludes_files_outside_sessions_dir(self):
        # Files not under any sessions/ dir are not session transcripts.
        f1 = self.agents / "main" / "scratch.jsonl"
        self._touch(f1, "2026-08-15T20:00:00+00:00")
        results = find_session_files(self.agents, self.start, self.end)
        self.assertEqual(results, [])

    def test_missing_agents_dir_returns_empty(self):
        no_such = Path(self.tmp) / "no-such-agents"
        results = find_session_files(no_such, self.start, self.end)
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# End-to-end run_backfill tests with stubbed HonchoClient
# ---------------------------------------------------------------------------


class _StubHonchoClient:
    """Minimal stub for HonchoClient used by run_backfill tests."""

    def __init__(
        self,
        honcho_sessions=None,
        count_overrides=None,
    ):
        self.honcho_sessions = honcho_sessions or []
        self.count_overrides = count_overrides or {}
        self.add_messages_calls = []
        self.fail_add_messages = False

    def list_sessions(self):
        return list(self.honcho_sessions)

    def count_messages(self, session_id):
        if session_id in self.count_overrides:
            return self.count_overrides[session_id]
        return 0

    def add_messages(self, session_id, messages):
        if self.fail_add_messages:
            raise HonchoAPIError("stub: forced failure")
        self.add_messages_calls.append((session_id, list(messages)))
        return {"items": [{"id": f"msg-{i}"} for i in range(len(messages))]}


class TestRunBackfillDryRun(unittest.TestCase):
    """Dry-run mode must NEVER call add_messages (HR37 hard constraint)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="honcho-bf-run-")
        self.agents = Path(self.tmp) / "agents"
        self.agents.mkdir()
        # Three transcripts: one corrupted-watermark gap, one intact, one empty.
        self.corrupted_path = self.agents / "main" / "sessions" / "session-corrupted.jsonl"
        write_transcript(
            self.corrupted_path,
            [make_msg_event_dict(i, role="user" if i % 2 == 0 else "assistant", content=f"msg-{i}") for i in range(10)],
        )
        self.intact_path = self.agents / "main" / "sessions" / "session-intact.jsonl"
        write_transcript(
            self.intact_path,
            [make_msg_event_dict(i, role="user" if i % 2 == 0 else "assistant", content=f"msg-{i}") for i in range(5)],
        )
        self.empty_path = self.agents / "main" / "sessions" / "session-empty.jsonl"
        write_transcript(self.empty_path, [])

        # Touch all files into the outage window so find_session_files picks them.
        for p in (self.corrupted_path, self.intact_path, self.empty_path):
            ts = datetime(2026, 8, 15, 20, 30, 0, tzinfo=timezone.utc).timestamp()
            os.utime(p, (ts, ts))

        # Stub Honcho: corrupted has watermark 8 with 4 actually saved (gap=2);
        # intact has watermark 5 with 5 saved (gap=0).
        self.client = _StubHonchoClient(
            honcho_sessions=[
                {
                    "id": "honcho-corrupted",
                    "metadata": {
                        "oc_session_id": "session-corrupted",
                        "lastSavedIndex": 8,
                    },
                },
                {
                    "id": "honcho-intact",
                    "metadata": {
                        "oc_session_id": "session-intact",
                        "lastSavedIndex": 5,
                    },
                },
            ],
            count_overrides={
                "honcho-corrupted": 4,  # count < lsi -> CORRUPTED, gap = 10-8 = 2
                "honcho-intact": 5,  # count == lsi -> INTACT, gap = 0
            },
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dry_run_zero_writes(self):
        stats = hmb.run_backfill(self.agents, self.client, apply=False)
        # HR37 hard constraint: dry-run MUST NOT call add_messages.
        self.assertEqual(stats.writes_attempted, 0)
        self.assertEqual(self.client.add_messages_calls, [])
        # 3 sessions discovered.
        self.assertEqual(stats.sessions_discovered, 3)
        # 1 empty filtered, 1 intact, 1 corrupted.
        self.assertEqual(stats.sessions_empty, 1)
        self.assertEqual(stats.sessions_watermark_intact, 1)
        self.assertEqual(stats.sessions_watermark_corrupted, 1)
        # 2 messages missing across all sessions (10-8=2).
        self.assertEqual(stats.messages_missing, 2)

    def test_apply_calls_add_messages_with_correct_payload(self):
        stats = hmb.run_backfill(self.agents, self.client, apply=True)
        # Apply path actually invokes add_messages.
        self.assertGreater(len(self.client.add_messages_calls), 0)
        # Exactly 1 call (one chunk since gap_size=2 < ADD_MESSAGES_LIMIT).
        self.assertEqual(len(self.client.add_messages_calls), 1)
        session_id, payload = self.client.add_messages_calls[0]
        self.assertEqual(session_id, "honcho-corrupted")
        # Payload has 2 messages (gap of 2 from watermark 8 to length 10).
        self.assertEqual(len(payload), 2)
        # Messages are the 2 beyond-watermark events (seq=8 and seq=9).
        self.assertEqual(payload[0]["metadata"]["transcript_seq"], 8)
        self.assertEqual(payload[1]["metadata"]["transcript_seq"], 9)
        # Metadata includes idempotency_key for Honcho dedup.
        self.assertIn("idempotency_key", payload[0]["metadata"])
        self.assertIn("recovered_from", payload[0]["metadata"])
        self.assertEqual(payload[0]["metadata"]["recovered_from"], "hr37_outage_2026_08_15")
        # Stats reflect writes.
        self.assertEqual(stats.writes_attempted, 1)
        self.assertEqual(stats.writes_succeeded, 1)
        self.assertEqual(stats.writes_failed, 0)

    def test_apply_chunks_large_gaps(self):
        # Use a session with > ADD_MESSAGES_LIMIT messages beyond watermark to
        # verify chunking works. Build a fresh agents dir + stub so the assertion
        # isolates this session's chunking behaviour.
        big_tmp = tempfile.mkdtemp(prefix="honcho-bf-big-")
        try:
            big_agents = Path(big_tmp) / "agents"
            big_agents.mkdir()
            big_path = big_agents / "main" / "sessions" / "session-big.jsonl"
            write_transcript(
                big_path,
                [
                    make_msg_event_dict(
                        i,
                        role="user" if i % 2 == 0 else "assistant",
                        content=f"msg-{i}",
                    )
                    for i in range(250)
                ],
            )
            ts = datetime(2026, 8, 15, 20, 30, 0, tzinfo=timezone.utc).timestamp()
            os.utime(big_path, (ts, ts))
            big_client = _StubHonchoClient(
                honcho_sessions=[
                    {
                        "id": "honcho-big",
                        "metadata": {
                            "oc_session_id": "session-big",
                            "lastSavedIndex": 0,  # All 250 messages are the gap.
                        },
                    }
                ],
                count_overrides={"honcho-big": 0},
            )
            hmb.run_backfill(big_agents, big_client, apply=True)
            # 250 / 100 = 2 full chunks + 1 partial (50) = 3 chunks.
            self.assertEqual(len(big_client.add_messages_calls), 3)
            self.assertEqual(
                [len(c[1]) for c in big_client.add_messages_calls],
                [100, 100, 50],
            )
        finally:
            shutil.rmtree(big_tmp, ignore_errors=True)

    def test_apply_records_write_failures(self):
        # Force add_messages to fail; stats must reflect.
        self.client.fail_add_messages = True
        stats = hmb.run_backfill(self.agents, self.client, apply=True)
        self.assertEqual(stats.writes_failed, 1)
        self.assertEqual(stats.writes_succeeded, 0)
        self.assertEqual(stats.writes_attempted, 1)


class TestRunBackfillFilters(unittest.TestCase):
    """Verify spec edge cases: empty transcript, no Honcho session."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="honcho-bf-filt-")
        self.agents = Path(self.tmp) / "agents"
        self.agents.mkdir()
        self.empty_path = self.agents / "main" / "sessions" / "session-empty.jsonl"
        write_transcript(self.empty_path, [])
        ts = datetime(2026, 8, 15, 20, 30, 0, tzinfo=timezone.utc).timestamp()
        os.utime(self.empty_path, (ts, ts))

        self.no_honcho_path = self.agents / "main" / "sessions" / "session-no-honcho.jsonl"
        write_transcript(
            self.no_honcho_path,
            [
                make_msg_event_dict(0, role="user", content="orphan"),
                make_msg_event_dict(1, role="assistant", content="orphan-reply"),
            ],
        )
        os.utime(self.no_honcho_path, (ts, ts))

        self.client = _StubHonchoClient(honcho_sessions=[])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_transcript_filtered(self):
        stats = hmb.run_backfill(self.agents, self.client, apply=False)
        self.assertEqual(stats.sessions_empty, 1)
        # Empty session is filtered — no add_messages attempt.
        self.assertEqual(self.client.add_messages_calls, [])
        self.assertEqual(stats.writes_attempted, 0)

    def test_no_honcho_session_filtered(self):
        stats = hmb.run_backfill(self.agents, self.client, apply=False)
        self.assertEqual(stats.sessions_no_honcho, 1)
        # Transcript without matching Honcho session is filtered.
        self.assertEqual(self.client.add_messages_calls, [])
        self.assertEqual(stats.writes_attempted, 0)


class TestBuildSessionLookup(unittest.TestCase):
    """Verify metadata.oc_session_id matching."""

    def test_lookup_by_oc_session_id(self):
        sessions = [
            {"id": "h1", "metadata": {"oc_session_id": "abc-123", "lastSavedIndex": 5}},
            {"id": "h2", "metadata": {"oc_session_id": "xyz-789", "lastSavedIndex": 3}},
            {"id": "h3", "metadata": {}},  # no oc_session_id -> not indexed
            {"id": "h4"},  # no metadata -> not indexed
        ]
        lookup = hmb.build_session_lookup(sessions)
        self.assertEqual(set(lookup.keys()), {"abc-123", "xyz-789"})
        self.assertEqual(lookup["abc-123"]["id"], "h1")


class TestApplyGate(unittest.TestCase):
    """Verify --apply env-var gate (HONCHO_BACKFILL_LIVE=1 required)."""

    def setUp(self):
        self._saved = os.environ.pop(LIVE_ENV_VAR, None)

    def tearDown(self):
        if self._saved is not None:
            os.environ[LIVE_ENV_VAR] = self._saved
        else:
            os.environ.pop(LIVE_ENV_VAR, None)

    def test_apply_without_env_var_returns_error(self):
        # Ensure env var is unset.
        os.environ.pop(LIVE_ENV_VAR, None)
        # Invoke main() with --apply and no env var — must return non-zero.
        from honcho_message_backfill import main

        rc = main(["--apply"])
        self.assertEqual(rc, 2)

    def test_apply_with_env_var_proceeds(self):
        # Set env var. Main may still fail (Honcho unreachable in test env),
        # but it should NOT exit with code 2 (the gate failure).
        os.environ[LIVE_ENV_VAR] = LIVE_ENV_VALUE
        # Point at a nonexistent agents dir to abort early before any network call.
        from honcho_message_backfill import main

        rc = main(["--apply", "--agents-dir", "/nonexistent"])
        # 0 = no sessions discovered, no writes attempted, no failure.
        self.assertEqual(rc, 0)

    def test_dry_run_does_not_check_env_var(self):
        # Dry-run should work even without the env var (it's the default).
        os.environ.pop(LIVE_ENV_VAR, None)
        from honcho_message_backfill import main

        rc = main(["--agents-dir", "/nonexistent"])
        self.assertEqual(rc, 0)


class TestFormatStatsTable(unittest.TestCase):
    """Sanity-check the human-readable report format."""

    def test_dry_run_output_contains_expected_labels(self):
        stats = ScanStats(
            sessions_discovered=42,
            sessions_empty=5,
            sessions_no_honcho=2,
            sessions_watermark_intact=20,
            sessions_watermark_corrupted=15,
            messages_missing=85,
            writes_attempted=0,
        )
        out = hmb.format_stats_table(stats, apply=False)
        self.assertIn("DRY RUN", out)
        self.assertIn("sessions_discovered: 42", out)
        self.assertIn("writes_attempted:    0", out)
        self.assertIn("messages_missing:    85", out)


# ---------------------------------------------------------------------------
# End-to-end CLI smoke test (real subprocess)
# ---------------------------------------------------------------------------


class TestCliSmoke(unittest.TestCase):
    """End-to-end smoke test: --apply without env var exits with code 2."""

    def test_apply_without_env_var_subprocess(self):
        env = os.environ.copy()
        env.pop(LIVE_ENV_VAR, None)
        result = subprocess.run(
            [sys.executable, "scripts/ops/honcho_message_backfill.py", "--apply"],
            cwd=str(_HERE.parent.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(LIVE_ENV_VAR, result.stderr)

    def test_dry_run_help_smoke(self):
        # --help works without env var (read-only path).
        result = subprocess.run(
            [sys.executable, "scripts/ops/honcho_message_backfill.py", "--help"],
            cwd=str(_HERE.parent.parent),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--apply", result.stdout)
        self.assertIn("--dry-run", result.stdout)


if __name__ == "__main__":
    unittest.main()
