"""Test coverage for backtest type definitions and helpers.

Covers:
  - get_spread_for_pair: case normalization, known pairs, unknown-pair fallback
  - BacktestConfig.effective_spread_pips: precedence (explicit > pair-derived > default)
  - MarketState.latest_bar and atr: insufficient history + deterministic 15-bar fixture
  - BarPeriod constants and BacktestConfig.units_per_lot
"""

from datetime import datetime, timezone

import pytest

from backtest.types import (
    PAIR_SPREAD_PIPS,
    DEFAULT_SPREAD_PIPS,
    Bar,
    BarPeriod,
    BacktestConfig,
    MarketState,
    get_spread_for_pair,
)


# ---------------------------------------------------------------------------
# get_spread_for_pair
# ---------------------------------------------------------------------------

class TestGetSpreadForPair:
    """Tests for get_spread_for_pair — case normalization, known pairs, fallback."""

    def test_known_pair_uppercase(self):
        """Known pair in uppercase returns the defined spread."""
        assert get_spread_for_pair("EURUSD") == PAIR_SPREAD_PIPS["EURUSD"]

    def test_known_pair_lowercase(self):
        """Case normalization: lowercase input is uppercased internally."""
        assert get_spread_for_pair("eurusd") == PAIR_SPREAD_PIPS["EURUSD"]

    def test_known_pair_mixed_case(self):
        """Case normalization: mixed-case input works."""
        assert get_spread_for_pair("EurUsd") == PAIR_SPREAD_PIPS["EURUSD"]

    def test_known_pair_gbpjpy(self):
        """GBPJPY has a distinct spread (3.0) — verify it's not default."""
        result = get_spread_for_pair("GBPJPY")
        assert result == PAIR_SPREAD_PIPS["GBPJPY"]
        assert result != DEFAULT_SPREAD_PIPS

    def test_known_pair_xauusd(self):
        """XAUUSD (gold) has a distinct spread — verify."""
        result = get_spread_for_pair("XAUUSD")
        assert result == PAIR_SPREAD_PIPS["XAUUSD"]
        assert result != DEFAULT_SPREAD_PIPS

    def test_unknown_pair_returns_default(self):
        """Unknown pair falls back to DEFAULT_SPREAD_PIPS."""
        assert get_spread_for_pair("UNKNOWN") == DEFAULT_SPREAD_PIPS

    def test_unknown_pair_lowercase_returns_default(self):
        """Unknown pair in lowercase still falls back to default."""
        assert get_spread_for_pair("unknown") == DEFAULT_SPREAD_PIPS

    def test_empty_string_returns_default(self):
        """Empty string is not a known pair — returns default."""
        assert get_spread_for_pair("") == DEFAULT_SPREAD_PIPS

    def test_all_defined_pairs_reachable(self):
        """Every pair in PAIR_SPREAD_PIPS is retrievable via get_spread_for_pair."""
        for pair, spread in PAIR_SPREAD_PIPS.items():
            assert get_spread_for_pair(pair) == spread
            assert get_spread_for_pair(pair.lower()) == spread


# ---------------------------------------------------------------------------
# BacktestConfig.effective_spread_pips
# ---------------------------------------------------------------------------

class TestEffectiveSpreadPips:
    """Tests for BacktestConfig.effective_spread_pips precedence.

    Precedence:
      1. Explicit spread_pips > 0 → use it
      2. Pair set → derive from get_spread_for_pair
      3. Fallback → DEFAULT_SPREAD_PIPS
    """

    def test_explicit_spread_takes_precedence(self):
        """When spread_pips > 0, it wins over everything else."""
        cfg = BacktestConfig(spread_pips=5.0, pair="EURUSD")
        assert cfg.effective_spread_pips == 5.0

    def test_explicit_spread_with_no_pair(self):
        """Explicit spread with empty pair still works."""
        cfg = BacktestConfig(spread_pips=2.0, pair="")
        assert cfg.effective_spread_pips == 2.0

    def test_pair_derived_spread_when_explicit_is_zero(self):
        """When spread_pips == 0 and pair is set, derive from PAIR_SPREAD_PIPS."""
        cfg = BacktestConfig(spread_pips=0.0, pair="GBPJPY")
        assert cfg.effective_spread_pips == PAIR_SPREAD_PIPS["GBPJPY"]

    def test_pair_derived_spread_case_insensitive(self):
        """Pair name is case-insensitive for spread lookup."""
        cfg = BacktestConfig(spread_pips=0.0, pair="gbpjpy")
        assert cfg.effective_spread_pips == PAIR_SPREAD_PIPS["GBPJPY"]

    def test_unknown_pair_falls_to_default(self):
        """When spread_pips == 0 and pair is unknown, use DEFAULT_SPREAD_PIPS."""
        cfg = BacktestConfig(spread_pips=0.0, pair="UNKNOWNXYZ")
        assert cfg.effective_spread_pips == DEFAULT_SPREAD_PIPS

    def test_no_pair_no_spread_returns_default(self):
        """When spread_pips == 0 and pair is empty, return DEFAULT_SPREAD_PIPS."""
        cfg = BacktestConfig(spread_pips=0.0, pair="")
        assert cfg.effective_spread_pips == DEFAULT_SPREAD_PIPS

    def test_default_config_spread(self):
        """The BacktestConfig default spread_pips is 0.5 per the dataclass."""
        cfg = BacktestConfig()
        assert cfg.spread_pips == 0.5
        assert cfg.effective_spread_pips == 0.5


# ---------------------------------------------------------------------------
# MarketState.latest_bar and atr
# ---------------------------------------------------------------------------

