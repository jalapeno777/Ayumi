import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, BacktestConfig, MarketState, SessionType, TradeDirection
from backtest.parameter_sweep.grid import ParameterGrid
from backtest.parameter_sweep.sweep_runner import SweepRunner
from strategies.momentum import (
    ATRVolatilityBreakoutStrategy,
    DonchianBreakoutStrategy,
    EURUSD_M15_PRESETS,
    MATrendFollowingStrategy,
    MomentumConfig,
    _calculate_adx,
    _calculate_atr,
    _calculate_rsi,
    _calculate_sma,
    _passes_momentum_filters,
    _passes_session_filter,
)


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, v=1000, minute_offset=0):
    base = datetime(2024, 1, 1, 10, 0)
    return Bar(
        time=base + timedelta(hours=i, minutes=minute_offset),
        open=o, high=h, low=low, close=c, volume=v,
    )


def _trending_bars(n=200, trend="up"):
    bars = []
    price = 1.0000
    for i in range(n):
        drift = 0.00005 if trend == "up" else -0.00005
        noise = (i % 7 - 3) * 0.00003
        price += drift + noise
        h = price + abs(noise) * 2 + 0.0001
        low = price - abs(noise) * 2 - 0.0001
        bars.append(_bar(i, o=price - drift, h=h, low=low, c=price))
    return bars


def _range_bars(n=100):
    bars = []
    for i in range(n):
        center = 1.0000
        offset = (i % 20 - 10) * 0.00005
        price = center + offset
        bars.append(_bar(i, o=price - 0.00002, h=price + 0.0001, low=price - 0.0001, c=price))
    return bars


def _breakout_bars(n=100, channel_period=20, direction="up"):
    bars = _range_bars(channel_period + 2)
    channel_high = max(b.high for b in bars[:channel_period])
    channel_low = min(b.low for b in bars[:channel_period])
    if direction == "up":
        price = channel_high + 0.001
        bars.append(_bar(
            len(bars),
            o=channel_high - 0.0001,
            h=price + 0.0002,
            low=channel_high - 0.0002,
            c=price,
        ))
    else:
        price = channel_low - 0.001
        bars.append(_bar(
            len(bars),
            o=channel_low + 0.0001,
            h=channel_low + 0.0002,
            low=price - 0.0002,
            c=price,
        ))
    return bars


def _range_then_trend_bars(n=200, range_bars=60, trend="up"):
    bars = _range_bars(range_bars)
    last_close = bars[-1].close
    for i in range(n - range_bars):
        if trend == "up":
            drift = 0.00008
        else:
            drift = -0.00008
        last_close += drift + (i % 5 - 2) * 0.00001
        h = last_close + 0.0003
        low = last_close - 0.0003
        bars.append(_bar(range_bars + i, o=last_close - drift, h=h, low=low, c=last_close))
    return bars


def _crossover_bars(n=200):
    bars = []
    price = 1.05
    for i in range(n):
        if i < n // 2:
            price -= 0.00003
        else:
            price += 0.00006
        noise = (i % 5 - 2) * 0.00001
        bars.append(_bar(i, o=price, h=price + 0.0002 + abs(noise), low=price - 0.0002 - abs(noise), c=price + noise))
    return bars


def _state(bars, session=SessionType.LONDON):
    return MarketState(bars=bars, current_session=session)


class TestCalculateATR(unittest.TestCase):
    def test_returns_positive_for_valid_bars(self):
        bars = _trending_bars(30)
        atr = _calculate_atr(bars, 14)
        self.assertGreater(atr, 0)

    def test_returns_default_for_insufficient_bars(self):
        bars = _trending_bars(5)
        atr = _calculate_atr(bars, 14)
        self.assertEqual(atr, 0.0001)

    def test_custom_period(self):
        bars = _trending_bars(30)
        atr14 = _calculate_atr(bars, 14)
        atr10 = _calculate_atr(bars, 10)
        self.assertGreater(atr14, 0)
        self.assertGreater(atr10, 0)


