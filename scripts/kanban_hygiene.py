#!/usr/bin/env python3
"""Kanban hygiene — archive done cards, surface stale/blocked.

Implements the workboard-side housekeeping pieces called out in
``docs/design/hayate-checkpoint-design-2026-07-08.md`` §3.7 (KH-001..KH-007):

  * Done-card archive  — archive cards in ``status=done`` older than the
    configurable threshold (default 72 h).
  * Stale-card surface — list ``todo``/``ready`` cards older than the
    stale threshold (default 7 days) to ``data/ops/stale_cards.jsonl``.
  * Blocked surface    — list cards in ``status=blocked`` older than the
    blocked threshold (default 48 h) to ``data/ops/escalation_queue.jsonl``.

Usage::

    scripts/kanban_hygiene.py --dry-run        # default — preview only
    scripts/kanban_hygiene.py --apply          # actually perform changes
    scripts/kanban_hygiene.py --max-archive 100  # cap the number of archives

The script is deliberately conservative:

  * Default mode is ``--dry-run``.
  * Archive actions never delete workboard rows — only set ``archived_at``.
  * A hard ``--max-archive`` cap (default 200) prevents mass-archives in
    one cron invocation.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_WORKBOARD_DB = os.path.expanduser(
    "~/.openclaw/plugins/workboard/workboard.sqlite"
)
DEFAULT_OPS_DIR = Path("data/ops")
DEFAULT_STALE_LOG = DEFAULT_OPS_DIR / "stale_cards.jsonl"
DEFAULT_ESCALATION_QUEUE = DEFAULT_OPS_DIR / "escalation_queue.jsonl"

DEFAULT_DONE_ARCHIVE_DAYS = 3  # 72 h
DEFAULT_STALE_DAYS = 7
DEFAULT_BLOCKED_DAYS = 2  # 48 h
DEFAULT_MAX_ARCHIVE = 200  # safety cap


@dataclass
class HygieneReport:
    """Result of one hygiene pass."""

    archive_candidates: list[dict[str, Any]]
    stale_candidates: list[dict[str, Any]]
    blocked_candidates: list[dict[str, Any]]
    archived_count: int
    stale_appended_count: int
    blocked_appended_count: int
    dry_run: bool
    notes: list[str]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso(ms: int | float) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _open_db(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"workboard sqlite not found at {db_path!r} — is the gateway running?"
        )
    # Note: this script needs write access for the archive action. The
    # daily audit cron runs as the same uid as the gateway, so the
    # permissions align in production. In tests we always open a
    # separate temp DB.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_ops_dir(ops_dir: Path) -> None:
    ops_dir.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def _fetch_by_status(
    db_path: str,
    *,
    statuses: Iterable[str],
    min_age_days: float,
    exclude_archived: bool = True,
) -> list[dict[str, Any]]:
    statuses = list(statuses)
    status_placeholders = ",".join("?" for _ in statuses)
    now_ms = _now_ms()
    age_ms = int(min_age_days * 24 * 60 * 60 * 1000)
    cutoff = now_ms - age_ms

    query = f"""
        SELECT id, board_id, title, status, agent_id, priority,
               updated_at, created_at, completed_at, archived_at
          FROM workboard_cards
         WHERE status IN ({status_placeholders})
           AND updated_at <= ?
    """
    params: list[Any] = list(statuses) + [cutoff]
    if exclude_archived:
        query += "   AND archived_at IS NULL\n"

    conn = _open_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        updated = r["updated_at"] or 0
        age_days = round(max(0, now_ms - updated) / (24 * 60 * 60 * 1000), 3)
        out.append(
            {
                "id": r["id"],
                "board_id": r["board_id"],
                "title": r["title"],
                "status": r["status"],
                "agent_id": r["agent_id"],
                "priority": r["priority"],
                "updated_at": updated,
                "updated_at_iso": _iso(updated),
                "age_days": age_days,
                "completed_at": r["completed_at"],
                "archived_at": r["archived_at"],
            }
        )
    return out


def run_hygiene(
    db_path: str = DEFAULT_WORKBOARD_DB,
    *,
    dry_run: bool = True,
    done_archive_days: float = DEFAULT_DONE_ARCHIVE_DAYS,
    stale_days: float = DEFAULT_STALE_DAYS,
    blocked_days: float = DEFAULT_BLOCKED_DAYS,
    max_archive: int = DEFAULT_MAX_ARCHIVE,
    ops_dir: Path = DEFAULT_OPS_DIR,
    now_ms: int | None = None,
) -> HygieneReport:
    """Run a single hygiene pass and return a structured report."""
    notes: list[str] = []

    # 1. Done-card archive candidates
    archive_candidates = _fetch_by_status(
        db_path,
        statuses=("done",),
        min_age_days=done_archive_days,
    )
    if len(archive_candidates) > max_archive:
        notes.append(
            f"Truncating archive batch from {len(archive_candidates)} to "
            f"--max-archive={max_archive}; remainder stays for the next pass."
        )
        archive_candidates = archive_candidates[:max_archive]

    # 2. Stale (todo/ready) — surfaced to JSONL
    stale_candidates = _fetch_by_status(
        db_path,
        statuses=("todo", "ready"),
        min_age_days=stale_days,
    )

    # 3. Blocked — surfaced to escalation_queue.jsonl
    blocked_candidates = _fetch_by_status(
        db_path,
        statuses=("blocked",),
        min_age_days=blocked_days,
    )

    archived_count = 0
    stale_appended_count = 0
    blocked_appended_count = 0

    if not dry_run:
        if archive_candidates:
            conn = _open_db(db_path)
            try:
                ts = int(time.time() * 1000)
                cur = conn.cursor()
                cur.executemany(
                    "UPDATE workboard_cards SET archived_at = ? WHERE id = ?",
                    [(ts, c["id"]) for c in archive_candidates],
                )
                conn.commit()
                archived_count = cur.rowcount
            finally:
                conn.close()

        if stale_candidates:
            for c in stale_candidates:
                _append_jsonl(
                    ops_dir / DEFAULT_STALE_LOG.name,
                    {
                        "ts": (now_ms is not None and _iso(now_ms)) or _iso(_now_ms()),
                        "kind": "stale_card",
                        "card_id": c["id"],
                        "title": c["title"],
                        "status": c["status"],
                        "board_id": c["board_id"],
                        "age_days": c["age_days"],
                        "updated_at_iso": c["updated_at_iso"],
                    },
                )
                stale_appended_count += 1

        if blocked_candidates:
            for c in blocked_candidates:
                _append_jsonl(
                    ops_dir / DEFAULT_ESCALATION_QUEUE.name,
                    {
                        "ts": (now_ms is not None and _iso(now_ms)) or _iso(_now_ms()),
                        "kind": "blocked_stale",
                        "card_id": c["id"],
                        "title": c["title"],
                        "status": c["status"],
                        "board_id": c["board_id"],
                        "age_days": c["age_days"],
                        "agent_id": c["agent_id"],
                        "priority": c["priority"],
                        "recommended_action": (
                            f"Blocked card held for {c['age_days']:.1f} days "
                            f"(>= {blocked_days}d threshold) — needs review."
                        ),
                    },
                )
                blocked_appended_count += 1

    return HygieneReport(
        archive_candidates=archive_candidates,
        stale_candidates=stale_candidates,
        blocked_candidates=blocked_candidates,
        archived_count=archived_count,
        stale_appended_count=stale_appended_count,
        blocked_appended_count=blocked_appended_count,
        dry_run=dry_run,
        notes=notes,
    )


def render_report(report: HygieneReport) -> str:
    lines: list[str] = []
    lines.append("# Kanban Hygiene Report")
    lines.append("")
    lines.append(f"Mode: **{'DRY-RUN' if report.dry_run else 'APPLIED'}**")
    lines.append("")
    lines.append("## Done-card archive")
    lines.append("")
    if not report.archive_candidates:
        lines.append("- 0 cards eligible for archive (≥ 72 h old).")
    else:
        lines.append(
            f"- {len(report.archive_candidates)} cards eligible "
            f"({'already applied' if report.archived_count else 'pending'})"
        )
        for c in report.archive_candidates[:10]:
            lines.append(
                f"  - `{c['id'][:8]}` **{c['status']}** {c['title'][:60]} "
                f"({c['age_days']:.1f}d)"
            )
        if len(report.archive_candidates) > 10:
            lines.append(f"  - … and {len(report.archive_candidates) - 10} more.")
    lines.append("")
    lines.append("## Stale todo/ready cards")
    lines.append("")
    if not report.stale_candidates:
        lines.append("- 0 stale todo/ready cards (≥ 7d).")
    else:
        lines.append(
            f"- {len(report.stale_candidates)} stale card(s); "
            f"{'appended to' if not report.dry_run else 'would append to'} "
            f"`data/ops/stale_cards.jsonl`."
        )
    lines.append("")
    lines.append("## Blocked cards")
    lines.append("")
    if not report.blocked_candidates:
        lines.append("- 0 blocked cards (≥ 48 h).")
    else:
        lines.append(
            f"- {len(report.blocked_candidates)} blocked card(s); "
            f"{'appended to' if not report.dry_run else 'would append to'} "
            f"`data/ops/escalation_queue.jsonl`."
        )
    lines.append("")
    if report.notes:
        lines.append("## Notes")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Kanban hygiene.")
    p.add_argument(
        "--db",
        default=DEFAULT_WORKBOARD_DB,
        help="Path to the workboard sqlite (default: %(default)s)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview actions without modifying anything (default)",
    )
    p.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Perform the actions (archive + append to JSONL)",
    )
    p.add_argument(
        "--ops-dir",
        type=Path,
        default=DEFAULT_OPS_DIR,
        help="Directory for stale_cards.jsonl and escalation_queue.jsonl",
    )
    p.add_argument(
        "--stale-days",
        type=float,
        default=DEFAULT_STALE_DAYS,
        help="Days idle before todo/ready counts as stale (default %(default)s)",
    )
    p.add_argument(
        "--blocked-hours",
        type=float,
        default=DEFAULT_BLOCKED_DAYS * 24,
        help="Hours idle before blocked card surfaces to escalation_queue (default %(default)s)",
    )
    p.add_argument(
        "--max-archive",
        type=int,
        default=DEFAULT_MAX_ARCHIVE,
        help="Cap on how many done cards to archive per invocation",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    p = _build_parser()
    args = p.parse_args(argv)

    blocked_days = args.blocked_hours / 24.0

    try:
        report = run_hygiene(
            db_path=args.db,
            dry_run=args.dry_run,
            done_archive_days=DEFAULT_DONE_ARCHIVE_DAYS,
            stale_days=args.stale_days,
            blocked_days=blocked_days,
            max_archive=args.max_archive,
            ops_dir=args.ops_dir,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(render_report(report))
    if not args.dry_run:
        print(
            f"\nApplied: archived={report.archived_count}, "
            f"stale_appended={report.stale_appended_count}, "
            f"blocked_appended={report.blocked_appended_count}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