def _make_bar(
    t: str = "2026-01-01T00:00:00",
    o: float = 1.1000,
    h: float = 1.1010,
    lo: float = 1.0990,
    c: float = 1.1005,
) -> Bar:
    """Helper to build a Bar with sensible defaults."""
    return Bar(
        time=datetime.fromisoformat(t),
        open=o,
        high=h,
        low=lo,
        close=c,
    )


class TestMarketStateLatestBar:
    """Tests for MarketState.latest_bar property."""

    def test_latest_bar_returns_last_element(self):
        """latest_bar returns the final bar in the list."""
        b0 = _make_bar(t="2026-01-01T00:00:00")
        b1 = _make_bar(t="2026-01-01T01:00:00", c=1.1050)
        b2 = _make_bar(t="2026-01-01T02:00:00", c=1.1100)
        state = MarketState(bars=[b0, b1, b2])
        assert state.latest_bar is b2
        assert state.latest_bar.close == 1.1100


class TestMarketStateATR:
    """Tests for MarketState.atr property."""

    def test_atr_insufficient_history_returns_tiny_default(self):
        """Fewer than 15 bars → returns 0.0001."""
        bars = [_make_bar(t=f"2026-01-01T{i:02d}:00:00") for i in range(10)]
        state = MarketState(bars=bars)
        assert state.atr == pytest.approx(0.0001)

    def test_atr_exactly_14_bars_still_insufficient(self):
        """14 bars is still < 15 → returns 0.0001."""
        bars = [_make_bar(t=f"2026-01-01T{i:02d}:00:00") for i in range(14)]
        state = MarketState(bars=bars)
        assert state.atr == pytest.approx(0.0001)

    def test_atr_with_15_deterministic_bars(self):
        """15 bars with known OHLC → deterministic ATR.

        Bars have:
          high-low = 0.0020 (1.1010 - 1.0990)
          No gaps between consecutive closes and next bar ranges.

        So for each of the last 14 bars (indices 1..14):
          TR = max(H-L, |H - prev_close|, |L - prev_close|)

        With close=1.1005 and next bar H=1.1010, L=1.0990:
          |H - prev_close| = |1.1010 - 1.1005| = 0.0005
          |L - prev_close| = |1.0990 - 1.1005| = 0.0015
          H - L = 0.0020

          TR = 0.0020 for every bar

        ATR = sum(TR) / 14 = 14 * 0.0020 / 14 = 0.0020
        """
        bars = [
            _make_bar(t=f"2026-01-01T{i:02d}:00:00")
            for i in range(15)
        ]
        state = MarketState(bars=bars)
        assert state.atr == pytest.approx(0.0020)

    def test_atr_with_20_bars_uses_last_14(self):
        """With 20 bars, ATR uses the last 14 (indices 6..19)."""
        # All identical bars → ATR = 0.0020 as above
        bars = [
            _make_bar(t=f"2026-01-01T{i:02d}:00:00")
            for i in range(20)
        ]
        state = MarketState(bars=bars)
        assert state.atr == pytest.approx(0.0020)

    def test_atr_reflects_volatile_bar(self):
        """One bar with a large range influences the ATR upward."""
        bars = [
            _make_bar(t=f"2026-01-01T{i:02d}:00:00")
            for i in range(15)
        ]
        # Make the last bar extremely volatile
        bars[-1] = _make_bar(
            t="2026-01-01T14:00:00",
            h=1.2000,
            lo=1.0000,
            c=1.1000,
            o=1.1000,
        )
        state = MarketState(bars=bars)
        # The last bar's TR will dominate:
        #   H-L = 0.2000
        #   |H - prev_close| = |1.2000 - 1.1005| = 0.0995
        #   |L - prev_close| = |1.0000 - 1.1005| = 0.1005
        #   TR = max(0.2000, 0.0995, 0.1005) = 0.2000
        # Previous 13 bars: TR = 0.0020 each
        # ATR = (13 * 0.0020 + 0.2000) / 14
        expected = (13 * 0.0020 + 0.2000) / 14
        assert state.atr == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# BarPeriod constants and units_per_lot
# ---------------------------------------------------------------------------

class TestBarPeriod:
    """Tests for BarPeriod class constants and minute values."""

    def test_m15_minutes(self):
        assert BarPeriod.M15.minutes == 15

    def test_h1_minutes(self):
        assert BarPeriod.H1.minutes == 60

    def test_h4_minutes(self):
        assert BarPeriod.H4.minutes == 240

    def test_d1_minutes(self):
        assert BarPeriod.D1.minutes == 1440

    def test_all_periods_distinct(self):
        """All four period constants are distinct objects."""
        periods = {BarPeriod.M15, BarPeriod.H1, BarPeriod.H4, BarPeriod.D1}
        assert len(periods) == 4

    def test_bar_period_is_initialized(self):
        """BarPeriod constants are not None after _init()."""
        assert BarPeriod.M15 is not None
        assert BarPeriod.H1 is not None
        assert BarPeriod.H4 is not None
        assert BarPeriod.D1 is not None


class TestBarPeriodProperty:
    """Bar.period returns BarPeriod.H1 by default."""

    def test_bar_default_period_is_h1(self):
        b = _make_bar()
        assert b.period is BarPeriod.H1


class TestUnitsPerLot:
    """Tests for BacktestConfig.units_per_lot."""

    def test_units_per_lot_default(self):
        cfg = BacktestConfig()
        assert cfg.units_per_lot == 100000.0

    def test_units_per_lot_is_float(self):
        cfg = BacktestConfig()
        assert isinstance(cfg.units_per_lot, float)

    def test_units_per_lot_constant_across_configs(self):
        """units_per_lot does not depend on config values."""
        cfg1 = BacktestConfig(starting_balance=500.0)
        cfg2 = BacktestConfig(starting_balance=100000.0)
        assert cfg1.units_per_lot == cfg2.units_per_lot == 100000.0
