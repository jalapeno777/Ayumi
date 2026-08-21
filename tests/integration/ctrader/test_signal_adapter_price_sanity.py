"""Tests for the price-sanity guardrail in cTraderSignalAdapter.

Defends against data-feed / decoder bugs that emit physically impossible
entry prices (e.g. $4.1M for XAUUSD when gold trades at ~$3,300).

Triggered multiple times in production by SRMR+ and Session-Range Mean
Reversion on XAUUSD bars (forward_test-stderr.log: 2026-07-08..10).
"""

from unittest.mock import MagicMock

from adapters.ctrader.models import CTraderTradeSignal
from adapters.ctrader.signal_adapter import (
    _DEFAULT_SANE_PRICE_MAX,
    _max_reasonable_price,
    _price_exceeds_sanity_bound,
    cTraderSignalAdapter,
)
from backtest.engine import StrategySignal, TradeDirection

# ── Helpers ────────────────────────────────────────────────────────────


def _make_strategy(
    name: str,
    *,
    entry_price: float,
    stop_loss: float = None,
    take_profit_1: float = None,
    take_profit_2: float = None,
    take_profit_3: float = None,
    confidence: float = 0.75,
):
    """Create a mock ISignalStrategy that returns a StrategySignal with given prices.

    By default SL/TP are tight (1-3% from entry) so the bound test on entry_price
    is unambiguous. Tests that want to corrupt SL/TP must pass them explicitly.
    Tests at the bound (e.g. entry=5000) must pass explicit SL/TP below the bound.
    """
    strategy = MagicMock()
    strategy.name = name

    # When entry_price is the corrupted value (huge), SL/TP must also be huge
    # so the test of "entry corruption" matches production bug behavior.
    if entry_price > 10_000.0:
        default_sl = entry_price - 0.25
        default_tp1 = entry_price + 0.5
        default_tp2 = entry_price + 1.0
        default_tp3 = entry_price + 1.5
    else:
        # Sane SL/TP within the bound — fixed $1 increments from entry, never
        # exceeding sane-max of $5000 for XAUUSD.
        default_sl = entry_price - 1.0
        default_tp1 = entry_price + 1.0
        default_tp2 = entry_price + 2.0
        default_tp3 = entry_price + 3.0

    strategy.evaluate.return_value = StrategySignal(
        direction=TradeDirection.LONG,
        confidence=confidence,
        entry_price=entry_price,
        stop_loss=stop_loss if stop_loss is not None else default_sl,
        take_profit_1=take_profit_1 if take_profit_1 is not None else default_tp1,
        take_profit_2=take_profit_2 if take_profit_2 is not None else default_tp2,
        take_profit_3=take_profit_3 if take_profit_3 is not None else default_tp3,
        rationale="test",
    )
    return strategy


def _make_market_state():
    return MagicMock()


# ── Unit tests for the helper functions ────────────────────────────────


class TestMaxReasonablePrice:
    def test_known_symbols_have_tight_bounds(self):
        assert _max_reasonable_price("XAUUSD") == 5000.0
        assert _max_reasonable_price("EURUSD") == 2.0
        assert _max_reasonable_price("GBPUSD") == 3.0
        assert _max_reasonable_price("USDJPY") == 300.0
        assert _max_reasonable_price("AUDUSD") == 2.0

    def test_unknown_symbol_falls_back_to_default(self):
        assert _max_reasonable_price("BTCUSD") == _DEFAULT_SANE_PRICE_MAX
        assert _DEFAULT_SANE_PRICE_MAX == 10_000.0

    def test_case_insensitive(self):
        assert _max_reasonable_price("xauusd") == 5000.0
        assert _max_reasonable_price("XauUsd") == 5000.0

    def test_xauusd_bound_is_above_current_price_but_below_observed_bug(self):
        # Current gold ~$3,300, observed bug prices ~$4.1M
        assert _max_reasonable_price("XAUUSD") > 3300.0  # legit price passes
        assert _max_reasonable_price("XAUUSD") < 4_000_000.0  # bug price fails


class TestPriceExceedsSanityBound:
    def test_normal_xauusd_price_passes(self):
        assert _price_exceeds_sanity_bound("XAUUSD", 3300.50) is False

    def test_bug_xauusd_price_4_million_fails(self):
        assert _price_exceeds_sanity_bound("XAUUSD", 4_000_000.0) is True
        assert _price_exceeds_sanity_bound("XAUUSD", 4_126_545.0) is True

    def test_just_above_bound_fails(self):
        # Just above XAUUSD bound of 5000
        assert _price_exceeds_sanity_bound("XAUUSD", 5000.01) is True

    def test_just_at_bound_passes(self):
        # At the bound exactly (inclusive limit)
        assert _price_exceeds_sanity_bound("XAUUSD", 5000.0) is False

    def test_negative_fails(self):
        assert _price_exceeds_sanity_bound("XAUUSD", -1.0) is True
        assert _price_exceeds_sanity_bound("EURUSD", 0.0) is True

    def test_nan_fails(self):
        assert _price_exceeds_sanity_bound("XAUUSD", float("nan")) is True

    def test_none_fails(self):
        assert _price_exceeds_sanity_bound("XAUUSD", None) is True

    def test_non_numeric_fails(self):
        assert _price_exceeds_sanity_bound("XAUUSD", "not-a-number") is True


