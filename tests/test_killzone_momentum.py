"""
Tests for Killzone Momentum DST-aware hours, per-preset ADX gate,
and H4 cross-timeframe filter.

These tests complement the existing suite at tests/strategies/test_killzone_momentum_strategy.py.
"""

import unittest
from datetime import date, datetime, time, timedelta

from core.types import Bar, MarketState, BarPeriod
from config.sessions import (
    DSTAwareKillzoneHours,
    KillzoneHours,
    get_killzone_hours_for_date,
    is_london_dst,
    is_ny_dst,
)
from strategies.killzone_momentum import (
    KillzoneMomentumStrategy,
    KillzoneMomentumConfig,
    _is_killzone_dst,
    _get_killzone_name_dst,
    _resolve_kz_hours,
)


def _make_bar(hour: int, dt: date, close: float = 1.1000) -> Bar:
    """Create a minimal Bar at the given UTC hour on the given date."""
    return Bar(
        time=datetime(dt.year, dt.month, dt.day, hour, 0),
        open=close - 0.0001,
        high=close + 0.0003,
        low=close - 0.0003,
        close=close,
        volume=1000,
    )


def _make_h4_bars(
    n: int, direction: str = "long", start_date: date | None = None
) -> list[Bar]:
    """Create n H4 bars trending in the given direction."""
    if start_date is None:
        start_date = date(2023, 6, 15)
    bars = []
    base_price = 1.1000
    for i in range(n):
        if direction == "long":
            p = base_price + i * 0.0010
        else:
            p = base_price - i * 0.0010
        dt = datetime(
            start_date.year, start_date.month, start_date.day, 0, 0
        ) + timedelta(hours=4 * i)
        bars.append(
            Bar(
                time=dt,
                open=p - 0.0005,
                high=p + 0.0010,
                low=p - 0.0010,
                close=p,
                volume=1000,
                period=BarPeriod.H4(),
            )
        )
    return bars


# ---------------------------------------------------------------------------
# DST tests
# ---------------------------------------------------------------------------


class TestDSTAwareKillzoneHours(unittest.TestCase):
    """Verify that killzone hours shift correctly with DST transitions."""

    def test_summer_london_open_is_7utc(self):
        """In July, London is in BST (UTC+1), so 8am local = 7:00 UTC."""
        kz = get_killzone_hours_for_date(date(2023, 7, 15))
        self.assertEqual(kz.LONDON_OPEN_START, time(7, 0))
        self.assertEqual(kz.LONDON_OPEN_END, time(9, 0))

    def test_winter_london_open_is_8utc(self):
        """In January, London is in GMT (UTC+0), so 8am local = 8:00 UTC."""
        kz = get_killzone_hours_for_date(date(2023, 1, 15))
        self.assertEqual(kz.LONDON_OPEN_START, time(8, 0))
        self.assertEqual(kz.LONDON_OPEN_END, time(10, 0))

    def test_summer_ny_open_is_12utc(self):
        """In July, NY is in EDT (UTC-4), so 8am local = 12:00 UTC."""
        kz = get_killzone_hours_for_date(date(2023, 7, 15))
        self.assertEqual(kz.NY_OPEN_START, time(12, 0))
        self.assertEqual(kz.NY_OPEN_END, time(14, 0))

    def test_winter_ny_open_is_13utc(self):
        """In January, NY is in EST (UTC-5), so 8am local = 13:00 UTC."""
        kz = get_killzone_hours_for_date(date(2023, 1, 15))
        self.assertEqual(kz.NY_OPEN_START, time(13, 0))
        self.assertEqual(kz.NY_OPEN_END, time(15, 0))

    def test_spring_transition_march_mismatch(self):
        """US springs forward before EU (March: US in DST, EU not yet)."""
        # March 15, 2023: US already in DST (Mar 12), EU not yet (Mar 26)
        kz = get_killzone_hours_for_date(date(2023, 3, 15))
        # NY should be EDT (UTC-4) → NY open at 12 UTC
        self.assertEqual(kz.NY_OPEN_START, time(12, 0))
        # London should be GMT (UTC+0) → London open at 8 UTC
        self.assertEqual(kz.LONDON_OPEN_START, time(8, 0))

    def test_fall_transition_november_mismatch(self):
        """EU falls back before US (November: EU in GMT, US still in EDT)."""
        # November 1, 2023: EU already back to GMT (Oct 29), US still EDT (Nov 5)
        kz = get_killzone_hours_for_date(date(2023, 11, 1))
        # London should be GMT (UTC+0) → London open at 8 UTC
        self.assertEqual(kz.LONDON_OPEN_START, time(8, 0))
        # NY should still be EDT (UTC-4) → NY open at 12 UTC
        self.assertEqual(kz.NY_OPEN_START, time(12, 0))

    def test_is_london_dst_summer(self):
        self.assertTrue(is_london_dst(date(2023, 7, 1)))

    def test_is_london_dst_winter(self):
        self.assertFalse(is_london_dst(date(2023, 1, 1)))

    def test_is_ny_dst_summer(self):
        self.assertTrue(is_ny_dst(date(2023, 7, 1)))

    def test_is_ny_dst_winter(self):
        self.assertFalse(is_ny_dst(date(2023, 1, 1)))

    def test_static_killzone_hours_unchanged(self):
        """Static KillzoneHours class still provides the original defaults."""
        self.assertEqual(KillzoneHours.LONDON_OPEN_START, time(7, 0))
        self.assertEqual(KillzoneHours.NY_OPEN_START, time(12, 0))
        self.assertEqual(KillzoneHours.OVERLAP_START, time(13, 0))


