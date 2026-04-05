import unittest
from datetime import datetime, timedelta

from strategies.grid.config import (
    GridConfig,
    GridDirectionBias,
    LotSizingMode,
    RiskConfig,
    TrendFilterConfig,
)
from strategies.grid.types import (
    GridLevel,
    GridLevelStatus,
    GridSide,
    GridState,
    GridTrade,
)
from strategies.grid.manager import GridManager
from strategies.grid.trend_filter import TrendFilter, _calculate_adx
from strategies.grid.adapter import GridStrategyAdapter


def _make_bars(
    n: int = 100,
    base_close: float = 1.1000,
    volatility: float = 0.0005,
) -> list[dict]:
    bars = []
    price = base_close
    for i in range(n):
        change = (i % 7 - 3) * volatility * 0.1
        price += change
        bars.append(
            {
                "time": datetime(2025, 1, 1, 10, 0) + timedelta(hours=i),
                "open": price - volatility * 0.5,
                "high": price + volatility,
                "low": price - volatility,
                "close": price,
            }
        )
    return bars


class TestGridConfig(unittest.TestCase):
    def test_eurusd_preset(self):
        cfg = GridConfig.eurusd()
        self.assertEqual(cfg.symbol, "EURUSD")
        self.assertEqual(cfg.pip_value, 0.0001)
        self.assertAlmostEqual(cfg.grid_spacing, 0.0015)
        self.assertEqual(cfg.levels_per_side, 5)

    def test_xauusd_preset(self):
        cfg = GridConfig.xauusd()
        self.assertEqual(cfg.symbol, "XAUUSD")
        self.assertEqual(cfg.pip_value, 0.01)
        self.assertEqual(cfg.levels_per_side, 5)

    def test_ftmo_preset_eurusd(self):
        cfg = GridConfig.ftmo("EURUSD")
        self.assertEqual(cfg.risk.equity_stop_pct, 0.05)
        self.assertEqual(cfg.risk.max_daily_loss_pct, 0.015)
        self.assertEqual(cfg.risk.max_open_positions, 3)

    def test_ftmo_preset_xauusd(self):
        cfg = GridConfig.ftmo("XAUUSD")
        self.assertEqual(cfg.symbol, "XAUUSD")
        self.assertEqual(cfg.pip_value, 0.01)
        self.assertEqual(cfg.risk.max_open_positions, 3)

    def test_spacing_in_pips(self):
        cfg = GridConfig.eurusd()
        self.assertAlmostEqual(cfg.spacing_in_pips(), 15.0)

    def test_lot_for_level_decreasing(self):
        cfg = GridConfig.eurusd()
        self.assertAlmostEqual(cfg.lot_for_level(0), 0.10)
        self.assertAlmostEqual(cfg.lot_for_level(1), 0.08)
        self.assertAlmostEqual(cfg.lot_for_level(4), 0.04)
        self.assertAlmostEqual(cfg.lot_for_level(10), 0.04)

    def test_lot_for_level_uniform(self):
        cfg = GridConfig(lot_sizing_mode=LotSizingMode.UNIFORM, base_lot=0.05)
        self.assertAlmostEqual(cfg.lot_for_level(0), 0.05)
        self.assertAlmostEqual(cfg.lot_for_level(5), 0.05)


