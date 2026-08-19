"""Tests for Phase 6 kanban hygiene (scripts/kanban_hygiene.py).

Tests use a temp sqlite DB (no production DB read).
"""

from __future__ import annotations

import importlib
import importlib.util
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import ModuleType

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


@pytest.fixture(scope="module")
def kh_module() -> ModuleType:
    """Import kanban_hygiene.py as a fresh module so its module-level
    argparse defaults don't bleed into other tests."""
    spec = importlib.util.spec_from_file_location(
        "kanban_hygiene", SCRIPTS_DIR / "kanban_hygiene.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kanban_hygiene"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def workboard_db(tmp_path: Path) -> Path:
    db = tmp_path / "wb.sqlite"
    conn = sqlite3.connect(db)
    try:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE workboard_cards (
                id TEXT PRIMARY KEY,
                board_id TEXT NOT NULL,
                title TEXT NOT NULL,
                notes TEXT,
                status TEXT NOT NULL,
                priority TEXT NOT NULL,
                agent_id TEXT,
                session_key TEXT,
                run_id TEXT,
                task_id TEXT,
                source_url TEXT,
                position INTEGER,
                created_at INTEGER,
                updated_at INTEGER,
                started_at INTEGER,
                completed_at INTEGER,
                execution_id TEXT,
                execution_kind TEXT,
                execution_engine TEXT,
                execution_mode TEXT,
                execution_status TEXT,
                execution_model TEXT,
                execution_session_key TEXT,
                execution_run_id TEXT,
                execution_started_at INTEGER,
                execution_updated_at INTEGER,
                automation_json TEXT,
                claim_json TEXT,
                template_id TEXT,
                archived_at INTEGER,
                stale_json TEXT,
                lifecycle_status_source_updated_at INTEGER,
                failure_count INTEGER
            )
        """
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _insert_card(
    db_path: Path,
    card_id: str,
    status: str,
    *,
    age_days: float,
    title: str | None = None,
) -> None:
    ts = int((datetime.now(timezone.utc) - timedelta(days=age_days)).timestamp() * 1000)
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO workboard_cards
              (id, board_id, title, status, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (card_id, "default", title or f"Card {card_id}", status, "normal", ts, ts),
        )
        conn.commit()
    finally:
        conn.close()


def test_run_hygiene_dry_run_detects_done_and_stale(
    kh_module, workboard_db: Path, tmp_path: Path
) -> None:
    """Dry run identifies done cards >3d, stale >7d, blocked >48h."""
    ops = tmp_path / "ops"
    ops.mkdir()

    _insert_card(workboard_db, "done-old", "done", age_days=4.5)
    _insert_card(workboard_db, "done-recent", "done", age_days=1.5)
    _insert_card(workboard_db, "stale-ready", "ready", age_days=8.0)
    _insert_card(workboard_db, "stale-todo", "todo", age_days=10.0)
    _insert_card(workboard_db, "blocked-old", "blocked", age_days=3.0)
    _insert_card(workboard_db, "blocked-new", "blocked", age_days=0.5)

    report = kh_module.run_hygiene(
        db_path=str(workboard_db),
        dry_run=True,
        done_archive_days=3.0,
        stale_days=7.0,
        blocked_days=2.0,
        max_archive=200,
        ops_dir=ops,
    )
    archive_ids = {c["id"] for c in report.archive_candidates}
    stale_ids = {c["id"] for c in report.stale_candidates}
    blocked_ids = {c["id"] for c in report.blocked_candidates}
    assert archive_ids == {"done-old"}
    assert stale_ids == {"stale-ready", "stale-todo"}
    assert blocked_ids == {"blocked-old"}

    # dry_run = True → no archive, no JSONL writes
    assert report.archived_count == 0
    assert report.stale_appended_count == 0
    assert report.blocked_appended_count == 0
    assert not list(ops.iterdir()), "no files should be created in dry-run"


def test_run_hygiene_apply_writes_files(
    kh_module, workboard_db: Path, tmp_path: Path
) -> None:
    """Apply mode writes JSONL logs and updates archived_at in the DB."""
    ops = tmp_path / "ops"
    ops.mkdir()

    _insert_card(workboard_db, "done-old", "done", age_days=4.5)
    _insert_card(workboard_db, "stale-1", "ready", age_days=8.0)
    _insert_card(workboard_db, "blocked-1", "blocked", age_days=3.0)

    report = kh_module.run_hygiene(
        db_path=str(workboard_db),
        dry_run=False,
        done_archive_days=3.0,
        stale_days=7.0,
        blocked_days=2.0,
        max_archive=200,
        ops_dir=ops,
    )

    # Apply mode → archive + JSONL writes happened
    assert report.archived_count == 1
    assert report.stale_appended_count == 1
    assert report.blocked_appended_count == 1

    # Verify the DB row got archived_at
    conn = sqlite3.connect(str(workboard_db))
    cur = conn.cursor()
    cur.execute("SELECT archived_at FROM workboard_cards WHERE id = ?", ("done-old",))
    row = cur.fetchone()
    conn.close()
    assert row[0] is not None, "done-old should have archived_at set"

    # Verify JSONL contents
    stale_path = ops / "stale_cards.jsonl"
    escalation_path = ops / "escalation_queue.jsonl"
    assert stale_path.exists() and stale_path.read_text().strip() != ""
    assert escalation_path.exists() and escalation_path.read_text().strip() != ""


def test_run_hygiene_respects_max_archive(
    kh_module, workboard_db: Path, tmp_path: Path
) -> None:
    """--max-archive should cap how many cards get archived per run."""
    ops = tmp_path / "ops"
    ops.mkdir()

    for i in range(10):
        _insert_card(workboard_db, f"done-{i}", "done", age_days=5 + i * 0.1)

    report = kh_module.run_hygiene(
        db_path=str(workboard_db),
        dry_run=True,
        done_archive_days=3.0,
        max_archive=5,
        ops_dir=ops,
    )
    assert len(report.archive_candidates) == 5
    assert any("Truncating" in n for n in report.notes)
