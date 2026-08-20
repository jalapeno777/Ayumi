#!/usr/bin/env python3
"""Unit tests for FTMO broker validation script.

Tests the statistics, parsing, and event-detection logic
without requiring a broker connection.
"""

import sys
from pathlib import Path

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest  # noqa: I001
from ftmo_broker_validation import (
    OrderRecord,
    SpreadSample,
    calculate_slippage_distribution,
    calculate_spread_stats,
    detect_spread_events,
    _percentile,
    _parse_ts,
    _classify_trigger,
    _dry_run_orders,
    _dry_run_spreads,
    CONDITIONS,
)


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def sample_orders():
    """Realistic order records across 2 pairs and 2 conditions."""
    return [
        OrderRecord(
            "2026-07-31T10:00:00Z",
            "EURUSD",
            "low_volatility",
            "buy",
            1.0850,
            1.0851,
            1.0,
            0.5,
            0.01,
            45.0,
            "filled",
        ),
        OrderRecord(
            "2026-07-31T10:00:01Z",
            "EURUSD",
            "low_volatility",
            "sell",
            1.0850,
            1.0849,
            1.0,
            0.5,
            0.01,
            52.0,
            "filled",
        ),
        OrderRecord(
            "2026-07-31T10:00:02Z",
            "EURUSD",
            "low_volatility",
            "buy",
            1.0850,
            1.0853,
            3.0,
            0.6,
            0.01,
            48.0,
            "filled",
        ),
        OrderRecord(
            "2026-07-31T10:00:03Z",
            "EURUSD",
            "news",
            "buy",
            1.0850,
            1.0858,
            8.0,
            3.0,
            0.01,
            120.0,
            "filled",
        ),
        OrderRecord(
            "2026-07-31T10:00:04Z",
            "GBPUSD",
            "low_volatility",
            "buy",
            1.2720,
            1.2722,
            2.0,
            0.8,
            0.01,
            55.0,
            "filled",
        ),
        OrderRecord(
            "2026-07-31T10:00:05Z",
            "GBPUSD",
            "news",
            "sell",
            1.2720,
            1.2720,
            0.0,
            4.0,
            0.01,
            200.0,
            "rejected",
        ),
        OrderRecord(
            "2026-07-31T10:00:06Z",
            "GBPUSD",
            "news",
            "buy",
            1.2720,
            1.2730,
            10.0,
            4.5,
            0.01,
            95.0,
            "filled",
        ),
    ]


@pytest.fixture
def sample_spreads():
    """Spread samples with a widening event for EURUSD."""
    samples = []
    # 10 normal samples
    for i in range(10):
        samples.append(
            SpreadSample(
                f"2026-07-31T10:00:{i:02d}Z",
                "EURUSD",
                "low_volatility",
                1.0849,
                1.0851,
                0.5,
            )
        )
    # 5 spiked samples (widening event)
    for i in range(10, 15):
        samples.append(
            SpreadSample(
                f"2026-07-31T10:00:{i:02d}Z",
                "EURUSD",
                "news",
                1.0840,
                1.0860,
                2.0,  # 4x baseline
            )
        )
    # 5 normal again
    for i in range(15, 20):
        samples.append(
            SpreadSample(
                f"2026-07-31T10:00:{i:02d}Z",
                "EURUSD",
                "low_volatility",
                1.0849,
                1.0851,
                0.5,
            )
        )
    return samples


# ─── Slippage distribution tests ─────────────────────────────────────


class TestSlippageDistribution:
    def test_per_pair_grouping(self, sample_orders):
        stats = calculate_slippage_distribution(sample_orders)
        assert "EURUSD" in stats
        assert "GBPUSD" in stats

    def test_eurusd_stats(self, sample_orders):
        stats = calculate_slippage_distribution(sample_orders)
        eur = stats["EURUSD"]
        # EURUSD filled orders: slips = [1.0, 1.0, 3.0, 8.0]
        assert eur["count"] == 4
        assert eur["min"] == 1.0
        assert eur["max"] == 8.0
        assert eur["mean"] == pytest.approx(3.25, abs=0.01)

    def test_gbpusd_excludes_rejected(self, sample_orders):
        stats = calculate_slippage_distribution(sample_orders)
        gbp = stats["GBPUSD"]
        # GBPUSD filled: [2.0, 10.0] — rejected order excluded
        assert gbp["count"] == 2

    def test_median_calculation(self, sample_orders):
        stats = calculate_slippage_distribution(sample_orders)
        # EURUSD slips sorted: [1.0, 1.0, 3.0, 8.0] → median = (1.0+3.0)/2 = 2.0
        assert stats["EURUSD"]["median"] == pytest.approx(2.0, abs=0.01)

    def test_empty_orders(self):
        stats = calculate_slippage_distribution([])
        assert stats == {}

    def test_all_rejected(self):
        orders = [
            OrderRecord(
                "2026-07-31T10:00:00Z",
                "EURUSD",
                "news",
                "buy",
                1.0,
                0.0,
                0.0,
                1.0,
                0.01,
                50.0,
                "rejected",
            ),
        ]
        stats = calculate_slippage_distribution(orders)
        assert stats == {}

    def test_p95_p99_present(self, sample_orders):
        stats = calculate_slippage_distribution(sample_orders)
        for pair, s in stats.items():  # noqa: B007
            assert "p95" in s
            assert "p99" in s
            assert s["p95"] >= s["median"]
            assert s["p99"] >= s["p95"]