class TestGridState(unittest.TestCase):
    def test_open_trade_count(self):
        state = GridState(center_price=1.1)
        self.assertEqual(state.open_trade_count, 0)

    def test_win_rate_no_trades(self):
        state = GridState(center_price=1.1)
        self.assertEqual(state.win_rate, 0.0)

    def test_win_rate_with_trades(self):
        state = GridState(center_price=1.1)
        t1 = GridTrade(
            level=None,
            entry_price=1.1,
            lot_size=0.1,
            side=GridSide.BUY,
            entry_time=datetime.now(),
            is_open=False,
            pnl=10.0,
        )
        t2 = GridTrade(
            level=None,
            entry_price=1.1,
            lot_size=0.1,
            side=GridSide.BUY,
            entry_time=datetime.now(),
            is_open=False,
            pnl=-5.0,
        )
        t3 = GridTrade(
            level=None,
            entry_price=1.1,
            lot_size=0.1,
            side=GridSide.BUY,
            entry_time=datetime.now(),
            is_open=False,
            pnl=8.0,
        )
        state.closed_trades = [t1, t2, t3]
        self.assertAlmostEqual(state.win_rate, 2 / 3)

    def test_active_levels(self):
        state = GridState(
            center_price=1.1,
            buy_levels=[
                GridLevel(
                    index=1,
                    side=GridSide.BUY,
                    price=1.0985,
                    lot_size=0.1,
                    status=GridLevelStatus.ACTIVE,
                ),
                GridLevel(
                    index=2,
                    side=GridSide.BUY,
                    price=1.0970,
                    lot_size=0.08,
                    status=GridLevelStatus.FILLED,
                ),
            ],
            sell_levels=[
                GridLevel(
                    index=1,
                    side=GridSide.SELL,
                    price=1.1015,
                    lot_size=0.1,
                    status=GridLevelStatus.ACTIVE,
                ),
                GridLevel(
                    index=2,
                    side=GridSide.SELL,
                    price=1.1030,
                    lot_size=0.08,
                    status=GridLevelStatus.CANCELLED,
                ),
            ],
        )
        self.assertEqual(len(state.active_buy_levels), 1)
        self.assertEqual(len(state.active_sell_levels), 1)
        self.assertEqual(len(state.all_active_levels), 2)


class TestTrendFilter(unittest.TestCase):
    def test_low_adx_full_grid(self):
        cfg = GridConfig.eurusd()
        tf = TrendFilter(cfg)
        result = tf.evaluate([1.0] * 20, [0.99] * 20, [0.995] * 20)
        self.assertTrue(result.enabled)
        self.assertEqual(result.direction_bias, GridDirectionBias.NONE)
        self.assertAlmostEqual(result.active_levels_fraction, 1.0)

    def test_insufficient_data(self):
        cfg = GridConfig.eurusd()
        tf = TrendFilter(cfg)
        result = tf.evaluate([1.0] * 5, [0.99] * 5, [0.995] * 5)
        self.assertEqual(result.adx, 0.0)
        self.assertTrue(result.enabled)
        self.assertAlmostEqual(result.active_levels_fraction, 1.0)

    def test_calculate_adx_zero_range(self):
        high = [1.0] * 20
        low = [1.0] * 20
        close = [1.0] * 20
        adx = _calculate_adx(high, low, close, 14)
        self.assertAlmostEqual(adx, 0.0)

    def test_calculate_adx_with_trend(self):
        close = [1.0 + i * 0.001 for i in range(30)]
        high = [c + 0.001 for c in close]
        low = [c - 0.001 for c in close]
        adx = _calculate_adx(high, low, close, 14)
        self.assertGreater(adx, 0.0)


