#!/usr/bin/env python3
"""Unit tests for the FTMO challenge simulation engine.

Tests cover:
    - Daily loss limit enforcement
    - Max drawdown enforcement
    - Profit target detection
    - Equity curve and P&L computation
    - Per-strategy and blended simulation
    - CSV loading
    - Edge cases (empty trades, single trade, boundary values)
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# ── Import the ftmo_simulation module without triggering backtest/__init__.py
# The backtest package's __init__.py imports heavy deps (statsmodels etc.)
# that aren't installed in this environment. The FTMO simulation itself is
# self-contained, so we load it directly via importlib and stub the package.

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SIM_PATH = PROJECT_ROOT / "src" / "forex-bot" / "backtest" / "ftmo_simulation.py"

# Stub the `backtest` package to prevent __init__.py from running.
if "backtest" not in sys.modules:
    _backtest_pkg = types.ModuleType("backtest")
    _backtest_pkg.__path__ = [str(PROJECT_ROOT / "src" / "forex-bot" / "backtest")]
    sys.modules["backtest"] = _backtest_pkg

# Load the module as backtest.ftmo_simulation
_spec = importlib.util.spec_from_file_location("backtest.ftmo_simulation", SIM_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["backtest.ftmo_simulation"] = _mod
_spec.loader.exec_module(_mod)

CSV_COLUMNS = _mod.CSV_COLUMNS
FTMOConfig = _mod.FTMOConfig
FTMOResult = _mod.FTMOResult
FTMOSimulation = _mod.FTMOSimulation
Trade = _mod.Trade


# ── Fixtures ───────────────────────────────────────────────────────────


def make_trade(
    days_ago: int = 0,
    pnl: float = 100.0,
    pair: str = "EURUSD",
    direction: str = "long",
    strategy: str = "test_strategy",
    hour: int = 10,
) -> Trade:
    """Helper: create a Trade with a timestamp relative to today."""
    ts = datetime.now() - timedelta(days=days_ago, hours=0)
    ts = ts.replace(hour=hour, minute=0, second=0, microsecond=0)
    return Trade(
        timestamp=ts,
        pair=pair,
        direction=direction,
        entry_price=1.1000,
        exit_price=1.1050,
        size=0.10,
        pnl=pnl,
        strategy=strategy,
    )


def make_trades(pnls: list[float], strategy: str = "test") -> list[Trade]:
    """Create a list of trades from P&L values (one per day)."""
    return [
        make_trade(days_ago=len(pnls) - i - 1, pnl=pnl, strategy=strategy)
        for i, pnl in enumerate(pnls)
    ]


@pytest.fixture
def default_config() -> FTMOConfig:
    return FTMOConfig()


@pytest.fixture
def default_sim(default_config: FTMOConfig) -> FTMOSimulation:
    return FTMOSimulation(default_config)


@pytest.fixture
def temp_csv() -> Path:
    """Create a temporary CSV with sample trade data."""
    tmpdir = tempfile.mkdtemp()
    csv_path = Path(tmpdir) / "test_wf_results.csv"

    rows = [
        # timestamp,pair,direction,entry_price,exit_price,size,pnl,strategy
        {
            "timestamp": "2026-06-01 10:00:00",
            "pair": "EURUSD",
            "direction": "long",
            "entry_price": "1.1000",
            "exit_price": "1.1050",
            "size": "0.10",
            "pnl": "50.0",
            "strategy": "srmr_plus",
        },
        {
            "timestamp": "2026-06-01 14:00:00",
            "pair": "GBPUSD",
            "direction": "short",
            "entry_price": "1.2800",
            "exit_price": "1.2750",
            "size": "0.10",
            "pnl": "50.0",
            "strategy": "killzone",
        },
        {
            "timestamp": "2026-06-02 10:00:00",
            "pair": "EURUSD",
            "direction": "long",
            "entry_price": "1.1050",
            "exit_price": "1.1100",
            "size": "0.10",
            "pnl": "50.0",
            "strategy": "srmr_plus",
        },
        {
            "timestamp": "2026-06-03 10:00:00",
            "pair": "USDJPY",
            "direction": "short",
            "entry_price": "150.00",
            "exit_price": "149.50",
            "size": "0.10",
            "pnl": "33.0",
            "strategy": "killzone",
        },
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path


# ── Rule enforcement tests ─────────────────────────────────────────────


class TestDailyLossLimit:
    """Tests for FTMO daily loss limit rule."""

    def test_daily_loss_triggers_violation(self, default_sim: FTMOSimulation):
        """A 5% daily loss should trigger a daily_loss violation."""
        # $10K account, 5% daily limit = $500
        # One trade losing $500 → exactly at limit
        trades = [make_trade(pnl=-500.0)]
        result = default_sim.run(trades)

        assert len(result.violations) >= 1
        assert result.violations[0]["rule"] == "daily_loss"
        assert not result.passed

    def test_daily_loss_below_limit_no_violation(
        self, default_sim: FTMOSimulation
    ):
        """A loss below 5% should not trigger a violation."""
        trades = [make_trade(pnl=-400.0)]  # 4% loss
        result = default_sim.run(trades)

        daily_violations = [
            v for v in result.violations if v["rule"] == "daily_loss"
        ]
        assert len(daily_violations) == 0

    def test_daily_loss_accumulates_across_trades(
        self, default_sim: FTMOSimulation
    ):
        """Multiple trades on the same day accumulate for daily loss."""
        # Two trades, same day, -$300 each = -$600 total → exceeds $500
        ts = datetime(2026, 6, 1, 10, 0, 0)
        trades = [
            Trade(ts, "EURUSD", "long", 1.10, 1.09, 0.10, -300.0, "strat"),
            Trade(
                ts.replace(hour=14), "GBPUSD", "short",
                1.28, 1.29, 0.10, -300.0, "strat",
            ),
        ]
        result = default_sim.run(trades)

        daily_violations = [
            v for v in result.violations if v["rule"] == "daily_loss"
        ]
        assert len(daily_violations) >= 1

    def test_daily_loss_resets_each_day(self, default_sim: FTMOSimulation):
        """Daily loss counter resets at the start of a new day."""
        # Day 1: -$400 (below limit). Day 2: -$400 (below limit, fresh start).
        trades = [
            make_trade(days_ago=1, pnl=-400.0),
            make_trade(days_ago=0, pnl=-400.0),
        ]
        result = default_sim.run(trades)

        daily_violations = [
            v for v in result.violations if v["rule"] == "daily_loss"
        ]
        assert len(daily_violations) == 0


class TestMaxDrawdown:
    """Tests for FTMO max drawdown rule."""

    def test_max_drawdown_triggers_violation(
        self, default_sim: FTMOSimulation
    ):
        """A 10% drawdown from peak should trigger max_drawdown violation."""
        # Earn $1000 first (peak = $11K), then lose within daily limit
        # each day until cumulative drawdown crosses 10%.
        # Day 1: +$1000 → equity $11K, peak $11K
        # Day 2: -$400 → equity $10.6K, daily loss $400 < 5% ($550), DD = $400
        # Day 3: -$700 → equity $9.9K, daily loss $700 > 5% ($530)?
        #   Actually $10.6K * 0.05 = $530. $700 > $530 → daily loss fires
        # Use stop_on_violation=False to isolate the max_drawdown check.
        trades = [
            make_trade(days_ago=2, pnl=1000.0),    # peak $11K
            make_trade(days_ago=1, pnl=-400.0),    # equity $10.6K, DD $400
            make_trade(days_ago=0, pnl=-700.0),    # equity $9.9K, DD $1100
        ]
        result = default_sim.run(trades, stop_on_violation=False)

        dd_violations = [
            v for v in result.violations if v["rule"] == "max_drawdown"
        ]
        assert len(dd_violations) >= 1
        assert not result.passed

    def test_drawdown_below_limit_no_violation(
        self, default_sim: FTMOSimulation
    ):
        """Drawdown below 10% should not trigger a violation."""
        trades = [
            make_trade(days_ago=1, pnl=500.0),    # peak $10.5K
            make_trade(days_ago=0, pnl=-200.0),    # DD $200 < 10% of $10.5K
        ]
        result = default_sim.run(trades)

        dd_violations = [
            v for v in result.violations if v["rule"] == "max_drawdown"
        ]
        assert len(dd_violations) == 0


class TestProfitTarget:
    """Tests for FTMO profit target rule."""

    def test_profit_target_reached(self, default_sim: FTMOSimulation):
        """Reaching +10% profit should mark simulation as passed."""
        # $10K + $1000 = $11K → exactly at 10% target
        trades = [make_trade(pnl=1000.0)]
        result = default_sim.run(trades)

        assert result.passed
        assert result.final_equity >= 11000.0

    def test_profit_below_target_not_passed(
        self, default_sim: FTMOSimulation
    ):
        """Profit below 10% should not pass."""
        trades = [make_trade(pnl=500.0)]   # 5%
        result = default_sim.run(trades)

        assert not result.passed


# ── Computation tests ──────────────────────────────────────────────────


class TestComputations:
    """Tests for P&L, equity curve, and drawdown computations."""

    def test_equity_curve_values(self, default_sim: FTMOSimulation):
        """Equity curve should reflect running equity after each trade."""
        trades = [
            make_trade(days_ago=2, pnl=100.0),
            make_trade(days_ago=1, pnl=200.0),
            make_trade(days_ago=0, pnl=-50.0),
        ]
        result = default_sim.run(trades)

        assert len(result.equity_curve) == 3
        assert result.equity_curve[0]["equity"] == 10100.0
        assert result.equity_curve[1]["equity"] == 10300.0
        assert result.equity_curve[2]["equity"] == 10250.0

    def test_daily_pnl_grouping(self, default_sim: FTMOSimulation):
        """Daily P&L should group trades by day."""
        ts = datetime(2026, 6, 1, 10, 0, 0)
        trades = [
            Trade(ts, "EURUSD", "long", 1.10, 1.11, 0.10, 100.0, "s"),
            Trade(
                ts.replace(hour=14), "GBPUSD", "short",
                1.28, 1.27, 0.10, 50.0, "s",
            ),
            Trade(
                ts.replace(day=2), "EURUSD", "long",
                1.11, 1.12, 0.10, 75.0, "s",
            ),
        ]
        result = default_sim.run(trades)

        assert "2026-06-01" in result.daily_pnl
        assert result.daily_pnl["2026-06-01"] == 150.0
        assert result.daily_pnl["2026-06-02"] == 75.0

    def test_max_drawdown_calculation(self, default_sim: FTMOSimulation):
        """Max drawdown should be peak-to-trough."""
        trades = [
            make_trade(days_ago=3, pnl=500.0),    # $10.5K
            make_trade(days_ago=2, pnl=500.0),    # $11K (peak)
            make_trade(days_ago=1, pnl=-300.0),    # $10.7K, DD=$300
            make_trade(days_ago=0, pnl=200.0),    # $10.9K
        ]
        result = default_sim.run(trades)

        # Peak was $11K, trough was $10.7K, DD = $300
        assert result.max_drawdown_abs == 300.0

    def test_final_equity(self, default_sim: FTMOSimulation):
        """Final equity should be starting balance plus sum of P&L."""
        trades = [
            make_trade(days_ago=2, pnl=100.0),
            make_trade(days_ago=1, pnl=-50.0),
            make_trade(days_ago=0, pnl=200.0),
        ]
        result = default_sim.run(trades)

        assert result.final_equity == 10250.0


# ── Per-strategy & blended tests ───────────────────────────────────────


class TestPerStrategy:
    """Tests for per-strategy and blended simulation."""

    def test_per_strategy_run(self, default_sim: FTMOSimulation):
        """Per-strategy run should separate results by strategy."""
        trades = [
            make_trade(days_ago=1, pnl=100.0, strategy="alpha"),
            make_trade(days_ago=0, pnl=200.0, strategy="beta"),
        ]
        results = default_sim.run_per_strategy(trades)

        assert "alpha" in results
        assert "beta" in results
        assert "blended" in results

        assert results["alpha"].final_equity == 10100.0
        assert results["beta"].final_equity == 10200.0
        assert results["blended"].final_equity == 10300.0

    def test_strategy_filter(self, default_sim: FTMOSimulation):
        """Strategy filter should only simulate matching trades."""
        trades = [
            make_trade(days_ago=1, pnl=100.0, strategy="alpha"),
            make_trade(days_ago=0, pnl=-50.0, strategy="beta"),
        ]
        result = default_sim.run(trades, strategy_filter="alpha")

        assert len(result.trade_log) == 1
        assert result.trade_log[0]["strategy"] == "alpha"
        assert result.strategy == "alpha"


# ── CSV loading tests ──────────────────────────────────────────────────


class TestCSVLoading:
    """Tests for CSV file loading."""

    def test_load_valid_csv(self, temp_csv: Path):
        """Loading a valid CSV should return sorted trades."""
        trades = FTMOSimulation.load_trades(temp_csv)

        assert len(trades) == 4
        assert trades[0].pair == "EURUSD"
        assert trades[0].strategy == "srmr_plus"
        assert trades[1].strategy == "killzone"

        # Verify chronological order
        assert trades[0].timestamp < trades[-1].timestamp

    def test_load_missing_file(self):
        """Loading a non-existent file should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            FTMOSimulation.load_trades("/nonexistent/path/to/file.csv")

    def test_load_missing_columns(self, tmp_path: Path):
        """CSV missing required columns should raise ValueError."""
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("a,b,c\n1,2,3\n")

        with pytest.raises(ValueError, match="missing required columns"):
            FTMOSimulation.load_trades(bad_csv)

    def test_load_empty_csv(self, tmp_path: Path):
        """Empty CSV (header only) should return empty list."""
        empty_csv = tmp_path / "empty.csv"
        with open(empty_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()

        trades = FTMOSimulation.load_trades(empty_csv)
        assert len(trades) == 0

    def test_malformed_rows_skipped(self, tmp_path: Path):
        """Malformed rows should be skipped with a warning."""
        csv_path = tmp_path / "malformed.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerow({
                "timestamp": "2026-06-01 10:00:00",
                "pair": "EURUSD",
                "direction": "long",
                "entry_price": "1.1000",
                "exit_price": "1.1050",
                "size": "0.10",
                "pnl": "50.0",
                "strategy": "test",
            })
            # Malformed: bad pnl
            writer.writerow({
                "timestamp": "2026-06-02 10:00:00",
                "pair": "EURUSD",
                "direction": "long",
                "entry_price": "1.1000",
                "exit_price": "1.1050",
                "size": "0.10",
                "pnl": "not_a_number",
                "strategy": "test",
            })

        trades = FTMOSimulation.load_trades(csv_path)
        assert len(trades) == 1  # only the valid row


