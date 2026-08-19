#!/usr/bin/env python3
"""Honcho message backfill — recover dropped conversation messages from local
session transcripts after the 2026-08-15 PG password outage (HR37).

Spec: `docs/investigations/honcho-outage-dataloss-2026-08-15.md` §5.2 + §6.

Algorithm (per HR37 §5.2):
  1. Scan local session transcripts (`agents/<agent>/sessions/*.jsonl`) whose
     mtime falls in the outage window.
  2. Filter out empty transcripts and Codex CLI rollouts (separate path).
  3. For each transcript, parse `type=message` events with role in
     `{user, assistant}` (mirrors `openclaw-honcho/extractMessages`).
  4. Locate the matching Honcho session (matched by
     `metadata.oc_session_id == jsonl_stem`).
  5. Fetch session's `lastSavedIndex` watermark and current Honcho message count.
  6. **Gap-fill mode only** — never overwrite intact watermarks:
       - if `honcho.messages count >= lastSavedIndex`: treat watermark as INTACT,
         skip the session (no writes attempted).
       - if `honcho.messages count < lastSavedIndex`: watermark may be corrupted
         (HR37 §3 caveat). Fill gap = `[lastSavedIndex, transcript.length)`.
  7. Insert via `session.addMessages` — Honcho's natural dedup via
     `idempotency_key` metadata guards against double-write on retry.

Safety (HR37 hard constraint):
  - **Default mode is dry-run.** Zero Honcho writes.
  - `--apply` is gated behind the explicit env var `HONCHO_BACKFILL_LIVE=1`.
    Live run is OUT of sprint per HR37 / Ava dispatch — operator must set the
    env var to acknowledge the danger.

Usage:
    python3 scripts/ops/honcho_message_backfill.py --dry-run
    HONCHO_BACKFILL_LIVE=1 python3 scripts/ops/honcho_message_backfill.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_AGENTS_DIR = Path("/root/.openclaw/agents")
DEFAULT_BASE_URL = "http://127.0.0.1:8008"
DEFAULT_WORKSPACE = "honcho-ava-primary"

# HR37 outage window (UTC). Endpoints are inclusive.
OUTAGE_START = datetime(2026, 8, 15, 19, 30, 0, tzinfo=timezone.utc)
OUTAGE_END = datetime(2026, 8, 15, 22, 10, 0, tzinfo=timezone.utc)

# Honcho addMessages rejects >100 messages per request (HR37 plugin code).
ADD_MESSAGES_LIMIT = 100

# Apply gate: explicit env var required for live writes.
LIVE_ENV_VAR = "HONCHO_BACKFILL_LIVE"
LIVE_ENV_VALUE = "1"

# Codex CLI rollouts live under agents/<agent>/agent/codex-home/sessions/...
# which uses a different JSONL schema (session_meta, response_item, etc).
# We deliberately skip these — the spec calls out "Codex CLI rollouts
# (separate path)" as out-of-scope for this backfill.
CODEX_PATH_PART = "codex-home"

# Page size for Honcho list endpoints.
LIST_PAGE_SIZE = 200


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MessageEvent:
    """Single parsed message from a session transcript.

    Mirrors `openclaw-honcho/extractMessages` selection: role in {user, assistant}
    and non-empty content after extraction.
    """

    seq: int                # 0-based position in transcript (after filtering)
    role: str               # "user" | "assistant"
    content: str            # extracted text content
    timestamp: str | None   # ISO 8601 timestamp from event (or None)
    idempotency_key: str    # transcript event id (unique per message)
    session_stem: str       # JSONL filename stem (the oc_session_id)
    agent_id: str           # OpenClaw agent id (parent dir of sessions/)
    source_path: str        # absolute path to transcript


@dataclass(frozen=True)
class SessionRecord:
    """Honcho session metadata snapshot for one transcript."""

    oc_session_id: str           # JSONL stem
    agent_id: str                # OpenClaw agent id
    honcho_session_id: str        # Honcho session id (digest-derived or direct)
    last_saved_index: int         # lastSavedIndex watermark (0 if missing)
    message_count: int             # current honcho.messages count for this session
    transcript_length: int        # total message events in transcript


@dataclass(frozen=True)
class GapInfo:
    """Result of gap-detection on one session."""

    status: str                  # "watermark_intact" | "watermark_corrupted"
    last_saved_index: int
    current_count: int
    transcript_length: int
    gap_size: int                 # number of messages to insert (0 = skip)
    reason: str


@dataclass
class ScanStats:
    """Aggregate counters for one backfill run."""

    sessions_discovered: int = 0
    sessions_empty: int = 0            # filtered (0 messages)
    sessions_no_honcho: int = 0        # no matching Honcho session
    sessions_watermark_intact: int = 0  # count >= lastSavedIndex, skip
    sessions_watermark_corrupted: int = 0  # count < lastSavedIndex, gap fill
    messages_missing: int = 0          # sum of gap_size across all sessions
    writes_attempted: int = 0          # how many addMessages calls actually executed
    writes_succeeded: int = 0
    writes_failed: int = 0
    per_session: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def parse_iso_timestamp(ts):
    """Parse an ISO-8601 timestamp string into a tz-aware datetime.

    Returns None if the input is empty or unparseable.
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def extract_text_content(content) -> str:
    """Extract text from a message content field.

    Mirrors openclaw-honcho/getRawContent + cleanMessageContent for the
    common cases. Handles:
      - plain string content
      - list of content blocks ({"type": "text", "text": "..."})
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    parts.append(str(block.get("text", "")))
                elif btype == "thinking":
                    # Skip thinking blocks — they aren't sent to Honcho.
                    continue
                # Other block types (toolCall, toolResult) are not sent.
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip()


def agent_id_for_path(path: Path) -> str:
    """Derive OpenClaw agent_id from a session transcript path.

    Examples:
        /root/.openclaw/agents/main/sessions/abc.jsonl      -> "main"
        /root/.openclaw/agents/reina/sessions/abc.jsonl     -> "reina"
    """
    parts = path.resolve().parts
    for i, part in enumerate(parts):
        if part == "agents" and i + 1 < len(parts):
            return parts[i + 1]
    return "unknown"


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------

def find_session_files(agents_dir, start, end):
    """Discover session JSONL files with mtime in [start, end] (UTC, tz-aware).

    Skips:
      - Codex CLI rollouts (*/codex-home/sessions/...) — different schema.
      - Trajectory sidecars (*.trajectory.jsonl) — duplicates of main JSONL.
      - Files not under any sessions/ dir.
    """
    if not agents_dir.exists():
        return []

    matches = []
    for jsonl_path in agents_dir.rglob("*.jsonl"):
        if jsonl_path.name.endswith(".trajectory.jsonl"):
            continue
        if CODEX_PATH_PART in jsonl_path.parts:
            continue
        if "sessions" not in jsonl_path.parts:
            continue
        try:
            stat = jsonl_path.stat()
        except OSError:
            continue
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        if start <= mtime <= end:
            matches.append(jsonl_path)
    return sorted(matches)


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def read_transcript_messages(path: Path) -> list:
    """Parse a session JSONL transcript into MessageEvent objects.

    Filters to type=message events with role in {user, assistant} (mirrors
    openclaw-honcho/extractMessages). Empty content after extraction is
    dropped (matches the plugin's `if (!content) continue`).

    Returns events in chronological order with `seq` assigned 0..N-1.
    """
    agent_id = agent_id_for_path(path)
    session_stem = path.stem
    events = []

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("type") != "message":
                    continue
                msg = obj.get("message")
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue
                content = extract_text_content(msg.get("content"))
                if not content:
                    continue
                events.append(MessageEvent(
                    seq=len(events),
                    role=role,
                    content=content,
                    timestamp=obj.get("timestamp") or msg.get("timestamp"),
                    idempotency_key=str(obj.get("id") or ""),
                    session_stem=session_stem,
                    agent_id=agent_id,
                    source_path=str(path),
                ))
    except OSError:
        return []

    return events


# ---------------------------------------------------------------------------
# Honcho API client
# ---------------------------------------------------------------------------

class HonchoClient:
    """Minimal Honcho HTTP client for the backfill script.

    Encapsulates the three endpoints we need:
      - POST /v3/workspaces/{ws}/sessions/list           -> page of sessions
      - POST /v3/workspaces/{ws}/sessions/{sid}/messages/list -> page of messages
      - POST /v3/workspaces/{ws}/sessions/{sid}/messages       -> addMessages

    Sessions are matched to transcripts via metadata.oc_session_id (set by
    openclaw-honcho when it creates a session).

    All methods raise HonchoAPIError on non-2xx responses so callers can decide
    whether to abort or skip the session.
    """

    def __init__(
        self,
        base_url=DEFAULT_BASE_URL,
        workspace=DEFAULT_WORKSPACE,
        api_key=None,
        timeout=30,
    ):
        self.base_url = base_url.rstrip("/")
        self.workspace = workspace
        self.api_key = api_key if api_key is not None else os.environ.get("HONCHO_API_KEY", "")
        self.timeout = timeout

    def _request(self, method, path, body=None):
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # S310: base_url is operator-controlled (CLI arg or env var), not user input.
        req = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                detail = "<unreadable>"
            raise HonchoAPIError(
                f"Honcho HTTP {exc.code} on {method} {path}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise HonchoAPIError(
                f"Honcho unreachable at {self.base_url}: {exc}"
            ) from exc

    def list_sessions(self):
        """Fetch all sessions in the workspace (paginated)."""
        all_items = []
        page = 1
        while True:
            body = {"limit": LIST_PAGE_SIZE, "page": page}
            resp = self._request(
                "POST",
                f"/v3/workspaces/{self.workspace}/sessions/list",
                body,
            )
            if not isinstance(resp, dict):
                break
            items = resp.get("items", [])
            if not items:
                break
            all_items.extend(items)
            total = resp.get("total", 0)
            if len(all_items) >= total or len(items) < LIST_PAGE_SIZE:
                break
            page += 1
        return all_items

    def count_messages(self, session_id):
        """Return the total count of messages in a Honcho session.

        Reads `total` from a single-page list call (limit=1, page=1) — avoids
        fetching every message just to count.
        """
        resp = self._request(
            "POST",
            f"/v3/workspaces/{self.workspace}/sessions/{session_id}/messages/list",
            {"limit": 1, "page": 1},
        )
        if not isinstance(resp, dict):
            return 0
        return int(resp.get("total", 0))

    def add_messages(self, session_id, messages):
        """Add messages to a Honcho session.

        Each message dict must conform to the v3 schema:
          {peer_id, content, metadata?, created_at?}.

        Honcho enforces a per-request message limit (100), so callers should
        pre-chunk. This method sends the payload as-is and returns the parsed
        response body.
        """
        return self._request(
            "POST",
            f"/v3/workspaces/{self.workspace}/sessions/{session_id}/messages",
            {"messages": messages},
        )


class HonchoAPIError(RuntimeError):
    """Raised when a Honcho API call returns non-2xx or is unreachable."""


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def detect_gap(last_saved_index, transcript_length, current_count):
    """Apply HR37 §5.2 + §3 watermark corruption logic.

    Rules (per spec edge case "data_corruption_partial"):
      - if last_saved_index >= transcript_length: skip (watermark at/past end).
      - if last_saved_index == 0 and current_count == 0 and
        transcript_length > 0: watermark was never initialised — fill all
        messages as the gap. (matches plugin semantics where lsi=0 means
        "nothing saved yet, send everything".)
      - if current_count >= last_saved_index (and lsi > 0): treat watermark as
        INTACT, skip (even if there are messages beyond — conservative, don't
        risk re-send).
      - if current_count < last_saved_index: watermark may be corrupted
        (HR37 §3 caveat). Fill gap = [last_saved_index, transcript.length).

    Returns a GapInfo. GapInfo.gap_size is the number of messages to insert
    (0 = skip the session).
    """
    last_saved_index = max(0, int(last_saved_index))
    transcript_length = max(0, int(transcript_length))
    current_count = max(0, int(current_count))

    # Empty transcript -> no gap possible.
    if transcript_length == 0:
        return GapInfo(
            status="watermark_intact",
            last_saved_index=last_saved_index,
            current_count=current_count,
            transcript_length=transcript_length,
            gap_size=0,
            reason="empty transcript (filtered)",
        )

    # Watermark at or past transcript end -> INTACT (nothing to backfill).
    if last_saved_index >= transcript_length:
        return GapInfo(
            status="watermark_intact",
            last_saved_index=last_saved_index,
            current_count=current_count,
            transcript_length=transcript_length,
            gap_size=0,
            reason=(
                f"watermark ({last_saved_index}) >= transcript length "
                f"({transcript_length}); nothing to backfill"
            ),
        )

    # Watermark INTACT (count >= lastSavedIndex, with lsi > 0) -> skip.
    # Special case: lsi == 0 AND count == 0 with non-empty transcript means
    # the watermark was never initialised. Treat as full gap (matches
    # openclaw-honcho semantics where lsi=0 means "nothing saved yet").
    if last_saved_index == 0 and current_count == 0:
        return GapInfo(
            status="watermark_corrupted",
            last_saved_index=last_saved_index,
            current_count=current_count,
            transcript_length=transcript_length,
            gap_size=transcript_length,
            reason=(
                f"watermark uninitialised (lsi=0, count=0); "
                f"gap={transcript_length} messages to backfill from transcript[0:]"
            ),
        )

    if current_count >= last_saved_index:
        return GapInfo(
            status="watermark_intact",
            last_saved_index=last_saved_index,
            current_count=current_count,
            transcript_length=transcript_length,
            gap_size=0,
            reason=(
                f"watermark intact (count={current_count} >= "
                f"lastSavedIndex={last_saved_index}); skip conservatively"
            ),
        )

    # Watermark CORRUPTED: count < lastSavedIndex. Gap fill from watermark.
    gap_size = transcript_length - last_saved_index
    return GapInfo(
        status="watermark_corrupted",
        last_saved_index=last_saved_index,
        current_count=current_count,
        transcript_length=transcript_length,
        gap_size=gap_size,
        reason=(
            f"watermark corrupted (count={current_count} < "
            f"lastSavedIndex={last_saved_index}); gap={gap_size} messages "
            f"to backfill from transcript[{last_saved_index}:]"
        ),
    )


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def build_session_lookup(sessions):
    """Build a {oc_session_id: session} map from Honcho sessions list.

    Each session dict in the list has `metadata` which may include
    `oc_session_id` (set by openclaw-honcho). Sessions without
    `oc_session_id` are not added to the map.
    """
    lookup = {}
    for s in sessions:
        if not isinstance(s, dict):
            continue
        meta = s.get("metadata") or {}
        oc_id = meta.get("oc_session_id")
        if not oc_id:
            continue
        lookup[str(oc_id)] = s
    return lookup


def resolve_session_record(
    transcript_path,
    transcript_events,
    honcho_session_lookup,
    client,
):
    """Resolve one transcript to its Honcho SessionRecord and GapInfo.

    Returns:
      (SessionRecord, GapInfo, "ok") on a fully resolved session.
      (None, None, reason) when no matching Honcho session is found
        (skipped — spec edge case "filter_edge_case" applies).
    """
    if not transcript_events:
        return None, None, "empty transcript"

    oc_session_id = transcript_events[0].session_stem
    agent_id = transcript_events[0].agent_id
    transcript_length = len(transcript_events)

    honcho_session = honcho_session_lookup.get(oc_session_id)
    if honcho_session is None:
        return None, None, "no Honcho session with matching metadata.oc_session_id"

    honcho_session_id = str(honcho_session.get("id", ""))
    if not honcho_session_id:
        return None, None, "Honcho session missing id field"

    meta = honcho_session.get("metadata") or {}
    raw_last = meta.get("lastSavedIndex", 0)
    try:
        last_saved_index = int(raw_last)
    except (TypeError, ValueError):
        last_saved_index = 0

    try:
        message_count = client.count_messages(honcho_session_id)
    except HonchoAPIError as exc:
        return None, None, f"Honcho count_messages failed: {exc}"

    record = SessionRecord(
        oc_session_id=oc_session_id,
        agent_id=agent_id,
        honcho_session_id=honcho_session_id,
        last_saved_index=last_saved_index,
        message_count=message_count,
        transcript_length=transcript_length,
    )
    gap = detect_gap(last_saved_index, transcript_length, message_count)
    return record, gap, "ok"


def events_to_honcho_payload(events, recovered_at):
    """Convert transcript events into Honcho v3 addMessages payload.

    Each message includes:
      - peer_id: "owner" for user messages, "agent-{agent_id}" for assistant
      - content: extracted text
      - metadata: idempotency_key (used for Honcho's natural dedup), source
        provenance for downstream audits
    """
    payload = []
    for ev in events:
        if ev.role == "user":
            peer_id = "owner"
        else:
            peer_id = f"agent-{ev.agent_id}"
        payload.append({
            "peer_id": peer_id,
            "content": ev.content,
            "metadata": {
                "idempotency_key": ev.idempotency_key,
                "role": ev.role,
                "source": "honcho_message_backfill",
                "recovered_from": "hr37_outage_2026_08_15",
                "recovered_at": recovered_at,
                "oc_session_id": ev.session_stem,
                "oc_agent_id": ev.agent_id,
                "transcript_seq": ev.seq,
            },
        })
    return payload


def chunked(seq, size):
    """Yield consecutive chunks of `seq` of length at most `size`."""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def run_backfill(agents_dir, client, apply, start=OUTAGE_START, end=OUTAGE_END):
    """Drive one full backfill pass.

    Returns a ScanStats object with aggregate counts and per-session details.
    """
    stats = ScanStats()
    stats.sessions_discovered = 0

    session_files = find_session_files(agents_dir, start, end)
    stats.sessions_discovered = len(session_files)
    if not session_files:
        return stats

    # Single Honcho sessions-list call — reused across all transcripts.
    try:
        sessions = client.list_sessions()
    except HonchoAPIError as exc:
        raise SystemExit(f"Could not list Honcho sessions: {exc}") from exc
    honcho_lookup = build_session_lookup(sessions)

    recovered_at = datetime.now(timezone.utc).isoformat()

    for path in session_files:
        events = read_transcript_messages(path)
        if not events:
            stats.sessions_empty += 1
            stats.per_session.append({
                "transcript": str(path),
                "oc_session_id": path.stem,
                "agent_id": agent_id_for_path(path),
                "status": "empty_transcript",
                "messages_in_transcript": 0,
                "writes_attempted": 0,
            })
            continue

        record, gap, status = resolve_session_record(
            path, events, honcho_lookup, client
        )
        if record is None:
            stats.sessions_no_honcho += 1
            stats.per_session.append({
                "transcript": str(path),
                "oc_session_id": path.stem,
                "agent_id": agent_id_for_path(path),
                "status": "no_honcho_session",
                "skip_reason": status,
                "messages_in_transcript": len(events),
                "writes_attempted": 0,
            })
            continue

        per_session = {
            "transcript": str(path),
            "oc_session_id": record.oc_session_id,
            "agent_id": record.agent_id,
            "honcho_session_id": record.honcho_session_id,
            "transcript_messages": record.transcript_length,
            "last_saved_index": record.last_saved_index,
            "current_honcho_count": record.message_count,
            "gap_status": gap.status,
            "gap_size": gap.gap_size,
            "gap_reason": gap.reason,
            "writes_attempted": 0,
        }

        if gap.gap_size == 0:
            if gap.status == "watermark_intact":
                stats.sessions_watermark_intact += 1
            stats.per_session.append(per_session)
            continue

        stats.sessions_watermark_corrupted += 1
        stats.messages_missing += gap.gap_size

        if not apply:
            per_session["status"] = "would_write_dry_run"
            stats.per_session.append(per_session)
            continue

        # Live apply: insert messages in chunks of ADD_MESSAGES_LIMIT.
        gap_events = events[gap.last_saved_index:gap.last_saved_index + gap.gap_size]
        payload = events_to_honcho_payload(gap_events, recovered_at)

        writes_ok = 0
        writes_failed = 0
        for chunk in chunked(payload, ADD_MESSAGES_LIMIT):
            stats.writes_attempted += 1
            try:
                client.add_messages(record.honcho_session_id, chunk)
                writes_ok += 1
            except HonchoAPIError as exc:
                writes_failed += 1
                errs = per_session.get("write_errors", [])
                per_session["write_errors"] = errs + [str(exc)]
        stats.writes_succeeded += writes_ok
        stats.writes_failed += writes_failed
        per_session["writes_attempted"] = writes_ok + writes_failed
        per_session["writes_succeeded"] = writes_ok
        per_session["writes_failed"] = writes_failed
        per_session["status"] = "applied" if writes_failed == 0 else "applied_with_errors"
        stats.per_session.append(per_session)

    return stats


def format_stats_table(stats, apply):
    """Format a human-readable summary of one backfill run."""
    mode = "APPLY (LIVE)" if apply else "DRY RUN"
    lines = []
    lines.append("=" * 70)
    lines.append(f"HONCHO MESSAGE BACKFILL — {mode}")
    lines.append(f"Outage window: {OUTAGE_START.isoformat()} -> {OUTAGE_END.isoformat()}")
    lines.append("=" * 70)
    lines.append(f"  sessions_discovered: {stats.sessions_discovered}")
    lines.append(f"  sessions_empty:      {stats.sessions_empty}")
    lines.append(f"  sessions_no_honcho:  {stats.sessions_no_honcho}")
    lines.append(f"  sessions_watermark_intact:    {stats.sessions_watermark_intact}")
    lines.append(f"  sessions_watermark_corrupted: {stats.sessions_watermark_corrupted}")
    lines.append(f"  messages_missing:    {stats.messages_missing}")
    lines.append(f"  writes_attempted:    {stats.writes_attempted}")
    if apply:
        lines.append(f"  writes_succeeded:    {stats.writes_succeeded}")
        lines.append(f"  writes_failed:       {stats.writes_failed}")
    lines.append("")
    if stats.per_session:
        lines.append("Per-session detail:")
        for s in stats.per_session:
            sid = s.get("oc_session_id", "?")
            agent = s.get("agent_id", "?")
            status = s.get("status") or s.get("gap_status") or "?"
            ms = s.get("transcript_messages") or s.get("messages_in_transcript", 0)
            gap = s.get("gap_size", 0)
            wa = s.get("writes_attempted", 0)
            reason = s.get("gap_reason") or s.get("skip_reason") or ""
            lines.append(
                f"  - [{agent}] {sid[:36]:36} "
                f"msgs={ms:>4}  gap={gap:>4}  writes={wa}  status={status}  {reason}"
            )
    lines.append("=" * 70)
    return "\n".join(lines)


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Honcho message backfill — recover dropped messages from session "
            "transcripts after the 2026-08-15 PG outage (HR37). Default mode "
            "is dry-run; --apply requires HONCHO_BACKFILL_LIVE=1."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--agents-dir",
        type=Path,
        default=DEFAULT_AGENTS_DIR,
        help="Directory containing agent session transcripts (default: %(default)s)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("HONCHO_BASE_URL", DEFAULT_BASE_URL),
        help="Honcho base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("HONCHO_WORKSPACE_ID", DEFAULT_WORKSPACE),
        help="Honcho workspace id (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="(default) Read-only — scan and report without Honcho writes.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually write missing messages. Gated behind HONCHO_BACKFILL_LIVE=1 "
            "env var. Live run is OUT of sprint per HR37 / Ava dispatch."
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # Apply gate.
    if args.apply:
        if os.environ.get(LIVE_ENV_VAR) != LIVE_ENV_VALUE:
            print(
                f"ERROR: --apply requires {LIVE_ENV_VAR}={LIVE_ENV_VALUE} env var. "
                f"Live run is OUT of sprint per HR37 / Ava dispatch. "
                f"Set the env var to acknowledge the danger.",
                file=sys.stderr,
            )
            return 2
        apply = True
    else:
        apply = False

    client = HonchoClient(
        base_url=args.base_url,
        workspace=args.workspace,
    )

    stats = run_backfill(args.agents_dir, client, apply=apply)
    print(format_stats_table(stats, apply=apply))

    # Non-zero exit if any writes failed (apply mode only).
    if apply and stats.writes_failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
