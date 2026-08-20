import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, MarketState, StrategySignal, TradeDirection
from backtest.strategies import ISignalStrategy
from backtest.walk_forward_runner import (
    STRATEGY_REGISTRY,
    get_registered_strategies,
    register_strategy,
    run_named_strategy_walk_forward,
    run_strategy_walk_forward,
)


def _make_bars(n: int, base_price: float = 1.1000) -> list[Bar]:
    bars = []
    price = base_price
    for i in range(n):
        bars.append(
            Bar(
                time=datetime(2024, 1, 1) + timedelta(hours=i),
                open=price,
                high=price + 0.0005,
                low=price - 0.0005,
                close=price + 0.0001 * (1 if i % 2 == 0 else -1),
                volume=1000,
            )
        )
        price += 0.0001 * (1 if i % 2 == 0 else -1)
    return bars


class _AlwaysSignal(ISignalStrategy):
    name_val = "Always Signal"

    @property
    def name(self) -> str:
        return self.name_val

    def evaluate(self, state: MarketState):
        if len(state.bars) < 31:
            return None
        entry = state.latest_bar.close
        return StrategySignal(
            direction=TradeDirection.LONG,
            confidence=0.8,
            entry_price=entry,
            stop_loss=entry - 0.002,
            take_profit_1=entry + 0.002,
            take_profit_2=entry + 0.004,
            take_profit_3=entry + 0.006,
            rationale="test",
        )


class _NeverSignal(ISignalStrategy):
    @property
    def name(self) -> str:
        return "Never Signal"

    def evaluate(self, state: MarketState):
        return None


class _MLStrategy(ISignalStrategy):
    trained_on = None

    @property
    def name(self) -> str:
        return "ML Strategy"

    def train(self, data):
        self.trained_on = data

    def evaluate(self, state: MarketState):
        return None


class TestRunStrategyWalkForward(unittest.TestCase):
    def test_simple_strategy_factory(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="EURUSD",
            n_windows=3,
            train_ratio=0.7,
            val_ratio=0.15,
        )
        self.assertEqual(len(results.per_window), 3)
        self.assertIsNotNone(results.aggregated)

    def test_no_signal_strategy(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_NeverSignal,
            pair="EURUSD",
            n_windows=3,
        )
        self.assertEqual(len(results.per_window), 3)
        for m in results.per_window:
            self.assertEqual(m.trade_count, 0)
            self.assertFalse(m.passed_go_nogo)

    def test_ml_strategy_with_train(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=lambda train_bars: _MLStrategy(),
            pair="EURUSD",
            n_windows=3,
        )
        self.assertEqual(len(results.per_window), 3)

    def test_custom_spread_and_commission(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="EURUSD",
            n_windows=3,
            spread_pips=2.0,
            commission_per_lot=5.0,
        )
        self.assertEqual(len(results.per_window), 3)

    def test_custom_initial_balance(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="EURUSD",
            n_windows=3,
            initial_balance=50000,
        )
        self.assertEqual(len(results.per_window), 3)

    def test_insufficient_data(self):
        bars = _make_bars(10)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="EURUSD",
            n_windows=3,
        )
        self.assertEqual(len(results.per_window), 0)
        self.assertFalse(results.go_nogo)

    def test_go_nogo_threshold(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="EURUSD",
            n_windows=3,
        )
        expected = len(results.per_window) >= 3 and sum(1 for m in results.per_window if m.passed_go_nogo) >= 2
        self.assertEqual(results.go_nogo, expected)

    def test_overlap_ratio(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="EURUSD",
            n_windows=3,
            overlap_ratio=0.3,
        )
        self.assertGreaterEqual(len(results.per_window), 1)

    def test_per_window_indices(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="EURUSD",
            n_windows=5,
        )
        for i, m in enumerate(results.per_window):
            self.assertEqual(m.window_index, i)


class TestStrategyRegistry(unittest.TestCase):
    def setUp(self):
        self._original = dict(STRATEGY_REGISTRY)
        STRATEGY_REGISTRY.clear()

    def tearDown(self):
        STRATEGY_REGISTRY.clear()
        STRATEGY_REGISTRY.update(self._original)

    def test_register_and_list(self):
        register_strategy("test_strat", lambda: _AlwaysSignal())
        self.assertIn("test_strat", get_registered_strategies())

    def test_get_registered_sorted(self):
        register_strategy("b_strat", lambda: _NeverSignal())
        register_strategy("a_strat", lambda: _AlwaysSignal())
        names = get_registered_strategies()
        self.assertEqual(names, ["a_strat", "b_strat"])

    def test_run_named_strategy(self):
        register_strategy("my_strat", lambda: _AlwaysSignal())
        bars = _make_bars(1000)
        results = run_named_strategy_walk_forward(
            strategy_name="my_strat",
            bars=bars,
            pair="EURUSD",
            n_windows=3,
        )
        self.assertEqual(len(results.per_window), 3)

    def test_run_unknown_strategy_raises(self):
        with self.assertRaises(ValueError) as ctx:
            run_named_strategy_walk_forward(
                strategy_name="nonexistent",
                bars=_make_bars(100),
                pair="EURUSD",
            )
        self.assertIn("nonexistent", str(ctx.exception))


class TestAggregatedMetrics(unittest.TestCase):
    def test_aggregated_present_with_windows(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="EURUSD",
            n_windows=3,
        )
        agg = results.aggregated
        self.assertIsNotNone(agg)
        self.assertEqual(agg.total_windows, 3)
        self.assertGreaterEqual(agg.windows_passed, 0)
        self.assertGreaterEqual(agg.mean_win_rate, 0)

    def test_aggregated_fields_populated(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="EURUSD",
            n_windows=3,
        )
        agg = results.aggregated
        self.assertIsNotNone(agg)
        self.assertIsInstance(agg.mean_profit_factor, float)
        self.assertIsInstance(agg.std_max_drawdown, float)
        self.assertIsInstance(agg.mean_sharpe_ratio, float)
        self.assertIsInstance(agg.mean_trade_count, float)


class TestSpreadDefaults(unittest.TestCase):
    def test_auto_detects_spread_from_pair(self):
        from backtest.engine import get_spread_for_pair

        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_AlwaysSignal,
            pair="GBPJPY",
            n_windows=3,
        )
        self.assertEqual(len(results.per_window), 3)
        expected_spread = get_spread_for_pair("GBPJPY")
        self.assertAlmostEqual(expected_spread, 3.0)

    def test_explicit_spread_overrides_pair(self):
        bars = _make_bars(1000)
        results = run_strategy_walk_forward(
            bars=bars,
            strategy_factory=_NeverSignal,
            pair="EURUSD",
            n_windows=3,
            spread_pips=4.2,
        )
        self.assertEqual(len(results.per_window), 3)


if __name__ == "__main__":
    unittest.main()
