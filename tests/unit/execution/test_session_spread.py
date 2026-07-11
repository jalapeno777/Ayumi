"""Tests for session-aware spread modelling in ExecutionSimulator.

Validates:
- Spread varies by session and pair per SPREAD_TABLE
- Volatility multiplier works (ATR-based, capped at 5×)
- ExecutionResult includes session-aware breakdown
- Session detection helper returns correct TradingSession
- Backward compatibility (no vol_atr_pips → multiplier = 1.0)
"""
import pandas as pd
import pytest
import numpy as np

from config.sessions import TradingSession, get_trading_session
from forex_trading.services.backtest.execution import (
    ExecutionSimulator,
    ExecutionConfig,
    SPREAD_TABLE,
    DEFAULT_SPREAD_PIPS,
)


# ---------------------------------------------------------------------------
# Session detection
# ---------------------------------------------------------------------------
class TestGetTradingSession:
    def test_london_session(self):
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        assert get_trading_session(ts) == TradingSession.LONDON

    def test_ny_overlap_session(self):
        ts = pd.Timestamp("2026-07-10 13:00:00Z")
        assert get_trading_session(ts) == TradingSession.NY_OVERLAP

    def test_asian_session(self):
        ts = pd.Timestamp("2026-07-10 02:00:00Z")
        assert get_trading_session(ts) == TradingSession.ASIAN

    def test_ny_afternoon_session(self):
        ts = pd.Timestamp("2026-07-10 17:00:00Z")
        assert get_trading_session(ts) == TradingSession.NY_AFTERNOON

    def test_off_hours_session(self):
        ts = pd.Timestamp("2026-07-10 21:00:00Z")
        assert get_trading_session(ts) == TradingSession.OFF_HOURS

    def test_boundary_start_inclusive(self):
        """Session start time is inclusive."""
        ts = pd.Timestamp("2026-07-10 12:00:00Z")
        assert get_trading_session(ts) == TradingSession.NY_OVERLAP

    def test_boundary_end_exclusive(self):
        """Session end time is exclusive (belongs to next session)."""
        ts = pd.Timestamp("2026-07-10 16:00:00Z")
        assert get_trading_session(ts) == TradingSession.NY_AFTERNOON

    def test_naive_timestamp_assumed_utc(self):
        ts = pd.Timestamp("2026-07-10 08:00:00")  # naive = UTC
        assert get_trading_session(ts) == TradingSession.LONDON


# ---------------------------------------------------------------------------
# Session-aware spread lookup
# ---------------------------------------------------------------------------
class TestSessionAwareSpread:
    def setup_method(self):
        np.random.seed(42)
        self.sim = ExecutionSimulator()

    def test_eurusd_spread_varies_by_session(self):
        """EURUSD spread should differ between London and Asian sessions."""
        london_ts = pd.Timestamp("2026-07-10 08:00:00Z")
        asian_ts = pd.Timestamp("2026-07-10 02:00:00Z")

        london_result = self.sim.execute_long(1.1000, london_ts, pair="EURUSD")
        asian_result = self.sim.execute_long(1.1000, asian_ts, pair="EURUSD")

        # London base spread = 0.5 pips, Asian = 1.0 pips
        assert london_result.base_spread_pips == 0.5
        assert asian_result.base_spread_pips == 1.0
        assert asian_result.spread_cost > london_result.spread_cost

    def test_gbpusd_spread_varies_by_session(self):
        """GBPUSD should show different spreads for different sessions."""
        overlap_ts = pd.Timestamp("2026-07-10 13:00:00Z")
        off_hours_ts = pd.Timestamp("2026-07-10 21:00:00Z")

        overlap_result = self.sim.execute_long(1.2500, overlap_ts, pair="GBPUSD")
        off_hours_result = self.sim.execute_long(1.2500, off_hours_ts, pair="GBPUSD")

        assert overlap_result.base_spread_pips == 0.5
        assert off_hours_result.base_spread_pips == 2.0

    def test_unknown_pair_uses_default_spread(self):
        """Unknown pairs should fall back to DEFAULT_SPREAD_PIPS."""
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        result = self.sim.execute_long(1.0, ts, pair="UNKNOWN")
        assert result.base_spread_pips == DEFAULT_SPREAD_PIPS

    def test_jpy_pair_uses_correct_pip_size(self):
        """JPY pairs use 0.01 pip size, so spread cost should be larger in price terms."""
        ts = pd.Timestamp("2026-07-10 13:00:00Z")  # NY_OVERLAP
        eurusd_result = self.sim.execute_long(1.1000, ts, pair="EURUSD")
        usdjpy_result = self.sim.execute_long(150.00, ts, pair="USDJPY")

        # EURUSD overlap: 0.3 pips × 0.0001 = 0.00003
        # USDJPY overlap: 0.4 pips × 0.01 = 0.004
        # JPY spread cost in price terms should be proportionally larger
        assert usdjpy_result.spread_cost > eurusd_result.spread_cost

    def test_execution_result_includes_session(self):
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        result = self.sim.execute_long(1.1000, ts, pair="EURUSD")
        assert result.session == "london"
        assert result.pair == "EURUSD"

    def test_all_pairs_in_spread_table_have_all_sessions(self):
        """Verify SPREAD_TABLE completeness."""
        for pair, sessions in SPREAD_TABLE.items():
            for session in TradingSession:
                assert session in sessions, (
                    f"{pair} missing spread for {session.value}"
                )