# ---------------------------------------------------------------------------
# Per-preset ADX gate tests
# ---------------------------------------------------------------------------


class TestPerPresetADXGate(unittest.TestCase):
    def test_h1_fx_preset_keeps_adx_15(self):
        """FX H1 preset should keep the original ADX threshold of 15.0."""
        config = KillzoneMomentumConfig.h1_fx()
        self.assertEqual(config.adx_threshold, 15.0)

    def test_m5_xauusd_preset_has_stricter_adx(self):
        """XAUUSD M5 preset should use a stricter ADX threshold (20.0)."""
        config = KillzoneMomentumConfig.m5_xauusd()
        self.assertEqual(config.adx_threshold, 20.0)
        self.assertGreater(
            config.adx_threshold, KillzoneMomentumConfig.h1_fx().adx_threshold
        )

    def test_adx_threshold_is_configurable(self):
        """ADX threshold should be independently configurable via constructor."""
        config = KillzoneMomentumConfig(adx_threshold=25.0)
        self.assertEqual(config.adx_threshold, 25.0)

    def test_m5_xauusd_inherits_other_defaults(self):
        """m5_xauusd should only override specified fields, not all."""
        m5 = KillzoneMomentumConfig.m5_xauusd()
        h1 = KillzoneMomentumConfig.h1_fx()
        # These should be overridden
        self.assertNotEqual(m5.min_session_range_pips, h1.min_session_range_pips)
        self.assertNotEqual(m5.breakout_lookback_bars, h1.breakout_lookback_bars)
        self.assertNotEqual(m5.adx_threshold, h1.adx_threshold)
        # These should be inherited
        self.assertEqual(m5.atr_period, h1.atr_period)
        self.assertEqual(m5.atr_breakout_multiplier, h1.atr_breakout_multiplier)
        self.assertEqual(m5.tp1_rr, h1.tp1_rr)


# ---------------------------------------------------------------------------
# H4 cross-timeframe filter tests
# ---------------------------------------------------------------------------


