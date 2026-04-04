import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.engine import BacktestConfig, Bar, TradeDirection
from backtest.strategies import MACrossStrategy, RSIStrategy, ROCMStrategy
from backtest.ict_smc.strategy_adapter import ICTSMCStrategy
from backtest.amalgamation import (
    AmalgamatedBacktestEngine,
    AmalgamationConfig,
    ComponentExtractor,
    VotingMethod,
    INDICATOR_STRATEGY_PATTERNS,
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


class TestAmalgamationICTOnly(unittest.TestCase):
    def test_indicator_strategies_filtered(self):
        config = AmalgamationConfig(ict_smc_only=True)
        self.assertTrue(config.is_indicator_strategy("MA Crossover"))
        self.assertTrue(config.is_indicator_strategy("RSI Divergence"))
        self.assertTrue(config.is_indicator_strategy("Momentum ROC"))
        self.assertTrue(config.is_indicator_strategy("Bollinger Band Mean Reversion"))
        self.assertFalse(config.is_indicator_strategy("ICT/SMC Confluence"))

    def test_no_indicator_strategies_loaded(self):
        btc = BacktestConfig(starting_balance=10000)
        strategies = [
            MACrossStrategy(),
            RSIStrategy(),
            ROCMStrategy(),
        ]
        amalgamation_config = AmalgamationConfig(ict_smc_only=True)
        engine = AmalgamatedBacktestEngine(btc, strategies, amalgamation_config)
        self.assertEqual(len(engine.strategies), 1)
        self.assertIsInstance(engine.strategies[0], ICTSMCStrategy)

    def test_indicator_strategies_loaded_when_disabled(self):
        btc = BacktestConfig(starting_balance=10000)
        strategies = [
            MACrossStrategy(),
            RSIStrategy(),
            ROCMStrategy(),
        ]
        amalgamation_config = AmalgamationConfig(ict_smc_only=False)
        engine = AmalgamatedBacktestEngine(btc, strategies, amalgamation_config)
        self.assertEqual(len(engine.strategies), 3)

    def test_ict_smc_strategy_default_when_empty(self):
        btc = BacktestConfig(starting_balance=10000)
        strategies = [
            MACrossStrategy(),
        ]
        amalgamation_config = AmalgamationConfig(ict_smc_only=True)
        engine = AmalgamatedBacktestEngine(btc, strategies, amalgamation_config)
        self.assertEqual(len(engine.strategies), 1)
        self.assertIsInstance(engine.strategies[0], ICTSMCStrategy)

    def test_ict_smc_strategy_not_filtered(self):
        btc = BacktestConfig(starting_balance=10000)
        strategies = [
            ICTSMCStrategy(),
            MACrossStrategy(),
        ]
        amalgamation_config = AmalgamationConfig(ict_smc_only=True)
        engine = AmalgamatedBacktestEngine(btc, strategies, amalgamation_config)
        self.assertEqual(len(engine.strategies), 1)
        self.assertIsInstance(engine.strategies[0], ICTSMCStrategy)

    def test_component_extractor_profiles_ict(self):
        extractor = ComponentExtractor()
        ict_strategy = ICTSMCStrategy()
        profile = extractor.profile_strategy(ict_strategy)
        self.assertEqual(profile.component_type, "ict_smc_confluence")

    def test_component_extractor_unknown_for_indicator(self):
        extractor = ComponentExtractor()
        ma_strategy = MACrossStrategy()
        profile = extractor.profile_strategy(ma_strategy)
        self.assertEqual(profile.component_type, "unknown")

    def test_engine_run_with_ict_only(self):
        btc = BacktestConfig(starting_balance=10000)
        bars = make_test_bars(100)
        strategies = [ICTSMCStrategy()]
        amalgamation_config = AmalgamationConfig(
            ict_smc_only=True,
            min_combined_confidence=0.5,
            min_confluence=1,
        )
        engine = AmalgamatedBacktestEngine(btc, strategies, amalgamation_config)
        metrics = engine.run(bars)
        self.assertIsNotNone(metrics)
        self.assertGreaterEqual(metrics.total_trades, 0)

    def test_engine_produces_valid_signals(self):
        btc = BacktestConfig(starting_balance=10000)
        bars = make_test_bars(150)
        strategies = [ICTSMCStrategy()]
        amalgamation_config = AmalgamationConfig(
            ict_smc_only=True,
            min_combined_confidence=0.4,
            min_confluence=1,
            voting_method=VotingMethod.VOTE,
        )
        engine = AmalgamatedBacktestEngine(btc, strategies, amalgamation_config)
        metrics = engine.run(bars)
        self.assertIsNotNone(metrics)
        for trade in metrics.trades:
            self.assertIn(trade.direction, [TradeDirection.LONG, TradeDirection.SHORT])
            self.assertGreater(trade.entry_price, 0)
            self.assertGreater(trade.stop_loss, 0)

    def test_min_confluence_adjusted_for_single_ict_strategy(self):
        btc = BacktestConfig(starting_balance=10000)
        strategies = [MACrossStrategy()]
        amalgamation_config = AmalgamationConfig(
            ict_smc_only=True,
            min_confluence=3,
        )
        engine = AmalgamatedBacktestEngine(btc, strategies, amalgamation_config)
        self.assertEqual(engine.amalgamation.min_confluence, 1)

    def test_indicator_patterns_defined(self):
        self.assertIn("MA Crossover", INDICATOR_STRATEGY_PATTERNS)
        self.assertIn("RSI Divergence", INDICATOR_STRATEGY_PATTERNS)
        self.assertIn("Momentum ROC", INDICATOR_STRATEGY_PATTERNS)


if __name__ == "__main__":
    unittest.main()