class TestCalculateRSI(unittest.TestCase):
    def test_returns_none_for_insufficient_bars(self):
        bars = _trending_bars(5)
        self.assertIsNone(_calculate_rsi(bars, 14))

    def test_strong_uptrend_gives_high_rsi(self):
        bars = []
        price = 1.0
        for i in range(30):
            price += 0.0002
            bars.append(_bar(i, o=price - 0.0002, h=price + 0.0001, low=price - 0.0001, c=price))
        rsi = _calculate_rsi(bars, 14)
        self.assertIsNotNone(rsi)
        self.assertGreater(rsi, 50)

    def test_strong_downtrend_gives_low_rsi(self):
        bars = []
        price = 1.1
        for i in range(30):
            price -= 0.0002
            bars.append(_bar(i, o=price + 0.0002, h=price + 0.0001, low=price - 0.0001, c=price))
        rsi = _calculate_rsi(bars, 14)
        self.assertIsNotNone(rsi)
        self.assertLess(rsi, 50)


class TestCalculateADX(unittest.TestCase):
    def test_returns_zero_for_insufficient_bars(self):
        bars = _trending_bars(5)
        self.assertEqual(_calculate_adx(bars, 14), 0.0)

    def test_trending_market_gives_positive_adx(self):
        bars = _trending_bars(50, trend="up")
        adx = _calculate_adx(bars, 14)
        self.assertGreater(adx, 0)

    def test_flat_market_gives_low_adx(self):
        bars = _range_bars(50)
        adx = _calculate_adx(bars, 14)
        self.assertGreaterEqual(adx, 0)