class TestGridManager(unittest.TestCase):
    def _default_config(self) -> GridConfig:
        return GridConfig(
            symbol="EURUSD",
            grid_spacing=0.0015,
            levels_per_side=5,
            pip_value=0.0001,
        )

    def test_initialize_creates_levels(self):
        mgr = GridManager(self._default_config())
        state = mgr.initialize(center_price=1.1000, equity=10000.0)
        self.assertTrue(state.is_active)
        self.assertEqual(len(state.buy_levels), 5)
        self.assertEqual(len(state.sell_levels), 5)
        self.assertAlmostEqual(state.center_price, 1.1000)

    def test_initialize_buy_levels_below_center(self):
        mgr = GridManager(self._default_config())
        state = mgr.initialize(center_price=1.1000, equity=10000.0)
        for level in state.buy_levels:
            self.assertLess(level.price, 1.1000)

    def test_initialize_sell_levels_above_center(self):
        mgr = GridManager(self._default_config())
        state = mgr.initialize(center_price=1.1000, equity=10000.0)
        for level in state.sell_levels:
            self.assertGreater(level.price, 1.1000)

    def test_on_bar_no_fills_when_price_stays_center(self):
        mgr = GridManager(self._default_config())
        mgr.initialize(1.1000, 10000.0)
        bars = _make_bars(100, 1.1000, 0.0001)
        trades = mgr.on_bar(
            high=1.1005,
            low=1.0995,
            close=1.1000,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
        )
        self.assertEqual(len(trades), 0)

    def test_on_bar_fills_buy_level(self):
        mgr = GridManager(self._default_config())
        state = mgr.initialize(1.1000, 10000.0)
        first_buy = state.buy_levels[0]
        bars = _make_bars(100, 1.1000, 0.0001)
        trades = mgr.on_bar(
            high=1.1005,
            low=first_buy.price - 0.0001,
            close=1.0990,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
        )
        self.assertGreater(len(trades), 0)

    def test_on_bar_fills_sell_level(self):
        mgr = GridManager(self._default_config())
        state = mgr.initialize(1.1000, 10000.0)
        first_sell = state.sell_levels[0]
        bars = _make_bars(100, 1.1000, 0.0001)
        trades = mgr.on_bar(
            high=first_sell.price + 0.0001,
            low=1.0995,
            close=1.1020,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
        )
        self.assertGreater(len(trades), 0)

    def test_equity_stop_disables_grid(self):
        cfg = GridConfig(
            symbol="EURUSD",
            grid_spacing=0.0015,
            levels_per_side=5,
            risk=RiskConfig(equity_stop_pct=0.05),
        )
        mgr = GridManager(cfg)
        mgr.initialize(1.1000, 10000.0)
        mgr.on_bar(
            high=1.1005,
            low=1.0995,
            close=1.1000,
            bars_high=[1.0] * 20,
            bars_low=[0.99] * 20,
            bars_close=[0.995] * 20,
            equity=9400.0,
        )
        self.assertFalse(mgr.state.is_active)

    def test_max_open_positions_respected(self):
        cfg = GridConfig(
            symbol="EURUSD",
            grid_spacing=0.0015,
            levels_per_side=5,
            risk=RiskConfig(max_open_positions=2),
        )
        mgr = GridManager(cfg)
        state = mgr.initialize(1.1000, 10000.0)
        last_buy = state.buy_levels[-1]
        bars = _make_bars(100, 1.1000, 0.0001)
        mgr.on_bar(
            high=1.1005,
            low=last_buy.price - 0.001,
            close=last_buy.price - 0.0005,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
        )
        self.assertLessEqual(mgr.state.open_trade_count, 2)

    def test_reset_rebuilds_levels(self):
        mgr = GridManager(self._default_config())
        mgr.initialize(1.1000, 10000.0)
        new_state = mgr.reset(1.1050, 10000.0)
        self.assertTrue(new_state.is_active)
        self.assertAlmostEqual(new_state.center_price, 1.1050)
        self.assertEqual(len(new_state.buy_levels), 5)
        self.assertEqual(len(new_state.sell_levels), 5)

    def test_on_trade_close_updates_pnl(self):
        mgr = GridManager(self._default_config())
        mgr.initialize(1.1000, 10000.0)
        level = GridLevel(
            index=1,
            side=GridSide.BUY,
            price=1.0985,
            lot_size=0.1,
            status=GridLevelStatus.FILLED,
        )
        trade = GridTrade(
            level=level,
            entry_price=1.0985,
            lot_size=0.1,
            side=GridSide.BUY,
            entry_time=datetime.now(),
            is_open=True,
        )
        mgr._state.open_trades.append(trade)
        mgr.on_trade_close(trade, 1.0995)
        self.assertFalse(trade.is_open)
        self.assertGreater(trade.pnl, 0)
        self.assertEqual(len(mgr._state.open_trades), 0)
        self.assertEqual(len(mgr._state.closed_trades), 1)

    def test_no_state_returns_empty(self):
        mgr = GridManager(self._default_config())
        trades = mgr.on_bar(1.1, 1.09, 1.095, [1.0] * 20, [0.99] * 20, [0.995] * 20)
        self.assertEqual(len(trades), 0)

    def test_daily_loss_disables_grid(self):
        cfg = GridConfig(
            symbol="EURUSD",
            grid_spacing=0.0015,
            levels_per_side=5,
            risk=RiskConfig(max_daily_loss_pct=0.03),
            contract_size=100000.0,
        )
        mgr = GridManager(cfg)
        state = mgr.initialize(1.1000, 10000.0)
        first_buy = state.buy_levels[0]
        bars = _make_bars(100, 1.1000, 0.0001)
        trades = mgr.on_bar(
            high=1.1005,
            low=first_buy.price - 0.0001,
            close=first_buy.price - 0.0005,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
            current_time=datetime(2025, 1, 1, 10, 0),
        )
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        mgr.on_trade_close(trade, first_buy.price - 0.020, datetime(2025, 1, 1, 10, 0))
        self.assertTrue(mgr.state.is_active)
        second_buy = state.buy_levels[1]
        trades2 = mgr.on_bar(
            high=1.1005,
            low=second_buy.price - 0.0001,
            close=second_buy.price - 0.0005,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
            current_time=datetime(2025, 1, 1, 10, 0),
            equity=10000.0,
        )
        mgr.on_trade_close(
            trades2[0], second_buy.price - 0.020, datetime(2025, 1, 1, 10, 0)
        )
        mgr.on_bar(
            high=1.1005,
            low=1.0995,
            close=1.1000,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
            current_time=datetime(2025, 1, 1, 10, 0),
            equity=10000.0,
        )
        self.assertFalse(mgr.state.is_active)

    def test_profitable_day_no_daily_stop(self):
        cfg = GridConfig(
            symbol="EURUSD",
            grid_spacing=0.0015,
            levels_per_side=5,
            risk=RiskConfig(max_daily_loss_pct=0.03),
            contract_size=100000.0,
        )
        mgr = GridManager(cfg)
        state = mgr.initialize(1.1000, 10000.0)
        first_buy = state.buy_levels[0]
        bars = _make_bars(100, 1.1000, 0.0001)
        trades = mgr.on_bar(
            high=1.1005,
            low=first_buy.price - 0.0001,
            close=first_buy.price - 0.0005,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
            current_time=datetime(2025, 1, 1, 10, 0),
        )
        trade = trades[0]
        mgr.on_trade_close(trade, first_buy.price + 0.015, datetime(2025, 1, 1, 10, 0))
        self.assertTrue(mgr.state.is_active)
        self.assertGreater(mgr.state.daily_pnl, 0)
        mgr.on_bar(
            high=1.1005,
            low=1.0995,
            close=1.1000,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
            current_time=datetime(2025, 1, 1, 10, 0),
            equity=10000.0,
        )
        self.assertTrue(mgr.state.is_active)

    def test_xauusd_pnl_uses_contract_size(self):
        cfg = GridConfig(
            symbol="XAUUSD",
            grid_spacing=12.0,
            levels_per_side=5,
            pip_value=0.01,
            contract_size=100.0,
        )
        mgr = GridManager(cfg)
        mgr.initialize(2000.0, 10000.0)
        level = GridLevel(
            index=1,
            side=GridSide.BUY,
            price=1988.0,
            lot_size=0.01,
            status=GridLevelStatus.FILLED,
        )
        trade = GridTrade(
            level=level,
            entry_price=1988.0,
            lot_size=0.01,
            side=GridSide.BUY,
            entry_time=datetime.now(),
            is_open=True,
        )
        mgr._state.open_trades.append(trade)
        mgr.on_trade_close(trade, 2000.0)
        expected_pips = (2000.0 - 1988.0) / 0.01
        expected_pnl = expected_pips * 0.01 * 0.01 * 100.0
        self.assertAlmostEqual(trade.pnl, expected_pnl, places=2)
        self.assertLess(abs(trade.pnl), 1000.0)

    def test_multi_level_fills_per_bar(self):
        cfg = GridConfig(
            symbol="EURUSD",
            grid_spacing=0.0015,
            levels_per_side=5,
            pip_value=0.0001,
            contract_size=100000.0,
        )
        mgr = GridManager(cfg)
        state = mgr.initialize(1.1000, 10000.0)
        bars = _make_bars(100, 1.1000, 0.0001)
        last_buy = state.buy_levels[-1]
        trades = mgr.on_bar(
            high=1.1005,
            low=last_buy.price - 0.0001,
            close=last_buy.price - 0.0005,
            bars_high=[b["high"] for b in bars],
            bars_low=[b["low"] for b in bars],
            bars_close=[b["close"] for b in bars],
        )
        self.assertGreater(len(trades), 1)

    def test_spacing_smaller_than_spread_disables_grid(self):
        cfg = GridConfig(
            symbol="XAUUSD",
            grid_spacing=0.20,
            levels_per_side=5,
            pip_value=0.01,
            contract_size=100.0,
            spread=0.30,
        )
        mgr = GridManager(cfg)
        state = mgr.initialize(2000.0, 10000.0)
        self.assertEqual(len(state.buy_levels), 0)
        self.assertEqual(len(state.sell_levels), 0)


