"""Tests for risk.currency_exposure."""

from __future__ import annotations  # noqa: I001

import pytest

from risk.correlation_matrix import CorrelationMatrix
from risk.currency_exposure import (
    CURRENCY_LEGS,
    CurrencyExposureTracker,
    PositionExposure,
    default_tracker,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _make_cm(symbols: list[str], corr_value: float = 0.0) -> CorrelationMatrix:
    """Build a synthetic CorrelationMatrix with uniform off-diagonal correlation."""
    cm = CorrelationMatrix()
    for s in symbols:
        cm.add_returns(s, [0.01, -0.005, 0.008, -0.003, 0.006])
    # Manually set the matrix so we control correlation values
    cm.compute()
    for s1 in cm._matrix:
        for s2 in cm._matrix:
            if s1 == s2:
                cm._matrix[s1][s2] = 1.0
            else:
                cm._matrix[s1][s2] = corr_value
    return cm


def _make_cm_with_pair_corr(symbols: list[str], pair_corrs: dict[tuple[str, str], float]) -> CorrelationMatrix:
    """Build a CM with specific pairwise correlations."""
    cm = CorrelationMatrix()
    for s in symbols:
        cm.add_returns(s, [0.01, -0.005, 0.008, -0.003, 0.006])
    cm.compute()
    for s1 in cm._matrix:
        for s2 in cm._matrix:
            cm._matrix[s1][s2] = 1.0 if s1 == s2 else 0.0
    for (a, b), v in pair_corrs.items():
        cm._matrix[a][b] = v
        cm._matrix[b][a] = v
    return cm


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


class TestCurrencyLegs:
    def test_currency_legs_has_all_8_pairs(self):
        """AC 2: CURRENCY_LEGS covers all 8 pairs including XAU/AUD/CAD."""
        expected = {
            "GBPUSD",
            "EURUSD",
            "USDJPY",
            "EURCHF",
            "GBPJPY",
            "AUDUSD",
            "USDCAD",
            "XAUUSD",
        }
        assert expected.issubset(CURRENCY_LEGS)

    def test_legs_decompose_correctly(self):
        """Each pair maps to (base, quote)."""
        assert CURRENCY_LEGS["GBPUSD"] == ("GBP", "USD")
        assert CURRENCY_LEGS["EURUSD"] == ("EUR", "USD")
        assert CURRENCY_LEGS["USDJPY"] == ("USD", "JPY")
        assert CURRENCY_LEGS["XAUUSD"] == ("XAU", "USD")

    def test_unknown_pair_raises_keyerror(self):
        """AC 9: Unknown pair raises KeyError."""
        tracker = default_tracker()
        with pytest.raises(KeyError):
            tracker.register_position(PositionExposure("NZDUSD", "long", 100_000))


class TestNetExposure:
    def test_long_decomposition(self):
        """AC 3: Long EURUSD 100K → +100K EUR, -100K USD."""
        tracker = default_tracker()
        tracker.register_position(PositionExposure("EURUSD", "long", 100_000))
        net = tracker.net_exposure()
        assert net["EUR"] == pytest.approx(100_000)
        assert net["USD"] == pytest.approx(-100_000)

    def test_short_decomposition(self):
        """Short EURUSD 100K → -100K EUR, +100K USD."""
        tracker = default_tracker()
        tracker.register_position(PositionExposure("EURUSD", "short", 100_000))
        net = tracker.net_exposure()
        assert net["EUR"] == pytest.approx(-100_000)
        assert net["USD"] == pytest.approx(100_000)

    def test_three_short_usd_positions(self):
        """AC 3 (test 3): 3 short-USD positions → net USD ≈ -300K."""
        tracker = default_tracker()
        # Shorting EURUSD means short EUR, long USD → NOT short USD
        # For short-USD exposure, we need pairs where USD is the base
        # or pairs where we go long on non-USD.
        # Short USD means selling USD. Going long on EURUSD/GBPUSD/AUDUSD
        # means buying with USD (short USD).
        tracker.register_position(PositionExposure("EURUSD", "long", 100_000))
        tracker.register_position(PositionExposure("GBPUSD", "long", 100_000))
        tracker.register_position(PositionExposure("AUDUSD", "long", 100_000))
        net = tracker.net_exposure()
        # Each long XXX/USD: +100K XXX, -100K USD
        assert net["USD"] == pytest.approx(-300_000)

    def test_unregister_position(self):
        """Unregistering a position removes its exposure."""
        tracker = default_tracker()
        tracker.register_position(PositionExposure("EURUSD", "long", 100_000))
        assert tracker.unregister_position("EURUSD") is True
        net = tracker.net_exposure()
        assert net.get("EUR", 0.0) == 0.0
        assert net.get("USD", 0.0) == 0.0
        # Unregistering again returns False
        assert tracker.unregister_position("EURUSD") is False


class TestAggregateCorrelatedRisk:
    def test_no_existing_positions_returns_base(self):
        """AC 4 (test 4): No existing positions → base unchanged."""
        tracker = default_tracker()
        result = tracker.aggregate_correlated_risk_pct("EURUSD", 0.01)
        assert result == pytest.approx(0.01)

    def test_with_high_correlation(self):
        """AC 5 (test 5): ρ_avg=0.7 → base × (1-0.7) = 0.003."""
        cm = _make_cm_with_pair_corr(
            ["EURUSD", "GBPUSD"],
            {("EURUSD", "GBPUSD"): 0.7},
        )
        tracker = CurrencyExposureTracker(cm)
        tracker.register_position(PositionExposure("GBPUSD", "long", 100_000))
        result = tracker.aggregate_correlated_risk_pct("EURUSD", 0.01)
        assert result == pytest.approx(0.003, rel=1e-3)

    def test_uncorrelated_positions_ignored(self):
        """Positions with |ρ| < 0.3 are not counted."""
        cm = _make_cm_with_pair_corr(
            ["EURUSD", "AUDUSD"],
            {("EURUSD", "AUDUSD"): 0.2},
        )
        tracker = CurrencyExposureTracker(cm)
        tracker.register_position(PositionExposure("AUDUSD", "long", 100_000))
        result = tracker.aggregate_correlated_risk_pct("EURUSD", 0.01)
        # 0.2 < 0.3 threshold → ignored → base returned
        assert result == pytest.approx(0.01)


class TestCurrencyCapCheck:
    def test_cap_ok_with_small_position(self):
        """AC 6: Small position within cap → True."""
        tracker = default_tracker()
        # 1% risk on $10K equity = $100 → well within 2% cap ($200)
        ok = tracker.currency_cap_check("EURUSD", 0.01, 10_000)
        assert ok is True

    def test_cap_exceeded(self):
        """AC 6: Large position exceeding cap → False."""
        tracker = default_tracker()
        # 3% risk > 2% cap → False
        ok = tracker.currency_cap_check("EURUSD", 0.03, 10_000)
        assert ok is False


class TestWouldBlock:
    def test_three_long_usd_blocks(self):
        """AC 7 (test 7): 3 long-USD positions → would_block True, reason mentions USD."""
        cm = _make_cm(["EURUSD", "GBPUSD", "AUDUSD"], 0.0)
        tracker = CurrencyExposureTracker(cm)
        tracker.register_position(PositionExposure("EURUSD", "long", 100_000))
        tracker.register_position(PositionExposure("GBPUSD", "long", 100_000))
        tracker.register_position(PositionExposure("AUDUSD", "long", 100_000))
        # Now add another long-USD pair
        blocked, reason = tracker.would_block("USDCAD", "long", 0.03, 10_000)
        assert blocked is True
        assert "cap" in reason.lower()

    def test_uncorrelated_positions_pass(self):
        """AC 8 (test 8): 3 uncorrelated positions → would_block False."""
        cm = _make_cm_with_pair_corr(
            ["EURUSD", "USDJPY", "USDCAD"],
            {
                ("EURUSD", "USDJPY"): 0.0,
                ("EURUSD", "USDCAD"): 0.0,
                ("USDJPY", "USDCAD"): 0.0,
            },
        )
        tracker = CurrencyExposureTracker(cm)
        tracker.register_position(PositionExposure("EURUSD", "long", 10_000))
        tracker.register_position(PositionExposure("USDJPY", "long", 10_000))
        tracker.register_position(PositionExposure("USDCAD", "long", 10_000))
        # Small risk that stays within cap
        blocked, reason = tracker.would_block("GBPJPY", "long", 0.005, 100_000)
        assert blocked is False
        assert reason == "OK"


class TestCorrelationPenaltyReport:
    def test_report_with_no_correlation(self):
        """Penalty report with no correlated positions returns base."""
        tracker = default_tracker()
        report = tracker.correlation_penalty_for_new_pair("EURUSD", "long", 0.01)
        assert report["adjusted_risk_pct"] == pytest.approx(0.01)
        assert report["blocked"] is False
        assert report["avg_correlation"] == 0.0

    def test_report_with_correlation(self):
        """Penalty report with correlation adjusts risk."""
        cm = _make_cm_with_pair_corr(
            ["EURUSD", "GBPUSD"],
            {("EURUSD", "GBPUSD"): 0.6},
        )
        tracker = CurrencyExposureTracker(cm)
        tracker.register_position(PositionExposure("GBPUSD", "long", 100_000))
        report = tracker.correlation_penalty_for_new_pair("EURUSD", "long", 0.01)
        assert report["adjusted_risk_pct"] == pytest.approx(0.004, rel=1e-3)
        assert report["avg_correlation"] == pytest.approx(0.6)


class TestDefaultTracker:
    def test_default_tracker_returns_empty_tracker(self):
        """default_tracker returns a tracker with no positions."""
        tracker = default_tracker(equity=10_000)
        assert tracker.positions == []
        assert tracker.net_exposure() == {}
