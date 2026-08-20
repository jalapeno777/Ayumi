"""Integration tests for Kelly Criterion wiring in MultiStrategyBacktestEngine."""

from unittest.mock import MagicMock  # noqa: I001
from datetime import datetime, timezone

from backtest.multi_strategy_engine import (
    KellyConfig,
    MultiStrategyBacktestEngine,
)
from backtest.engine import (
    BacktestConfig,
    Bar,
    ExitReason,
    SimulatedTrade,
    StrategySignal,
    TradeDirection,
    TradeOutcome,
)
from backtest.strategies import ISignalStrategy


def _make_config(**overrides) -> BacktestConfig:
    defaults = dict(
        starting_balance=10_000,
        leverage=100,
        spread_pips=0.0,
        slippage_pips=0.0,
        commission_per_lot=0.0,
        swap_per_lot_per_day=0.0,
        min_bars_before_signal=10,
        min_confidence=0.5,
        max_open_trades=1,
        max_total_drawdown_pct=0.25,
        max_daily_drawdown_pct=0.05,
        round_trip_spread=False,
    )
    defaults.update(overrides)
    return BacktestConfig(**defaults)


def _bar(i: int, price: float, high: float = 0.0, low: float = 0.0) -> Bar:
    return Bar(
        time=datetime(2026, 1, 1, 12, i, tzinfo=timezone.utc),
        open=price,
        high=high or price + 0.001,
        low=low or price - 0.001,
        close=price,
        volume=1000,
    )


class FixedSignalStrategy(ISignalStrategy):
    """Emits a signal on every evaluate() call."""

    name = "fixed"

    def __init__(self, direction=TradeDirection.LONG, confidence=0.8):
        self._direction = direction
        self._confidence = confidence

    def evaluate(self, state):
        entry = 1.1000
        if self._direction == TradeDirection.LONG:
            sl, tp1, tp2, tp3 = 1.0950, 1.1050, 1.1100, 1.1150
        else:
            sl, tp1, tp2, tp3 = 1.1050, 1.0950, 1.0900, 1.0850
        return StrategySignal(
            direction=self._direction,
            confidence=self._confidence,
            entry_price=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            rationale="test signal",
        )


class TestWarmUp:
    """First min_trades closed trades get no Kelly adjustment (multiplier=1.0)."""

    def test_warmup_no_adjustment(self):
        """Before min_trades closed trades, Kelly should not suppress or shrink."""
        cfg = _make_config()
        engine = MultiStrategyBacktestEngine(
            config=cfg,
            strategies=[FixedSignalStrategy()],
            kelly_config=KellyConfig(enabled=True, min_trades=20),
        )
        # Simulate 15 closed trades manually
        for i in range(15):
            t = SimulatedTrade(
                entry_bar_index=i,
                exit_bar_index=i + 1,
                direction=TradeDirection.LONG,
                entry_price=1.1000,
                stop_loss=1.0950,
                take_profit_1=1.1050,
                take_profit_2=1.1100,
                take_profit_3=1.1150,
                exit_price=1.1030,
                lot_size=0.01,
                risk_amount=50,
                pips=30,
                profit_loss=30.0,
                outcome=TradeOutcome.WIN,
                exit_reason=ExitReason.TAKE_PROFIT_1,
                entry_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
                exit_time=datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc),
                confidence_score=0.8,
                confluence_count=1,
                rationale="test",
            )
            engine._kelly_closed_trades.append(t)

        # With 15 trades < 20 min_trades, Kelly should NOT activate
        signal = FixedSignalStrategy().evaluate(MagicMock())
        bar = _bar(20, 1.1000)
        trade = engine._open_trade(signal, bar, 20)
        assert trade is not None, "Trade should open during warm-up"
        assert engine._kelly_skips == 0


