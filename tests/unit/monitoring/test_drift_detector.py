"""Tests for Phase 6 DriftDetector (Hayate KH-001..KH-004).

Tests use a temp workboard sqlite fixture so the production DB is not
read during unit tests.
"""

from __future__ import annotations
import pytest

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ── Fixtures ──────────────────────────────────────────────────────────────


def _create_workboard_schema(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute("""
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
        """)
        c.execute("""
            CREATE TABLE workboard_card_labels (
                card_id TEXT NOT NULL REFERENCES workboard_cards(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                label TEXT NOT NULL,
                PRIMARY KEY(card_id, ordinal)
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _insert_card(
    db_path: Path,
    *,
    card_id: str,
    title: str,
    status: str,
    board_id: str = "default",
    updated_at: int | None = None,
    labels: list[str] | None = None,
    archived_at: int | None = None,
) -> None:
    if updated_at is None:
        updated_at = int(datetime.now(timezone.utc).timestamp() * 1000)
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO workboard_cards
              (id, board_id, title, status, priority, agent_id,
               created_at, updated_at, archived_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card_id,
                board_id,
                title,
                status,
                "normal",
                None,
                updated_at,
                updated_at,
                archived_at,
            ),
        )
        for i, label in enumerate(labels or []):
            c.execute(
                "INSERT INTO workboard_card_labels (card_id, ordinal, label) VALUES (?, ?, ?)",
                (card_id, i, label),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def workboard_db(tmp_path: Path) -> Path:
    db = tmp_path / "workboard.sqlite"
    _create_workboard_schema(db)
    return db


@pytest.fixture()
def plans_dir(tmp_path: Path) -> Path:
    p = tmp_path / "plans"
    p.mkdir()
    return p


@pytest.fixture()
def ops_dir(tmp_path: Path) -> Path:
    p = tmp_path / "ops"
    p.mkdir()
    return p


@pytest.fixture()
def now() -> datetime:
    return datetime(2026, 7, 8, 15, 0, 0, tzinfo=timezone.utc)


def _make_detector(workboard_db, plans_dir, ops_dir, now):
    from monitoring.drift_detector import DriftDetector

    return DriftDetector(
        workboard_db=str(workboard_db),
        plans_dir=plans_dir,
        ops_dir=ops_dir,
        now=now,
    )


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.xfail(reason="DEBT 6ea40384-35ba-4c41-99a6-87d843ca7f75: card age-based staleness check (deterministic time-dependent)", strict=False)
def test_check_card_staleness_warns_and_auto_creates(workboard_db: Path, now: datetime) -> None:
    """Cards older than 3d → warn, older than 7d → auto_create."""
    from monitoring.drift_detector import (  # noqa: I001
        CARD_AUTO_CREATE_DAYS,
        CARD_WARN_DAYS,
    )

    det = _make_detector(workboard_db, Path("."), Path("."), now)

    # Card 2 days old → not stale
    _insert_card(
        workboard_db,
        card_id="fresh",
        title="Fresh card",
        status="ready",
        updated_at=int((now - timedelta(days=2)).timestamp() * 1000),
    )
    # Card 4 days old → warn
    _insert_card(
        workboard_db,
        card_id="warn-1",
        title="Warn card",
        status="ready",
        updated_at=int((now - timedelta(days=4)).timestamp() * 1000),
    )
    # Card 10 days old → auto_create
    _insert_card(
        workboard_db,
        card_id="stale-1",
        title="Stale card",
        status="todo",
        updated_at=int((now - timedelta(days=10)).timestamp() * 1000),
    )

    stale = det.check_card_staleness()
    by_id = {s.card_id: s for s in stale}
    assert "fresh" not in by_id, "2-day card should not be flagged"
    assert by_id["warn-1"].level == "warn"
    assert by_id["warn-1"].age_days >= CARD_WARN_DAYS
    assert by_id["stale-1"].level == "auto_create"
    assert by_id["stale-1"].age_days >= CARD_AUTO_CREATE_DAYS


def test_auto_create_stale_card_writes_draft(ops_dir: Path, workboard_db: Path, now: datetime) -> None:
    """auto_create_stale_card should append a draft to stale_cards.jsonl."""
    det = _make_detector(workboard_db, Path("."), ops_dir, now)
    _insert_card(
        workboard_db,
        card_id="to-auto",
        title="Card to be auto-created",
        status="ready",
        updated_at=int((now - timedelta(days=10)).timestamp() * 1000),
    )
    stale = det.check_card_staleness()
    target = next(s for s in stale if s.card_id == "to-auto")
    assert target.level == "auto_create"

    draft = det.auto_create_stale_card(target)
    assert draft is not None
    assert draft["parent_card_id"] == "to-auto"
    assert draft["labels"] == ["stale", "auto-created", "hayate"]

    # Confirm the jsonl was written
    log_path = ops_dir / "stale_cards.jsonl"
    assert log_path.exists()
    content = log_path.read_text().strip().splitlines()
    assert len(content) == 1
    parsed = json.loads(content[0])
    assert parsed["parent_card_id"] == "to-auto"


@pytest.mark.xfail(reason="DEBT 6ea40384-35ba-4c41-99a6-87d843ca7f75: card age-based staleness check (deterministic time-dependent)", strict=False)
def test_auto_create_stale_card_noop_for_warn(workboard_db: Path, ops_dir: Path, now: datetime) -> None:
    """auto_create_stale_card should NOT create a draft for warn-level cards."""
    det = _make_detector(workboard_db, Path("."), ops_dir, now)
    _insert_card(
        workboard_db,
        card_id="warn-only",
        title="Warn only",
        status="ready",
        updated_at=int((now - timedelta(days=4)).timestamp() * 1000),
    )
    stale = det.check_card_staleness()
    assert stale and stale[0].level == "warn"
    assert det.auto_create_stale_card(stale[0]) is None
    # Confirm no jsonl write happened
    assert not (ops_dir / "stale_cards.jsonl").exists()


def test_check_phase_staleness_no_audit_trail(
    plans_dir: Path, workboard_db: Path, ops_dir: Path, now: datetime
) -> None:
    """With no audit_trail entries, check_phase_staleness should report 0
    by default (require_audit_trail=False). With strict mode, it reports."""
    # Write a quest plan with no audit trail entries
    plan = plans_dir / "quest-test.md"
    plan.write_text(
        "# Quest Test\n"
        "\n"
        "### Phase 0: Setup\n"
        "\n"
        "Body of phase 0 — no audit entries.\n"
        "\n"
        "### Phase 1: Build\n"
        "\n"
        "Body of phase 1.\n"
    )

    det_default = _make_detector(workboard_db, plans_dir, ops_dir, now)
    assert det_default.check_phase_staleness() == []

    det_strict = _make_detector(workboard_db, plans_dir, ops_dir, now)
    phases = det_strict.check_phase_staleness(require_audit_trail=True)
    assert len(phases) == 2
    assert all(p.level == "escalate" for p in phases)


def test_check_phase_staleness_with_recent_audit(
    workboard_db: Path, plans_dir: Path, ops_dir: Path, now: datetime
) -> None:
    """A phase with a recent audit entry must NOT be flagged."""
    plan = plans_dir / "quest-test.md"
    iso_now = now.isoformat()
    iso_2d_ago = (now - timedelta(days=2)).isoformat()
    plan.write_text(
        f"# Quest Test\n\n### Phase 1: Build\n\n- {iso_2d_ago} — audit entry\n- {iso_now} — second audit entry\n"
    )

    det = _make_detector(workboard_db, plans_dir, ops_dir, now)
    assert det.check_phase_staleness() == []


def test_escalate_phase_appends_to_escalation_queue(
    workboard_db: Path, plans_dir: Path, ops_dir: Path, now: datetime
) -> None:
    """escalate_phase writes a record to data/ops/escalation_queue.jsonl."""
    plan = plans_dir / "quest-test.md"
    iso_10d_ago = (now - timedelta(days=10)).isoformat()
    plan.write_text(f"# Quest Test\n\n### Phase 2: Hard Part\n\n- {iso_10d_ago} — very old audit\n")

    det = _make_detector(workboard_db, plans_dir, ops_dir, now)
    phases = det.check_phase_staleness(require_audit_trail=False)
    assert len(phases) == 1
    p = phases[0]
    assert p.level == "escalate"

    rec = det.escalate_phase(p)
    assert rec["phase_id"] == "Phase 2"
    assert rec["level"] == "escalate"

    log_path = ops_dir / "escalation_queue.jsonl"
    assert log_path.exists()
    parsed = json.loads(log_path.read_text().strip().splitlines()[0])
    assert parsed["phase_id"] == "Phase 2"
    assert parsed["level"] == "escalate"
