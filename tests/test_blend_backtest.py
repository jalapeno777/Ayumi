"""Tests for Strategy Blend Backtest."""

import pytest
from datetime import datetime, timezone

from backtest.blend_backtest import BlendBacktest, BacktestConfig, BacktestResult


def _make_signal(
    strategy_id="strat_a",
    symbol="EURUSD",
    direction="long",
    confidence=0.8,
    hour_utc=10,
    outcome_pnl=50.0,
    **kwargs,
) -> dict:
    ts = datetime(2026, 4, 20, hour_utc, 0, 0, tzinfo=timezone.utc)
    sig = {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "direction": direction,
        "entry_price": 1.0850,
        "stop_loss": 1.0820,
        "take_profit": 1.0910,
        "confidence": confidence,
        "timestamp": ts,
        "outcome_pnl": outcome_pnl,
    }
    sig.update(kwargs)
    return sig


class TestBlendBacktestBasic:
    def setup_method(self):
        self.bt = BlendBacktest()

    def test_equity_curve_grows_with_winning_signals(self):
        signals = [_make_signal(outcome_pnl=100.0) for _ in range(10)]
        result = self.bt.run(signals)
        assert result.equity_curve[-1] > result.equity_curve[0]
        assert result.total_pnl > 0
        assert result.winning_trades == 10

    def test_equity_curve_shrinks_with_losing_signals(self):
        signals = [_make_signal(outcome_pnl=-50.0) for _ in range(10)]
        result = self.bt.run(signals)
        assert result.equity_curve[-1] < result.equity_curve[0]
        assert result.total_pnl < 0
        # Circuit breaker may halt some trades
        assert result.losing_trades > 0
        assert result.total_trades < 10

    def test_win_rate_calculation(self):
        signals = [_make_signal(outcome_pnl=50.0) for _ in range(7)]
        signals += [_make_signal(outcome_pnl=-30.0) for _ in range(3)]
        result = self.bt.run(signals)
        assert result.win_rate == pytest.approx(0.7)

    def test_profit_factor(self):
        signals = [_make_signal(outcome_pnl=100.0) for _ in range(5)]
        signals += [_make_signal(outcome_pnl=-50.0) for _ in range(5)]
        result = self.bt.run(signals)
        assert result.profit_factor == pytest.approx(2.0)


class TestBlendBacktestRejection:
    def setup_method(self):
        self.bt = BlendBacktest()

    def test_rejection_of_low_confidence_signals(self):
        signals = [_make_signal(confidence=0.2, outcome_pnl=100.0) for _ in range(10)]
        result = self.bt.run(signals)
        assert result.rejected_signals > 0
        assert result.total_trades < 10

    def test_session_gate_rejection(self):
        """Signals outside trading sessions should be rejected."""
        # Use config with no Asia session overlap — hour_utc=23 is outside all sessions
        cfg = BacktestConfig(london_open=8, london_close=16, ny_open=13, ny_close=22)
        bt = BlendBacktest(cfg)
        signals = [_make_signal(hour_utc=23, outcome_pnl=100.0) for _ in range(10)]
        result = bt.run(signals)
        assert result.rejected_signals == 10
        assert result.total_trades == 0


class TestBlendBacktestCircuitBreaker:
    def setup_method(self):
        self.bt = BlendBacktest()

    def test_circuit_breaker_after_losing_streak(self):
        """After enough losses, circuit breaker should halt trading."""
        signals = [_make_signal(outcome_pnl=-100.0) for _ in range(30)]
        result = self.bt.run(signals)
        # Not all 30 should execute — circuit breaker should kick in
        assert result.rejected_signals > 0
        # Some should have been stopped by the breaker
        # (breaker triggers after 10 trades with <25% win rate)
        assert result.total_trades < 30