class TestKellyActivation:
    """After min_trades, multiplier should differ from 1.0 based on edge."""

    def test_kelly_reduces_lot_size_with_poor_edge(self):
        """With low win rate after warm-up, Kelly should reduce lot size."""
        cfg = _make_config()
        engine = MultiStrategyBacktestEngine(
            config=cfg,
            strategies=[FixedSignalStrategy()],
            kelly_config=KellyConfig(enabled=True, min_trades=20),
        )
        # 25 trades: only 5 wins (20% win rate), avg_win=30, avg_loss=-50
        for i in range(25):
            outcome = TradeOutcome.WIN if i % 5 == 0 else TradeOutcome.LOSS
            pnl = 30.0 if outcome == TradeOutcome.WIN else -50.0
            t = SimulatedTrade(
                entry_bar_index=i,
                exit_bar_index=i + 1,
                direction=TradeDirection.LONG,
                entry_price=1.1000,
                stop_loss=1.0950,
                take_profit_1=1.1050,
                take_profit_2=1.1100,
                take_profit_3=1.1150,
                exit_price=1.1030,
                lot_size=0.01,
                risk_amount=50,
                pips=30 if outcome == TradeOutcome.WIN else -50,
                profit_loss=pnl,
                outcome=outcome,
                exit_reason=ExitReason.TAKE_PROFIT_1 if outcome == TradeOutcome.WIN else ExitReason.STOP_LOSS,
                entry_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
                exit_time=datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc),
                confidence_score=0.8,
                confluence_count=1,
                rationale="test",
            )
            engine._kelly_closed_trades.append(t)

        # Compute multiplier — should be < 1.0 for poor edge
        mult = engine._compute_kelly_multiplier(engine._kelly_closed_trades)
        assert mult < 1.0, f"Expected multiplier < 1.0 for 20% win rate, got {mult}"


class TestKellySuppression:
    """When Kelly returns 0, trades should be skipped entirely."""

    def test_zero_edge_skips_trade(self):
        """With no winning trades, Kelly should suppress new trades."""
        cfg = _make_config()
        engine = MultiStrategyBacktestEngine(
            config=cfg,
            strategies=[FixedSignalStrategy()],
            kelly_config=KellyConfig(enabled=True, min_trades=20),
        )
        # 25 trades: all losses → win_rate=0 → kelly=0 → suppress
        for i in range(25):
            t = SimulatedTrade(
                entry_bar_index=i,
                exit_bar_index=i + 1,
                direction=TradeDirection.LONG,
                entry_price=1.1000,
                stop_loss=1.0950,
                take_profit_1=1.1050,
                take_profit_2=1.1100,
                take_profit_3=1.1150,
                exit_price=1.0950,
                lot_size=0.01,
                risk_amount=50,
                pips=-50,
                profit_loss=-50.0,
                outcome=TradeOutcome.LOSS,
                exit_reason=ExitReason.STOP_LOSS,
                entry_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
                exit_time=datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc),
                confidence_score=0.8,
                confluence_count=1,
                rationale="test",
            )
            engine._kelly_closed_trades.append(t)

        signal = FixedSignalStrategy().evaluate(MagicMock())
        bar = _bar(30, 1.1000)
        trade = engine._open_trade(signal, bar, 30)
        assert trade is None, "Trade should be suppressed when Kelly=0"
        assert engine._kelly_skips == 1


class TestDisabledConfig:
    """Disabled KellyConfig should produce same results as no config."""

    def test_disabled_same_as_no_config(self):
        """With enabled=False, Kelly should never activate."""
        cfg = _make_config()
        engine = MultiStrategyBacktestEngine(
            config=cfg,
            strategies=[FixedSignalStrategy()],
            kelly_config=KellyConfig(enabled=False, min_trades=20),
        )
        # Add all-loss trades that would suppress if enabled
        for i in range(25):
            t = SimulatedTrade(
                entry_bar_index=i,
                exit_bar_index=i + 1,
                direction=TradeDirection.LONG,
                entry_price=1.1000,
                stop_loss=1.0950,
                take_profit_1=1.1050,
                take_profit_2=1.1100,
                take_profit_3=1.1150,
                exit_price=1.0950,
                lot_size=0.01,
                risk_amount=50,
                pips=-50,
                profit_loss=-50.0,
                outcome=TradeOutcome.LOSS,
                exit_reason=ExitReason.STOP_LOSS,
                entry_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
                exit_time=datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc),
                confidence_score=0.8,
                confluence_count=1,
                rationale="test",
            )
            engine._kelly_closed_trades.append(t)

        signal = FixedSignalStrategy().evaluate(MagicMock())
        bar = _bar(30, 1.1000)
        trade = engine._open_trade(signal, bar, 30)
        assert trade is not None, "Trade should open when Kelly is disabled"
        assert engine._kelly_skips == 0
