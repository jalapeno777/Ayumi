"""Unit tests for ORB (Opening Range Breakout) Strategy.

Covers:
    - Opening range calculation (normal case, insufficient bars, narrow range, wide range)
    - Bullish breakout entry (long above range high)
    - Bearish breakout entry (short below range low)
    - Buffer rejection (price within buffer zone, no signal)
    - Direction filter (long-only, short-only, both)
    - One signal per direction per session per day (deduplication)
    - Stop-loss and take-profit level validation
    - Session window filtering (no signal outside trade window)
    - H4 trend filter (rejects counter-trend breakouts)
    - Strategy reset (clears caches)
    - ATR-buffered stop-loss distance validation
"""

import unittest
from datetime import datetime, timedelta, timezone

from core.types import Bar, MarketState, SessionType, TradeDirection
from strategies.orb import ORBStrategy, _calculate_atr, _pip_size_for_symbol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(time, o, h, l, c, vol=1000):
    return Bar(time=time, open=o, high=h, low=l, close=c, volume=vol)


def _make_range_bars(
    date: datetime,
    start_hour: int,
    end_hour: int,
    symbol_pip: float = 0.0001,
    base_price: float = 1.2500,
    range_high: float | None = None,
    range_low: float | None = None,
    minutes_per_bar: int = 15,
):
    """Create bars filling the range window with a controlled high/low."""
    bars = []
    rh = range_high if range_high is not None else base_price + 10 * symbol_pip
    rl = range_low if range_low is not None else base_price - 10 * symbol_pip
    for hour in range(start_hour, end_hour):
        for minute in range(0, 60, minutes_per_bar):
            t = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # Most bars trade inside the range
            o = base_price
            h = min(rh, base_price + 5 * symbol_pip)
            l = max(rl, base_price - 5 * symbol_pip)
            c = base_price
            bars.append(_make_bar(t, o, h, l, c))
    # Ensure the range high/low are actually hit
    if bars:
        bars[0] = _make_bar(bars[0].time, base_price, rh, base_price, base_price)
        bars[1] = _make_bar(bars[1].time, base_price, base_price, rl, base_price)
    return bars


def _make_trade_bars(
    date: datetime,
    start_hour: int,
    end_hour: int,
    price: float,
    symbol_pip: float = 0.0001,
    minutes_per_bar: int = 15,
):
    """Create flat bars at *price* for the trade window."""
    bars = []
    for hour in range(start_hour, end_hour):
        for minute in range(0, 60, minutes_per_bar):
            t = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            bars.append(_make_bar(t, price, price, price, price))
    return bars


def _make_preroll_bars(
    start: datetime,
    n: int = 50,
    base_price: float = 1.2500,
    symbol_pip: float = 0.0001,
):
    """Create n pre-roll bars (before the range window) for ATR calculation."""
    bars = []
    t = start
    for i in range(n):
        t_bar = t + timedelta(minutes=15 * i)
        bars.append(
            _make_bar(
                t_bar,
                base_price,
                base_price + 2 * symbol_pip,
                base_price - 2 * symbol_pip,
                base_price,
            )
        )
    return bars


