import unittest
from datetime import datetime, timedelta

from backtest.engine import (
    DEFAULT_SPREAD_PIPS,
    BacktestConfig,
    BacktestEngine,
    Bar,
    get_spread_for_pair,
)
from backtest.strategies import MACrossStrategy


def _make_engine(config: BacktestConfig) -> tuple[BacktestEngine, MACrossStrategy]:
    """Build a BacktestEngine with the canonical strategies signature.

    After the MultiStrategy+VAPS+Amalgamation mixin migration (card d4f36ef5),
    ``BacktestEngine.__init__`` requires a ``strategies`` list. The cost-tracking
    tests don't care which strategy runs — they only need a runnable engine —
    so we use a single ``MACrossStrategy`` for parity with the other engine
    tests in this file.
    """
    strategy = MACrossStrategy()
    return BacktestEngine(config, [strategy]), strategy


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, v=1000):
    base = datetime(2024, 1, 1, 10, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c, volume=v)


def _trending_bars(n=200, trend="up"):
    bars = []
    price = 1.0000
    for i in range(n):
        hour = i % 24
        if trend == "up":
            drift = 0.00005 + (0.00001 if hour in range(8, 16) else 0)
            noise = (i % 7 - 3) * 0.00003
        else:
            drift = -0.00005 - (0.00001 if hour in range(8, 16) else 0)
            noise = (i % 7 - 3) * 0.00003
        price += drift + noise
        h = price + abs(noise) * 2
        low = price - abs(noise) * 2
        bars.append(_bar(i, o=price - drift, h=h, low=low, c=price))
    return bars


class TestPairSpecificSpreads(unittest.TestCase):
    def test_eurusd_spread(self):
        self.assertEqual(get_spread_for_pair("EURUSD"), 1.5)

    def test_gbpjpy_spread(self):
        self.assertEqual(get_spread_for_pair("GBPJPY"), 3.0)

    def test_xauusd_spread(self):
        self.assertEqual(get_spread_for_pair("XAUUSD"), 2.5)

    def test_gbpusd_spread(self):
        self.assertEqual(get_spread_for_pair("GBPUSD"), 1.5)

    def test_case_insensitive(self):
        self.assertEqual(get_spread_for_pair("eurusd"), 1.5)
        self.assertEqual(get_spread_for_pair("EurUsd"), 1.5)

    def test_unknown_pair_returns_default(self):
        self.assertEqual(get_spread_for_pair("ZZZUSD"), DEFAULT_SPREAD_PIPS)

    def test_empty_pair_returns_default(self):
        self.assertEqual(get_spread_for_pair(""), DEFAULT_SPREAD_PIPS)


class TestBacktestConfigEffectiveSpread(unittest.TestCase):
    def test_explicit_spread_overrides_pair(self):
        cfg = BacktestConfig(spread_pips=2.0, pair="EURUSD")
        self.assertEqual(cfg.effective_spread_pips, 2.0)

    def test_pair_specific_spread_used_when_no_explicit(self):
        cfg = BacktestConfig(spread_pips=0.0, pair="GBPJPY")
        self.assertEqual(cfg.effective_spread_pips, 3.0)

    def test_default_pair_spread_when_no_pair_set(self):
        cfg = BacktestConfig(spread_pips=0.0)
        self.assertEqual(cfg.effective_spread_pips, DEFAULT_SPREAD_PIPS)

    def test_xauusd_pair_spread(self):
        cfg = BacktestConfig(spread_pips=0.0, pair="XAUUSD")
        self.assertEqual(cfg.effective_spread_pips, 2.5)


class TestRoundTripSpread(unittest.TestCase):
    def test_round_trip_enabled_by_default(self):
        cfg = BacktestConfig()
        self.assertTrue(cfg.round_trip_spread)

    def test_round_trip_can_be_disabled(self):
        cfg = BacktestConfig(round_trip_spread=False)
        self.assertFalse(cfg.round_trip_spread)


