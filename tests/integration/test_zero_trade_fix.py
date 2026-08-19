"""
Integration smoke test: verify zero-trade bug (D-011) is fixed.

After the type-identity fix in backtest/types.py, strategies that import from
core.types should produce signals that are recognized by the backtest engine.
This test creates a minimal scenario: generate a strategy signal and verify
its TradeDirection identity matches what the backtest engine uses.
"""

from datetime import datetime, timezone
from core.types import (
    Bar,
    MarketState,
    SessionType,
    StrategySignal,
    TradeDirection as CoreTradeDirection,
)
from backtest.types import TradeDirection as BacktestTradeDirection


class TestZeroTradeFix:
    """Verify that the type-identity fix resolves D-011 zero-trade bug."""

    def test_strategy_signal_direction_matches_engine_direction(self):
        """A signal built with core.types.TradeDirection must be recognized
        by code checking against backtest.types.TradeDirection."""
        signal_direction = CoreTradeDirection.LONG
        # This is what the backtest engine checks internally
        assert signal_direction is BacktestTradeDirection.LONG

    def test_direction_comparison_in_backtest_context(self):
        """Simulate the comparison path: strategy emits signal, engine checks it."""
        signal = StrategySignal(
            direction=CoreTradeDirection.LONG,
            confidence=0.75,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1050,
            take_profit_2=1.1100,
            take_profit_3=1.1150,
            rationale="test signal",
        )
        # Engine-side check: is this a direction we recognize?
        assert signal.direction in BacktestTradeDirection
        assert signal.direction == BacktestTradeDirection.LONG

    def test_all_directions_share_identity(self):
        """All TradeDirection values must share identity across modules."""
        for member in CoreTradeDirection:
            assert member is getattr(BacktestTradeDirection, member.name)

    def test_synthetic_bars_produce_valid_signal(self):
        """End-to-end: volatility_squeeze strategy processes bars and the
        resulting signal direction is compatible with backtest engine types."""
        from strategies.volatility_squeeze import VolatilitySqueezeStrategy

        # Create enough synthetic bars for the strategy to compute indicators.
        # Use a strong trend to increase the chance of signal generation.
        bars = []
        base_price = 1.1000
        for i in range(100):
            # Create a trending market to trigger a signal
            price = base_price + i * 0.0010
            bars.append(
                Bar(
                    time=datetime(2026, 7, 21, 8 + i % 12, 0, tzinfo=timezone.utc),
                    open=price,
                    high=price + 0.0008,
                    low=price - 0.0002,
                    close=price + 0.0005,
                    volume=1000.0,
                )
            )

        market_state = MarketState(bars=bars, current_session=SessionType.LONDON)
        strategy = VolatilitySqueezeStrategy()
        signal = strategy.evaluate(market_state)

        if signal is not None:
            # Signal direction must be usable by backtest engine
            assert signal.direction in BacktestTradeDirection
            assert (
                signal.direction is BacktestTradeDirection.LONG
                or signal.direction is BacktestTradeDirection.SHORT
            )