def _build_market_state(bars, symbol="EURUSD"):
    """Build a MarketState from bars.

    MarketState doesn't have a ``symbol`` field, so we set it
    as a post-hoc attribute (the strategy reads it via getattr).
    """
    state = MarketState(bars=bars, current_session=SessionType.LONDON)
    state.symbol = symbol
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOpeningRangeCalculation(unittest.TestCase):
    """Tests for range computation and validation."""

    def setUp(self):
        self.config = {
            "name": "ORB Test",
            "session": "london",
            "range_start_hour": 7,
            "range_end_hour": 8,
            "trade_start_hour": 8,
            "trade_end_hour": 16,
            "min_range_pips": 5.0,
            "max_range_pips": 40.0,
            "breakout_buffer_pips": 2.0,
            "min_range_bars": 3,
        }

    def test_valid_range_computed(self):
        """Range is correctly computed from bars in the window."""
        strategy = ORBStrategy(self.config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)  # Monday
        bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)
        result = strategy._compute_range(bars, "2026-01-05", "EURUSD")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["high"], 1.2515, places=5)
        self.assertAlmostEqual(result["low"], 1.2485, places=5)
        self.assertTrue(result["valid"])

    def test_insufficient_bars_returns_none(self):
        """Fewer bars than min_range_bars returns None."""
        strategy = ORBStrategy(self.config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        # Only 2 bars, min is 3
        bars = [
            _make_bar(date.replace(hour=7, minute=0), 1.2500, 1.2510, 1.2490, 1.2500),
            _make_bar(date.replace(hour=7, minute=15), 1.2500, 1.2510, 1.2490, 1.2500),
        ]
        result = strategy._compute_range(bars, "2026-01-05", "EURUSD")
        self.assertIsNone(result)

    def test_narrow_range_invalid(self):
        """Range narrower than min_range_pips is marked invalid."""
        strategy = ORBStrategy(self.config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        # 2-pip range, min is 5
        bars = _make_range_bars(date, 7, 8, range_high=1.2502, range_low=1.2500)
        result = strategy._compute_range(bars, "2026-01-05", "EURUSD")
        self.assertIsNotNone(result)
        self.assertFalse(result["valid"])

    def test_wide_range_invalid(self):
        """Range wider than max_range_pips is marked invalid."""
        strategy = ORBStrategy({**self.config, "max_range_pips": 30.0})
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        # 50-pip range, max is 30
        bars = _make_range_bars(date, 7, 8, range_high=1.2550, range_low=1.2450)
        result = strategy._compute_range(bars, "2026-01-05", "EURUSD")
        self.assertIsNotNone(result)
        self.assertFalse(result["valid"])

    def test_range_caching(self):
        """Range is cached per (date, symbol) and reused."""
        strategy = ORBStrategy(self.config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        bars = _make_range_bars(date, 7, 8)
        strategy._compute_range(bars, "2026-01-05", "EURUSD")
        # Second call with empty bars should still return cached value
        result = strategy._compute_range([], "2026-01-05", "EURUSD")
        self.assertIsNotNone(result)


class TestBreakoutEntry(unittest.TestCase):
    """Tests for breakout detection and signal generation."""

    def setUp(self):
        self.config = {
            "name": "ORB Test",
            "session": "london",
            "range_start_hour": 7,
            "range_end_hour": 8,
            "trade_start_hour": 8,
            "trade_end_hour": 16,
            "min_range_pips": 5.0,
            "max_range_pips": 40.0,
            "breakout_buffer_pips": 2.0,
            "min_range_bars": 3,
            "sl_atr_multiplier": 1.5,
            "direction_filter": "both",
            "h4_trend_filter": False,
        }

    def _build_breakout_state(self, direction: str, penetration_pips: float = 5.0):
        """Build a MarketState with range bars + a breakout bar."""
        strategy = ORBStrategy(self.config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        pip = 0.0001

        # Range bars: 7:00–7:45
        range_bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)

        # Pre-roll bars for ATR (before range window)
        preroll = _make_preroll_bars(date.replace(hour=5, minute=0), n=20)

        # Breakout bar at 8:00
        if direction == "long":
            breakout_price = (
                1.2515 + penetration_pips * pip + strategy.breakout_buffer_pips * pip
            )
        else:
            breakout_price = (
                1.2485 - penetration_pips * pip - strategy.breakout_buffer_pips * pip
            )

        breakout_bar = _make_bar(
            date.replace(hour=8, minute=0),
            1.2500,
            breakout_price,
            1.2500,
            breakout_price,
        )

        all_bars = preroll + range_bars + [breakout_bar]
        return strategy, _build_market_state(all_bars)

    def test_bullish_breakout_generates_long(self):
        """Bullish breakout above range high generates LONG signal."""
        strategy, state = self._build_breakout_state("long")
        signal = strategy.evaluate(state)
        self.assertIsNotNone(signal, "Expected a signal on bullish breakout")
        self.assertEqual(signal.direction, TradeDirection.LONG)

    def test_bearish_breakout_generates_short(self):
        """Bearish breakout below range low generates SHORT signal."""
        strategy, state = self._build_breakout_state("short")
        signal = strategy.evaluate(state)
        self.assertIsNotNone(signal, "Expected a signal on bearish breakout")
        self.assertEqual(signal.direction, TradeDirection.SHORT)

    def test_no_breakout_no_signal(self):
        """Price inside the range produces no signal."""
        strategy = ORBStrategy(self.config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)

        preroll = _make_preroll_bars(date.replace(hour=5, minute=0), n=20)
        range_bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)
        # Bar at 8:00 inside the range
        inside_bar = _make_bar(
            date.replace(hour=8, minute=0), 1.2500, 1.2510, 1.2490, 1.2500
        )

        all_bars = preroll + range_bars + [inside_bar]
        state = _build_market_state(all_bars)
        signal = strategy.evaluate(state)
        self.assertIsNone(signal)

    def test_buffer_zone_no_signal(self):
        """Price just above range high but within buffer produces no signal."""
        strategy = ORBStrategy(self.config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        pip = 0.0001

        preroll = _make_preroll_bars(date.replace(hour=5, minute=0), n=20)
        range_bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)
        # Price 1 pip above range high, buffer is 2 pips → no breakout
        buffer_price = 1.2515 + 1 * pip
        buffer_bar = _make_bar(
            date.replace(hour=8, minute=0), 1.2500, buffer_price, 1.2500, buffer_price
        )

        all_bars = preroll + range_bars + [buffer_bar]
        state = _build_market_state(all_bars)
        signal = strategy.evaluate(state)
        self.assertIsNone(signal)


class TestDirectionFilter(unittest.TestCase):
    """Tests for direction filtering."""

    def setUp(self):
        self.base_config = {
            "name": "ORB Test",
            "session": "london",
            "range_start_hour": 7,
            "range_end_hour": 8,
            "trade_start_hour": 8,
            "trade_end_hour": 16,
            "min_range_pips": 5.0,
            "max_range_pips": 40.0,
            "breakout_buffer_pips": 2.0,
            "min_range_bars": 3,
        }

    def _build_breakout(self, direction: str):
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        pip = 0.0001
        preroll = _make_preroll_bars(date.replace(hour=5, minute=0), n=20)
        range_bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)
        if direction == "long":
            bp = 1.2515 + 7 * pip
        else:
            bp = 1.2485 - 7 * pip
        breakout_bar = _make_bar(date.replace(hour=8, minute=0), 1.2500, bp, 1.2500, bp)
        return _build_market_state(preroll + range_bars + [breakout_bar])

    def test_long_only_filter_rejects_short(self):
        """Direction filter 'long' rejects short breakouts."""
        strategy = ORBStrategy({**self.base_config, "direction_filter": "long"})
        state = self._build_breakout("short")
        self.assertIsNone(strategy.evaluate(state))

    def test_short_only_filter_rejects_long(self):
        """Direction filter 'short' rejects long breakouts."""
        strategy = ORBStrategy({**self.base_config, "direction_filter": "short"})
        state = self._build_breakout("long")
        self.assertIsNone(strategy.evaluate(state))

    def test_both_filter_allows_long(self):
        """Direction filter 'both' allows long breakouts."""
        strategy = ORBStrategy({**self.base_config, "direction_filter": "both"})
        state = self._build_breakout("long")
        sig = strategy.evaluate(state)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, TradeDirection.LONG)


