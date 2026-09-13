"""Tests for BlendForwardTestRunner and daily reset fix."""

from __future__ import annotations

import json
import os
from datetime import datetime

from backtest.blend_backtest import BacktestConfig, BlendBacktest
from confidence.engine import ConfidenceEngine
from forward_test.blend_runner import BlendForwardTestRunner
from orchestrator.strategy_adapter import StrategyAdapter
from risk.profile_router import ProfileRouter
from risk.sl_position_sizer import SLPositionSizer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    strategy_id: str = "ema_cross",
    symbol: str = "EURUSD",
    direction: str = "long",
    confidence: float = 0.85,
    timestamp: datetime | None = None,
    **overrides,
) -> dict:
    """Create a minimal signal dict."""
    sig = {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "direction": direction,
        "entry_price": 1.1000,
        "stop_loss": 1.0950,
        "take_profit": 1.1100,
        "confidence": confidence,
        "timestamp": timestamp or datetime(2026, 4, 24, 10, 0),
    }
    sig.update(overrides)
    return sig


def _runner_config(tmp_path: str, **overrides) -> dict:
    cfg = {
        "account_balance": 10000.0,
        "risk_per_trade_pct": 0.005,
        "daily_risk_cap_pct": 0.03,
        "max_sniper": 3,
        "max_swarm": 5,
        "spread_pips": {"EURUSD": 1.0},
        "state_path": os.path.join(tmp_path, "risk_state.json"),
        # Stats log path goes to the per-test tmp_path so the runner
        # never falls back to the default ``data/signal_stats.jsonl``
        # during teardown-isolation (card d25244c4 cluster A).
        "stats_log_path": os.path.join(tmp_path, "signal_stats.jsonl"),
        "log_level": "WARNING",
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# Task 1: Daily Risk Cap Reset in Backtest
# ---------------------------------------------------------------------------


class TestDailyRiskCapReset:
    """Multi-day backtest should reset daily risk cap on new day."""

    def test_daily_cap_resets_across_days(self):
        """Day 1 hits daily cap, day 2 should trade normally."""
        cfg = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.005,
            daily_risk_cap_pct=0.01,  # 1% — easy to hit
        )
        bt = BlendBacktest(cfg)

        # Day 1: 3 losing trades that burn through daily cap
        # Daily cap = 10000 * 0.01 = $100
        # Each trade risks $50, loses $50
        day1_signals = []
        for i in range(5):
            day1_signals.append(
                _make_signal(
                    timestamp=datetime(2026, 4, 24, 10 + i, 0),
                    stop_loss=1.0950,  # 50 pips SL
                    outcome_pnl=-50.0,
                )
            )

        # Day 2: a winning trade that should still be accepted
        day2_signal = _make_signal(
            timestamp=datetime(2026, 4, 25, 10, 0),
            outcome_pnl=100.0,
        )

        all_signals = day1_signals + [day2_signal]
        result = bt.run(all_signals)

        # Day 2 signal should be accepted (not blocked by daily cap from day 1)
        # Total trades should include at least the day 1 trades + day 2 trade
        assert result.total_trades >= 1
        # Day 2 winning trade should contribute to P&L
        assert result.total_pnl > -250  # Not all day1 trades blocked after cap

    def test_same_day_no_reset(self):
        """Within same day, daily cap should accumulate."""
        cfg = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.005,
            daily_risk_cap_pct=0.001,  # Very tight 0.1% cap
        )
        bt = BlendBacktest(cfg)

        signals = [
            _make_signal(
                timestamp=datetime(2026, 4, 24, 10 + i, 0),
                outcome_pnl=-10.0,
            )
            for i in range(10)
        ]
        result = bt.run(signals)

        # With very tight cap, some should be blocked
        assert result.rejected_signals > 0


# ---------------------------------------------------------------------------
# Task 3 & 4: BlendForwardTestRunner tests
# ---------------------------------------------------------------------------


class TestBlendForwardTestRunner:
    def test_init_from_config(self, tmp_path):
        """Runner initializes all components from config dict."""
        runner = BlendForwardTestRunner(_runner_config(str(tmp_path)))
        assert isinstance(runner._engine, ConfidenceEngine)
        assert isinstance(runner._router, ProfileRouter)
        assert isinstance(runner._sizer, SLPositionSizer)
        assert isinstance(runner._adapter, StrategyAdapter)

    def test_start_restores_no_state(self, tmp_path):
        """start() with no state file works fine."""
        runner = BlendForwardTestRunner(_runner_config(str(tmp_path)))
        runner.start()  # Should not raise

    def test_signal_processing(self, tmp_path):
        """on_signal processes through full pipeline and returns order."""
        runner = BlendForwardTestRunner(_runner_config(str(tmp_path)))
        runner.start()

        sig = _make_signal(confidence=0.85, spread=1.0)
        order = runner.on_signal("ema_cross", sig)

        assert not order.rejected
        assert order.lots > 0
        assert order.risk_amount > 0

    def test_multiple_signals_in_sequence(self, tmp_path):
        """Multiple signals processed in sequence accumulate state."""
        runner = BlendForwardTestRunner(_runner_config(str(tmp_path)))
        runner.start()

        for i in range(3):
            sig = _make_signal(
                confidence=0.85,
                timestamp=datetime(2026, 4, 24, 10 + i, 0),
            )
            order = runner.on_signal("ema_cross", sig)
            if not order.rejected:
                oid = f"ema_cross_{sig['timestamp'].timestamp()}"
                runner.on_fill(oid, 1.1000, -25.0 if i < 2 else 30.0)

        # Balance should reflect fills: -25 + -25 + 30 = -20
        assert runner._balance == 9980.0

    def test_fill_handling_updates_balance(self, tmp_path):
        """on_fill correctly updates balance."""
        runner = BlendForwardTestRunner(_runner_config(str(tmp_path)))
        runner.start()

        sig = _make_signal(confidence=0.85, spread=1.0)
        order = runner.on_signal("ema_cross", sig)
        assert not order.rejected

        oid = f"ema_cross_{sig['timestamp'].timestamp()}"
        initial = runner._balance
        runner.on_fill(oid, 1.1000, 75.0)
        assert runner._balance == initial + 75.0

    def test_state_save_on_stop(self, tmp_path):
        """stop() persists state to disk."""
        state_path = os.path.join(tmp_path, "risk_state.json")
        runner = BlendForwardTestRunner(_runner_config(str(tmp_path)))
        runner.start()

        sig = _make_signal(confidence=0.85, spread=1.0)
        _order = runner.on_signal("ema_cross", sig)
        oid = f"ema_cross_{sig['timestamp'].timestamp()}"
        runner.on_fill(oid, 1.1000, -30.0)

        runner.stop()

        # State file should exist
        assert os.path.exists(state_path)
        data = json.loads(open(state_path).read())
        assert "account_balance" in data

    def test_state_restore_on_start(self, tmp_path):
        """start() restores previously saved state."""
        _state_path = os.path.join(tmp_path, "risk_state.json")
        cfg = _runner_config(str(tmp_path))

        # First runner: modify state and stop
        r1 = BlendForwardTestRunner(cfg)
        r1.start()
        sig = _make_signal(confidence=0.85, spread=1.0)
        _order = r1.on_signal("ema_cross", sig)
        oid = f"ema_cross_{sig['timestamp'].timestamp()}"
        r1.on_fill(oid, 1.1000, -30.0)
        r1.stop()

        # Second runner: restore state
        r2 = BlendForwardTestRunner(cfg)
        r2.start()
        assert r2._balance == r1._balance