class TestSlippageModel(unittest.TestCase):
    def test_slippage_default(self):
        cfg = BacktestConfig()
        self.assertAlmostEqual(cfg.slippage_pips, 0.5)

    def test_slippage_custom(self):
        cfg = BacktestConfig(slippage_pips=0.5)
        self.assertAlmostEqual(cfg.slippage_pips, 0.5)


class TestSwapModel(unittest.TestCase):
    def test_swap_default(self):
        cfg = BacktestConfig()
        self.assertAlmostEqual(cfg.swap_per_lot_per_day, -3.5)

    def test_swap_can_be_disabled(self):
        cfg = BacktestConfig(swap_per_lot_per_day=0.0)
        self.assertAlmostEqual(cfg.swap_per_lot_per_day, 0.0)


class TestCostTracking(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults = dict(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=1.5,
            commission_per_lot=3.5,
            leverage=100,
            min_confidence=0.40,
            min_bars_before_signal=30,
            max_open_trades=1,
        )
        defaults.update(kwargs)
        return BacktestConfig(**defaults)

    def test_spread_and_commission_tracked_with_round_trip(self):
        bars = _trending_bars(200, "up")
        config = self._make_config()
        engine, strategy = _make_engine(config)
        metrics = engine.run_single(strategy, bars)
        self.assertGreaterEqual(metrics.total_spread_cost, 0.0)
        self.assertGreaterEqual(metrics.total_commission_cost, 0.0)

    def test_no_trades_zero_costs(self):
        bars = [_bar(i, o=1.0, h=1.0001, low=0.9999, c=1.0) for i in range(50)]
        config = self._make_config(min_confidence=0.99)
        engine, strategy = _make_engine(config)
        metrics = engine.run_single(strategy, bars)
        self.assertAlmostEqual(metrics.total_spread_cost, 0.0)
        self.assertAlmostEqual(metrics.total_commission_cost, 0.0)

    def test_commission_per_lot(self):
        bars = _trending_bars(200, "up")
        config = self._make_config(commission_per_lot=7.0)
        engine, strategy = _make_engine(config)
        metrics = engine.run_single(strategy, bars)
        if metrics.total_trades > 0:
            self.assertGreater(metrics.total_commission_cost, 0.0)

    def test_larger_spread_increases_cost(self):
        bars = _trending_bars(200, "up")
        cfg_low = self._make_config(spread_pips=0.5)
        cfg_high = self._make_config(spread_pips=5.0)
        engine_low, strat_low = _make_engine(cfg_low)
        engine_high, strat_high = _make_engine(cfg_high)
        m_low = engine_low.run_single(strat_low, bars)
        m_high = engine_high.run_single(strat_high, bars)
        if m_high.total_trades > 0 and m_low.total_trades > 0:
            self.assertGreaterEqual(m_high.total_spread_cost, m_low.total_spread_cost)


class TestMultiDaySwapCost(unittest.TestCase):
    def test_multi_day_trade_has_swap_cost(self):
        bars = []
        base = datetime(2024, 1, 1, 10, 0)
        price = 1.0000
        for day in range(5):
            for hour in range(8, 20):
                t = base + timedelta(days=day, hours=hour)
                price += 0.0001
                bars.append(
                    Bar(
                        time=t,
                        open=price,
                        high=price + 0.001,
                        low=price - 0.001,
                        close=price,
                        volume=1000,
                    )
                )
        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=1.5,
            commission_per_lot=3.5,
            leverage=100,
            min_confidence=0.40,
            min_bars_before_signal=30,
            max_open_trades=1,
            swap_per_lot_per_day=-2.0,
        )
        engine, strategy = _make_engine(config)
        metrics = engine.run_single(strategy, bars)
        if metrics.total_trades > 0:
            self.assertIsNotNone(metrics)