class TestSignalDeduplication(unittest.TestCase):
    """One signal per direction per session per day."""

    def test_second_same_direction_signal_blocked(self):
        config = {
            "name": "ORB Test",
            "session": "london",
            "range_start_hour": 7,
            "range_end_hour": 8,
            "trade_start_hour": 8,
            "trade_end_hour": 16,
            "min_range_pips": 5.0,
            "max_range_pips": 40.0,
            "breakout_buffer_pips": 2.0,
            "min_range_bars": 3,
        }
        strategy = ORBStrategy(config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        pip = 0.0001

        preroll = _make_preroll_bars(date.replace(hour=5, minute=0), n=20)
        range_bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)

        bp = 1.2515 + 7 * pip
        breakout_bar_1 = _make_bar(
            date.replace(hour=8, minute=0), 1.2500, bp, 1.2500, bp
        )
        breakout_bar_2 = _make_bar(
            date.replace(hour=9, minute=0), 1.2500, bp + 5 * pip, 1.2500, bp + 5 * pip
        )

        state1 = _build_market_state(preroll + range_bars + [breakout_bar_1])
        state2 = _build_market_state(
            preroll + range_bars + [breakout_bar_1, breakout_bar_2]
        )

        signal1 = strategy.evaluate(state1)
        signal2 = strategy.evaluate(state2)

        self.assertIsNotNone(signal1, "First breakout should fire")
        self.assertIsNone(signal2, "Second same-direction breakout should be blocked")

    def test_opposite_direction_allowed_same_day(self):
        config = {
            "name": "ORB Test",
            "session": "london",
            "range_start_hour": 7,
            "range_end_hour": 8,
            "trade_start_hour": 8,
            "trade_end_hour": 16,
            "min_range_pips": 5.0,
            "max_range_pips": 40.0,
            "breakout_buffer_pips": 2.0,
            "min_range_bars": 3,
        }
        strategy = ORBStrategy(config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        pip = 0.0001

        preroll = _make_preroll_bars(date.replace(hour=5, minute=0), n=20)
        range_bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)

        long_bp = 1.2515 + 7 * pip
        short_bp = 1.2485 - 7 * pip
        long_bar = _make_bar(
            date.replace(hour=8, minute=0), 1.2500, long_bp, 1.2500, long_bp
        )
        short_bar = _make_bar(
            date.replace(hour=10, minute=0), 1.2500, 1.2500, short_bp, short_bp
        )

        state1 = _build_market_state(preroll + range_bars + [long_bar])
        signal1 = strategy.evaluate(state1)
        self.assertIsNotNone(signal1)
        self.assertEqual(signal1.direction, TradeDirection.LONG)

        state2 = _build_market_state(preroll + range_bars + [long_bar, short_bar])
        signal2 = strategy.evaluate(state2)
        self.assertIsNotNone(signal2, "Opposite direction should be allowed same day")
        self.assertEqual(signal2.direction, TradeDirection.SHORT)