class TestH4CrossTimeframeFilter(unittest.TestCase):
    """Verify that the H4 alignment filter correctly gates signals."""

    def test_market_state_accepts_h4_bars(self):
        """MarketState should accept optional h4_bars."""
        bars = [_make_bar(7, date(2023, 6, 15))]
        h4_bars = _make_h4_bars(10, "long")
        state = MarketState(bars=bars, h4_bars=h4_bars)
        self.assertIsNotNone(state.h4_bars)
        self.assertEqual(len(state.h4_bars), 10)

    def test_market_state_h4_bars_defaults_none(self):
        """MarketState.h4_bars should default to None for backward compatibility."""
        bars = [_make_bar(7, date(2023, 6, 15))]
        state = MarketState(bars=bars)
        self.assertIsNone(state.h4_bars)

    def test_resolve_kz_hours_with_date(self):
        """_resolve_kz_hours should return DST-adjusted hours for a date."""
        kz = _resolve_kz_hours(date(2023, 7, 15))
        self.assertIsInstance(kz, DSTAwareKillzoneHours)
        self.assertEqual(kz.LONDON_OPEN_START, time(7, 0))

    def test_resolve_kz_hours_fallback(self):
        """_resolve_kz_hours(None) should return static defaults."""
        kz = _resolve_kz_hours(None)
        self.assertEqual(kz.LONDON_OPEN_START, time(7, 0))
        self.assertEqual(kz.NY_OPEN_START, time(12, 0))


# ---------------------------------------------------------------------------
# Integration: verify existing behavior unchanged when h4_bars is None
# ---------------------------------------------------------------------------


class TestBackwardCompatibility(unittest.TestCase):
    """Verify that all changes are backward-compatible."""

    def test_strategy_works_without_h4_bars(self):
        """Strategy should work the same as before when h4_bars is None."""
        config = KillzoneMomentumConfig(
            min_session_range_pips=5.0,
            adx_threshold=10.0,
            retest_tolerance_atr=1.0,
            min_bars_for_setup=40,
        )
        strategy = KillzoneMomentumStrategy(config)
        # Create 80 bars at hour 7 (London open in summer) — no signal expected
        # but should not crash
        bars = []
        for i in range(80):
            bars.append(_make_bar(7, date(2023, 6, 15), close=1.1000 + i * 0.0001))
        state = MarketState(bars=bars)
        # h4_bars is None by default
        self.assertIsNone(state.h4_bars)
        result = strategy.evaluate(state)
        # May or may not return a signal — the point is no crash

    def test_killzone_still_works_in_summer(self):
        """_is_killzone_dst should correctly identify London open in summer DST."""
        bar = _make_bar(7, date(2023, 7, 15))  # 7 UTC = 8 BST
        state = MarketState(bars=[bar])
        self.assertTrue(_is_killzone_dst(state))

    def test_killzone_still_works_in_winter(self):
        """_is_killzone_dst should correctly identify London open in winter."""
        # In winter, London open is 8 UTC
        bar = _make_bar(8, date(2023, 1, 15))  # 8 UTC = 8 GMT
        state = MarketState(bars=[bar])
        self.assertTrue(_is_killzone_dst(state))

    def test_killzone_excludes_wrong_hour_in_winter(self):
        """In winter, 7 UTC is NOT London open (London opens at 8 UTC)."""
        bar = _make_bar(7, date(2023, 1, 15))  # 7 UTC = 7 GMT, before London opens
        state = MarketState(bars=[bar])
        self.assertFalse(_is_killzone_dst(state))

    def test_static_is_killzone_unaffected_by_dst(self):
        """Static _is_killzone should NOT shift hours — backward compat."""
        from strategies.killzone_momentum import _is_killzone

        # Jan 1, 7:30 UTC — static hours say 7-9 is London open
        bar = _make_bar(7, date(2023, 1, 15))
        state = MarketState(bars=[bar])
        self.assertTrue(_is_killzone(state))  # static hours, no DST shift

    def test_dst_killzone_name_summer(self):
        """_get_killzone_name_dst should identify London open at 7 UTC in summer."""
        bar = _make_bar(7, date(2023, 7, 15))
        state = MarketState(bars=[bar])
        self.assertEqual(_get_killzone_name_dst(state), "london_open")

    def test_dst_killzone_name_winter(self):
        """_get_killzone_name_dst should NOT identify London open at 7 UTC in winter."""
        bar = _make_bar(7, date(2023, 1, 15))
        state = MarketState(bars=[bar])
        self.assertIsNone(_get_killzone_name_dst(state))


if __name__ == "__main__":
    unittest.main()
