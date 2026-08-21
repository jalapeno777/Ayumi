"""Focused tests for SimpleRSIThresholdStrategy.

Tests:
    1. RSI calculation correctness (Wilder's smoothing)
    2. BUY signal on oversold cross
    3. SELL signal on overbought cross
    4. No signal in neutral zone
    5. No signal when RSI is in zone but did not cross (no repeated fires)
    6. Insufficient-bars guard
    7. StrategySignal fields are well-formed

Run with:
    cd /home/TacoPants/projects/Ayumi && source .venv/bin/activate \\
      && python3 -m pytest tests/test_rsi_strategy.py -q --tb=short
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from core.types import Bar, MarketState, TradeDirection
from strategies.rsi_threshold import (
    RSIThresholdConfig,
    SimpleRSIThresholdStrategy,
    _rsi_wilder,
)


def _make_bars(closes: list[float], start: datetime | None = None) -> list[Bar]:
    """Build a list of Bar objects from a flat close-price list.

    Each bar has a small synthetic spread around the close. Default start time
    is 2023-01-02 00:00 UTC; bars are spaced 1 hour apart.
    """
    if start is None:
        start = datetime(2023, 1, 2, 0, 0)
    bars: list[Bar] = []
    for i, c in enumerate(closes):
        bars.append(
            Bar(
                time=start + timedelta(hours=i),
                open=c,
                high=c + 0.00010,
                low=c - 0.00010,
                close=c,
                volume=1000.0,
            )
        )
    return bars


def _alternating_then_drop_bars(
    base: float = 1.1000,
    alt_count: int = 16,
    alt_step: float = 0.00010,
    final_drop: float = 0.00300,
) -> list[Bar]:
    """Build bars: alternating +/- moves, then one big drop.

    The alternating pattern keeps prev_rsi near 50 (neutral). The final big
    drop pushes current_rsi below 20 → triggers a BUY cross exactly once.
    """
    closes = [base]
    for i in range(alt_count):
        if i % 2 == 0:
            closes.append(closes[-1] + alt_step)
        else:
            closes.append(closes[-1] - alt_step)
    closes.append(closes[-1] - final_drop)
    return _make_bars(closes)


def _alternating_then_rise_bars(
    base: float = 1.1000,
    alt_count: int = 16,
    alt_step: float = 0.00010,
    final_rise: float = 0.00300,
) -> list[Bar]:
    """Build bars: alternating +/- moves, then one big rise.

    The alternating pattern keeps prev_rsi near 50. The final big rise
    pushes current_rsi above 80 → triggers a SELL cross exactly once.
    """
    closes = [base]
    for i in range(alt_count):
        if i % 2 == 0:
            closes.append(closes[-1] + alt_step)
        else:
            closes.append(closes[-1] - alt_step)
    closes.append(closes[-1] + final_rise)
    return _make_bars(closes)


def _flat_bars(n: int = 30, base: float = 1.1000) -> list[Bar]:
    """Build N flat bars — RSI should hover near 50 with no signals."""
    return _make_bars([base] * n)


class TestRSICalculation(unittest.TestCase):
    """Verify the internal RSI calculation matches Wilder's smoothing spec."""

    def test_rsi_returns_none_until_enough_data(self):
        # Need rsi_period + 1 closes; 14 closes is not enough
        closes = [1.1000 + 0.0001 * i for i in range(14)]
        self.assertIsNone(_rsi_wilder(closes, 14))

    def test_rsi_returns_value_with_enough_data(self):
        # 15 closes is exactly rsi_period + 1 — should produce a value
        closes = [1.1000 + 0.0001 * i for i in range(15)]
        self.assertIsNotNone(_rsi_wilder(closes, 14))

    def test_rsi_all_gains_returns_100(self):
        """Monotonically rising closes → RSI = 100 (no losses)."""
        closes = [1.1000 + 0.0001 * i for i in range(20)]
        rsi = _rsi_wilder(closes, 14)
        self.assertIsNotNone(rsi)
        self.assertGreater(rsi, 99.0)

    def test_rsi_all_losses_returns_near_zero(self):
        """Monotonically falling closes → RSI near 0 (no gains)."""
        closes = [1.1100 - 0.0001 * i for i in range(20)]
        rsi = _rsi_wilder(closes, 14)
        self.assertIsNotNone(rsi)
        self.assertLess(rsi, 1.0)

    def test_rsi_bounded_0_100(self):
        """Random-ish price series: RSI must always be in [0, 100]."""
        closes = [1.1000 + 0.0001 * ((i * 7) % 13 - 6) for i in range(40)]
        rsi = _rsi_wilder(closes, 14)
        self.assertIsNotNone(rsi)
        self.assertGreaterEqual(rsi, 0.0)
        self.assertLessEqual(rsi, 100.0)


