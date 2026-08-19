"""Tests for ConfluenceDetector."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from confidence.confluence import ConfluenceDetector
from strategies.registry import StrategyConfig, StrategyRegistry


def _make_registry() -> StrategyRegistry:
    reg = StrategyRegistry()
    reg.register(
        StrategyConfig(
            strategy_id="mr1",
            name="MR1",
            strategy_type="mean_reversion",
            symbols=["EURUSD"],
            timeframes=["H1"],
            typical_confidence_range=(0.4, 0.7),
        )
    )
    reg.register(
        StrategyConfig(
            strategy_id="mr2",
            name="MR2",
            strategy_type="mean_reversion",
            symbols=["EURUSD"],
            timeframes=["M15"],
            typical_confidence_range=(0.4, 0.7),
        )
    )
    reg.register(
        StrategyConfig(
            strategy_id="mom1",
            name="Mom1",
            strategy_type="momentum",
            symbols=["EURUSD"],
            timeframes=["H1"],
            typical_confidence_range=(0.5, 0.8),
        )
    )
    reg.register(
        StrategyConfig(
            strategy_id="trend1",
            name="Trend1",
            strategy_type="trend",
            symbols=["EURUSD"],
            timeframes=["D1"],
            typical_confidence_range=(0.5, 0.8),
        )
    )
    return reg


NOW = datetime(2026, 4, 24, 17, 0, tzinfo=timezone.utc)


class TestConfluenceDetector:
    def test_single_signal_no_confluence(self):
        reg = _make_registry()
        det = ConfluenceDetector(reg)
        det.record_signal("mr1", "EURUSD", "long", 0.6, NOW)
        result = det.get_confluence("EURUSD", "long", NOW)
        assert result.confluence_score == 0.0
        assert len(result.agreeing_strategies) == 1

    def test_two_same_type_score_0_3(self):
        reg = _make_registry()
        det = ConfluenceDetector(reg)
        det.record_signal("mr1", "EURUSD", "long", 0.6, NOW)
        det.record_signal("mr2", "EURUSD", "long", 0.5, NOW)
        result = det.get_confluence("EURUSD", "long", NOW)
        assert result.confluence_score == 0.3
        assert result.cross_type_agreement is False

    def test_two_different_types_score_0_5(self):
        reg = _make_registry()
        det = ConfluenceDetector(reg)
        det.record_signal("mr1", "EURUSD", "long", 0.6, NOW)
        det.record_signal("mom1", "EURUSD", "long", 0.7, NOW)
        result = det.get_confluence("EURUSD", "long", NOW)
        assert result.confluence_score == 0.5
        assert result.cross_type_agreement is True

    def test_three_strategies_same_type_score_0_7(self):
        reg = _make_registry()
        det = ConfluenceDetector(reg)
        # Two MR + add a third MR via a second registry entry
        reg.register(
            StrategyConfig(
                strategy_id="mr3",
                name="MR3",
                strategy_type="mean_reversion",
                symbols=["EURUSD"],
                timeframes=["M5"],
                typical_confidence_range=(0.4, 0.7),
            )
        )
        det.record_signal("mr1", "EURUSD", "long", 0.6, NOW)
        det.record_signal("mr2", "EURUSD", "long", 0.5, NOW)
        det.record_signal("mr3", "EURUSD", "long", 0.5, NOW)
        result = det.get_confluence("EURUSD", "long", NOW)
        assert result.confluence_score == 0.7
        assert result.cross_type_agreement is False

    def test_three_strategies_different_types_score_0_9(self):
        reg = _make_registry()
        det = ConfluenceDetector(reg)
        det.record_signal("mr1", "EURUSD", "long", 0.6, NOW)
        det.record_signal("mom1", "EURUSD", "long", 0.7, NOW)
        det.record_signal("trend1", "EURUSD", "long", 0.6, NOW)
        result = det.get_confluence("EURUSD", "long", NOW)
        assert result.confluence_score == 0.9
        assert len(result.agreeing_types) == 3

    def test_window_expiry_old_signals_ignored(self):
        reg = _make_registry()
        det = ConfluenceDetector(reg, window_minutes=60)
        old = NOW - timedelta(minutes=61)
        det.record_signal("mr1", "EURUSD", "long", 0.6, old)
        det.record_signal("mom1", "EURUSD", "long", 0.7, NOW)
        result = det.get_confluence("EURUSD", "long", NOW)
        assert result.confluence_score == 0.0

    def test_wrong_direction_no_agreement(self):
        reg = _make_registry()
        det = ConfluenceDetector(reg)
        det.record_signal("mr1", "EURUSD", "long", 0.6, NOW)
        det.record_signal("mom1", "EURUSD", "long", 0.7, NOW)
        result = det.get_confluence("EURUSD", "short", NOW)
        assert result.confluence_score == 0.0

    def test_cross_type_agreement_flag(self):
        reg = _make_registry()
        det = ConfluenceDetector(reg)
        det.record_signal("mr1", "EURUSD", "long", 0.6, NOW)
        det.record_signal("mom1", "EURUSD", "long", 0.7, NOW)
        result = det.get_confluence("EURUSD", "long", NOW)
        assert result.cross_type_agreement is True

    def test_agreeing_timeframes_populated(self):
        reg = _make_registry()
        det = ConfluenceDetector(reg)
        det.record_signal("mr1", "EURUSD", "long", 0.6, NOW)
        det.record_signal("trend1", "EURUSD", "long", 0.6, NOW)
        result = det.get_confluence("EURUSD", "long", NOW)
        assert "H1" in result.agreeing_timeframes
        assert "D1" in result.agreeing_timeframes