# ── Integration tests for cTraderSignalAdapter ─────────────────────────


class TestPriceSanityGuardrailRejects:
    """Verify the guardrail blocks signals with impossible entry/SL/TP prices."""

    def test_xauusd_entry_4_million_rejected(self):
        """The exact bug from the logs: XAUUSD entry=$4M+ must be dropped."""
        strategy = _make_strategy("SRMR+", entry_price=4_000_000.0)
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="XAUUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is None, f"Expected guardrail to reject $4M XAUUSD signal, got {result}"

    def test_xauusd_entry_observed_bug_price_rejected(self):
        """Exact observed log value: 4126545.00000 must be rejected."""
        strategy = _make_strategy("Session-Range Mean Reversion", entry_price=4_126_545.0)
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="XAUUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is None

    def test_xauusd_corrupted_sl_rejected(self):
        """Even if entry looks sane, a corrupted SL must be caught."""
        strategy = _make_strategy("SRMR+", entry_price=3300.0, stop_loss=3_300_250.0)  # SL inflated
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="XAUUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is None

    def test_xauusd_corrupted_tp_rejected(self):
        """A corrupted TP must be caught even if entry looks sane."""
        strategy = _make_strategy("SRMR+", entry_price=3300.0, take_profit_1=3_300_500.0)  # TP inflated
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="XAUUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is None

    def test_paper_trader_not_called_when_rejected_by_guardrail(self):
        """Critical: the guardrail must stop the signal BEFORE paper_trader runs."""
        strategy = _make_strategy("SRMR+", entry_price=4_000_000.0)
        mock_paper = MagicMock()
        adapter = cTraderSignalAdapter(
            paper_trader=mock_paper,
            strategy=strategy,
            symbol="XAUUSD",
            blend_mode=False,  # would call paper_trader if not blocked
        )
        result = adapter.evaluate_and_trade(_make_market_state(), bid=3300.0, ask=3300.1)
        assert result is None
        mock_paper.process_signal.assert_not_called()

    def test_eurusd_corrupted_entry_rejected(self):
        """Guardrail also catches EURUSD entry = $1M (would be 1000x off)."""
        strategy = _make_strategy("SRMR+", entry_price=1_000_000.0)
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="EURUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is None


class TestPriceSanityGuardrailAllows:
    """Verify the guardrail does NOT block legitimate signals."""

    def test_normal_xauusd_signal_passes(self):
        """Gold at ~$3300 should pass."""
        strategy = _make_strategy("SRMR+", entry_price=3300.50)
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="XAUUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is not None
        assert isinstance(result, CTraderTradeSignal)
        assert result.entry_price == 3300.50

    def test_normal_eurusd_signal_passes(self):
        strategy = _make_strategy(
            "SRMR+",
            entry_price=1.08500,
            stop_loss=1.0840,
            take_profit_1=1.0860,
            take_profit_2=1.0870,
            take_profit_3=1.0880,
        )
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="EURUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is not None
        assert result.entry_price == 1.08500

    def test_xauusd_at_bound_passes(self):
        """At the sane-max bound of $5000, signal should still be allowed."""
        strategy = _make_strategy(
            "SRMR+",
            entry_price=5000.0,
            stop_loss=4999.0,
            take_profit_1=4999.5,
            take_profit_2=4999.6,
            take_profit_3=4999.7,
        )
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="XAUUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is not None
        assert result.entry_price == 5000.0

    def test_xauusd_just_below_bound_passes(self):
        strategy = _make_strategy(
            "SRMR+",
            entry_price=4999.99,
            stop_loss=4999.0,
            take_profit_1=4999.5,
            take_profit_2=4999.6,
            take_profit_3=4999.7,
        )
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="XAUUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is not None


class TestGuardrailPriorityVsOtherGates:
    """Guardrail runs after confidence threshold but before paper_trader."""

    def test_low_confidence_signal_returns_none_even_if_price_corrupt(self):
        """Low confidence + corrupt price: returns None, no error."""
        strategy = _make_strategy("SRMR+", entry_price=4_000_000.0, confidence=0.10)  # Below 0.50 threshold
        adapter = cTraderSignalAdapter(
            paper_trader=MagicMock(),
            strategy=strategy,
            symbol="XAUUSD",
            blend_mode=True,
        )
        result = adapter.evaluate_and_trade(_make_market_state())
        assert result is None  # confidence gate (or guardrail) blocked it
