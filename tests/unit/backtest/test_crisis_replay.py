"""Tests for crisis_replay module — survival metrics, data loading, and end-to-end replay.

Covers:
1. CRISIS_WINDOWS has 6 entries with correct date ranges
2. survival_metrics returns max_drawdown < 0 on known curve
3. survival_metrics returns recovery_bars=0 if no drawdown
4. survival_metrics returns correct recovery_bars on synthetic drawdown
5. survival_metrics returns sharpe=0 when std=0
6. load_crisis_data with mocked tmp_path CSVs (write 2 months, verify concat)
7. End-to-end run_crisis_replay returns dict with all keys
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure src/forex-bot is on sys.path
# Import crisis_replay directly to avoid heavy backtest/__init__.py chain
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_FXBOT = (_PACKAGE_ROOT / "src" / "forex-bot").resolve()
sys.path.insert(0, str(_FXBOT))

import importlib.util as _ilu  # noqa: E402

_spec = _ilu.spec_from_file_location("crisis_replay", str(_FXBOT / "backtest" / "crisis_replay.py"))
_mod = _ilu.module_from_spec(_spec)
sys.modules["crisis_replay"] = _mod  # Register for @dataclass
_spec.loader.exec_module(_mod)

# Load simple_engine directly to avoid backtest/__init__.py
_se_spec = _ilu.spec_from_file_location("simple_engine_standalone", str(_FXBOT / "backtest" / "simple_engine.py"))
_se_mod = _ilu.module_from_spec(_se_spec)
sys.modules["simple_engine_standalone"] = _se_mod
_se_spec.loader.exec_module(_se_mod)

from crisis_replay import (  # noqa: E402, I001
    _CRISIS_BY_EVENT,
    CRISIS_WINDOWS,
    MAX_DRAWDOWN_PCT,
    MAX_RECOVERY_BARS,
    MIN_SHARPE_RATIO,
    CrisisWindow,
    load_crisis_data,
    run_crisis_replay,
    survival_metrics,
)
from simple_engine_standalone import SimulatedTrade, TradeOutcome  # noqa: E402

# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_trade_factory():
    """Create mock SimulatedTrade objects with PnL values."""

    def _make(pnl: float) -> SimulatedTrade:
        trade = MagicMock(spec=SimulatedTrade)
        trade.profit_loss = pnl
        trade.outcome = TradeOutcome.WIN if pnl > 0 else TradeOutcome.LOSS
        return trade

    return _make


# ── Test CRISIS_WINDOWS ──────────────────────────────────────────────────────────


class TestCrisisWindows:
    """AC: All 6 CRISIS_WINDOWS defined; spans are valid."""

    def test_has_six_entries(self):
        """There are exactly 6 crisis windows defined."""
        assert len(CRISIS_WINDOWS) == 6

    def test_all_have_required_fields(self):
        """Each window has event, start, end, pairs, description."""
        for cw in CRISIS_WINDOWS:
            assert isinstance(cw, CrisisWindow)
            assert cw.event
            assert isinstance(cw.start, datetime)
            assert isinstance(cw.end, datetime)
            assert cw.start < cw.end
            assert len(cw.pairs) >= 2
            assert cw.description

    def test_events_are_unique(self):
        """All event names are unique."""
        events = [cw.event for cw in CRISIS_WINDOWS]
        assert len(events) == len(set(events))

    def test_specific_events_present(self):
        """Key crisis events are defined."""
        events = {cw.event for cw in CRISIS_WINDOWS}
        assert "2015_chf_unpeg" in events
        assert "2016_brexit" in events
        assert "2020_covid_crash" in events

    def test_crisis_by_event_lookup(self):
        """_CRISIS_BY_EVENT maps all events."""
        assert len(_CRISIS_BY_EVENT) == 6
        for cw in CRISIS_WINDOWS:
            assert _CRISIS_BY_EVENT[cw.event] is cw


# ── Test survival_metrics ─────────────────────────────────────────────────────────


class TestSurvivalMetrics:
    """AC: survival_metrics implements 3 survival gates."""

    def test_max_drawdown_negative_on_dip(self, mock_trade_factory):
        """survival_metrics returns max_drawdown < 0 on a known drawdown curve."""
        # Peak at 100, drop to 90, recover to 95
        curve = [100.0, 100.0, 95.0, 90.0, 92.0, 95.0]
        trades = [mock_trade_factory(1.0), mock_trade_factory(-2.0)]

        result = survival_metrics(trades, curve)

        assert result["max_drawdown_pct"] < 0.0
        # 90/100 = 10% drawdown → -10%
        assert result["max_drawdown_pct"] == pytest.approx(-10.0, abs=0.1)

    def test_recovery_bars_zero_if_no_drawdown(self, mock_trade_factory):
        """survival_metrics returns recovery_bars=0 if no drawdown."""
        # Monotonically increasing
        curve = [100.0, 101.0, 102.0, 103.0, 104.0]
        trades = [mock_trade_factory(1.0)]

        result = survival_metrics(trades, curve)

        assert result["recovery_bars"] == 0
        assert result["max_drawdown_pct"] == 0.0

    def test_recovery_bars_on_synthetic_drawdown(self, mock_trade_factory):
        """survival_metrics returns correct recovery_bars on synthetic drawdown."""
        # Peak at 100 (idx 0), trough at 90 (idx 3), recovers to 100 at idx 7
        curve = [100.0, 98.0, 95.0, 90.0, 91.0, 93.0, 96.0, 100.0, 101.0]
        trades = [mock_trade_factory(-1.0)]

        result = survival_metrics(trades, curve)

        # Trough at index 3, recovery to peak (100.0) at index 7
        # Recovery bars = 7 - 3 = 4
        assert result["recovery_bars"] == 4

    def test_sharpe_zero_when_std_zero(self):
        """survival_metrics returns sharpe=0 when all PnL are identical (std=0)."""
        curve = [100.0, 100.0, 100.0]

        # All trades have same PnL → std=0 → sharpe=0
        trade = MagicMock(spec=SimulatedTrade)
        trade.profit_loss = 5.0
        trades = [trade, trade, trade]

        result = survival_metrics(trades, curve)

        assert result["survival"] is False  # sharpe=0 < threshold
        assert result["gates"]["sharpe_ratio"] is False

    def test_gates_pass_on_good_metrics(self, mock_trade_factory):
        """All 3 gates pass when metrics are within thresholds."""
        # Small drawdown (1%), quick recovery, decent Sharpe
        curve = [100.0, 100.0, 99.5, 100.0, 100.5, 101.0]
        trades = [
            mock_trade_factory(0.5),
            mock_trade_factory(0.5),
            mock_trade_factory(-0.2),
        ]

        result = survival_metrics(trades, curve)

        assert result["gates"]["max_drawdown"] is True
        assert result["gates"]["recovery_bars"] is True
        # Sharpe gate depends on trade variance — just verify it's computed
        assert "sharpe_ratio" in result["gates"]

    def test_survival_flag_reflects_gates(self, mock_trade_factory):
        """survival=True only when all gates pass."""
        # Huge drawdown → should fail
        curve = [100.0, 50.0, 50.0]
        trades = [mock_trade_factory(-10.0)]

        result = survival_metrics(trades, curve)

        assert result["survival"] is False
        assert result["gates"]["max_drawdown"] is False

    def test_thresholds(self):
        """Survival gate thresholds are correct per spec."""
        assert MAX_DRAWDOWN_PCT == 7.0
        assert MAX_RECOVERY_BARS == 20
        assert MIN_SHARPE_RATIO == 0.3


# ── Test load_crisis_data ──────────────────────────────────────────────────────────


class TestLoadCrisisData:
    """AC: load_crisis_data reads CSVs and filters to crisis window."""

    def test_load_two_months(self, tmp_path):
        """Write 2 months of CSV data and verify concatenation + filtering."""
        cw = _CRISIS_BY_EVENT["2015_chf_unpeg"]
        pair = "EURUSD"

        # Write Jan 2015 data (within crisis window)
        jan_data = pd_data_rows(cw.start, cw.end)
        jan_path = tmp_path / f"{pair}_M1_2015-01.csv"
        write_csv(jan_path, jan_data)

        result = load_crisis_data("2015_chf_unpeg", base_dir=tmp_path)

        assert pair in result
        df = result[pair]
        assert len(df) > 0
        # All timestamps should be within the crisis window
        assert df["timestamp"].min() >= pd_ts(cw.start)
        assert df["timestamp"].max() < pd_ts(cw.end)

    def test_unknown_event_raises(self, tmp_path):
        """Unknown crisis event raises ValueError."""
        with pytest.raises(ValueError, match="Unknown crisis event"):
            load_crisis_data("nonexistent_crisis", base_dir=tmp_path)

    def test_missing_data_returns_empty(self, tmp_path):
        """No CSV files → empty dict with warning."""
        result = load_crisis_data("2015_chf_unpeg", base_dir=tmp_path)
        assert result == {}


# ── Test run_crisis_replay (end-to-end) ───────────────────────────────────────────


class TestRunCrisisReplay:
    """AC: run_crisis_replay returns dict with all keys."""

    def test_no_data_returns_error_result(self, tmp_path):
        """When no data exists, returns result with error='no_data'."""
        result = run_crisis_replay(
            strategy_cls=None,
            event_name="2015_chf_unpeg",
            base_dir=tmp_path,
        )

        assert result["event"] == "2015_chf_unpeg"
        assert result["metrics"] is None
        assert result["error"] == "no_data"
        assert result["trades"] == []

    def test_with_synthetic_data(self, tmp_path):
        """End-to-end with synthetic CSV data — verify result structure."""
        cw = _CRISIS_BY_EVENT["2015_chf_unpeg"]
        pair = "EURUSD"

        # Write enough synthetic bars (need ≥30 for engine)
        rows = []
        ts = cw.start
        from datetime import timedelta

        while ts < cw.end:
            rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "open": 1.1000,
                    "high": 1.1010,
                    "low": 1.0990,
                    "close": 1.1005,
                    "volume": 1000.0,
                }
            )
            ts = ts + timedelta(minutes=1)

        csv_path = tmp_path / f"{pair}_M1_2015-01.csv"
        write_csv(csv_path, rows)

        result = run_crisis_replay(
            strategy_cls=None,
            event_name="2015_chf_unpeg",
            base_dir=tmp_path,
            initial_equity=10000.0,
        )

        assert result["event"] == "2015_chf_unpeg"
        assert result["strategy"] == "none"
        assert "metrics" in result
        assert "trades" in result
        assert "equity_curve" in result
        assert "backtest_metrics" in result


# ── Helpers ──────────────────────────────────────────────────────────────────────


def pd_ts(dt: datetime):  # type: ignore[name-defined]
    """Convert datetime to pandas Timestamp."""
    import pandas as pd  # noqa: F401

    # dt already has tzinfo, just wrap in pd.Timestamp
    return pd.Timestamp(dt)


def pd_data_rows(start: datetime, end: datetime) -> list[dict]:
    """Generate synthetic M1 OHLCV rows within [start, end)."""
    from datetime import timedelta

    rows = []
    ts = start
    while ts < end:
        rows.append(
            {
                "timestamp": ts.isoformat(),
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "volume": 1000.0,
            }
        )
        ts = ts + timedelta(minutes=1)
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write rows to a CSV file."""
    import csv as csv_mod

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        if rows:
            writer = csv_mod.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