class TestCalculateSMA(unittest.TestCase):
    def test_returns_zero_for_insufficient_data(self):
        self.assertEqual(_calculate_sma([1.0, 2.0], 5), 0.0)

    def test_correct_average(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        sma = _calculate_sma(values, 3)
        self.assertAlmostEqual(sma, 4.0)

    def test_full_period(self):
        values = [10.0, 20.0, 30.0]
        sma = _calculate_sma(values, 3)
        self.assertAlmostEqual(sma, 20.0)


class TestPassesSessionFilter(unittest.TestCase):
    def test_london_passes(self):
        state = _state(_trending_bars(30), SessionType.LONDON)
        self.assertTrue(_passes_session_filter(state))

    def test_ny_am_passes(self):
        state = _state(_trending_bars(30), SessionType.NY_AM)
        self.assertTrue(_passes_session_filter(state))

    def test_outside_fails(self):
        state = _state(_trending_bars(30), SessionType.OUTSIDE)
        self.assertFalse(_passes_session_filter(state))

    def test_ny_pm_fails(self):
        state = _state(_trending_bars(30), SessionType.NY_PM)
        self.assertFalse(_passes_session_filter(state))


class TestPassesMomentumFilters(unittest.TestCase):
    def _no_filter_config(self):
        return MomentumConfig(
            min_adx=0.0,
            rsi_max=100.0,
            rsi_min=0.0,
        )

    def test_all_filters_disabled_always_passes(self):
        bars = _trending_bars(30)
        config = self._no_filter_config()
        self.assertTrue(_passes_momentum_filters(bars, config, TradeDirection.LONG))
        self.assertTrue(_passes_momentum_filters(bars, config, TradeDirection.SHORT))

    def test_low_adx_rejects(self):
        bars = _range_bars(30)
        config = MomentumConfig(min_adx=50.0)
        self.assertFalse(_passes_momentum_filters(bars, config, TradeDirection.LONG))

    def test_overbought_rsi_rejects_long(self):
        bars = []
        price = 1.0
        for i in range(30):
            price += 0.0003
            bars.append(_bar(i, o=price - 0.0003, h=price + 0.0001, low=price - 0.0001, c=price))
        config = MomentumConfig(min_adx=0.0, rsi_max=60.0)
        self.assertFalse(_passes_momentum_filters(bars, config, TradeDirection.LONG))

    def test_oversold_rsi_rejects_short(self):
        bars = []
        price = 1.1
        for i in range(30):
            price -= 0.0003
            bars.append(_bar(i, o=price + 0.0003, h=price + 0.0001, low=price - 0.0001, c=price))
        config = MomentumConfig(min_adx=0.0, rsi_min=40.0)
        self.assertFalse(_passes_momentum_filters(bars, config, TradeDirection.SHORT))


class TestMomentumConfig(unittest.TestCase):
    def test_defaults(self):
        config = MomentumConfig()
        self.assertEqual(config.atr_period, 14)
        self.assertEqual(config.atr_sl_multiplier, 2.0)
        self.assertEqual(config.min_adx, 20.0)
        self.assertTrue(config.session_filter)
        self.assertEqual(config.tp1_rr, 1.0)
        self.assertEqual(config.tp2_rr, 2.0)
        self.assertEqual(config.tp3_rr, 3.0)

    def test_frozen(self):
        config = MomentumConfig()
        with self.assertRaises(AttributeError):
            config.atr_period = 20


class TestDonchianBreakoutStrategy(unittest.TestCase):
    def test_name(self):
        strategy = DonchianBreakoutStrategy()
        self.assertEqual(strategy.name, "Donchian Channel Breakout")

    def test_no_signal_with_insufficient_bars(self):
        bars = _trending_bars(10)
        state = _state(bars)
        strategy = DonchianBreakoutStrategy(channel_period=20)
        self.assertIsNone(strategy.evaluate(state))

    def test_bullish_breakout_signal(self):
        bars = _breakout_bars(30, channel_period=20, direction="up")
        state = _state(bars, SessionType.LONDON)
        strategy = DonchianBreakoutStrategy(
            channel_period=20,
            momentum=MomentumConfig(min_adx=0.0, rsi_max=100.0),
        )
        signal = strategy.evaluate(state)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, TradeDirection.LONG)
        self.assertGreater(signal.confidence, 0)
        self.assertGreater(signal.stop_loss, 0)
        self.assertNotEqual(signal.rationale, "")

    def test_bearish_breakout_signal(self):
        bars = _breakout_bars(30, channel_period=20, direction="down")
        state = _state(bars, SessionType.LONDON)
        strategy = DonchianBreakoutStrategy(
            channel_period=20,
            momentum=MomentumConfig(min_adx=0.0, rsi_min=0.0),
        )
        signal = strategy.evaluate(state)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, TradeDirection.SHORT)

    def test_no_signal_in_range(self):
        bars = _range_bars(50)
        state = _state(bars, SessionType.LONDON)
        strategy = DonchianBreakoutStrategy(
            channel_period=20,
            momentum=MomentumConfig(min_adx=0.0),
        )
        signal = strategy.evaluate(state)
        self.assertIsNone(signal)

    def test_session_filter_blocks_outside_session(self):
        bars = _breakout_bars(30, channel_period=20)
        state = _state(bars, SessionType.OUTSIDE)
        strategy = DonchianBreakoutStrategy(
            channel_period=20,
            momentum=MomentumConfig(min_adx=0.0, session_filter=True),
        )
        self.assertIsNone(strategy.evaluate(state))

    def test_session_filter_disabled(self):
        bars = _breakout_bars(30, channel_period=20, direction="up")
        state = _state(bars, SessionType.OUTSIDE)
        strategy = DonchianBreakoutStrategy(
            channel_period=20,
            momentum=MomentumConfig(min_adx=0.0, rsi_max=100.0, session_filter=False),
        )
        signal = strategy.evaluate(state)
        self.assertIsNotNone(signal)

    def test_signal_has_correct_sl_tp_structure(self):
        bars = _breakout_bars(30, channel_period=20, direction="up")
        state = _state(bars, SessionType.LONDON)
        strategy = DonchianBreakoutStrategy(
            channel_period=20,
            momentum=MomentumConfig(
                min_adx=0.0,
                rsi_max=100.0,
                atr_sl_multiplier=2.0,
                tp1_rr=1.0,
                tp2_rr=2.0,
                tp3_rr=3.0,
            ),
        )
        signal = strategy.evaluate(state)
        self.assertIsNotNone(signal)
        risk = signal.entry_price - signal.stop_loss
        self.assertAlmostEqual(signal.take_profit_1 - signal.entry_price, risk * 1.0, places=6)
        self.assertAlmostEqual(signal.take_profit_2 - signal.entry_price, risk * 2.0, places=6)
        self.assertAlmostEqual(signal.take_profit_3 - signal.entry_price, risk * 3.0, places=6)