# ---------------------------------------------------------------------------
# Volatility multiplier
# ---------------------------------------------------------------------------
class TestVolatilityMultiplier:
    def setup_method(self):
        np.random.seed(42)
        self.sim = ExecutionSimulator()

    def test_no_atr_defaults_to_1x(self):
        """Without vol_atr_pips, multiplier should be 1.0."""
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        result = self.sim.execute_long(1.1000, ts, pair="EURUSD")
        assert result.vol_multiplier == 1.0

    def test_normal_atr_gives_1x(self):
        """ATR equal to baseline gives 1.0 multiplier."""
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        result = self.sim.execute_long(
            1.1000, ts, pair="EURUSD",
            vol_atr_pips=10.0,  # == baseline
        )
        assert result.vol_multiplier == 1.0

    def test_high_atr_widens_spread(self):
        """High ATR should produce multiplier > 1.0."""
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        result = self.sim.execute_long(
            1.1000, ts, pair="EURUSD",
            vol_atr_pips=20.0,  # 2× baseline
        )
        assert result.vol_multiplier == 2.0

    def test_vol_multiplier_capped_at_5x(self):
        """Multiplier should never exceed the configured cap (5.0)."""
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        result = self.sim.execute_long(
            1.1000, ts, pair="EURUSD",
            vol_atr_pips=100.0,  # 10× baseline → should cap at 5×
        )
        assert result.vol_multiplier == 5.0

    def test_custom_cap(self):
        """Custom vol_multiplier_cap should be respected."""
        config = ExecutionConfig(vol_multiplier_cap=3.0)
        sim = ExecutionSimulator(config)
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        result = sim.execute_long(
            1.1000, ts, pair="EURUSD",
            vol_atr_pips=100.0,
        )
        assert result.vol_multiplier == 3.0

    def test_low_atr_stays_at_1x(self):
        """ATR below baseline should not shrink spread below 1×."""
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        result = self.sim.execute_long(
            1.1000, ts, pair="EURUSD",
            vol_atr_pips=5.0,  # half baseline
        )
        assert result.vol_multiplier == 1.0


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------
class TestBackwardCompat:
    def test_long_short_still_work(self):
        np.random.seed(42)
        sim = ExecutionSimulator()
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        long_r = sim.execute_long(1.1000, ts, pair="EURUSD")
        short_r = sim.execute_short(1.1000, ts, pair="EURUSD")
        # Long pays spread upward, short pays downward
        assert long_r.executed_price > 1.1000
        assert short_r.executed_price < 1.1000

    def test_default_lot_size(self):
        np.random.seed(42)
        sim = ExecutionSimulator()
        ts = pd.Timestamp("2026-07-10 08:00:00Z")
        result = sim.execute_long(1.1000, ts)
        # Commission = 7.0 × 0.1 = 0.7
        assert result.commission == pytest.approx(0.7)

    def test_calculate_pip_value_non_jpy(self):
        sim = ExecutionSimulator()
        # 0.1 lot × 100000 × 0.0001 = 1.0
        assert sim.calculate_pip_value("EURUSD", 0.1) == pytest.approx(1.0)

    def test_calculate_pip_value_jpy(self):
        sim = ExecutionSimulator()
        # 0.1 lot × 100000 × 0.01 = 100.0
        assert sim.calculate_pip_value("USDJPY", 0.1) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Per-trade breakdown
# ---------------------------------------------------------------------------
class TestPerTradeBreakdown:
    def test_result_has_all_breakdown_fields(self):
        np.random.seed(42)
        sim = ExecutionSimulator()
        ts = pd.Timestamp("2026-07-10 13:00:00Z")
        result = sim.execute_long(
            1.1000, ts, pair="EURUSD",
            lot_size=0.5, vol_atr_pips=15.0,
        )
        assert result.session == "ny_overlap"
        assert result.pair == "EURUSD"
        assert result.base_spread_pips == 0.3  # NY_OVERLAP for EURUSD
        assert result.vol_multiplier == 1.5  # 15/10
        # Effective spread = 0.3 × 1.5 = 0.45 pips
        effective_pips = result.base_spread_pips * result.vol_multiplier
        expected_cost = effective_pips * 0.0001
        assert result.spread_cost == pytest.approx(expected_cost, rel=1e-6)

    def test_off_hours_has_highest_spread(self):
        """OFF_HOURS should have the highest base spread for most pairs."""
        np.random.seed(42)
        sim = ExecutionSimulator()
        pair = "EURUSD"
        results = {}
        for session_name, hour in [
            ("asian", 2), ("london", 8),
            ("ny_overlap", 13), ("ny_afternoon", 17), ("off_hours", 21),
        ]:
            ts = pd.Timestamp(f"2026-07-10 {hour:02d}:00:00Z")
            r = sim.execute_long(1.1000, ts, pair=pair)
            results[session_name] = r.base_spread_pips

        assert results["off_hours"] == max(results.values())
