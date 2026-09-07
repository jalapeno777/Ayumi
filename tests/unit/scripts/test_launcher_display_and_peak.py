"""Tests for card 627b4f66 — DD display sign fix + FTMO peak reconcile.

Covers two launcher-side bug fixes:

1. ``_compute_pnl_from_start_pct(start, current)`` — formerly the buggy
   ``_dd_pct`` formula ``(start - current) / start * 100`` which produced a
   drawdown with a flipped sign (the launcher reported ``dd=-2.62%`` while
   the account was UP +2.62%, evidence DA-1).
2. ``_reconcile_ftmo_peak_from_persisted_state(ftmo_guard, state_path)`` —
   reconcile the FTMO peak-balance high-water-mark with the persisted
   RiskGuard state file on startup, so trailing-DD does not silently reset
   to the reference account size after every restart (evidence DA-8).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

# Importing the launcher module executes its top-level load_dotenv() call,
# which is harmless if .env is absent.  pythonpath in pytest.ini includes
# ``scripts`` so this resolves cleanly.
from launch_blend_forward_test import (
    _compute_pnl_from_start_pct,
    _reconcile_ftmo_peak_from_persisted_state,
)
from risk.ftmo_guard import FTMOGuard

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_ftmo_guard(starting_balance: float = 10_000.0) -> FTMOGuard:
    """Fresh FTMOGuard with starting_balance = FTMO reference account size."""
    return FTMOGuard(starting_balance=starting_balance)


def _write_state_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


# ── 1. ``_compute_pnl_from_start_pct`` — DD display sign fix ───────────────


class TestComputePnlFromStartPct:
    """Regression coverage for the DD display sign bug (evidence DA-1).

    Card spec: ``(current - start) / start * 100``.  Positive when the
    account is up, negative when down — i.e. *P&L-from-start*, NOT
    drawdown.  The canonical peak-based drawdown is reported separately
    via ``FTMOGuard.get_status()['current_dd_pct']``.
    """

    def test_account_up_reports_positive(self) -> None:
        # Card evidence: balance 10,262.45 vs start 10,000 → +2.62%
        result = _compute_pnl_from_start_pct(start=10_000.0, current=10_262.45)
        assert result == pytest.approx(2.6245, rel=1e-3)

    def test_account_down_reports_negative(self) -> None:
        # Symmetric case: balance 9,737.55 vs start 10,000 → -2.62%
        result = _compute_pnl_from_start_pct(start=10_000.0, current=9_737.55)
        assert result == pytest.approx(-2.6245, rel=1e-3)

    def test_unchanged_account_is_zero(self) -> None:
        assert _compute_pnl_from_start_pct(10_000.0, 10_000.0) == 0.0

    def test_buggy_old_formula_would_have_produced_negative_here(self) -> None:
        """Negative control: prove the OLD formula would have flipped the sign.

        Old code: ``(start - current) / start * 100`` → produces -2.62%
        when the account is UP +2.62% (the user-visible bug).
        """
        old_formula_value = (10_000.0 - 10_262.45) / 10_000.0 * 100.0
        new_value = _compute_pnl_from_start_pct(10_000.0, 10_262.45)
        # Old formula negative, new formula positive, magnitudes match
        assert old_formula_value == pytest.approx(-2.6245, rel=1e-3)
        assert new_value == pytest.approx(+2.6245, rel=1e-3)
        assert new_value == pytest.approx(-old_formula_value, rel=1e-6)

    def test_zero_start_balance_returns_zero(self) -> None:
        """Defensive: never divide by zero / never report a misleading %."""
        assert _compute_pnl_from_start_pct(0.0, 5_000.0) == 0.0

    def test_negative_start_balance_returns_zero(self) -> None:
        assert _compute_pnl_from_start_pct(-1.0, 5_000.0) == 0.0


# ── 2. ``_reconcile_ftmo_peak_from_persisted_state`` ───────────────────────


class TestReconcileFtmoPeak:
    """Regression coverage for the startup peak reconcile (evidence DA-8).

    Card spec: reconcile the persisted peak with the broker high-water-mark
    BEFORE FTMO guard initialization; take the max.  Persisted peak above
    the FTMO-guard init value must NOT be silently lost on restart.
    """

    def test_persisted_peak_higher_than_current_is_preserved(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Card acceptance criterion: persisted peak > current is preserved."""
        guard = _make_ftmo_guard(starting_balance=10_000.0)
        assert guard._state.peak_balance == 10_000.0  # constructor baseline

        state_file = tmp_path / "data" / "state" / "risk_guard_state.json"
        _write_state_json(
            state_file,
            {
                "peak_balance": 10_415.81,  # matches card evidence
                "current_balance": 10_262.45,
                "daily_start_balance": 10_262.45,
            },
        )

        with caplog.at_level(logging.INFO):
            resolved = _reconcile_ftmo_peak_from_persisted_state(guard, state_file)

        assert resolved == pytest.approx(10_415.81)
        assert guard._state.peak_balance == pytest.approx(10_415.81)
        # Confirms reconcile was logged
        assert any(
            "FTMO peak reconciled UP" in record.message
            for record in caplog.records
        )

    def test_persisted_peak_lower_than_current_is_noop(self, tmp_path: Path) -> None:
        """In-memory value already ≥ persisted → leave guard untouched."""
        guard = _make_ftmo_guard(starting_balance=10_000.0)
        # Simulate that the in-memory guard already saw a higher peak via
        # the natural peak-ratchet inside update().
        guard._state.peak_balance = 11_000.0

        state_file = tmp_path / "data" / "state" / "risk_guard_state.json"
        _write_state_json(state_file, {"peak_balance": 9_500.0})

        resolved = _reconcile_ftmo_peak_from_persisted_state(guard, state_file)

        assert resolved == pytest.approx(11_000.0)
        assert guard._state.peak_balance == pytest.approx(11_000.0)

    def test_persisted_peak_equal_to_current_is_noop(self, tmp_path: Path) -> None:
        guard = _make_ftmo_guard(starting_balance=10_000.0)
        state_file = tmp_path / "data" / "state" / "risk_guard_state.json"
        _write_state_json(state_file, {"peak_balance": 10_000.0})

        resolved = _reconcile_ftmo_peak_from_persisted_state(guard, state_file)

        assert resolved == pytest.approx(10_000.0)
        assert guard._state.peak_balance == pytest.approx(10_000.0)

    def test_missing_state_file_does_not_raise(self, tmp_path: Path) -> None:
        """Fresh worktree or paper-mode cold start: no state file exists.

        The reconcile must be a no-op (peak = constructor baseline), not
        a fatal error — otherwise every fresh worktree would crash on
        startup.
        """
        guard = _make_ftmo_guard(starting_balance=10_000.0)
        missing_path = tmp_path / "data" / "state" / "risk_guard_state.json"

        resolved = _reconcile_ftmo_peak_from_persisted_state(guard, missing_path)

        assert resolved == pytest.approx(10_000.0)
        assert guard._state.peak_balance == pytest.approx(10_000.0)

    def test_corrupt_state_file_does_not_raise(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Corrupt JSON: best-effort startup hygiene, never fatal."""
        guard = _make_ftmo_guard(starting_balance=10_000.0)
        state_file = tmp_path / "data" / "state" / "risk_guard_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{ this is not valid JSON")

        with caplog.at_level(logging.WARNING):
            resolved = _reconcile_ftmo_peak_from_persisted_state(guard, state_file)

        assert resolved == pytest.approx(10_000.0)
        assert guard._state.peak_balance == pytest.approx(10_000.0)
        assert any(
            "FTMO peak reconcile skipped" in record.message
            for record in caplog.records
        )

    def test_state_file_missing_peak_balance_key(self, tmp_path: Path) -> None:
        """State file exists but has no peak_balance → treat as 0, no reconcile."""
        guard = _make_ftmo_guard(starting_balance=10_000.0)
        state_file = tmp_path / "data" / "state" / "risk_guard_state.json"
        _write_state_json(state_file, {"current_balance": 10_500.0})  # no peak

        resolved = _reconcile_ftmo_peak_from_persisted_state(guard, state_file)

        assert resolved == pytest.approx(10_000.0)
        assert guard._state.peak_balance == pytest.approx(10_000.0)

    def test_state_file_with_non_numeric_peak_does_not_raise(
        self, tmp_path: Path,
    ) -> None:
        """Defensive: non-numeric peak_balance must not crash startup."""
        guard = _make_ftmo_guard(starting_balance=10_000.0)
        state_file = tmp_path / "data" / "state" / "risk_guard_state.json"
        _write_state_json(state_file, {"peak_balance": "not-a-number"})

        resolved = _reconcile_ftmo_peak_from_persisted_state(guard, state_file)

        assert resolved == pytest.approx(10_000.0)
        assert guard._state.peak_balance == pytest.approx(10_000.0)


# ── 3. End-to-end smoke: launcher imports cleanly ─────────────────────────


def test_launcher_module_imports_cleanly() -> None:
    """Smoke test: the launcher module is importable from the test scope
    (its top-level load_dotenv() runs at import time but is harmless if
    ``.env`` is absent) and the helper functions are exposed as callable
    module-level callables."""
    # The module-level imports above already cover this; if we got here,
    # import succeeded.  Confirm callability as the assertion.
    assert callable(_compute_pnl_from_start_pct)
    assert callable(_reconcile_ftmo_peak_from_persisted_state)
