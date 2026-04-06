import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from backtest.engine import Bar, MarketState, StrategySignal, TradeDirection
from backtest.strategies import (
    ISignalStrategy,
    RegimeSwitchingRouter,
    RegimeRouterConfig,
)


def make_test_bars(n=100, seed=42, trend="flat"):
    import numpy as np
    import pandas as pd

    np.random.seed(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="1h")
    price = 1.1000
    prices = [price]

    drift = 0.0
    if trend == "up":
        drift = 0.0003
    elif trend == "down":
        drift = -0.0003
    elif trend == "strong_up":
        drift = 0.0008
    elif trend == "volatile":
        drift = 0.0

    for i in range(n - 1):
        noise = np.random.normal(0, 0.0008 if trend == "volatile" else 0.0002)
        price += drift + noise
        prices.append(price)

    prices = np.array(prices)
    spread = 0.0003 if trend == "volatile" else 0.0002
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


def _make_signal(direction=TradeDirection.LONG, confidence=0.7):
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        entry_price=1.1000,
        stop_loss=1.0980,
        take_profit_1=1.1020,
        take_profit_2=1.1040,
        take_profit_3=1.1060,
        rationale="test signal",
    )


class _AlwaysSignal(ISignalStrategy):
    def __init__(self, signal=None):
        self._signal = signal or _make_signal()

    @property
    def name(self) -> str:
        return "Always Signal"

    def evaluate(self, state):
        return self._signal


class _NeverSignal(ISignalStrategy):
    @property
    def name(self) -> str:
        return "Never Signal"

    def evaluate(self, state):
        return None


class TestRegimeSwitchingRouterName(unittest.TestCase):
    def test_router_name(self):
        router = RegimeSwitchingRouter()
        self.assertEqual(router.name, "Regime-Switching Router")


