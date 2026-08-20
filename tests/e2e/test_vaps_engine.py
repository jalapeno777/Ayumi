import unittest
from datetime import datetime

from backtest.engine import BacktestConfig, Bar, StrategySignal, TradeDirection
from backtest.strategies import ISignalStrategy
from backtest.vaps_engine import VAPSBacktestEngine, _compute_atr
from quant.vaps import VAPSConfig


def _make_bar(index: int, high: float = 1.10, low: float = 1.09, close: float = 1.095) -> Bar:
    day = 1 + index // 24
    hour = index % 24
    return Bar(
        time=datetime(2024, 1, day, hour, 0),
        open=1.095,
        high=high,
        low=low,
        close=close,
    )


class _AlwaysLongStrategy(ISignalStrategy):
    name = "always_long"

    def evaluate(self, state):
        return StrategySignal(
            direction=TradeDirection.LONG,
            confidence=0.8,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1050,
            take_profit_2=1.1100,
            take_profit_3=1.1150,
            rationale="test",
        )


class TestComputeATR(unittest.TestCase):
    def test_returns_positive(self):
        bars = [_make_bar(i) for i in range(20)]
        atr = _compute_atr(bars, period=14)
        self.assertGreater(atr, 0.0)

    def test_short_series(self):
        bars = [_make_bar(i) for i in range(5)]
        atr = _compute_atr(bars, period=14)
        self.assertAlmostEqual(atr, 0.0001)

    def test_empty_series(self):
        atr = _compute_atr([], period=14)
        self.assertAlmostEqual(atr, 0.0001)

    def test_volatile_bars_higher_atr(self):
        calm_bars = [_make_bar(i, high=1.0955, low=1.0945, close=1.0950) for i in range(20)]
        wild_bars = [_make_bar(i, high=1.12, low=1.07, close=1.095) for i in range(20)]
        self.assertGreater(_compute_atr(wild_bars), _compute_atr(calm_bars))


class TestVAPSBacktestEngine(unittest.TestCase):
    def test_runs_without_error(self):
        config = BacktestConfig(
            starting_balance=10000,
            spread_pips=1.5,
            commission_per_lot=3.5,
            pair="GBPUSD",
            min_bars_before_signal=5,
        )
        bars = [_make_bar(i) for i in range(50)]
        strategy = _AlwaysLongStrategy()
        engine = VAPSBacktestEngine(config, [strategy])
        results = engine.run_all_strategies(bars)
        self.assertIn("always_long", results)

    def test_vaps_modifies_lot_size(self):
        config = BacktestConfig(
            starting_balance=10000,
            spread_pips=1.5,
            commission_per_lot=3.5,
            pair="GBPUSD",
            min_bars_before_signal=5,
        )
        bars = [_make_bar(i) for i in range(50)]
        strategy = _AlwaysLongStrategy()

        vaps_engine = VAPSBacktestEngine(config, [strategy], vaps_config=VAPSConfig(normal_multiplier=0.5))
        vaps_results = vaps_engine.run_all_strategies(bars)
        vaps_trades = vaps_results["always_long"].metrics.trades

        standard_engine = VAPSBacktestEngine(config, [strategy], vaps_config=VAPSConfig(normal_multiplier=1.0))
        standard_results = standard_engine.run_all_strategies(bars)
        standard_trades = standard_results["always_long"].metrics.trades

        self.assertGreater(len(vaps_trades), 1, "Need at least 2 trades for VAPS to kick in")
        self.assertGreater(len(standard_trades), 1)

        vaps_total_lots = sum(t.lot_size for t in vaps_trades)
        std_total_lots = sum(t.lot_size for t in standard_trades)
        self.assertLess(vaps_total_lots, std_total_lots)

    def test_atr_history_populated(self):
        config = BacktestConfig(
            starting_balance=10000,
            spread_pips=1.5,
            commission_per_lot=3.5,
            pair="GBPUSD",
            min_bars_before_signal=5,
        )
        bars = [_make_bar(i) for i in range(50)]
        strategy = _AlwaysLongStrategy()
        engine = VAPSBacktestEngine(config, [strategy])
        engine.run_all_strategies(bars)
        self.assertGreater(len(engine._atr_history), 0)

    def test_custom_vaps_config(self):
        config = BacktestConfig(
            starting_balance=10000,
            spread_pips=1.5,
            commission_per_lot=3.5,
            pair="GBPUSD",
            min_bars_before_signal=5,
        )
        vaps_cfg = VAPSConfig(lookback=10, low_multiplier=2.0)
        bars = [_make_bar(i) for i in range(50)]
        strategy = _AlwaysLongStrategy()
        engine = VAPSBacktestEngine(config, [strategy], vaps_config=vaps_cfg)
        results = engine.run_all_strategies(bars)
        self.assertIn("always_long", results)


if __name__ == "__main__":
    unittest.main()
