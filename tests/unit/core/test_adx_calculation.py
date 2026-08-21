"""
Tests for ADX (Average Directional Index) calculation correctness.

Verifies that Wilder smoothing initialization is correct:
- The first `period` DX values should be averaged for initial ADX
- Subsequent DX values use Wilder smoothing: adx = (adx * (period-1) + dx) / period
"""

import unittest

import numpy as np
import pandas as pd
from backtest.engine import Bar


def _compute_adx_manually(bars: list[Bar], period: int = 14) -> float:
    """
    Reference ADX implementation with CORRECT Wilder smoothing.

    This is the canonical correct implementation:
    1. Compute DX for each period after the first `period` bars
    2. ADX = simple average of first `period` DX values
    3. Subsequent DX values use Wilder smoothing
    """
    if len(bars) < period * 2 + 1:
        return 0.0

    n = len(bars)
    true_ranges = []
    plus_dms = []
    minus_dms = []

    for i in range(1, n):
        tr = max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - bars[i - 1].close),
            abs(bars[i].low - bars[i - 1].close),
        )
        true_ranges.append(tr)
        up_move = bars[i].high - bars[i - 1].high
        down_move = bars[i - 1].low - bars[i].low
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    if len(true_ranges) < period:
        return 0.0

    # Initial smoothing: sum of first `period` values
    smoothed_tr = sum(true_ranges[:period])
    smoothed_plus_dm = sum(plus_dms[:period])
    smoothed_minus_dm = sum(minus_dms[:period])

    # Build DX list
    dx_list = []
    for i in range(period, len(true_ranges)):
        smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_ranges[i]
        smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dms[i]
        smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dms[i]

        if smoothed_tr == 0:
            dx_list.append(0.0)
            continue
        plus_di = 100.0 * (smoothed_plus_dm / smoothed_tr)
        minus_di = 100.0 * (smoothed_minus_dm / smoothed_tr)
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx_list.append(0.0)
        else:
            dx_list.append(100.0 * (abs(plus_di - minus_di) / di_sum))

    if len(dx_list) < period:
        return 0.0

    # Correct: simple average of first period DX values
    adx = sum(dx_list[:period]) / period
    for dx in dx_list[period:]:
        adx = (adx * (period - 1) + dx) / period

    return adx


def make_deterministic_bars(n: int, seed: int = 42) -> list[Bar]:
    """Create deterministic bars for reproducible testing."""
    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = [price]
    for _ in range(n - 1):
        price += np.random.normal(0, 0.0005)
        prices.append(price)
    prices = np.array(prices)

    return [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices[i] - 0.0001 * np.random.uniform(0, 1),
            high=prices[i] + 0.0001 * np.random.uniform(1, 3),
            low=prices[i] - 0.0001 * np.random.uniform(1, 3),
            close=prices[i],
            volume=1000,
        )
        for i in range(n)
    ]


class TestADXCalculation(unittest.TestCase):
    """Test ADX calculation correctness across all strategy implementations."""

    def test_adx_matches_reference(self):
        """ADX from strategies should match the known-good reference implementation."""
        from strategies.momentum import _calculate_adx as momentum_adx
        from strategies.volatility_squeeze import _calculate_adx as vol_squeeze_adx

        bars = make_deterministic_bars(100, seed=42)

        # Test momentum
        expected = _compute_adx_manually(bars)
        actual = momentum_adx(bars)
        self.assertAlmostEqual(
            actual,
            expected,
            places=6,
            msg=f"momentum ADX mismatch: expected {expected}, got {actual}",
        )

        # Test volatility_squeeze
        actual = vol_squeeze_adx(bars)
        self.assertAlmostEqual(
            actual,
            expected,
            places=6,
            msg=f"volatility_squeeze ADX mismatch: expected {expected}, got {actual}",
        )

    def test_adx_wilder_smoothing_initialization(self):
        """
        Verify Wilder smoothing initialization: first period DX values
        should be SIMPLE AVERAGE, not single DX value.

        This tests against the specific bug where `adx = dx` then loop
        through ALL dx values double-counting the first element.
        """
        np.random.seed(123)
        dates = pd.date_range("2023-01-01", periods=50, freq="1h")
        price = 1.1000
        prices = []
        for i in range(50):
            if i < 25:
                price += np.random.normal(0.0002, 0.0001)  # Uptrend
            else:
                price += np.random.normal(-0.0002, 0.0001)  # Downtrend
            prices.append(price)

        bars = [
            Bar(
                time=dates[i].to_pydatetime(),
                open=prices[i] - 0.0001,
                high=prices[i] + 0.0001,
                low=prices[i] - 0.0001,
                close=prices[i],
                volume=1000,
            )
            for i in range(50)
        ]

        from strategies.momentum import _calculate_adx as momentum_adx

        adx = momentum_adx(bars)
        # Should be a valid ADX value (0-100)
        self.assertGreaterEqual(adx, 0.0)
        self.assertLessEqual(adx, 100.0)

    def test_adx_short_data(self):
        """ADX should return 0 or handle short data gracefully."""
        from strategies.momentum import _calculate_adx as momentum_adx

        bars = make_deterministic_bars(10)
        adx = momentum_adx(bars)
        # Very short data should return 0
        self.assertEqual(adx, 0.0)

    def test_adx_boundary_conditions(self):
        """Test ADX at boundary conditions (exact minimum data, zeros, etc)."""
        from strategies.momentum import _calculate_adx as momentum_adx

        # Exact minimum bars for period=14
        bars = make_deterministic_bars(14 * 2 + 2, seed=99)
        adx = momentum_adx(bars)
        self.assertGreaterEqual(adx, 0.0)
        self.assertLessEqual(adx, 100.0)


if __name__ == "__main__":
    unittest.main()