# ─── Spread stats tests ──────────────────────────────────────────────


class TestSpreadStats:
    def test_basic_stats(self, sample_spreads):
        stats = calculate_spread_stats(sample_spreads)
        assert "EURUSD" in stats
        assert stats["EURUSD"]["count"] == 20

    def test_min_max(self, sample_spreads):
        stats = calculate_spread_stats(sample_spreads)
        assert stats["EURUSD"]["min"] == 0.5
        assert stats["EURUSD"]["max"] == 2.0

    def test_empty_samples(self):
        stats = calculate_spread_stats([])
        assert stats == {}


# ─── Spread event detection tests ────────────────────────────────────


class TestSpreadEventDetection:
    def test_detects_widening(self, sample_spreads):
        events = detect_spread_events(sample_spreads, widening_threshold=2.0)
        assert len(events) >= 1
        event = events[0]
        assert event.pair == "EURUSD"
        assert event.peak_spread_pips >= 2.0
        assert event.baseline_spread_pips == 0.5
        assert event.widening_factor >= 4.0

    def test_no_events_below_threshold(self, sample_spreads):
        # With threshold 10x, the 4x spike won't trigger
        events = detect_spread_events(sample_spreads, widening_threshold=10.0)
        assert len(events) == 0

    def test_too_short_duration(self, sample_spreads):
        # 1-second minimum but our spike lasts 5 seconds, so it should still trigger
        events = detect_spread_events(sample_spreads, min_duration_seconds=3.0)
        assert len(events) >= 1

    def test_empty_samples(self):
        events = detect_spread_events([])
        assert events == []

    def test_insufficient_samples(self):
        """Fewer than 3 samples should return no events."""
        samples = [
            SpreadSample("2026-07-31T10:00:00Z", "EURUSD", "news", 1.0, 1.1, 1.0),
            SpreadSample("2026-07-31T10:00:01Z", "EURUSD", "news", 1.0, 1.1, 1.0),
        ]
        events = detect_spread_events(samples)
        assert events == []


# ─── Utility function tests ──────────────────────────────────────────


class TestPercentile:
    def test_single_value(self):
        assert _percentile([5.0], 95) == 5.0

    def test_known_values(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert _percentile(data, 50) == pytest.approx(5.0, abs=0.5)
        assert _percentile(data, 95) == pytest.approx(10.0, abs=0.5)
        assert _percentile(data, 0) == 1.0

    def test_empty(self):
        assert _percentile([], 95) == 0.0


class TestParseTs:
    def test_iso_with_z(self):
        ts = "2026-07-31T10:00:00Z"
        result = _parse_ts(ts)
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 31

    def test_iso_with_offset(self):
        ts = "2026-07-31T10:00:00+00:00"
        result = _parse_ts(ts)
        assert result.year == 2026

    def test_invalid_fallback(self):
        result = _parse_ts("not-a-timestamp")
        # Falls back to now() — just verify it returns a datetime
        from datetime import datetime

        assert isinstance(result, datetime)


class TestClassifyTrigger:
    def test_news(self):
        assert _classify_trigger("news") == "news"

    def test_session_open(self):
        assert _classify_trigger("session_open") == "session_transition"

    def test_session_close(self):
        assert _classify_trigger("session_close") == "session_transition"

    def test_unknown(self):
        assert _classify_trigger("low_volatility") == "unknown"


# ─── Dry-run generation tests ────────────────────────────────────────


class TestDryRunGeneration:
    def test_orders_count(self):
        pairs = ["EURUSD", "GBPUSD"]
        conditions = ["low_volatility", "news"]
        orders = _dry_run_orders(pairs, conditions, orders_per_condition=20)
        assert len(orders) == 40  # 20 per condition × 2 conditions

    def test_orders_have_valid_status(self):
        orders = _dry_run_orders(["EURUSD"], ["low_volatility"], 10)
        valid_statuses = {"filled", "rejected", "requoted", "partial_fill"}
        for o in orders:
            assert o.status in valid_statuses

    def test_orders_deterministic(self):
        """Same seed should produce same output."""
        o1 = _dry_run_orders(["EURUSD"], ["low_volatility"], 5)
        o2 = _dry_run_orders(["EURUSD"], ["low_volatility"], 5)
        assert len(o1) == len(o2)
        for a, b in zip(o1, o2):  # noqa: B905
            assert a.slippage_pips == b.slippage_pips
            assert a.fill_price == b.fill_price

    def test_spread_samples_count(self):
        samples = _dry_run_spreads(["EURUSD", "GBPUSD"], ["low_volatility"], 10)
        assert len(samples) == 20  # 10 per pair × 2 pairs

    def test_spread_samples_valid(self):
        samples = _dry_run_spreads(["EURUSD"], ["news"], 5)
        for s in samples:
            assert s.pair == "EURUSD"
            assert s.bid < s.ask  # Bid always below ask
            assert s.spread_pips > 0


# ─── Conditions definition tests ─────────────────────────────────────


class TestConditionsConfig:
    def test_all_conditions_have_expected_keys(self):
        for name, cond in CONDITIONS.items():  # noqa: B007
            assert "description" in cond
            assert "sessions" in cond
            assert "expected_spread_pips" in cond

    def test_expected_spread_pairs_consistent(self):
        """Each condition should have spread data for common pairs."""
        for name, cond in CONDITIONS.items():  # noqa: B007
            # At least EURUSD should be in every condition
            assert "EURUSD" in cond["expected_spread_pips"]