# ── Edge case tests ────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_trades(self, default_sim: FTMOSimulation):
        """Empty trade list should return a non-passed result."""
        result = default_sim.run([])

        assert not result.passed
        assert result.final_equity == 10000.0
        assert len(result.violations) == 0

    def test_single_winning_trade(self, default_sim: FTMOSimulation):
        """Single winning trade below profit target."""
        result = default_sim.run([make_trade(pnl=100.0)])

        assert not result.passed  # $100 < $1000 target
        assert result.final_equity == 10100.0

    def test_boundary_daily_loss(self, default_sim: FTMOSimulation):
        """Daily loss exactly at boundary ($500) triggers violation."""
        trades = [make_trade(pnl=-500.0)]
        result = default_sim.run(trades)

        daily_violations = [
            v for v in result.violations if v["rule"] == "daily_loss"
        ]
        assert len(daily_violations) == 1

    def test_stop_on_violation_false(self, default_sim: FTMOSimulation):
        """With stop_on_violation=False, all trades are processed."""
        trades = [
            make_trade(days_ago=1, pnl=-600.0),  # triggers daily loss
            make_trade(days_ago=0, pnl=200.0),   # should still be processed
        ]
        result = default_sim.run(trades, stop_on_violation=False)

        assert len(result.trade_log) == 2  # both trades processed

    def test_stop_on_violation_true(self, default_sim: FTMOSimulation):
        """With stop_on_violation=True (default), trading stops after violation."""
        trades = [
            make_trade(days_ago=1, pnl=-600.0),  # triggers daily loss → stop
            make_trade(days_ago=0, pnl=200.0),   # should NOT be processed
        ]
        result = default_sim.run(trades, stop_on_violation=True)

        assert len(result.trade_log) == 1  # only first trade

    def test_to_dict_serializable(self, default_sim: FTMOSimulation):
        """Result.to_dict() should produce JSON-serializable output."""
        trades = [make_trade(pnl=100.0)]
        result = default_sim.run(trades)

        d = result.to_dict()
        # Should not raise
        json.dumps(d)

    def test_custom_config(self):
        """Custom config values should be respected."""
        config = FTMOConfig(
            account_size=5_000.0,
            daily_loss_limit_pct=0.04,
            max_drawdown_pct=0.08,
            profit_target_pct=0.06,
        )
        sim = FTMOSimulation(config)

        # 4% of $5K = $200 daily limit
        trades = [make_trade(pnl=-200.0)]
        result = sim.run(trades)

        daily_violations = [
            v for v in result.violations if v["rule"] == "daily_loss"
        ]
        assert len(daily_violations) == 1

        # 6% of $5K = $300 profit target
        result2 = sim.run([make_trade(pnl=300.0)])
        assert result2.passed