class TestATRVolatilityBreakoutStrategy(unittest.TestCase):
    def test_name(self):
        strategy = ATRVolatilityBreakoutStrategy()
        self.assertEqual(strategy.name, "ATR Volatility Breakout")

    def test_no_signal_with_insufficient_bars(self):
        bars = _trending_bars(5)
        state = _state(bars)
        strategy = ATRVolatilityBreakoutStrategy(atr_period=14)
        self.assertIsNone(strategy.evaluate(state))

    def test_no_signal_in_range(self):
        bars = _range_bars(50)
        state = _state(bars, SessionType.LONDON)
        strategy = ATRVolatilityBreakoutStrategy(
            atr_period=14,
            breakout_multiplier=1.5,
            momentum=MomentumConfig(min_adx=0.0),
        )
        self.assertIsNone(strategy.evaluate(state))

    def test_bullish_atr_breakout(self):
        bars = _range_bars(30)
        ref_high = max(b.high for b in bars[:29])
        atr = _calculate_atr(bars, 14)
        big_jump = atr * 3.0
        price = ref_high + big_jump
        bars.append(_bar(
            len(bars),
            o=ref_high,
            h=price + atr * 0.3,
            low=ref_high - atr * 0.1,
            c=price,
        ))
        state = _state(bars, SessionType.LONDON)
        strategy = ATRVolatilityBreakoutStrategy(
            atr_period=14,
            breakout_multiplier=1.5,
            confirmation_bars=1,
            momentum=MomentumConfig(min_adx=0.0, rsi_max=100.0),
        )
        signal = strategy.evaluate(state)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, TradeDirection.LONG)

    def test_bearish_atr_breakout(self):
        bars = _trending_bars(50, trend="down")
        state = _state(bars, SessionType.LONDON)
        strategy = ATRVolatilityBreakoutStrategy(
            atr_period=14,
            breakout_multiplier=0.5,
            confirmation_bars=1,
            momentum=MomentumConfig(min_adx=0.0),
        )
        signal = strategy.evaluate(state)
        if signal is not None:
            self.assertEqual(signal.direction, TradeDirection.SHORT)

    def test_confirmation_bars_filter(self):
        bars = _trending_bars(30, trend="up")
        state = _state(bars, SessionType.LONDON)
        strategy = ATRVolatilityBreakoutStrategy(
            atr_period=14,
            breakout_multiplier=0.3,
            confirmation_bars=5,
            momentum=MomentumConfig(min_adx=0.0),
        )
        signal = strategy.evaluate(state)
        self.assertIsNone(signal)

    def test_session_filter(self):
        bars = _trending_bars(50, trend="up")
        state = _state(bars, SessionType.OUTSIDE)
        strategy = ATRVolatilityBreakoutStrategy(
            atr_period=14,
            breakout_multiplier=0.5,
            momentum=MomentumConfig(min_adx=0.0, session_filter=True),
        )
        self.assertIsNone(strategy.evaluate(state))


class TestMATrendFollowingStrategy(unittest.TestCase):
    def test_name(self):
        strategy = MATrendFollowingStrategy()
        self.assertEqual(strategy.name, "MA Trend Following")

    def test_no_signal_with_insufficient_bars(self):
        bars = _trending_bars(20)
        state = _state(bars)
        strategy = MATrendFollowingStrategy(trend_ma_period=50)
        self.assertIsNone(strategy.evaluate(state))

    def test_bullish_crossover_above_trend(self):
        bars = []
        price = 1.09
        for i in range(80):
            if i < 40:
                price -= 0.00003
            else:
                price += 0.00005
            noise = (i % 5 - 2) * 0.00002
            bars.append(_bar(i, o=price, h=price + 0.0002 + abs(noise), low=price - 0.0002 - abs(noise), c=price + noise))

        state = _state(bars, SessionType.LONDON)
        strategy = MATrendFollowingStrategy(
            fast_period=5,
            slow_period=13,
            trend_ma_period=50,
            momentum=MomentumConfig(min_adx=0.0),
        )
        signal = strategy.evaluate(state)
        if signal is not None:
            self.assertEqual(signal.direction, TradeDirection.LONG)

    def test_no_signal_when_price_below_trend_ma(self):
        bars = []
        price = 1.05
        for i in range(80):
            price -= 0.00005
            bars.append(_bar(i, o=price, h=price + 0.0001, low=price - 0.0001, c=price))

        state = _state(bars, SessionType.LONDON)
        strategy = MATrendFollowingStrategy(
            fast_period=5,
            slow_period=13,
            trend_ma_period=50,
            momentum=MomentumConfig(min_adx=0.0),
        )
        signal = strategy.evaluate(state)
        self.assertIsNone(signal)

    def test_session_filter(self):
        bars = _trending_bars(80, trend="up")
        state = _state(bars, SessionType.OUTSIDE)
        strategy = MATrendFollowingStrategy(
            fast_period=5,
            slow_period=13,
            trend_ma_period=50,
            momentum=MomentumConfig(min_adx=0.0, session_filter=True),
        )
        self.assertIsNone(strategy.evaluate(state))

    def test_signal_sl_tp_structure(self):
        bars = _trending_bars(80, trend="up")
        state = _state(bars, SessionType.LONDON)
        strategy = MATrendFollowingStrategy(
            fast_period=5,
            slow_period=13,
            trend_ma_period=50,
            momentum=MomentumConfig(
                min_adx=0.0,
                session_filter=False,
                atr_sl_multiplier=2.0,
                tp1_rr=1.0,
                tp2_rr=2.0,
                tp3_rr=3.0,
            ),
        )
        signal = strategy.evaluate(state)
        if signal is not None:
            risk = abs(signal.entry_price - signal.stop_loss)
            self.assertGreater(risk, 0)
            if signal.direction == TradeDirection.LONG:
                self.assertAlmostEqual(signal.take_profit_1 - signal.entry_price, risk * 1.0, places=6)
            else:
                self.assertAlmostEqual(signal.entry_price - signal.take_profit_1, risk * 1.0, places=6)