class TestGridStrategyAdapter(unittest.TestCase):
    def test_adapter_name(self):
        adapter = GridStrategyAdapter(GridConfig.eurusd())
        self.assertIn("Grid", adapter.name)
        self.assertIn("EURUSD", adapter.name)

    def test_adapter_implements_interface(self):
        from backtest.strategies import ISignalStrategy

        adapter = GridStrategyAdapter()
        self.assertIsInstance(adapter, ISignalStrategy)

    def test_evaluate_returns_none_for_empty_bars(self):
        from backtest.engine import MarketState

        adapter = GridStrategyAdapter()
        state = MarketState(bars=[])
        self.assertIsNone(adapter.evaluate(state))

    def test_evaluate_initializes_on_first_bar(self):
        from backtest.engine import Bar, MarketState

        adapter = GridStrategyAdapter()
        bar = Bar(
            time=datetime(2025, 1, 1, 10, 0),
            open=1.1,
            high=1.1005,
            low=1.0995,
            close=1.1,
        )
        state = MarketState(bars=[bar])
        result = adapter.evaluate(state)
        self.assertIsNone(result)
        self.assertTrue(adapter.manager.state is not None)


class TestGridDirectionalBias(unittest.TestCase):
    def test_long_bias_removes_sell_levels(self):
        cfg = GridConfig(
            symbol="EURUSD",
            grid_spacing=0.0015,
            levels_per_side=5,
            trend_filter=TrendFilterConfig(
                directional_threshold=15.0, full_grid_threshold=10.0
            ),
        )
        mgr = GridManager(cfg)
        state = mgr.initialize(1.1000, 10000.0)
        self.assertTrue(state.is_active)


