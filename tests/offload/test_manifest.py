"""Unit tests for the ``manifest`` module.

Coverage:
- Q4.b atomic two-phase write (``atomic_write_manifest``: draft → ``os.replace``
  to final; draft is gone after a successful run).
- Q4.c per-cell lock: contention raises ``RuntimeError`` immediately
  (the precondition the cycle-4a ``_run_one_cell`` fix relies on).
- Manifest dataclass: required fields + serial roundtrip via ``to_json``
  / ``from_dict`` (the path ``run_matrix_remote`` actually uses).
"""

from __future__ import annotations

import fcntl
import json
import pathlib

import pytest
from offload.manifest import (
    Manifest,
    atomic_write_manifest,
    per_cell_lock,
)


def _make_manifest(tmp_path: pathlib.Path) -> Manifest:
    """Helper: minimal Manifest with the required fields populated."""
    return Manifest(
        cell_id="abc1234",
        seed="abc1234",  # Q4 v1 binding exercised in roundtrip test
        strategy="q1_mw_formation",
        symbol="GBPUSD",
        timeframe="M5",
        git_sha="e97cd420" * 5,  # 40-char hex
        env_lock_hash="9123e0ab" * 8,  # 64-char hex
        env_lock_files=["requirements.txt", "requirements-duckdb.txt"],
    )


def test_atomic_write_creates_final_removes_draft(tmp_path: pathlib.Path) -> None:
    """Q4.b: manifest.json written; manifest.draft.json removed (POSIX-atomic)."""
    out = tmp_path / "cell"
    out.mkdir()
    m = _make_manifest(tmp_path)
    final = atomic_write_manifest(m, out)
    assert final.exists()
    assert not (out / "manifest.draft.json").exists()
    payload = json.loads(final.read_text())
    assert payload["cell_id"] == "abc1234"
    assert payload["strategy"] == "q1_mw_formation"


def test_atomic_write_overwrites_existing_manifest(tmp_path: pathlib.Path) -> None:
    """Q4.b: re-running a cell overwrites the prior terminal manifest cleanly."""
    out = tmp_path / "cell"
    out.mkdir()
    m1 = _make_manifest(tmp_path)
    m2 = _make_manifest(tmp_path)
    m2.strategy = "v2_strategy"
    atomic_write_manifest(m1, out)
    atomic_write_manifest(m2, out)
    payload = json.loads((out / "manifest.json").read_text())
    assert payload["strategy"] == "v2_strategy"


def test_per_cell_lock_basic_acquire_release(tmp_path: pathlib.Path) -> None:
    """per_cell_lock is a context manager; lock fully released on exit."""
    out = tmp_path / "cell"
    out.mkdir()
    with per_cell_lock(out) as fd:
        assert fd > 0
    # Re-acquire succeeds once the prior lock is released.
    with per_cell_lock(out) as fd:
        assert fd > 0


def test_per_cell_lock_raises_runtime_error_on_contention(tmp_path: pathlib.Path) -> None:
    """Q4.c: a second holder raises ``RuntimeError`` immediately (``LOCK_NB``).

    This is the precondition for the cycle-4a ``_run_one_cell`` fix —
    cycle 4b's ``test_run_matrix_remote.py::test_parallel_resume_exactly_once``
    exercises the integration end to end.
    """
    out = tmp_path / "cell"
    out.mkdir()
    held = open(out / "manifest.lock", "w")
    fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(RuntimeError):
            with per_cell_lock(out):
                pass  # never reached
    finally:
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
        held.close()


def test_manifest_serialization_roundtrip(tmp_path: pathlib.Path) -> None:
    """``Manifest.from_dict(to_json parsed)`` round-trips without loss."""
    m1 = _make_manifest(tmp_path)
    m1.local_fallback = True
    m1.exit_code = 0
    m1.output_path = "scorecard.json"
    m1.finished_at = "2026-09-15T16:00:00+00:00"

    parsed = json.loads(m1.to_json())
    m2 = Manifest.from_dict(parsed)

    assert m2.cell_id == m1.cell_id
    assert m2.seed == m1.seed
    assert m2.strategy == m1.strategy
    assert m2.git_sha == m1.git_sha
    assert m2.local_fallback is m1.local_fallback
    assert m2.exit_code == 0
    assert m2.output_path == "scorecard.json"
    assert m2.finished_at == "2026-09-15T16:00:00+00:00"
