"""Tests for Kelly Criterion integration in MultiStrategyBacktestEngine.

Covers:
- kelly_criterion helper function with known inputs/outputs
- _compute_kelly_multiplier for typical and edge-case trade histories
- Edge cases: zero trades, negative/zero win rate, extreme win rates,
  breakeven trades, fractional Kelly bounds
- KellyConfig defaults and field validation
"""
from __future__ import annotations

import pytest
from datetime import datetime

from backtest.engine import Bar, ExitReason, SimulatedTrade, TradeDirection, TradeOutcome
from backtest.multi_strategy_engine import KellyConfig, MultiStrategyBacktestEngine
from quant.position_sizing import kelly_criterion


def _make_trade(
    outcome: TradeOutcome,
    profit_loss: float,
    direction: TradeDirection = TradeDirection.LONG,
) -> SimulatedTrade:
    """Build a minimal SimulatedTrade for Kelly calculations."""
    return SimulatedTrade(
        entry_bar_index=0,
        exit_bar_index=1,
        direction=direction,
        entry_price=1.1000,
        stop_loss=1.0900,
        take_profit_1=1.1100,
        take_profit_2=1.1200,
        take_profit_3=1.1300,
        exit_price=1.1100,
        lot_size=1.0,
        risk_amount=100.0,
        pips=0.0,
        profit_loss=profit_loss,
        outcome=outcome,
        exit_reason=ExitReason.TAKE_PROFIT_1,
        entry_time=datetime(2024, 1, 1, 0, 0),
        exit_time=datetime(2024, 1, 1, 1, 0),
        confidence_score=0.75,
        confluence_count=1,
        rationale="test",
    )


# ---------------------------------------------------------------------------
# kelly_criterion helper
# ---------------------------------------------------------------------------

def test_kelly_criterion_known_inputs():
    """Classic example: W=0.6, b=2 => full Kelly=0.4, half=0.2."""
    result = kelly_criterion(win_rate=0.6, avg_win=200.0, avg_loss=100.0)
    assert result == pytest.approx(0.2)


def test_kelly_criterion_zero_avg_loss():
    """Zero average loss is degenerate; function returns 0.0."""
    assert kelly_criterion(win_rate=0.6, avg_win=200.0, avg_loss=0.0) == 0.0


def test_kelly_criterion_negative_edge():
    """Negative-expectancy bet clips to 0.0."""
    assert kelly_criterion(win_rate=0.4, avg_win=100.0, avg_loss=200.0) == 0.0


def test_kelly_criterion_neutral_edge():
    """Exact breakeven returns 0.0."""
    assert kelly_criterion(win_rate=0.5, avg_win=100.0, avg_loss=100.0) == 0.0


def test_kelly_criterion_caps_half_kelly():
    """Helper halves the raw Kelly fraction and caps it at 0.5.

    For W=0.9, b=100: raw Kelly = (100*0.9 - 0.1)/100 = 0.89,
    half-Kelly = 0.445, but the implementation returns ~0.4495
    due to min(raw/2, 0.5) ordering. Either way it must not exceed 0.5.
    """
    result = kelly_criterion(win_rate=0.9, avg_win=1000.0, avg_loss=10.0)
    assert 0.0 < result <= 0.5
    assert result == pytest.approx(0.4495)


# ---------------------------------------------------------------------------
# _compute_kelly_multiplier engine method
# ---------------------------------------------------------------------------

def test_compute_kelly_multiplier_with_known_trades():
    """Known trade history maps to predictable multiplier via normalization."""
    engine = MultiStrategyBacktestEngine.__new__(MultiStrategyBacktestEngine)
    engine._kelly_config = KellyConfig(enabled=True, min_trades=0, rolling_window=50)

    wins = [_make_trade(TradeOutcome.WIN, 200.0) for _ in range(6)]
    losses = [_make_trade(TradeOutcome.LOSS, -100.0) for _ in range(4)]
    trades = wins + losses

    mult = engine._compute_kelly_multiplier(trades)
    # kelly_criterion(0.6, 200, 100) ~= 0.2 -> normalized to ~= 0.4
    assert mult == pytest.approx(kelly_criterion(0.6, 200.0, 100.0) / 0.5)


def test_compute_kelly_multiplier_zero_trades():
    """Empty history -> no edge -> multiplier 0.0."""
    engine = MultiStrategyBacktestEngine.__new__(MultiStrategyBacktestEngine)
    engine._kelly_config = KellyConfig(enabled=True, min_trades=0, rolling_window=50)
    assert engine._compute_kelly_multiplier([]) == 0.0