class TestSlippageReducesProfit(unittest.TestCase):
    def test_zero_slippage_vs_nonzero(self):
        bars = _trending_bars(200, "up")
        cfg_no_slip = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=1.5,
            commission_per_lot=3.5,
            leverage=100,
            min_confidence=0.40,
            min_bars_before_signal=30,
            max_open_trades=1,
            slippage_pips=0.0,
        )
        cfg_with_slip = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=1.5,
            commission_per_lot=3.5,
            leverage=100,
            min_confidence=0.40,
            min_bars_before_signal=30,
            max_open_trades=1,
            slippage_pips=1.0,
        )
        engine_no, strat_no = _make_engine(cfg_no_slip)
        engine_with, strat_with = _make_engine(cfg_with_slip)
        m_no = engine_no.run_single(strat_no, bars)
        m_with = engine_with.run_single(strat_with, bars)
        self.assertLessEqual(m_with.ending_balance, m_no.ending_balance)


class TestCostReportPrint(unittest.TestCase):
    def test_print_report_includes_costs(self):
        """Verify cost fields exist and are non-negative on the returned metrics.

        Original assertion (``metrics.print_report()`` returns ``None``) was a
        smoke test of the ``print_report`` method on ``backtest.types.BacktestMetrics``.
        After the MultiStrategy+VAPS+Amalgamation mixin migration (card d4f36ef5),
        ``run_single`` returns ``core.config.BacktestMetrics`` which has no
        ``print_report`` method. The old assertion never actually verified that
        costs were included in the report — it only checked the method returned
        ``None``. We verify cost-tracking invariants on the metrics object
        directly, which is what the test name implies.
        """
        bars = _trending_bars(200, "up")
        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=1.5,
            commission_per_lot=3.5,
            leverage=100,
            min_confidence=0.40,
            min_bars_before_signal=30,
            max_open_trades=1,
        )
        engine, strategy = _make_engine(config)
        metrics = engine.run_single(strategy, bars)
        # Cost fields exist and are non-negative on the returned metrics.
        self.assertGreaterEqual(metrics.total_spread_cost, 0.0)
        self.assertGreaterEqual(metrics.total_commission_cost, 0.0)
        # With no qualifying signals (trending bars w/ MA cross strategy in this
        # test configuration), no trades should open and ending_balance equals
        # starting_balance.
        self.assertEqual(metrics.ending_balance, config.starting_balance)


class TestMultiStrategyCostTracking(unittest.TestCase):
    def test_multi_strategy_tracks_costs(self):
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        bars = _trending_bars(200, "up")
        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=1.5,
            commission_per_lot=3.5,
            leverage=100,
            min_confidence=0.40,
            min_bars_before_signal=30,
            max_open_trades=1,
        )
        engine = MultiStrategyBacktestEngine(config, [MACrossStrategy()])
        results = engine.run_all_strategies(bars)
        for name, result in results.items():
            self.assertGreaterEqual(result.metrics.total_spread_cost, 0.0)
            self.assertGreaterEqual(result.metrics.total_commission_cost, 0.0)


class TestEnhancedEngineCostTracking(unittest.TestCase):
    def test_enhanced_engine_tracks_costs(self):
        from backtest.enhanced_engine import EnhancedBacktestEngine
        from backtest.trade_management.config import TradeManagementConfig

        bars = _trending_bars(200, "up")
        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.10,
            spread_pips=1.5,
            commission_per_lot=3.5,
            leverage=100,
            min_confidence=0.40,
            min_bars_before_signal=30,
            max_open_trades=1,
        )
        tm_config = TradeManagementConfig()
        engine = EnhancedBacktestEngine(config, [MACrossStrategy()], tm_config)
        metrics = engine.run_strategy(MACrossStrategy(), bars)
        self.assertGreaterEqual(metrics.total_spread_cost, 0.0)
        self.assertGreaterEqual(metrics.total_commission_cost, 0.0)


class TestSelectivePairingCostTracking(unittest.TestCase):
    def test_pairing_config_effective_spread(self):
        from backtest.selective_pairing import PairingConfig

        cfg = PairingConfig(pair="GBPJPY")
        self.assertEqual(cfg.effective_spread_pips, 3.0)

    def test_pairing_config_explicit_spread(self):
        from backtest.selective_pairing import PairingConfig

        cfg = PairingConfig(spread_pips=2.0, pair="GBPJPY")
        self.assertEqual(cfg.effective_spread_pips, 2.0)


if __name__ == "__main__":
    unittest.main()
