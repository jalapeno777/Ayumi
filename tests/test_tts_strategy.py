"""Tests for TTSStrategy signal engine adapter — HTF, session, and quality gates."""

import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, MarketState
from backtest.strategies.tts_strategy import TTSStrategy


def _make_bars(n: int, base_price: float = 1.1000, trend: float = 0.0) -> list[Bar]:
    """Generate synthetic M15 bars."""
    bars = []
    price = base_price
    for i in range(n):
        change = trend * 0.0001 + 0.0002 * (
            1 if i % 3 == 0 else -1 if i % 3 == 1 else 0
        )
        high = price + abs(change) + 0.0001
        low = price - abs(change) - 0.0001
        close = price + change
        bars.append(
            Bar(
                time=datetime(2024, 6, 1, 7, 0) + timedelta(minutes=15 * i),
                open=price,
                high=high,
                low=low,
                close=close,
                volume=1000,
            )
        )
        price = close
    return bars


class TestTTSStrategyHTF(unittest.TestCase):
    """Test HTF state computation."""

    def test_htf_state_returned(self):
        """HTF state should be computed without errors."""
        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        bars = _make_bars(100, trend=1.0)  # uptrend
        htf = strategy._compute_htf_state(bars)
        self.assertIsNotNone(htf)
        # With trend, slope should be non-zero
        self.assertGreater(htf.ema_slope, 0)

    def test_htf_trending_up(self):
        """Uptrend should produce positive ema_slope."""
        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        bars = _make_bars(700, base_price=1.1000, trend=2.0)  # strong uptrend
        htf = strategy._compute_htf_state(bars)
        self.assertGreater(htf.ema_slope, 0)

    def test_htf_trending_down(self):
        """Downtrend should produce negative ema_slope."""
        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        bars = _make_bars(700, base_price=1.2000, trend=-2.0)  # strong downtrend
        htf = strategy._compute_htf_state(bars)
        self.assertLess(htf.ema_slope, 0)

    def test_htf_short_bars(self):
        """Should return NEUTRAL for insufficient data."""
        from signal_engine.data_types import HTFPhase

        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        bars = _make_bars(10)
        htf = strategy._compute_htf_state(bars)
        self.assertEqual(htf.phase, HTFPhase.NEUTRAL)


class TestTTSStrategySession(unittest.TestCase):
    """Test session filtering."""

    def test_outside_session_no_crash(self):
        """Should not crash when outside trading sessions."""
        strategy = TTSStrategy("EURUSD", min_confidence=0.15, min_quality_score=0.15)
        # 3am UTC = outside all sessions
        bars = _make_bars(60)
        bars[-1] = Bar(
            time=datetime(2024, 6, 1, 3, 0),
            open=1.1,
            high=1.1005,
            low=1.0995,
            close=1.1001,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        # Just verify no crash — result may be None (outside session)
        # or may be None (no pattern detected)
        self.assertIsNone(result)


class TestTTSStrategyInit(unittest.TestCase):
    """Test initialization and parameter defaults."""

    def test_default_params(self):
        strategy = TTSStrategy("EURUSD")
        self.assertEqual(strategy.min_confidence, 0.20)
        self.assertEqual(strategy.min_quality_score, 0.25)
        self.assertEqual(strategy.HISTORY_BARS, 50)

    def test_custom_params(self):
        strategy = TTSStrategy("EURUSD", min_confidence=0.40, min_quality_score=0.50)
        self.assertEqual(strategy.min_confidence, 0.40)
        self.assertEqual(strategy.min_quality_score, 0.50)

    def test_reset(self):
        strategy = TTSStrategy("EURUSD")
        strategy._last_bar_idx = 42
        strategy.reset()
        self.assertEqual(strategy._last_bar_idx, -1)


class TestTTSStrategyEMA(unittest.TestCase):
    """Test EMA computation."""

    def test_ema_short_data(self):
        """EMA with insufficient data should return NaN-filled array."""
        import numpy as np

        data = np.array([1.0, 2.0, 3.0])
        result = TTSStrategy._ema(data, 10)
        self.assertTrue(np.all(np.isnan(result)))

    def test_ema_computation(self):
        """EMA should produce valid values for sufficient data."""
        import numpy as np

        data = np.array([float(i) for i in range(100)])
        result = TTSStrategy._ema(data, 10)
        # First 10 values should be NaN
        self.assertTrue(np.isnan(result[:10]).all())
        # Remaining values should be valid
        self.assertFalse(np.isnan(result[10:]).any())


if __name__ == "__main__":
    unittest.main()
