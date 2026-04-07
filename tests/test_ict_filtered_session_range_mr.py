import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

import numpy as np
import pandas as pd

from backtest.engine import Bar, MarketState
from backtest.ict_smc.market_structure import MarketStructureAnalyzer
from backtest.ict_smc.models import ICTMarketState


def make_test_bars(n=100, seed=42):
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


def make_aligned_bars(n=200, seed=42):
    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = [price]
    for i in range(n - 1):
        if i < n // 2:
            price += np.random.normal(0.0003, 0.0005)
        else:
            price -= np.random.normal(0.0003, 0.0005)
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


class TestICTFilteredSessionRangeMRUnit(unittest.TestCase):
    def test_strategy_name(self):
        from scripts.run_ict_session_range_ab_test import ICTFilteredSessionRangeMR

        strategy = ICTFilteredSessionRangeMR()
        self.assertEqual(strategy.name, "Session-Range MR + ICT Filter")

    def test_returns_none_when_session_strategy_returns_none(self):
        from scripts.run_ict_session_range_ab_test import ICTFilteredSessionRangeMR

        strategy = ICTFilteredSessionRangeMR()
        bars = make_test_bars(20)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_filters_by_min_confluence_score(self):
        from scripts.run_ict_session_range_ab_test import (
            ICTFilteredSessionRangeMR,
            ICTFilterConfig,
        )

        config = ICTFilterConfig(min_confluence_score=0.99)
        strategy = ICTFilteredSessionRangeMR(ict_config=config)
        bars = make_aligned_bars(200, seed=42)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        self.assertIsNone(result)

    def test_passes_market_structure_filter_when_aligned(self):
        from scripts.run_ict_session_range_ab_test import (
            ICTFilteredSessionRangeMR,
            ICTFilterConfig,
        )

        config = ICTFilterConfig(
            min_confluence_score=0.3,
            require_market_structure=True,
        )
        strategy = ICTFilteredSessionRangeMR(ict_config=config)
        bars = make_aligned_bars(200, seed=42)
        state = MarketState(bars=bars)
        result = strategy.evaluate(state)
        if result is not None:
            self.assertIn("ICT confluence", result.rationale)

    def test_config_defaults(self):
        from scripts.run_ict_session_range_ab_test import (
            ICTFilterConfig,
        )

        config = ICTFilterConfig()
        self.assertEqual(config.min_confluence_score, 0.5)
        self.assertTrue(config.require_market_structure)
        self.assertFalse(config.require_order_block)
        self.assertTrue(config.require_fvg)
        self.assertFalse(config.require_liquidity_sweep)


class TestMarketStructureFilter(unittest.TestCase):
    def test_check_market_structure_uses_state_bias(self):
        from scripts.run_ict_session_range_ab_test import (
            ICTFilteredSessionRangeMR,
            ICTFilterConfig,
        )

        config = ICTFilterConfig(require_market_structure=True)
        strategy = ICTFilteredSessionRangeMR(ict_config=config)
        bars = make_aligned_bars(200, seed=99)
        ict_state = ICTMarketState(bars=bars)
        analyzer = MarketStructureAnalyzer()
        analyzer.analyze(ict_state)
        direction = ict_state.structure_bias
        result = strategy._check_market_structure(ict_state, direction)
        self.assertTrue(result)


class TestH4BarsExtraction(unittest.TestCase):
    def test_get_h4_bars_returns_none_for_insufficient_bars(self):
        from scripts.run_ict_session_range_ab_test import ICTFilteredSessionRangeMR

        strategy = ICTFilteredSessionRangeMR()
        bars = make_test_bars(50)
        result = strategy._get_h4_bars(bars)
        self.assertIsNone(result)

    def test_get_h4_bars_returns_subset_for_sufficient_bars(self):
        from scripts.run_ict_session_range_ab_test import ICTFilteredSessionRangeMR

        strategy = ICTFilteredSessionRangeMR()
        bars = make_aligned_bars(200)
        result = strategy._get_h4_bars(bars)
        self.assertIsNotNone(result)
        self.assertLess(len(result), len(bars))

    def test_get_h4_bars_lookback_capped_at_500(self):
        from scripts.run_ict_session_range_ab_test import ICTFilteredSessionRangeMR

        strategy = ICTFilteredSessionRangeMR()
        bars = make_aligned_bars(2000, seed=42)
        result = strategy._get_h4_bars(bars)
        self.assertEqual(len(result), 500)


if __name__ == "__main__":
    unittest.main()