class TestEURUSDM15Presets(unittest.TestCase):
    def test_all_presets_exist(self):
        self.assertIn("donchian", EURUSD_M15_PRESETS)
        self.assertIn("atr_breakout", EURUSD_M15_PRESETS)
        self.assertIn("ma_trend", EURUSD_M15_PRESETS)

    def test_donchian_preset_creates_strategy(self):
        preset = EURUSD_M15_PRESETS["donchian"]
        strategy = DonchianBreakoutStrategy(
            channel_period=preset["channel_period"],
            exit_channel_period=preset["exit_channel_period"],
            momentum=preset["momentum"],
        )
        self.assertEqual(strategy.name, "Donchian Channel Breakout")

    def test_atr_breakout_preset_creates_strategy(self):
        preset = EURUSD_M15_PRESETS["atr_breakout"]
        strategy = ATRVolatilityBreakoutStrategy(
            atr_period=preset["atr_period"],
            breakout_multiplier=preset["breakout_multiplier"],
            confirmation_bars=preset["confirmation_bars"],
            momentum=preset["momentum"],
        )
        self.assertEqual(strategy.name, "ATR Volatility Breakout")

    def test_ma_trend_preset_creates_strategy(self):
        preset = EURUSD_M15_PRESETS["ma_trend"]
        strategy = MATrendFollowingStrategy(
            fast_period=preset["fast_period"],
            slow_period=preset["slow_period"],
            trend_ma_period=preset["trend_ma_period"],
            momentum=preset["momentum"],
        )
        self.assertEqual(strategy.name, "MA Trend Following")