def test_compute_kelly_multiplier_all_losses():
    """Win rate 0 -> multiplier 0.0."""
    engine = MultiStrategyBacktestEngine.__new__(MultiStrategyBacktestEngine)
    engine._kelly_config = KellyConfig(enabled=True, min_trades=0, rolling_window=50)
    trades = [_make_trade(TradeOutcome.LOSS, -100.0) for _ in range(10)]
    assert engine._compute_kelly_multiplier(trades) == 0.0


def test_compute_kelly_multiplier_negative_win_rate_via_zero_wins():
    """No wins means 0 win rate and 0.0 multiplier."""
    engine = MultiStrategyBacktestEngine.__new__(MultiStrategyBacktestEngine)
    engine._kelly_config = KellyConfig(enabled=True, min_trades=0, rolling_window=50)
    trades = [_make_trade(TradeOutcome.LOSS, -50.0) for _ in range(5)]
    assert engine._compute_kelly_multiplier(trades) == 0.0


def test_compute_kelly_multiplier_extreme_high_win_rate():
    """Very high win rate produces normalized multiplier above 0.5 but capped at 1.0."""
    engine = MultiStrategyBacktestEngine.__new__(MultiStrategyBacktestEngine)
    engine._kelly_config = KellyConfig(enabled=True, min_trades=0, rolling_window=50)
    wins = [_make_trade(TradeOutcome.WIN, 500.0) for _ in range(19)]
    losses = [_make_trade(TradeOutcome.LOSS, -100.0)]
    trades = wins + losses
    mult = engine._compute_kelly_multiplier(trades)
    assert 0.0 < mult <= 1.0
    # Full Kelly for these numbers: b=5, W=0.95 -> (5*0.95 - 0.05)/5 = 0.94
    # The engine returns kelly_frac/0.5 capped at 1.0.
    raw = kelly_criterion(19 / 20, 500.0, 100.0)
    assert mult == pytest.approx(min(raw / 0.5, 1.0))


def test_compute_kelly_multiplier_breakeven_trades_affect_win_rate():
    """Breakeven trades count in the recent-window denominator (n).

    This means they dilute win_rate: 2 wins / 1 loss / 5 BE across 8 trades
    gives win_rate=2/8=0.25, which flips the Kelly edge to 0.
    """
    engine = MultiStrategyBacktestEngine.__new__(MultiStrategyBacktestEngine)
    engine._kelly_config = KellyConfig(enabled=True, min_trades=0, rolling_window=50)
    wins = [_make_trade(TradeOutcome.WIN, 200.0) for _ in range(2)]
    losses = [_make_trade(TradeOutcome.LOSS, -100.0)]
    breakevens = [_make_trade(TradeOutcome.BREAKEVEN, 0.0) for _ in range(5)]
    trades = wins + losses + breakevens
    mult = engine._compute_kelly_multiplier(trades)
    # With BE included in n: win_rate=0.25, b=2 -> kelly = (2*0.25 - 0.75)/2 = -0.125 -> 0
    assert mult == 0.0


def test_compute_kelly_multiplier_breakeven_only_history():
    """A history containing only breakeven trades returns 0.0."""
    engine = MultiStrategyBacktestEngine.__new__(MultiStrategyBacktestEngine)
    engine._kelly_config = KellyConfig(enabled=True, min_trades=0, rolling_window=50)
    trades = [_make_trade(TradeOutcome.BREAKEVEN, 0.0) for _ in range(10)]
    assert engine._compute_kelly_multiplier(trades) == 0.0


def test_compute_kelly_multiplier_rolling_window():
    """Only the most recent `rolling_window` trades influence the estimate."""
    engine = MultiStrategyBacktestEngine.__new__(MultiStrategyBacktestEngine)
    engine._kelly_config = KellyConfig(enabled=True, min_trades=0, rolling_window=10)
    old_wins = [_make_trade(TradeOutcome.WIN, 1000.0) for _ in range(50)]
    recent_losses = [_make_trade(TradeOutcome.LOSS, -100.0) for _ in range(10)]
    trades = old_wins + recent_losses
    mult = engine._compute_kelly_multiplier(trades)
    # Recent window is all losses -> 0 win rate
    assert mult == 0.0


# ---------------------------------------------------------------------------
# KellyConfig validation
# ---------------------------------------------------------------------------

def test_kelly_config_defaults():
    """Default config is enabled with conservative thresholds."""
    cfg = KellyConfig()
    assert cfg.enabled is True
    assert cfg.min_trades == 20
    assert cfg.rolling_window == 50


def test_kelly_config_fractional_bounds():
    """Config accepts fractional bounds and preserves them."""
    cfg = KellyConfig(enabled=True, min_trades=10, rolling_window=100)
    assert cfg.min_trades == 10
    assert cfg.rolling_window == 100


if __name__ == "__main__":
    pytest.main([__file__, "-q", "--tb=short"])