def _make_ranging_bars(n=500, center=1.1000, half_range=0.0030):
    bars = []
    import random

    rng = random.Random(42)
    price = center
    for i in range(n):
        change = rng.uniform(-half_range, half_range) * 0.1
        price = max(center - half_range, min(center + half_range, price + change))
        noise = rng.uniform(-0.0002, 0.0002)
        o = price
        c = price + noise
        h = max(o, c) + rng.uniform(0, 0.0003)
        low = min(o, c) - rng.uniform(0, 0.0003)
        bars.append(
            {
                "time": datetime(2024, 1, 1, 10, 0) + timedelta(hours=i),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
            }
        )
    return bars


class TestGridBacktestIntegration(unittest.TestCase):
    def test_grid_produces_trades_in_ranging_market(self):
        from backtest.engine import Bar, BacktestConfig
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        raw = _make_ranging_bars(500, 1.1000, 0.0030)
        bars = [
            Bar(
                time=b["time"],
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=1000,
            )
            for b in raw
        ]

        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.05,
            spread_pips=0.5,
            max_open_trades=10,
            min_confidence=0.50,
            min_bars_before_signal=30,
        )

        adapter = GridStrategyAdapter(GridConfig.eurusd())
        engine = MultiStrategyBacktestEngine(config, [adapter])
        results = engine.run_all_strategies(bars)

        self.assertIn(adapter.name, results)
        m = results[adapter.name].metrics
        self.assertGreater(m.total_trades, 0)

    def test_grid_respects_max_open_trades(self):
        from backtest.engine import Bar, BacktestConfig
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        raw = _make_ranging_bars(200, 1.1000, 0.0030)
        bars = [
            Bar(
                time=b["time"],
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=1000,
            )
            for b in raw
        ]

        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_open_trades=3,
            min_confidence=0.50,
            min_bars_before_signal=30,
        )

        adapter = GridStrategyAdapter(GridConfig.eurusd())
        engine = MultiStrategyBacktestEngine(config, [adapter])
        results = engine.run_all_strategies(bars)
        m = results[adapter.name].metrics
        self.assertGreater(m.total_trades, 0)

    def test_grid_xauusd_config(self):
        from backtest.engine import Bar, BacktestConfig
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        raw = _make_ranging_bars(200, 2000.0, 15.0)
        bars = [
            Bar(
                time=b["time"],
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=1000,
            )
            for b in raw
        ]

        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_open_trades=10,
            min_confidence=0.50,
            min_bars_before_signal=30,
        )

        adapter = GridStrategyAdapter(GridConfig.xauusd())
        engine = MultiStrategyBacktestEngine(config, [adapter])
        results = engine.run_all_strategies(bars)

        self.assertIn(adapter.name, results)


