"""Tests for strategy_id propagation in cTraderSignalAdapter.

Verifies that the strategy name is correctly threaded through to
the CTraderTradeSignal.strategy_id field when signals are adapted.
"""

from unittest.mock import MagicMock


from adapters.ctrader.models import TradeDirection, CTraderTradeSignal
from adapters.ctrader.signal_adapter import cTraderSignalAdapter
from backtest.types import StrategySignal, TradeDirection as BacktestTradeDirection


# ── Helpers ────────────────────────────────────────────────────────────


def _make_strategy(name: str = "Session Breakout Asian"):
    """Create a mock ISignalStrategy with the given name."""
    strategy = MagicMock()
    strategy.name = name
    # Return a valid StrategySignal from evaluate()
    strategy.evaluate.return_value = StrategySignal(
        direction=BacktestTradeDirection.LONG,
        confidence=0.75,
        entry_price=1.08500,
        stop_loss=1.08200,
        take_profit_1=1.08800,
        take_profit_2=1.09100,
        take_profit_3=1.09400,
        rationale="Asian session breakout",
    )
    return strategy


def _make_market_state():
    return MagicMock()


# ── Tests ──────────────────────────────────────────────────────────────


class TestStrategyIdPropagation:
    """Verify strategy_id is set correctly on adapted TradeSignals."""

    def test_strategy_id_set_from_strategy_name(self):
        """The #1 bug: strategy_id should be the strategy name, not empty."""
        strategy = _make_strategy("Session Breakout Asian")
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="GBPUSD",
            blend_mode=True,
        )

        result = adapter.evaluate_and_trade(_make_market_state())

        assert result is not None
        assert isinstance(result, CTraderTradeSignal)
        assert result.strategy_id == "Session Breakout Asian"

    def test_strategy_id_not_empty(self):
        """strategy_id must never be the default empty string after adaptation."""
        strategy = _make_strategy("MyStrategy")
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="EURUSD",
            blend_mode=True,
        )

        result = adapter.evaluate_and_trade(_make_market_state())

        assert result is not None
        assert result.strategy_id != ""
        assert result.strategy_id == "MyStrategy"

    def test_strategy_id_preserved_for_different_strategies(self):
        """Different strategy names produce different strategy_ids."""
        for name in ["Scalper", "TTS", "SRMR+", "Session Breakout Asian"]:
            strategy = _make_strategy(name)
            adapter = cTraderSignalAdapter(
                paper_trader=MagicMock(),
                strategy=strategy,
                symbol="EURUSD",
                blend_mode=True,
            )
            result = adapter.evaluate_and_trade(_make_market_state())
            assert result is not None
            assert result.strategy_id == name

    def test_strategy_id_set_in_non_blend_mode(self):
        """strategy_id should also be set when blend_mode=False (paper trade path)."""
        strategy = _make_strategy("TestStrategy")
        mock_paper_trader = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.slippage_applied = 0.0001
        mock_result.rejection_reason = ""
        mock_paper_trader.process_signal.return_value = mock_result

        adapter = cTraderSignalAdapter(
            paper_trader=mock_paper_trader,
            strategy=strategy,
            symbol="EURUSD",
            blend_mode=False,
        )

        result = adapter.evaluate_and_trade(_make_market_state(), bid=1.085, ask=1.0851)

        assert result is not None
        assert result.strategy_id == "TestStrategy"
        # Verify the signal passed to paper_trader also has strategy_id
        mock_paper_trader.process_signal.assert_called_once()
        passed_signal = mock_paper_trader.process_signal.call_args[0][0]
        assert passed_signal.strategy_id == "TestStrategy"

    def test_signal_rejected_by_confidence_still_no_signal(self):
        """Low-confidence signals return None — no CTraderTradeSignal constructed."""
        strategy = MagicMock()
        strategy.name = "LowConfStrategy"
        strategy.evaluate.return_value = StrategySignal(
            direction=BacktestTradeDirection.LONG,
            confidence=0.10,  # Below default 0.50 threshold
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit_1=1.08800,
            take_profit_2=1.09100,
            take_profit_3=1.09400,
            rationale="Weak signal",
        )
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="EURUSD",
            blend_mode=True,
        )

        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is None

    def test_strategy_id_with_special_characters(self):
        """Strategy names with spaces/special chars are preserved as-is."""
        names = [
            "Session Breakout Asian",
            "MR+ Reversal (v2)",
            "ICT/SMC — H4 Context",
        ]
        for name in names:
            strategy = _make_strategy(name)
            adapter = cTraderSignalAdapter(
                paper_trader=MagicMock(),
                strategy=strategy,
                symbol="EURUSD",
                blend_mode=True,
            )
            result = adapter.evaluate_and_trade(_make_market_state())
            assert result is not None
            assert result.strategy_id == name


class TestTradeSignalModel:
    """Verify CTraderTradeSignal model defaults and field behavior."""

    def test_strategy_id_defaults_to_empty(self):
        """CTraderTradeSignal without explicit strategy_id defaults to empty string."""
        ts = CTraderTradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.085,
            stop_loss=1.082,
            take_profit_1=1.088,
            take_profit_2=1.091,
            take_profit_3=1.094,
            volume=0.1,
            confidence=0.8,
            rationale="test",
        )
        assert ts.strategy_id == ""

    def test_strategy_id_can_be_set(self):
        """CTraderTradeSignal accepts strategy_id in constructor."""
        ts = CTraderTradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.085,
            stop_loss=1.082,
            take_profit_1=1.088,
            take_profit_2=1.091,
            take_profit_3=1.094,
            volume=0.1,
            confidence=0.8,
            rationale="test",
            strategy_id="MyStrategy",
        )
        assert ts.strategy_id == "MyStrategy"