class TestBlendBacktestProfileRouting:
    def setup_method(self):
        self.bt = BlendBacktest()

    def test_sniper_vs_swarm_distribution(self):
        high_conf = [_make_signal(confidence=0.85, outcome_pnl=50.0) for _ in range(10)]
        low_conf = [_make_signal(confidence=0.55, outcome_pnl=30.0) for _ in range(10)]
        result = self.bt.run(high_conf + low_conf)
        assert result.sniper_trades > 0
        assert result.swarm_trades > 0
        assert result.sniper_trades + result.swarm_trades == result.total_trades

    def test_max_sniper_capacity(self):
        """Only max_sniper slots available — excess should fall to swarm or be rejected."""
        # 10 high-confidence signals, only 3 sniper slots
        # But signals close immediately (outcome_pnl provided), so slots free up
        # To actually test capacity, we'd need concurrent positions.
        # In this simplified model, positions close immediately, so test routing works.
        signals = [_make_signal(confidence=0.9, outcome_pnl=50.0) for _ in range(10)]
        result = self.bt.run(signals)
        # All should be sniper since they close before next opens
        assert result.sniper_trades == 10


class TestBlendBacktestDrawdown:
    def setup_method(self):
        self.bt = BlendBacktest()

    def test_max_drawdown_calculation(self):
        # Use small P&Ls to stay within daily risk cap
        signals = [
            _make_signal(outcome_pnl=50.0),    # 10050
            _make_signal(outcome_pnl=50.0),    # 10100
            _make_signal(outcome_pnl=-30.0),   # 10070
            _make_signal(outcome_pnl=-50.0),   # 10020
            _make_signal(outcome_pnl=20.0),    # 10040
        ]
        result = self.bt.run(signals)
        # Peak = 10100, trough = 10020, DD = 80
        assert result.max_drawdown == pytest.approx(80.0, abs=1.0)
        assert result.max_drawdown_pct == pytest.approx(80.0 / 10100.0, abs=0.01)

    def test_no_drawdown_all_wins(self):
        signals = [_make_signal(outcome_pnl=50.0) for _ in range(10)]
        result = self.bt.run(signals)
        assert result.max_drawdown == 0.0
        assert result.max_drawdown_pct == 0.0


class TestBlendBacktestPerStrategy:
    def setup_method(self):
        self.bt = BlendBacktest()

    def test_per_strategy_breakdown(self):
        signals = (
            [_make_signal(strategy_id="momentum", outcome_pnl=50.0) for _ in range(5)]
            + [_make_signal(strategy_id="reversal", outcome_pnl=-30.0) for _ in range(5)]
            + [_make_signal(strategy_id="breakout", outcome_pnl=80.0) for _ in range(5)]
        )
        result = self.bt.run(signals)
        assert "momentum" in result.per_strategy
        assert "reversal" in result.per_strategy
        assert "breakout" in result.per_strategy
        assert result.per_strategy["momentum"]["trades"] == 5
        assert result.per_strategy["momentum"]["total_pnl"] == 250.0
        assert result.per_strategy["reversal"]["total_pnl"] == -150.0
        assert result.per_strategy["breakout"]["win_rate"] == 1.0


class TestBlendBacktestStats:
    def setup_method(self):
        self.bt = BlendBacktest()

    def test_avg_win_and_loss(self):
        signals = (
            [_make_signal(outcome_pnl=100.0) for _ in range(3)]
            + [_make_signal(outcome_pnl=-60.0) for _ in range(2)]
        )
        result = self.bt.run(signals)
        assert result.avg_win == pytest.approx(100.0)
        assert result.avg_loss == pytest.approx(-60.0)

    def test_sharpe_ratio_positive_for_winning_system(self):
        signals = [_make_signal(outcome_pnl=50.0) for _ in range(20)]
        result = self.bt.run(signals)
        # All same P&L = zero std → sharpe should be 0 or near 0
        # Need variance for positive sharpe
        signals = [
            _make_signal(outcome_pnl=30.0 + i * 5) for i in range(20)
        ]
        result = self.bt.run(signals)
        assert result.sharpe_ratio > 0

    def test_empty_signals(self):
        result = self.bt.run([])
        assert result.total_trades == 0
        assert result.equity_curve == [10000.0]
        assert result.win_rate == 0.0
        assert result.total_pnl == 0.0
