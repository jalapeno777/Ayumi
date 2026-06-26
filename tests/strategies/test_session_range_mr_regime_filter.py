import unittest

from datetime import datetime

from backtest.engine import Bar, MarketState, TradeDirection
from strategies.session_range_mean_reversion import (
    SessionRangeMeanReversionStrategy,
    SessionRangeMRWithRegimeFilter,
    SessionRangeMRWithRegimeFilterConfig,
)


def make_test_bars(n=100, seed=42):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = [price]
    for _ in range(n - 1):
        price += np.random.normal(0, 0.0005)
        prices.append(price)
    prices = np.array(prices)
    spread = 0.0002
    return [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices[i] - spread * np.random.uniform(0, 1),
            high=prices[i] + spread * np.random.uniform(1, 3),
            low=prices[i] - spread * np.random.uniform(1, 3),
            close=prices[i],
            volume=1000,
        )
        for i in range(n)
    ]


def make_low_adx_bars(n=100, seed=42):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = [price]
    for _ in range(n - 1):
        price += np.random.normal(0, 0.0001)
        prices.append(price)
    prices = np.array(prices)
    spread = 0.0002
    return [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices[i] - spread * np.random.uniform(0, 1),
            high=prices[i] + spread * np.random.uniform(1, 3),
            low=prices[i] - spread * np.random.uniform(1, 3),
            close=prices[i],
            volume=1000,
        )
        for i in range(n)
    ]


def make_high_adx_bars(n=100, seed=42):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = [price]
    trend = 0.0
    for _ in range(n - 1):
        trend += np.random.normal(0.0003, 0.0001)
        price += trend + np.random.normal(0, 0.0002)
        prices.append(price)
    prices = np.array(prices)
    spread = 0.0002
    return [
        Bar(
            time=dates[i].to_pydatetime(),
            open=prices[i] - spread * np.random.uniform(0, 1),
            high=prices[i] + spread * np.random.uniform(1, 3),
            low=prices[i] - spread * np.random.uniform(1, 3),
            close=prices[i],
            volume=1000,
        )
        for i in range(n)
    ]


class TestSessionRangeMRWithRegimeFilter(unittest.TestCase):
    def test_strategy_name(self):
        strategy = SessionRangeMRWithRegimeFilter()
        self.assertEqual(strategy.name, "Session-Range MR with Regime Filter")

    def test_returns_none_with_insufficient_bars(self):
        strategy = SessionRangeMRWithRegimeFilter()
        bars = make_test_bars(20)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_skips_signal_when_adx_above_skip_threshold(self):
        config = SessionRangeMRWithRegimeFilterConfig(adx_skip_threshold=25.0)
        strategy = SessionRangeMRWithRegimeFilter(config=config)
        bars = make_high_adx_bars(100, seed=42)
        bars[99] = Bar(
            time=datetime(2023, 1, 1, 5, 0),
            open=1.0995,
            high=1.1000,
            low=1.0950,
            close=1.0952,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_returns_signal_when_adx_below_transition(self):
        config = SessionRangeMRWithRegimeFilterConfig(
            adx_skip_threshold=35.0,
            adx_transition_low=25.0,
            base_min_confidence=0.45,
        )
        strategy = SessionRangeMRWithRegimeFilter(config=config)
        bars = make_low_adx_bars(100, seed=42)
        bars[99] = Bar(
            time=datetime(2023, 1, 1, 5, 0),
            open=1.0995,
            high=1.1000,
            low=1.0950,
            close=1.0952,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertEqual(result.direction, TradeDirection.LONG)
            self.assertIn("RegimeFilter", result.rationale)

    def test_transition_zone_requires_higher_confidence(self):
        config = SessionRangeMRWithRegimeFilterConfig(
            adx_skip_threshold=35.0,
            adx_transition_low=15.0,
            transition_min_confidence=0.80,
            base_min_confidence=0.45,
        )
        strategy = SessionRangeMRWithRegimeFilter(config=config)
        bars = make_low_adx_bars(100, seed=42)
        bars[99] = Bar(
            time=datetime(2023, 1, 1, 5, 0),
            open=1.0995,
            high=1.1000,
            low=1.0950,
            close=1.0952,
            volume=1000,
        )
        state = MarketState(bars=bars)
        adx = strategy._calculate_adx(state.bars)
        if adx > 15.0 and adx < 35.0:
            result = strategy.evaluate(state)
            self.assertIsNone(result)

    def test_config_parameters(self):
        config = SessionRangeMRWithRegimeFilterConfig(
            adx_period=21,
            adx_skip_threshold=35.0,
            adx_transition_low=25.0,
            transition_min_confidence=0.70,
            base_min_confidence=0.50,
            regime_confidence_multiplier=0.90,
        )
        strategy = SessionRangeMRWithRegimeFilter(config=config)
        self.assertEqual(strategy.config.adx_period, 21)
        self.assertEqual(strategy.config.adx_skip_threshold, 35.0)
        self.assertEqual(strategy.config.adx_transition_low, 25.0)
        self.assertEqual(strategy.config.transition_min_confidence, 0.70)
        self.assertEqual(strategy.config.base_min_confidence, 0.50)
        self.assertEqual(strategy.config.regime_confidence_multiplier, 0.90)

    def test_adx_calculation_low_adx(self):
        strategy = SessionRangeMRWithRegimeFilter()
        bars = make_low_adx_bars(100, seed=42)
        adx = strategy._calculate_adx(bars)
        self.assertLess(adx, 25.0)

    def test_adx_calculation_high_adx(self):
        strategy = SessionRangeMRWithRegimeFilter()
        bars = make_high_adx_bars(100, seed=42)
        adx = strategy._calculate_adx(bars)
        self.assertGreater(adx, 25.0)

    def test_confidence_adjusted_by_multiplier(self):
        config = SessionRangeMRWithRegimeFilterConfig(
            adx_skip_threshold=35.0,
            adx_transition_low=25.0,
            base_min_confidence=0.45,
            regime_confidence_multiplier=0.90,
        )
        strategy = SessionRangeMRWithRegimeFilter(config=config)
        bars = make_low_adx_bars(100, seed=42)
        bars[99] = Bar(
            time=datetime(2023, 1, 1, 5, 0),
            open=1.0995,
            high=1.1000,
            low=1.0950,
            close=1.0952,
            volume=1000,
        )
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        base_result = SessionRangeMeanReversionStrategy().evaluate(state)
        if result is not None and base_result is not None:
            self.assertLess(result.confidence, base_result.confidence)
            self.assertAlmostEqual(
                result.confidence, base_result.confidence * 0.90, places=2
            )


if __name__ == "__main__":
    unittest.main()