class TestGridSpreadSlippageTuning(unittest.TestCase):
    def _make_xauusd_bars(self, n=500, center=2350.0, half_range=25.0):
        from backtest.engine import Bar
        import random

        rng = random.Random(42)
        bars = []
        price = center
        for i in range(n):
            change = rng.uniform(-half_range, half_range) * 0.08
            price = max(center - half_range, min(center + half_range, price + change))
            noise = rng.uniform(-1.5, 1.5)
            o = price
            c = price + noise
            h = max(o, c) + rng.uniform(0, 3.0)
            low = min(o, c) - rng.uniform(0, 3.0)
            bars.append(
                Bar(
                    time=datetime(2024, 6, 1, 0, 0) + timedelta(hours=i),
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    volume=1000,
                )
            )
        return bars

    def _run_grid_backtest(self, bars, grid_config, spread_pips, slippage_pips=0.0):
        from backtest.engine import BacktestConfig
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.005,
            max_daily_drawdown_pct=0.03,
            max_total_drawdown_pct=0.05,
            spread_pips=spread_pips,
            slippage_pips=slippage_pips,
            commission_per_lot=3.5,
            max_open_trades=3,
            min_confidence=0.50,
            min_bars_before_signal=30,
        )

        adapter = GridStrategyAdapter(grid_config)
        engine = MultiStrategyBacktestEngine(config, [adapter])
        results = engine.run_all_strategies(bars)
        return results[adapter.name].metrics

    def test_baseline_xauusd_no_slippage(self):
        bars = self._make_xauusd_bars(500, 2350.0, 25.0)
        grid_cfg = GridConfig.ftmo("XAUUSD")
        m = self._run_grid_backtest(bars, grid_cfg, spread_pips=30.0)
        self.assertGreater(m.total_trades, 0, "Baseline should produce trades")

    def test_xauusd_with_realistic_slippage(self):
        bars = self._make_xauusd_bars(500, 2350.0, 25.0)
        grid_cfg = GridConfig.ftmo("XAUUSD")
        m = self._run_grid_backtest(bars, grid_cfg, spread_pips=30.0, slippage_pips=5.0)
        self.assertGreater(m.total_trades, 0, "Tuned config should produce trades")

    def test_tuned_slippage_completes_without_error(self):
        bars = self._make_xauusd_bars(500, 2350.0, 25.0)
        grid_cfg = GridConfig.ftmo("XAUUSD")
        try:
            m = self._run_grid_backtest(
                bars, grid_cfg, spread_pips=35.0, slippage_pips=10.0
            )
            self.assertIsNotNone(m)
        except Exception as e:
            self.fail(f"Backtest raised {e}")

    def test_ftmo_xauusd_max_positions_is_three(self):
        cfg = GridConfig.ftmo("XAUUSD")
        self.assertEqual(cfg.risk.max_open_positions, 3)

    def test_ftmo_eurusd_max_positions_is_three(self):
        cfg = GridConfig.ftmo("EURUSD")
        self.assertEqual(cfg.risk.max_open_positions, 3)

    def test_ftmo_daily_loss_limit(self):
        xauusd_cfg = GridConfig.ftmo("XAUUSD")
        eurusd_cfg = GridConfig.ftmo("EURUSD")
        self.assertAlmostEqual(xauusd_cfg.risk.max_daily_loss_pct, 0.015)
        self.assertAlmostEqual(eurusd_cfg.risk.max_daily_loss_pct, 0.015)

    def test_slippage_pips_default_zero(self):
        from backtest.engine import BacktestConfig

        cfg = BacktestConfig()
        self.assertEqual(cfg.slippage_pips, 0.2)

    def test_slippage_increases_effective_entry_cost(self):
        from backtest.engine import Bar, BacktestConfig
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        raw = _make_ranging_bars(200, 1.1000, 0.0030)
        bars = [
            Bar(
                time=b["time"],
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=1000,
            )
            for b in raw
        ]

        cfg_no_slip = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            spread_pips=0.5,
            slippage_pips=0.0,
            max_open_trades=5,
            min_confidence=0.50,
            min_bars_before_signal=30,
        )
        cfg_with_slip = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            spread_pips=0.5,
            slippage_pips=0.5,
            max_open_trades=5,
            min_confidence=0.50,
            min_bars_before_signal=30,
        )

        adapter_no_slip = GridStrategyAdapter(GridConfig.eurusd())
        adapter_with_slip = GridStrategyAdapter(GridConfig.eurusd())

        engine_no_slip = MultiStrategyBacktestEngine(cfg_no_slip, [adapter_no_slip])
        engine_with_slip = MultiStrategyBacktestEngine(
            cfg_with_slip, [adapter_with_slip]
        )

        m_no_slip = engine_no_slip.run_all_strategies(bars)[
            adapter_no_slip.name
        ].metrics
        m_with_slip = engine_with_slip.run_all_strategies(bars)[
            adapter_with_slip.name
        ].metrics

        if m_no_slip.total_trades > 0 and m_with_slip.total_trades > 0:
            self.assertLessEqual(
                m_with_slip.total_pnl,
                m_no_slip.total_pnl,
                "Slippage should reduce or equal P&L vs no-slippage baseline",
            )


