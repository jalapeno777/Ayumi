import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, TradeDirection
from backtest.strategies import (
    DEFAULT_LOD_HOD_STOP_BUFFER_PIPS,
    MomentumBreakoutStrategy,
    apply_lod_hod_stop_buffer,
)


def _make_bars_same_day(n=10, base_price=1.1000, day_high_extra=0.001, day_low_extra=0.001):
    bars = []
    dt = datetime(2024, 6, 1, 0, 0)
    for i in range(n):
        price = base_price + (i - n // 2) * 0.00005
        bars.append(
            Bar(
                time=dt,
                open=price,
                high=price + day_high_extra if i == n // 2 else price + 0.0001,
                low=price - day_low_extra if i == n // 2 else price - 0.0001,
                close=price,
                volume=1000,
            )
        )
        dt += timedelta(minutes=15)
    return bars


class TestApplyLodHodStopBuffer(unittest.TestCase):
    def test_long_stop_pushed_below_lod_with_buffer(self):
        bars = _make_bars_same_day(30, base_price=1.1000)
        day_low = min(b.low for b in bars)
        buffer_pips = 8.0
        stop_too_close = day_low - 0.0002
        result = apply_lod_hod_stop_buffer(stop_too_close, TradeDirection.LONG, bars, buffer_pips)
        expected = day_low - buffer_pips * 0.0001
        self.assertAlmostEqual(result, expected, places=6)

    def test_long_stop_already_below_lod_buffer_unchanged(self):
        bars = _make_bars_same_day(30, base_price=1.1000)
        day_low = min(b.low for b in bars)
        buffer_pips = 8.0
        stop_far_below = day_low - 0.0020
        result = apply_lod_hod_stop_buffer(stop_far_below, TradeDirection.LONG, bars, buffer_pips)
        self.assertAlmostEqual(result, stop_far_below, places=6)

    def test_short_stop_pushed_above_hod_with_buffer(self):
        bars = _make_bars_same_day(30, base_price=1.1000)
        day_high = max(b.high for b in bars)
        buffer_pips = 8.0
        stop_too_close = day_high + 0.0002
        result = apply_lod_hod_stop_buffer(stop_too_close, TradeDirection.SHORT, bars, buffer_pips)
        expected = day_high + buffer_pips * 0.0001
        self.assertAlmostEqual(result, expected, places=6)

    def test_short_stop_already_above_hod_buffer_unchanged(self):
        bars = _make_bars_same_day(30, base_price=1.1000)
        day_high = max(b.high for b in bars)
        buffer_pips = 8.0
        stop_far_above = day_high + 0.0020
        result = apply_lod_hod_stop_buffer(stop_far_above, TradeDirection.SHORT, bars, buffer_pips)
        self.assertAlmostEqual(result, stop_far_above, places=6)

    def test_zero_buffer_returns_original_stop(self):
        bars = _make_bars_same_day(30, base_price=1.1000)
        stop = 1.0950
        result = apply_lod_hod_stop_buffer(stop, TradeDirection.LONG, bars, buffer_pips=0.0)
        self.assertAlmostEqual(result, stop, places=6)

    def test_negative_buffer_returns_original_stop(self):
        bars = _make_bars_same_day(30, base_price=1.1000)
        stop = 1.0950
        result = apply_lod_hod_stop_buffer(stop, TradeDirection.LONG, bars, buffer_pips=-5.0)
        self.assertAlmostEqual(result, stop, places=6)

    def test_empty_bars_returns_original_stop(self):
        result = apply_lod_hod_stop_buffer(1.0950, TradeDirection.LONG, [], 8.0)
        self.assertAlmostEqual(result, 1.0950, places=6)

    def test_jpy_pair_pip_value(self):
        bars = _make_bars_same_day(30, base_price=150.00)
        day_low = min(b.low for b in bars)
        buffer_pips = 8.0
        stop_too_close = day_low - 0.02
        result = apply_lod_hod_stop_buffer(stop_too_close, TradeDirection.LONG, bars, buffer_pips)
        expected = day_low - buffer_pips * 0.01
        self.assertAlmostEqual(result, expected, places=4)

    def test_default_buffer_is_eight_pips(self):
        self.assertEqual(DEFAULT_LOD_HOD_STOP_BUFFER_PIPS, 8.0)


class TestMomentumBreakoutLODHODBuffer(unittest.TestCase):
    def test_default_buffer_pips(self):
        strat = MomentumBreakoutStrategy()
        self.assertEqual(strat.lod_hod_stop_buffer_pips, 8.0)

    def test_custom_buffer_pips(self):
        strat = MomentumBreakoutStrategy(lod_hod_stop_buffer_pips=12.0)
        self.assertEqual(strat.lod_hod_stop_buffer_pips, 12.0)

    def test_buffer_zero_disables_effect(self):
        strat = MomentumBreakoutStrategy(lod_hod_stop_buffer_pips=0.0)
        self.assertEqual(strat.lod_hod_stop_buffer_pips, 0.0)


if __name__ == "__main__":
    unittest.main()