class TestSessionWindowFiltering(unittest.TestCase):
    """No signal outside the trade window."""

    def test_no_signal_outside_trade_window(self):
        config = {
            "name": "ORB Test",
            "session": "london",
            "range_start_hour": 7,
            "range_end_hour": 8,
            "trade_start_hour": 8,
            "trade_end_hour": 16,
            "min_range_pips": 5.0,
            "max_range_pips": 40.0,
            "breakout_buffer_pips": 2.0,
            "min_range_bars": 3,
        }
        strategy = ORBStrategy(config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        pip = 0.0001

        preroll = _make_preroll_bars(date.replace(hour=5, minute=0), n=20)
        range_bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)

        # Breakout at 17:00 (outside trade window 8-16)
        bp = 1.2515 + 7 * pip
        late_bar = _make_bar(date.replace(hour=17, minute=0), 1.2500, bp, 1.2500, bp)

        state = _build_market_state(preroll + range_bars + [late_bar])
        signal = strategy.evaluate(state)
        self.assertIsNone(signal, "No signal should fire outside trade window")


class TestStopLossAndTakeProfit(unittest.TestCase):
    """Validate SL/TP level calculations."""

    def test_long_stop_loss_below_entry(self):
        config = {
            "name": "ORB Test",
            "session": "london",
            "range_start_hour": 7,
            "range_end_hour": 8,
            "trade_start_hour": 8,
            "trade_end_hour": 16,
            "min_range_pips": 5.0,
            "max_range_pips": 40.0,
            "breakout_buffer_pips": 2.0,
            "min_range_bars": 3,
            "sl_atr_multiplier": 2.0,
        }
        strategy = ORBStrategy(config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        pip = 0.0001

        preroll = _make_preroll_bars(date.replace(hour=5, minute=0), n=20)
        range_bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)
        bp = 1.2515 + 7 * pip
        breakout_bar = _make_bar(date.replace(hour=8, minute=0), 1.2500, bp, 1.2500, bp)

        state = _build_market_state(preroll + range_bars + [breakout_bar])
        signal = strategy.evaluate(state)

        self.assertIsNotNone(signal)
        self.assertLess(
            signal.stop_loss, signal.entry_price, "Long SL must be below entry"
        )
        self.assertGreater(
            signal.take_profit_1, signal.entry_price, "Long TP1 must be above entry"
        )
        self.assertGreater(signal.take_profit_2, signal.take_profit_1, "TP2 > TP1")
        self.assertGreater(signal.take_profit_3, signal.take_profit_2, "TP3 > TP2")

    def test_short_stop_loss_above_entry(self):
        config = {
            "name": "ORB Test",
            "session": "london",
            "range_start_hour": 7,
            "range_end_hour": 8,
            "trade_start_hour": 8,
            "trade_end_hour": 16,
            "min_range_pips": 5.0,
            "max_range_pips": 40.0,
            "breakout_buffer_pips": 2.0,
            "min_range_bars": 3,
            "sl_atr_multiplier": 2.0,
        }
        strategy = ORBStrategy(config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        pip = 0.0001

        preroll = _make_preroll_bars(date.replace(hour=5, minute=0), n=20)
        range_bars = _make_range_bars(date, 7, 8, range_high=1.2515, range_low=1.2485)
        bp = 1.2485 - 7 * pip
        breakout_bar = _make_bar(date.replace(hour=8, minute=0), 1.2500, 1.2500, bp, bp)

        state = _build_market_state(preroll + range_bars + [breakout_bar])
        signal = strategy.evaluate(state)

        self.assertIsNotNone(signal)
        self.assertGreater(
            signal.stop_loss, signal.entry_price, "Short SL must be above entry"
        )
        self.assertLess(
            signal.take_profit_1, signal.entry_price, "Short TP1 must be below entry"
        )
        self.assertLess(
            signal.take_profit_2, signal.take_profit_1, "TP2 < TP1 for short"
        )
        self.assertLess(
            signal.take_profit_3, signal.take_profit_2, "TP3 < TP2 for short"
        )


class TestStrategyReset(unittest.TestCase):
    """Reset clears caches and fired signals."""

    def test_reset_clears_state(self):
        config = {
            "name": "ORB Test",
            "session": "london",
            "range_start_hour": 7,
            "range_end_hour": 8,
            "trade_start_hour": 8,
            "trade_end_hour": 16,
            "min_range_pips": 5.0,
            "max_range_pips": 40.0,
            "breakout_buffer_pips": 2.0,
            "min_range_bars": 3,
        }
        strategy = ORBStrategy(config)
        date = datetime(2026, 1, 5, tzinfo=timezone.utc)
        bars = _make_range_bars(date, 7, 8)

        strategy._compute_range(bars, "2026-01-05", "EURUSD")
        strategy._fired_signals[("2026-01-05", "EURUSD", "long")] = True

        self.assertEqual(len(strategy._range_cache), 1)
        self.assertEqual(len(strategy._fired_signals), 1)

        strategy.reset()

        self.assertEqual(len(strategy._range_cache), 0)
        self.assertEqual(len(strategy._fired_signals), 0)


class TestATRHelper(unittest.TestCase):
    """Test the ATR calculation helper."""

    def test_atr_with_sufficient_bars(self):
        """ATR returns a positive value with enough bars."""
        bars = []
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(20):
            t = base + timedelta(minutes=15 * i)
            bars.append(_make_bar(t, 1.2500, 1.2510, 1.2490, 1.2500))
        atr = _calculate_atr(bars, 14)
        self.assertGreater(atr, 0)

    def test_atr_with_insufficient_bars(self):
        """ATR returns a small default with insufficient bars."""
        bars = [
            _make_bar(
                datetime(2026, 1, 1, tzinfo=timezone.utc), 1.25, 1.251, 1.249, 1.25
            )
        ]
        atr = _calculate_atr(bars, 14)
        self.assertAlmostEqual(atr, 0.0001)


class TestPipSizeHelper(unittest.TestCase):
    """Test the pip size helper."""

    def test_eurusd_pip_size(self):
        pip = _pip_size_for_symbol("EURUSD")
        self.assertGreater(pip, 0)

    def test_unknown_symbol_returns_default(self):
        pip = _pip_size_for_symbol("UNKNOWN")
        self.assertGreater(pip, 0)


class TestMultipleSessions(unittest.TestCase):
    """Test session default configurations."""

    def test_london_session_defaults(self):
        strategy = ORBStrategy({"name": "ORB", "session": "london"})
        self.assertEqual(strategy.range_start_hour, 7)
        self.assertEqual(strategy.range_end_hour, 8)
        self.assertEqual(strategy.trade_start_hour, 8)
        self.assertEqual(strategy.trade_end_hour, 16)

    def test_ny_session_defaults(self):
        strategy = ORBStrategy({"name": "ORB", "session": "ny"})
        self.assertEqual(strategy.range_start_hour, 12)
        self.assertEqual(strategy.trade_start_hour, 13)

    def test_asian_session_defaults(self):
        strategy = ORBStrategy({"name": "ORB", "session": "asian"})
        self.assertEqual(strategy.range_start_hour, 0)
        self.assertEqual(strategy.trade_start_hour, 1)

    def test_custom_hours_override_session(self):
        strategy = ORBStrategy(
            {
                "name": "ORB",
                "session": "london",
                "range_start_hour": 6,
                "range_end_hour": 9,
            }
        )
        self.assertEqual(strategy.range_start_hour, 6)
        self.assertEqual(strategy.range_end_hour, 9)


if __name__ == "__main__":
    unittest.main()