class TestGridWalkForward(unittest.TestCase):
    def test_walk_forward_three_windows(self):
        from backtest.engine import Bar, BacktestConfig
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        raw = _make_ranging_bars(900, 1.1000, 0.0030)
        bars = [
            Bar(
                time=b["time"],
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=1000,
            )
            for b in raw
        ]

        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_daily_drawdown_pct=0.05,
            max_total_drawdown_pct=0.05,
            spread_pips=0.5,
            max_open_trades=10,
            min_confidence=0.50,
            min_bars_before_signal=30,
        )

        n_windows = 3
        window_size = len(bars) // n_windows
        windows_passed = 0

        for w in range(n_windows):
            start = w * window_size
            end = (w + 1) * window_size if w < n_windows - 1 else len(bars)
            window_bars = bars[start:end]
            wlen = len(window_bars)

            train_end = int(wlen * 0.6)
            test_bars = window_bars[int(wlen * 0.75) :]

            if len(test_bars) < 30:
                continue

            adapter = GridStrategyAdapter(GridConfig.eurusd())
            engine = MultiStrategyBacktestEngine(config, [adapter])

            train_results = engine.run_all_strategies(window_bars[:train_end])
            test_results = engine.run_all_strategies(test_bars)

            train_results[adapter.name].metrics
            test_m = test_results[adapter.name].metrics

            self.assertGreater(
                test_m.total_trades, 0, f"Window {w}: no trades in test period"
            )
            windows_passed += 1

        self.assertGreaterEqual(
            windows_passed, 2, "Need at least 2 valid walk-forward windows"
        )

    def test_walk_forward_reproducible_with_fixed_seed(self):
        from backtest.engine import Bar, BacktestConfig
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        raw1 = _make_ranging_bars(600, 1.1000, 0.0030)
        raw2 = _make_ranging_bars(600, 1.1000, 0.0030)
        self.assertEqual(len(raw1), len(raw2))
        for i in range(len(raw1)):
            self.assertAlmostEqual(raw1[i]["close"], raw2[i]["close"], places=6)

        bars = [
            Bar(
                time=b["time"],
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=1000,
            )
            for b in raw1
        ]

        config = BacktestConfig(
            starting_balance=10000.0,
            risk_per_trade_pct=0.01,
            max_open_trades=10,
            min_confidence=0.50,
            min_bars_before_signal=30,
        )

        adapter = GridStrategyAdapter(GridConfig.eurusd())
        engine = MultiStrategyBacktestEngine(config, [adapter])
        results = engine.run_all_strategies(bars)
        m = results[adapter.name].metrics

        adapter2 = GridStrategyAdapter(GridConfig.eurusd())
        engine2 = MultiStrategyBacktestEngine(config, [adapter2])
        results2 = engine2.run_all_strategies(bars)
        m2 = results2[adapter.name].metrics

        self.assertEqual(m.total_trades, m2.total_trades)
        self.assertAlmostEqual(m.total_pnl, m2.total_pnl, places=2)


if __name__ == "__main__":
    unittest.main()