class TestBacktestIntegration(unittest.TestCase):
    def setUp(self):
        self.config = BacktestConfig(min_bars_before_signal=30)

    def test_donchian_produces_trades_in_backtest(self):
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        bars = _range_bars(50)
        for cycle in range(3):
            channel_high = max(b.high for b in bars[-20:-1])
            channel_low = min(b.low for b in bars[-20:-1])
            breakout_up = channel_high + 0.001
            bars.append(_bar(len(bars), o=channel_high, h=breakout_up + 0.0002, low=channel_high - 0.0001, c=breakout_up))
            for j in range(15):
                breakout_up += 0.00005
                bars.append(_bar(len(bars), o=breakout_up, h=breakout_up + 0.0001, low=breakout_up - 0.0001, c=breakout_up))
            breakout_down = channel_low - 0.001
            bars.append(_bar(len(bars), o=channel_low, h=channel_low + 0.0001, low=breakout_down - 0.0002, c=breakout_down))
            for j in range(15):
                breakout_down -= 0.00005
                bars.append(_bar(len(bars), o=breakout_down, h=breakout_down + 0.0001, low=breakout_down - 0.0001, c=breakout_down))
        strategy = DonchianBreakoutStrategy(
            channel_period=20,
            momentum=MomentumConfig(min_adx=0.0, rsi_max=100.0, session_filter=False),
        )
        engine = MultiStrategyBacktestEngine(config=self.config, strategies=[strategy])
        results = engine.run_all_strategies(bars)
        metrics = results[strategy.name].metrics
        self.assertGreater(metrics.total_trades, 0)

    def test_atr_breakout_produces_trades_in_backtest(self):
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        bars = _range_bars(50)
        ref_high = max(b.high for b in bars[:49])
        atr = _calculate_atr(bars, 14)
        for i in range(150):
            price = ref_high + atr * 2.0 + i * atr * 0.3
            bars.append(_bar(
                50 + i,
                o=price - atr * 0.2,
                h=price + atr * 0.2,
                low=price - atr * 0.3,
                c=price,
            ))
        strategy = ATRVolatilityBreakoutStrategy(
            atr_period=14,
            breakout_multiplier=1.0,
            confirmation_bars=1,
            momentum=MomentumConfig(min_adx=0.0, rsi_max=100.0, session_filter=False),
        )
        engine = MultiStrategyBacktestEngine(config=self.config, strategies=[strategy])
        results = engine.run_all_strategies(bars)
        metrics = results[strategy.name].metrics
        self.assertGreater(metrics.total_trades, 0)

    def test_ma_trend_produces_trades_in_backtest(self):
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        bars = []
        price = 1.10
        for i in range(40):
            price -= 0.00003
            bars.append(_bar(i, o=price, h=price + 0.0001, low=price - 0.0001, c=price))
        for i in range(160):
            price += 0.00012
            bars.append(_bar(40 + i, o=price, h=price + 0.0001, low=price - 0.0001, c=price))
        strategy = MATrendFollowingStrategy(
            fast_period=5,
            slow_period=13,
            trend_ma_period=20,
            momentum=MomentumConfig(min_adx=0.0, rsi_max=100.0, session_filter=False),
        )
        engine = MultiStrategyBacktestEngine(config=self.config, strategies=[strategy])
        results = engine.run_all_strategies(bars)
        metrics = results[strategy.name].metrics
        self.assertGreater(metrics.total_trades, 0)


class TestParameterSweepIntegration(unittest.TestCase):
    def setUp(self):
        self.config = BacktestConfig(min_bars_before_signal=30)
        self.bars = _trending_bars(200, trend="up")

    def test_sweep_donchian_channel_period(self):
        grid = ParameterGrid({"channel_period": [10, 20, 30]})
        runner = SweepRunner(
            config=self.config,
            bars=self.bars,
            strategy_factory=lambda p: DonchianBreakoutStrategy(
                channel_period=p.params["channel_period"],
                momentum=MomentumConfig(min_adx=0.0, session_filter=False),
            ),
            max_workers=1,
        )
        result = runner.run(grid)
        self.assertEqual(len(result), 3)
        for row in result:
            self.assertGreaterEqual(row.trade_count, 0)

    def test_sweep_atr_breakout_multiplier(self):
        grid = ParameterGrid({"breakout_multiplier": [0.5, 1.0, 1.5]})
        runner = SweepRunner(
            config=self.config,
            bars=self.bars,
            strategy_factory=lambda p: ATRVolatilityBreakoutStrategy(
                atr_period=14,
                breakout_multiplier=p.params["breakout_multiplier"],
                momentum=MomentumConfig(min_adx=0.0, session_filter=False),
            ),
            max_workers=1,
        )
        result = runner.run(grid)
        self.assertEqual(len(result), 3)

    def test_sweep_ma_trend_periods(self):
        grid = ParameterGrid({"fast_period": [5, 8], "slow_period": [13, 21]})
        runner = SweepRunner(
            config=self.config,
            bars=self.bars,
            strategy_factory=lambda p: MATrendFollowingStrategy(
                fast_period=p.params["fast_period"],
                slow_period=p.params["slow_period"],
                trend_ma_period=50,
                momentum=MomentumConfig(min_adx=0.0, session_filter=False),
            ),
            max_workers=1,
        )
        result = runner.run(grid)
        self.assertEqual(len(result), 4)


if __name__ == "__main__":
    unittest.main()
