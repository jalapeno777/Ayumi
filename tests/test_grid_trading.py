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
        bars.append({
            "time": datetime(2025, 1, 1, 10, 0) + timedelta(hours=i),
            "open": price - volatility * 0.5,
            "high": price + volatility,
            "low": price - volatility,
            "close": price,
        })
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
        self.assertEqual(cfg.risk.max_daily_loss_pct, 0.03)
        self.assertEqual(cfg.risk.max_open_positions, 10)

    def test_ftmo_preset_xauusd(self):
        cfg = GridConfig.ftmo("XAUUSD")
        self.assertEqual(cfg.symbol, "XAUUSD")
        self.assertEqual(cfg.pip_value, 0.01)

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
        t1 = GridTrade(level=None, entry_price=1.1, lot_size=0.1, side=GridSide.BUY, entry_time=datetime.now(), is_open=False, pnl=10.0)
        t2 = GridTrade(level=None, entry_price=1.1, lot_size=0.1, side=GridSide.BUY, entry_time=datetime.now(), is_open=False, pnl=-5.0)
        t3 = GridTrade(level=None, entry_price=1.1, lot_size=0.1, side=GridSide.BUY, entry_time=datetime.now(), is_open=False, pnl=8.0)
        state.closed_trades = [t1, t2, t3]
        self.assertAlmostEqual(state.win_rate, 2 / 3)

    def test_active_levels(self):
        state = GridState(
            center_price=1.1,
            buy_levels=[
                GridLevel(index=1, side=GridSide.BUY, price=1.0985, lot_size=0.1, status=GridLevelStatus.ACTIVE),
                GridLevel(index=2, side=GridSide.BUY, price=1.0970, lot_size=0.08, status=GridLevelStatus.FILLED),
            ],
            sell_levels=[
                GridLevel(index=1, side=GridSide.SELL, price=1.1015, lot_size=0.1, status=GridLevelStatus.ACTIVE),
                GridLevel(index=2, side=GridSide.SELL, price=1.1030, lot_size=0.08, status=GridLevelStatus.CANCELLED),
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
            high=1.1005, low=1.0995, close=1.1000,
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
            high=1.1005, low=first_buy.price - 0.0001, close=1.0990,
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
            high=first_sell.price + 0.0001, low=1.0995, close=1.1020,
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
            high=1.1005, low=1.0995, close=1.1000,
            bars_high=[1.0] * 20, bars_low=[0.99] * 20, bars_close=[0.995] * 20,
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
            high=1.1005, low=last_buy.price - 0.001, close=last_buy.price - 0.0005,
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
        level = GridLevel(index=1, side=GridSide.BUY, price=1.0985, lot_size=0.1, status=GridLevelStatus.FILLED)
        trade = GridTrade(
            level=level, entry_price=1.0985, lot_size=0.1,
            side=GridSide.BUY, entry_time=datetime.now(), is_open=True,
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
        bar = Bar(time=datetime(2025, 1, 1, 10, 0), open=1.1, high=1.1005, low=1.0995, close=1.1)
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
            trend_filter=TrendFilterConfig(directional_threshold=15.0, full_grid_threshold=10.0),
        )
        mgr = GridManager(cfg)
        state = mgr.initialize(1.1000, 10000.0)
        self.assertTrue(state.is_active)


if __name__ == "__main__":
    unittest.main()