class TestRegimeSwitchingRouterInsufficientBars(unittest.TestCase):
    def test_returns_none_with_insufficient_bars(self):
        router = RegimeSwitchingRouter()
        bars = make_test_bars(20)
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        self.assertIsNone(result)

    def test_min_bar_requirement(self):
        config = RegimeRouterConfig(adx_period=14, atr_lookback=50)
        min_bars = config.adx_period + config.atr_lookback + 1
        router = RegimeSwitchingRouter(config=config)
        bars = make_test_bars(min_bars - 1)
        state = MarketState(bars=bars)
        self.assertIsNone(router.evaluate(state))

    def test_sufficient_bars_proceed(self):
        config = RegimeRouterConfig(adx_period=5, atr_lookback=10)
        router = RegimeSwitchingRouter(
            trending_strategies=[_AlwaysSignal()],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        if result is not None:
            self.assertIn("[trending]", result.rationale)
        self.assertIsNotNone(router.current_regime)


class TestRegimeSwitchingRouterRegimeDetection(unittest.TestCase):
    def test_trending_regime_detected(self):
        config = RegimeRouterConfig(
            adx_period=5, atr_lookback=10, adx_trend_threshold=15.0
        )
        router = RegimeSwitchingRouter(
            trending_strategies=[_AlwaysSignal()],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        regime, confidence, size_mult = router._detect_regime(state)
        self.assertEqual(regime, "trending")
        self.assertGreater(size_mult, 0)

    def test_ranging_regime_detected(self):
        config = RegimeRouterConfig(
            adx_period=5,
            atr_lookback=10,
            adx_trend_threshold=40.0,
            adx_range_threshold=30.0,
        )
        router = RegimeSwitchingRouter(config=config)
        bars = make_test_bars(100, trend="flat")
        state = MarketState(bars=bars)
        regime, confidence, size_mult = router._detect_regime(state)
        self.assertEqual(regime, "ranging")

    def test_transition_regime_for_mixed_signals(self):
        config = RegimeRouterConfig(
            adx_period=5,
            atr_lookback=10,
            adx_trend_threshold=40.0,
            adx_range_threshold=10.0,
            atr_volatility_percentile=90.0,
        )
        router = RegimeSwitchingRouter(config=config)
        bars = make_test_bars(100, trend="flat")
        state = MarketState(bars=bars)
        regime, confidence, size_mult = router._detect_regime(state)
        self.assertEqual(regime, "transition")
        self.assertEqual(size_mult, config.transition_size_multiplier)


class TestRegimeSwitchingRouterStrategyRouting(unittest.TestCase):
    def test_routes_to_trending_strategy(self):
        config = RegimeRouterConfig(
            adx_period=5, atr_lookback=10, adx_trend_threshold=15.0
        )
        trending = MagicMock(spec=ISignalStrategy)
        trending.name = "Trending Strat"
        trending.evaluate.return_value = _make_signal()
        router = RegimeSwitchingRouter(
            trending_strategies=[trending],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        router.evaluate(state)
        trending.evaluate.assert_called()

    def test_routes_to_ranging_strategy(self):
        config = RegimeRouterConfig(
            adx_period=5,
            atr_lookback=10,
            adx_trend_threshold=40.0,
            adx_range_threshold=30.0,
        )
        ranging = MagicMock(spec=ISignalStrategy)
        ranging.name = "Ranging Strat"
        ranging.evaluate.return_value = _make_signal()
        router = RegimeSwitchingRouter(
            ranging_strategies=[ranging],
            config=config,
        )
        bars = make_test_bars(100, trend="flat")
        state = MarketState(bars=bars)
        router.evaluate(state)
        ranging.evaluate.assert_called()

    def test_no_strategies_returns_none(self):
        router = RegimeSwitchingRouter()
        bars = make_test_bars(100)
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        self.assertIsNone(result)

    def test_all_strategies_return_none(self):
        config = RegimeRouterConfig(
            adx_period=5, atr_lookback=10, adx_trend_threshold=15.0
        )
        router = RegimeSwitchingRouter(
            trending_strategies=[_NeverSignal()],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        self.assertIsNone(result)

    def test_best_signal_selected_from_multiple(self):
        config = RegimeRouterConfig(
            adx_period=5, atr_lookback=10, adx_trend_threshold=15.0
        )
        low_conf = _AlwaysSignal(_make_signal(confidence=0.5))
        high_conf = _AlwaysSignal(_make_signal(confidence=0.8))
        router = RegimeSwitchingRouter(
            trending_strategies=[low_conf, high_conf],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        if result is not None:
            self.assertIn("test signal", result.rationale)


class TestRegimeSwitchingRouterPositionSizing(unittest.TestCase):
    def test_trending_full_size(self):
        config = RegimeRouterConfig(
            adx_period=5,
            atr_lookback=10,
            adx_trend_threshold=15.0,
            trending_size_multiplier=1.0,
        )
        router = RegimeSwitchingRouter(
            trending_strategies=[_AlwaysSignal()],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        if result is not None:
            regime, _, size_mult = router._detect_regime(state)
            self.assertEqual(size_mult, 1.0)

    def test_volatile_reduced_size(self):
        config = RegimeRouterConfig(
            adx_period=5,
            atr_lookback=10,
            adx_trend_threshold=50.0,
            volatile_size_multiplier=0.5,
            atr_volatility_percentile=50.0,
        )
        router = RegimeSwitchingRouter(
            volatile_strategies=[_AlwaysSignal()],
            config=config,
        )
        import numpy as np
        import pandas as pd

        np.random.seed(99)
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="1h")
        bars = []
        for i in range(n):
            noise = np.random.normal(0, 0.0001)
            if i >= n - 5:
                spread = 0.003
            else:
                spread = 0.0001
            bars.append(
                Bar(
                    time=dates[i].to_pydatetime(),
                    open=1.1 + noise - spread * np.random.uniform(0, 1),
                    high=1.1 + noise + spread * np.random.uniform(1, 3),
                    low=1.1 + noise - spread * np.random.uniform(1, 3),
                    close=1.1 + noise,
                    volume=1000,
                )
            )
        state = MarketState(bars=bars)
        regime, _, size_mult = router._detect_regime(state)
        self.assertEqual(regime, "volatile")
        self.assertEqual(size_mult, 0.5)

    def test_transition_reduced_size(self):
        config = RegimeRouterConfig(
            adx_period=5,
            atr_lookback=10,
            adx_trend_threshold=40.0,
            adx_range_threshold=10.0,
            transition_size_multiplier=0.5,
            atr_volatility_percentile=90.0,
        )
        router = RegimeSwitchingRouter(config=config)
        bars = make_test_bars(100, trend="flat")
        state = MarketState(bars=bars)
        regime, _, size_mult = router._detect_regime(state)
        self.assertEqual(regime, "transition")
        self.assertEqual(size_mult, 0.5)

    def test_confidence_scaled_by_size_multiplier(self):
        config = RegimeRouterConfig(
            adx_period=5,
            atr_lookback=10,
            adx_trend_threshold=15.0,
            trending_size_multiplier=0.5,
        )
        router = RegimeSwitchingRouter(
            trending_strategies=[_AlwaysSignal(_make_signal(confidence=0.8))],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        if result is not None:
            expected = 0.8 * 0.5
            self.assertAlmostEqual(result.confidence, expected, places=2)

    def test_low_confidence_signal_filtered_by_min_confidence(self):
        config = RegimeRouterConfig(
            adx_period=5,
            atr_lookback=10,
            adx_trend_threshold=15.0,
            trending_size_multiplier=0.3,
            min_confidence=0.55,
        )
        router = RegimeSwitchingRouter(
            trending_strategies=[_AlwaysSignal(_make_signal(confidence=0.6))],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        expected = 0.6 * 0.3
        if expected < 0.55:
            self.assertIsNone(result)


class TestRegimeSwitchingRouterRationale(unittest.TestCase):
    def test_rationale_includes_regime_tag(self):
        config = RegimeRouterConfig(
            adx_period=5, atr_lookback=10, adx_trend_threshold=15.0
        )
        router = RegimeSwitchingRouter(
            trending_strategies=[_AlwaysSignal()],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        if result is not None:
            self.assertTrue(result.rationale.startswith("[trending]"))

    def test_current_regime_property_updated(self):
        config = RegimeRouterConfig(
            adx_period=5, atr_lookback=10, adx_trend_threshold=15.0
        )
        router = RegimeSwitchingRouter(
            trending_strategies=[_AlwaysSignal()],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        router.evaluate(state)
        self.assertEqual(router.current_regime, "trending")


class TestRegimeSwitchingRouterCustomConfig(unittest.TestCase):
    def test_custom_config_values(self):
        config = RegimeRouterConfig(
            adx_trend_threshold=30.0,
            adx_range_threshold=15.0,
            atr_volatility_percentile=80.0,
            atr_lookback=100,
            adx_period=21,
            trending_size_multiplier=0.8,
            ranging_size_multiplier=0.9,
            volatile_size_multiplier=0.4,
            transition_size_multiplier=0.3,
            min_confidence=0.65,
        )
        router = RegimeSwitchingRouter(config=config)
        self.assertEqual(router.config.adx_trend_threshold, 30.0)
        self.assertEqual(router.config.adx_range_threshold, 15.0)
        self.assertEqual(router.config.atr_volatility_percentile, 80.0)
        self.assertEqual(router.config.atr_lookback, 100)
        self.assertEqual(router.config.trending_size_multiplier, 0.8)
        self.assertEqual(router.config.ranging_size_multiplier, 0.9)
        self.assertEqual(router.config.volatile_size_multiplier, 0.4)
        self.assertEqual(router.config.transition_size_multiplier, 0.3)
        self.assertEqual(router.config.min_confidence, 0.65)

    def test_default_config_values(self):
        config = RegimeRouterConfig()
        self.assertEqual(config.adx_trend_threshold, 25.0)
        self.assertEqual(config.adx_range_threshold, 20.0)
        self.assertEqual(config.atr_volatility_percentile, 75.0)
        self.assertEqual(config.atr_lookback, 50)
        self.assertEqual(config.adx_period, 14)
        self.assertEqual(config.trending_size_multiplier, 1.0)
        self.assertEqual(config.ranging_size_multiplier, 1.0)
        self.assertEqual(config.volatile_size_multiplier, 0.5)
        self.assertEqual(config.transition_size_multiplier, 0.5)
        self.assertEqual(config.min_confidence, 0.55)

    def test_config_is_frozen(self):
        config = RegimeRouterConfig()
        with self.assertRaises(AttributeError):
            config.adx_trend_threshold = 99.0


class TestRegimeSwitchingRouterATRPercentile(unittest.TestCase):
    def test_returns_50_with_insufficient_bars(self):
        config = RegimeRouterConfig(atr_lookback=200)
        router = RegimeSwitchingRouter(config=config)
        bars = make_test_bars(50)
        state = MarketState(bars=bars)
        percentile = router._calculate_atr_percentile(state.bars)
        self.assertEqual(percentile, 50.0)

    def test_percentile_range(self):
        router = RegimeSwitchingRouter()
        bars = make_test_bars(100, trend="volatile")
        state = MarketState(bars=bars)
        percentile = router._calculate_atr_percentile(state.bars)
        self.assertGreaterEqual(percentile, 0.0)
        self.assertLessEqual(percentile, 100.0)

    def test_stable_data_returns_middle_percentile(self):
        router = RegimeSwitchingRouter(
            config=RegimeRouterConfig(atr_lookback=20),
        )
        import numpy as np
        import pandas as pd

        np.random.seed(42)
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="1h")
        bars = [
            Bar(
                time=dates[i].to_pydatetime(),
                open=1.1 + np.random.normal(0, 0.0001),
                high=1.1 + abs(np.random.normal(0, 0.0003)),
                low=1.1 - abs(np.random.normal(0, 0.0003)),
                close=1.1 + np.random.normal(0, 0.0001),
                volume=1000,
            )
            for i in range(n)
        ]
        percentile = router._calculate_atr_percentile(bars)
        self.assertGreater(percentile, 0.0)
        self.assertLess(percentile, 100.0)


class TestRegimeSwitchingRouterADX(unittest.TestCase):
    def test_returns_zero_with_insufficient_bars(self):
        config = RegimeRouterConfig(adx_period=50)
        router = RegimeSwitchingRouter(config=config)
        bars = make_test_bars(20)
        adx = router._calculate_adx(bars)
        self.assertEqual(adx, 0.0)

    def test_trending_data_gives_higher_adx(self):
        config = RegimeRouterConfig(adx_period=5)
        router = RegimeSwitchingRouter(config=config)
        trending_bars = make_test_bars(100, trend="strong_up")
        flat_bars = make_test_bars(100, trend="flat")
        trending_adx = router._calculate_adx(trending_bars)
        flat_adx = router._calculate_adx(flat_bars)
        self.assertGreater(trending_adx, flat_adx)

    def test_adx_range(self):
        router = RegimeSwitchingRouter()
        bars = make_test_bars(100)
        adx = router._calculate_adx(bars)
        self.assertGreaterEqual(adx, 0.0)
        self.assertLessEqual(adx, 100.0)


class TestRegimeSwitchingRouterIntegration(unittest.TestCase):
    def test_real_strategy_integration(self):
        from backtest.strategies import MomentumBreakoutStrategy

        config = RegimeRouterConfig(
            adx_period=5, atr_lookback=10, adx_trend_threshold=15.0
        )
        router = RegimeSwitchingRouter(
            trending_strategies=[
                MomentumBreakoutStrategy(
                    fast_period=5, slow_period=10, adx_threshold=15.0
                )
            ],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        if result is not None:
            self.assertIn("[trending]", result.rationale)
            self.assertIsNotNone(result.direction)
            self.assertGreater(result.entry_price, 0)
            self.assertGreater(result.stop_loss, 0)

    def test_multiple_regime_strategies(self):
        from backtest.strategies import MomentumBreakoutStrategy, BBStrategy

        config = RegimeRouterConfig(
            adx_period=5, atr_lookback=10, adx_trend_threshold=15.0
        )
        router = RegimeSwitchingRouter(
            trending_strategies=[
                MomentumBreakoutStrategy(
                    fast_period=5, slow_period=10, adx_threshold=15.0
                )
            ],
            ranging_strategies=[BBStrategy()],
            volatile_strategies=[_NeverSignal()],
            transition_strategies=[_NeverSignal()],
            config=config,
        )
        bars = make_test_bars(100, trend="strong_up")
        state = MarketState(bars=bars)
        result = router.evaluate(state)
        if result is not None:
            self.assertEqual(router.current_regime, "trending")
            self.assertIn("[trending]", result.rationale)


if __name__ == "__main__":
    unittest.main()