class TestStrategyInterface(unittest.TestCase):
    """Verify the class shape, defaults, and config wiring."""

    def test_default_name(self):
        s = SimpleRSIThresholdStrategy()
        self.assertEqual(s.name, "Simple RSI Threshold")

    def test_default_config(self):
        s = SimpleRSIThresholdStrategy()
        self.assertEqual(s.config.rsi_period, 14)
        self.assertEqual(s.config.oversold, 20.0)
        self.assertEqual(s.config.overbought, 80.0)

    def test_custom_config(self):
        cfg = RSIThresholdConfig(rsi_period=7, oversold=25, overbought=75)
        s = SimpleRSIThresholdStrategy(config=cfg)
        self.assertEqual(s.config.rsi_period, 7)
        self.assertEqual(s.config.oversold, 25.0)
        self.assertEqual(s.config.overbought, 75.0)


class TestSignalBehavior(unittest.TestCase):
    """Verify BUY / SELL / no-signal behavior on the live evaluate() path."""

    def test_returns_none_with_insufficient_bars(self):
        s = SimpleRSIThresholdStrategy()
        # 5 bars is way below rsi_period + 2 = 16
        state = MarketState(bars=_make_bars([1.1000] * 5))
        self.assertIsNone(s.evaluate(state))

    def test_no_signal_in_neutral_zone(self):
        """Flat bars → RSI hovers around 50 → no signal."""
        s = SimpleRSIThresholdStrategy()
        state = MarketState(bars=_flat_bars(n=30))
        self.assertIsNone(s.evaluate(state))

    def test_buy_signal_on_oversold_cross(self):
        """Alternating moves (prev_rsi ~50) + a big drop crosses below 20 → LONG."""
        s = SimpleRSIThresholdStrategy()
        bars = _alternating_then_drop_bars()
        state = MarketState(bars=bars)
        sig = s.evaluate(state)
        self.assertIsNotNone(sig, "expected a BUY signal on oversold cross")
        self.assertEqual(sig.direction, TradeDirection.LONG)
        self.assertGreater(sig.entry_price, 0.0)
        self.assertLess(sig.stop_loss, sig.entry_price)  # long SL is below entry
        # TP levels are above entry on a long
        self.assertGreater(sig.take_profit_1, sig.entry_price)
        self.assertGreater(sig.take_profit_2, sig.take_profit_1)
        self.assertGreater(sig.take_profit_3, sig.take_profit_2)
        # Confidence is bounded
        self.assertGreaterEqual(sig.confidence, 0.0)
        self.assertLessEqual(sig.confidence, 1.0)
        # Rationale mentions oversold
        self.assertIn("oversold", sig.rationale.lower())

    def test_sell_signal_on_overbought_cross(self):
        """Alternating moves (prev_rsi ~50) + a big rise crosses above 80 → SHORT."""
        s = SimpleRSIThresholdStrategy()
        bars = _alternating_then_rise_bars()
        state = MarketState(bars=bars)
        sig = s.evaluate(state)
        self.assertIsNotNone(sig, "expected a SELL signal on overbought cross")
        self.assertEqual(sig.direction, TradeDirection.SHORT)
        self.assertGreater(sig.entry_price, 0.0)
        self.assertGreater(sig.stop_loss, sig.entry_price)  # short SL is above entry
        # TP levels are below entry on a short
        self.assertLess(sig.take_profit_1, sig.entry_price)
        self.assertLess(sig.take_profit_2, sig.take_profit_1)
        self.assertLess(sig.take_profit_3, sig.take_profit_2)
        # Rationale mentions overbought
        self.assertIn("overbought", sig.rationale.lower())

    def test_no_repeat_fire_when_rsi_stays_in_zone(self):
        """Cross detection only — must NOT fire if RSI is already oversold on prev bar.

        If prev_rsi is already below the threshold and current_rsi is also below,
        the strategy must NOT fire a second time. Only a *cross* counts.
        """
        s = SimpleRSIThresholdStrategy()
        # Build bars where the entire window is one big drop (no flat prefix)
        # → prev_rsi will already be very low, so no cross on the latest bar.
        closes = [1.1000 - 0.0008 * i for i in range(30)]
        state = MarketState(bars=_make_bars(closes))
        sig = s.evaluate(state)
        # We cannot assert None unconditionally: with one big drop the first
        # oversold bar IS a cross (prev was above, current is below). So we
        # just confirm that, if a signal fires on bar N, it is NOT followed by
        # another on bar N+1 (which has prev_rsi already below the threshold).
        if sig is not None:
            state_next = MarketState(bars=_make_bars(closes + [closes[-1] - 0.0010]))
            sig_next = s.evaluate(state_next)
            self.assertIsNone(
                sig_next,
                "strategy must not re-fire while RSI remains in the oversold zone",
            )

    def test_signal_take_profit_math(self):
        """TP1/TP2/TP3 should be at 1R/2R/3R from entry, consistent with direction."""
        s = SimpleRSIThresholdStrategy()
        bars = _alternating_then_drop_bars()
        state = MarketState(bars=bars)
        sig = s.evaluate(state)
        self.assertIsNotNone(sig)
        risk = abs(sig.entry_price - sig.stop_loss)
        self.assertAlmostEqual(sig.take_profit_1, sig.entry_price + risk * 1.0, places=5)
        self.assertAlmostEqual(sig.take_profit_2, sig.entry_price + risk * 2.0, places=5)
        self.assertAlmostEqual(sig.take_profit_3, sig.entry_price + risk * 3.0, places=5)


if __name__ == "__main__":
    unittest.main()
