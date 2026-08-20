"""Direct unit coverage for previously untested signal_engine components."""

from __future__ import annotations  # noqa: I001

from datetime import datetime, timezone

import pandas as pd
import pytest

from signal_engine.backtest_bridge import SignalEngineBridge
from signal_engine.data_types import (
    HTFPhase,
    HTFState,
    Level,
    LevelType,
    Signal,
    Swing,
    SwingType,
)
from signal_engine.htf_analyzer import HTFAnalyzer
from signal_engine.level_counter import LevelCounter
from signal_engine.risk_sizer import (
    ConfidencePositionSizer,
    ConfidenceTier,
    parse_tiers,
)
from signal_engine.session_logic import SessionAnalyzer, get_ny_kz_hours
from signal_engine.swing_detector import SwingDetector
from signal_engine.tp_manager import TPManager


class TestConfidencePositionSizer:
    def test_get_risk_pct_uses_expected_tiers_and_bounds(self):
        sizer = ConfidencePositionSizer(account_size=10_000)

        assert sizer.get_risk_pct(0.85) == pytest.approx(0.015)
        assert sizer.get_risk_pct(0.70) == pytest.approx(0.0075)
        assert sizer.get_risk_pct(0.10) == pytest.approx(0.001)
        assert sizer.get_risk_pct(1.20) == pytest.approx(0.015)

    def test_get_risk_amount_and_lot_size(self):
        sizer = ConfidencePositionSizer(account_size=20_000)

        assert sizer.get_risk_amount(0.85) == pytest.approx(300.0)
        assert sizer.get_lot_size(0.85, stop_pips=20, pip_size=0.0001) == pytest.approx(150000.0)

    def test_get_lot_size_returns_zero_for_zero_stop_distance(self):
        sizer = ConfidencePositionSizer()

        assert sizer.get_lot_size(0.60, stop_pips=0, pip_size=0.0001) == 0.0

    def test_get_tier_label_handles_upper_and_lower_extremes(self):
        sizer = ConfidencePositionSizer()

        assert sizer.get_tier_label(0.92) == "85%-100%"
        assert sizer.get_tier_label(1.20) == "85%+"
        assert sizer.get_tier_label(0.52) == "50%-70%"
        assert sizer.get_tier_label(0.10) == "<20%"

    def test_parse_tiers_builds_custom_tier_objects(self):
        tiers = parse_tiers("[[0.6, 1.0, 0.02], [0.0, 0.6, 0.01]]")

        assert tiers == [
            ConfidenceTier(0.6, 1.0, 0.02),
            ConfidenceTier(0.0, 0.6, 0.01),
        ]


class TestLevelCounter:
    def test_detect_levels_returns_empty_without_both_sides(self):
        counter = LevelCounter()
        swing_highs = [Swing(2, 1.1100, SwingType.HIGH)]

        assert counter.detect_levels(swing_highs, []) == []

    def test_detect_levels_counts_new_highs_and_new_lows(self):
        counter = LevelCounter()
        swing_highs = [
            Swing(1, 1.1000, SwingType.HIGH),
            Swing(3, 1.1200, SwingType.HIGH),
            Swing(5, 1.1300, SwingType.HIGH),
        ]
        swing_lows = [
            Swing(0, 1.0900, SwingType.LOW),
            Swing(2, 1.0800, SwingType.LOW),
            Swing(4, 1.0700, SwingType.LOW),
        ]

        levels = counter.detect_levels(swing_highs, swing_lows)

        assert [level.level_type for level in levels] == [
            LevelType.R1,
            LevelType.D1,
            LevelType.R2,
            LevelType.D2,
            LevelType.R3,
        ]
        assert all(level.completed for level in levels)

    def test_detect_levels_with_tracking_stores_prior_r2_and_d2_magnitudes(self):
        counter = LevelCounter()
        swing_highs = [
            Swing(1, 1.1000, SwingType.HIGH),
            Swing(3, 1.1200, SwingType.HIGH),
            Swing(5, 1.1300, SwingType.HIGH),
        ]
        swing_lows = [
            Swing(0, 1.0900, SwingType.LOW),
            Swing(2, 1.0800, SwingType.LOW),
            Swing(4, 1.0700, SwingType.LOW),
        ]

        counter.detect_levels_with_tracking(swing_highs, swing_lows)

        assert counter._prev_rise_magnitude == pytest.approx(0.04)
        assert counter._prev_drop_magnitude == pytest.approx(0.05)

    def test_feed_to_htf_formats_level_payload(self):
        counter = LevelCounter()
        level = Level(1.1250, LevelType.R2, 0.0200, 12, completed=True)

        assert counter.feed_to_htf(level) == {
            "price": 1.1250,
            "type": "R2",
            "magnitude": 0.0200,
            "bar_index": 12,
            "completed": True,
        }


class TestHTFAnalyzer:
    def test_analyze_phase_returns_neutral_for_short_series(self):
        analyzer = HTFAnalyzer()

        state = analyzer.analyze_phase({"highs": [1, 2], "lows": [1, 1], "closes": [1, 2]})

        assert state == HTFState(HTFPhase.NEUTRAL, 0.0, 0.0, 0.0)

    def test_analyze_phase_detects_consolidation(self):
        analyzer = HTFAnalyzer()
        highs = [100.0 + (i % 2) * 0.02 for i in range(20)]
        lows = [99.9 - (i % 2) * 0.02 for i in range(20)]
        closes = [99.96 + (i % 2) * 0.01 for i in range(20)]
        ema = [100.0] * 20

        state = analyzer.analyze_phase({"highs": highs, "lows": lows, "closes": closes, "ema_50": ema})

        assert state.phase == HTFPhase.CONSOLIDATING
        assert state.ema_slope == 0.0
        assert state.range_size < 0.005

    def test_analyze_phase_detects_exhaustion_near_period_high(self):
        analyzer = HTFAnalyzer()
        highs = list(range(100, 150))
        lows = list(range(50, 100))
        closes = list(range(100, 149)) + [149.0]
        ema = [100.0] * 50

        state = analyzer.analyze_phase({"highs": highs, "lows": lows, "closes": closes, "ema_50": ema})

        assert state.phase == HTFPhase.EXHAUSTION

    def test_analyze_phase_detects_aligned_when_ema_slope_is_meaningful(self):
        analyzer = HTFAnalyzer()
        highs = [100.0 + i for i in range(20)]
        lows = [99.0 + i for i in range(20)]
        closes = [99.5 + i for i in range(20)]
        ema = [100.0 + i for i in range(20)]

        state = analyzer.analyze_phase({"highs": highs, "lows": lows, "closes": closes, "ema_50": ema})

        assert state.phase == HTFPhase.ALIGNED
        assert state.ema_slope > 0.0001

    @pytest.mark.parametrize(
        ("mtf_data", "expected"),
        [
            (
                {"D1": "bullish", "H4": "bullish", "H1": "bullish", "M15": "bullish"},
                1.0,
            ),
            (
                {"D1": "bullish", "H4": "bullish", "H1": "bullish", "M15": "bearish"},
                0.75,
            ),
            (
                {"D1": "bullish", "H4": "bullish", "H1": "bullish", "M15": "bearish"},
                0.75,
            ),
            ({"D1": "bullish", "H4": "bullish", "H1": "bullish"}, 0.75),
            ({"D1": "bullish", "H4": "bullish", "M15": "bearish"}, 0.0),
            ({"H1": "bullish", "M15": "bullish"}, 0.0),
        ],
    )
    def test_analyze_htf_alignment_scores_expected_cases(self, mtf_data, expected):
        analyzer = HTFAnalyzer()

        assert analyzer.analyze_htf_alignment(mtf_data) == expected

    def test_reconcile_dual_mechanism_handles_phase_specific_paths(self):
        analyzer = HTFAnalyzer()

        consolidating = analyzer.reconcile_dual_mechanism(HTFPhase.CONSOLIDATING, "long")
        conflicting = analyzer.reconcile_dual_mechanism(HTFPhase.ALIGNED, "long", htf_direction="short")
        aligned = analyzer.reconcile_dual_mechanism(HTFPhase.ALIGNED, "long", htf_direction="long")

        assert consolidating == {
            "htf_phase": HTFPhase.CONSOLIDATING,
            "htf_modifier": -0.15,
            "allowed": True,
        }
        assert conflicting == {
            "htf_phase": HTFPhase.CONFLICTING,
            "htf_modifier": -0.25,
            "allowed": True,
        }
        assert aligned == {
            "htf_phase": HTFPhase.ALIGNED,
            "htf_modifier": 0.15,
            "allowed": True,
        }


class TestSwingDetector:
    def test_detect_swings_finds_basic_swing_highs_and_lows(self):
        detector = SwingDetector(lookback=1)
        highs = [1, 2, 3, 5, 3, 2, 1, 2, 4, 2, 1]
        lows = [0.5, 1, 1.5, 2, 1.5, 1, 0.5, 1, 1.5, 1, 0.5]

        swing_highs, swing_lows = detector.detect_swings(highs, lows)

        assert [(s.bar_index, s.price) for s in swing_highs] == [(3, 5.0), (8, 4.0)]
        assert [(s.bar_index, s.price) for s in swing_lows] == [(6, 0.5)]

    def test_detect_swings_skips_inside_bars(self):
        detector = SwingDetector(lookback=1)
        highs = [3.0, 5.0, 4.0, 3.0]
        lows = [1.0, 0.5, 1.0, 0.2]

        swing_highs, swing_lows = detector.detect_swings(highs, lows)

        assert [(s.bar_index, s.price) for s in swing_highs] == [(1, 5.0)]
        assert [(s.bar_index, s.price) for s in swing_lows] == [(1, 0.5)]

    def test_merge_nearby_removes_nearly_equal_duplicate_swings(self):
        detector = SwingDetector(lookback=1)

        merged = detector._merge_nearby([(3, 1.1000), (5, 1.1004), (8, 1.1020)])

        assert merged == [(3, 1.1000), (8, 1.1020)]

    def test_get_swing_series_marks_detected_levels_on_dataframe(self):
        detector = SwingDetector(lookback=1)
        df = pd.DataFrame(
            {
                "high": [1, 2, 3, 5, 3, 2, 1, 2, 4, 2, 1],
                "low": [0.5, 1, 1.5, 2, 1.5, 1, 0.5, 1, 1.5, 1, 0.5],
            }
        )

        result = detector.get_swing_series(df)

        assert result.loc[3, "swing_high"] == 5.0
        assert result.loc[8, "swing_high"] == 4.0
        assert result.loc[6, "swing_low"] == 0.5
        assert pd.isna(result.loc[0, "swing_high"])


class TestSessionAnalyzer:
    def test_get_current_session_prioritizes_overlap_names(self):
        analyzer = SessionAnalyzer()

        assert analyzer.get_current_session(datetime(2026, 5, 14, 7, 30, tzinfo=timezone.utc)) == "ASIA_LONDON"
        assert analyzer.get_current_session(datetime(2026, 5, 14, 12, 30, tzinfo=timezone.utc)) == "LONDON_NY"
        assert analyzer.get_current_session(datetime(2026, 5, 14, 22, 0, tzinfo=timezone.utc)) == "OUTSIDE"

    def test_get_ny_kz_hours_switches_with_dst(self):
        assert get_ny_kz_hours(True) == (
            datetime.strptime("12:30", "%H:%M").time(),
            datetime.strptime("14:00", "%H:%M").time(),
        )
        assert get_ny_kz_hours(False) == (
            datetime.strptime("13:30", "%H:%M").time(),
            datetime.strptime("15:00", "%H:%M").time(),
        )

    def test_is_kill_zone_and_name_are_dst_aware(self):
        analyzer = SessionAnalyzer()

        edt_dt = datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc)
        est_dt = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)

        assert analyzer.is_kill_zone(edt_dt) is True
        assert analyzer.get_kill_zone_name(edt_dt) == "NY"
        assert analyzer.is_kill_zone(est_dt) is True
        assert analyzer.get_kill_zone_name(est_dt) == "NY"

    def test_score_session_phase_handles_outside_and_asia_control(self):
        analyzer = SessionAnalyzer()

        outside = analyzer.score_session_phase("OUTSIDE")
        asia = analyzer.score_session_phase(
            "ASIA",
            price_action={"asia_range_pct": 0.01, "asia_direction": "bullish"},
        )

        assert outside["phase_score"] == 0.0
        assert asia["asia_control_score"] == 1.0
        assert asia["directional_bias"] == "bullish"

    def test_score_session_phase_with_time_scores_open_mid_close(self):
        analyzer = SessionAnalyzer()

        opening = analyzer.score_session_phase_with_time("LONDON", datetime(2026, 5, 14, 7, 30, tzinfo=timezone.utc))
        mid = analyzer.score_session_phase_with_time("LONDON", datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc))
        closing = analyzer.score_session_phase_with_time("LONDON", datetime(2026, 5, 14, 15, 30, tzinfo=timezone.utc))

        assert opening["phase_score"] == 1.0
        assert mid["phase_score"] == 0.5
        assert closing["phase_score"] == 0.2

    def test_get_weekly_modifier_uses_weekday_mapping(self):
        analyzer = SessionAnalyzer()

        assert analyzer.get_weekly_modifier(datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)) == -0.10
        assert analyzer.get_weekly_modifier(datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)) == 0.05
        assert analyzer.get_weekly_modifier(datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)) == 0.0

    def test_check_ny_open_manipulation_detects_wicky_context(self):
        analyzer = SessionAnalyzer()
        bars_before_ny = [
            {"open": 1.10, "close": 1.101, "high": 1.104, "low": 1.098},
            {"open": 1.10, "close": 1.1005, "high": 1.104, "low": 1.099},
            {"open": 1.10, "close": 1.1003, "high": 1.105, "low": 1.0985},
            {"open": 1.10, "close": 1.1002, "high": 1.103, "low": 1.099},
            {"open": 1.10, "close": 1.1001, "high": 1.1035, "low": 1.0992},
            {"open": 1.10, "close": 1.1004, "high": 1.104, "low": 1.0991},
        ]
        ny_open = {"open": 1.1005, "close": 1.1007, "high": 1.1045, "low": 1.0995}

        result = analyzer.check_ny_open_manipulation(bars_before_ny, ny_open)

        assert result["manipulation_detected"] is True
        assert "Wick-heavy" in result["notes"]


class TestTPManager:
    def test_long_initializes_tp_levels_from_stop_distance(self):
        manager = TPManager(entry_price=1.1000, stop_price=1.0950, pip_size=0.0001, direction="long")

        assert manager.tp1_price == pytest.approx(1.1050)
        assert manager.tp2_price == pytest.approx(1.1075)
        assert manager.tp3_price == pytest.approx(1.1100)

    def test_short_initializes_tp_levels_from_stop_distance(self):
        manager = TPManager(entry_price=1.1000, stop_price=1.1050, pip_size=0.0001, direction="short")

        assert manager.tp1_price == pytest.approx(1.0950)
        assert manager.tp2_price == pytest.approx(1.0925)
        assert manager.tp3_price == pytest.approx(1.0900)

    def test_update_marks_tp1_and_moves_stop_for_long(self):
        manager = TPManager(entry_price=1.1000, stop_price=1.0950, pip_size=0.0001, direction="long")

        hit = manager.update(high=1.1051, low=1.0990, close=1.1040)

        assert hit == "tp1"
        assert manager.tp1_hit is True
        assert manager.sl_moved_to_be is True
        assert manager.stop == pytest.approx(1.0999)

    def test_update_marks_tp2_and_locks_stop_at_tp1_for_short(self):
        manager = TPManager(entry_price=1.1000, stop_price=1.1050, pip_size=0.0001, direction="short")

        hit = manager.update(high=1.1010, low=1.0924, close=1.0930)

        assert hit == "tp2"
        assert manager.tp1_hit is True
        assert manager.tp2_hit is True
        assert manager.sl_moved_to_tp1 is True
        assert manager.stop == pytest.approx(manager.tp1_price)

    def test_should_mandatory_exit_respects_new_york_time(self):
        assert TPManager.should_mandatory_exit(datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc)) is True
        assert TPManager.should_mandatory_exit(datetime(2026, 7, 1, 11, 59, tzinfo=timezone.utc)) is False


class TestSignalEngineBridge:
    def test_run_returns_empty_for_short_input(self):
        bridge = SignalEngineBridge()
        df = pd.DataFrame(
            {
                "open": [1.0] * 10,
                "high": [1.0] * 10,
                "low": [1.0] * 10,
                "close": [1.0] * 10,
            }
        )

        assert bridge.run(df) == []

    def test_run_orchestrates_components_and_filters_by_min_confidence(self, monkeypatch):
        bridge = SignalEngineBridge({"lookback": 5, "min_confidence": 0.5, "symbol": "GBPUSD"})
        df = pd.DataFrame(
            {
                "open": [1.0] * 60,
                "high": [1.1] * 60,
                "low": [0.9] * 60,
                "close": [1.0] * 60,
                "time": pd.date_range("2026-01-01", periods=60, freq="h", tz="UTC"),
            }
        )
        fake_highs = [Swing(1, 1.2, SwingType.HIGH)]
        fake_lows = [Swing(2, 0.8, SwingType.LOW)]
        fake_levels = [Level(1.0, LevelType.R1, 0.1, 5, completed=True)]
        calls = []

        monkeypatch.setattr(
            bridge.swing_detector,
            "detect_swings",
            lambda highs, lows: (fake_highs, fake_lows),
        )
        monkeypatch.setattr(
            bridge.level_counter,
            "detect_levels_with_tracking",
            lambda highs, lows: fake_levels,
        )

        def fake_evaluate(eval_df, idx):
            calls.append(idx)
            if idx == 0:
                return Signal("GBPUSD", "long", 1.0, 0.9, 1.3, 0.45)
            if idx == 1:
                return Signal("GBPUSD", "short", 1.0, 1.1, 0.7, 0.75)
            return None

        monkeypatch.setattr(bridge, "_evaluate_bar", fake_evaluate)

        signals = bridge.run(df)

        assert len(signals) == 1
        assert signals[0].direction == "short"
        assert bridge._swing_highs == fake_highs
        assert bridge._swing_lows == fake_lows
        assert bridge._levels == fake_levels
        assert calls == list(range(len(df.iloc[len(df) - bridge.lookback :])))

    def test_get_signals_for_bar_uses_cached_detection_when_needed(self, monkeypatch):
        bridge = SignalEngineBridge({"lookback": 3})
        df = pd.DataFrame(
            {
                "high": [1, 2, 3, 4, 5],
                "low": [0, 1, 2, 3, 4],
                "close": [0.5, 1.5, 2.5, 3.5, 4.5],
                "time": pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC"),
            }
        )
        fake_signal = Signal("EURUSD", "long", 1.0, 0.9, 1.2, 0.7)

        monkeypatch.setattr(
            bridge.swing_detector,
            "detect_swings",
            lambda highs, lows: (
                [Swing(1, 2.0, SwingType.HIGH)],
                [Swing(2, 1.0, SwingType.LOW)],
            ),
        )
        monkeypatch.setattr(
            bridge.level_counter,
            "detect_levels_with_tracking",
            lambda highs, lows: [Level(1.5, LevelType.R1, 0.5, 2, completed=True)],
        )
        monkeypatch.setattr(bridge, "_evaluate_bar", lambda df_in, idx: fake_signal)

        result = bridge.get_signals_for_bar(df, 4)

        assert result is fake_signal
        assert bridge._levels[0].level_type == LevelType.R1

    def test_get_signals_for_bar_returns_none_before_lookback(self):
        bridge = SignalEngineBridge({"lookback": 5})
        df = pd.DataFrame({"high": [1, 2, 3], "low": [0, 1, 2], "close": [0.5, 1.5, 2.5]})

        assert bridge.get_signals_for_bar(df, 2) is None

    def test_find_nearest_level_direction_confidence_and_timestamp_helpers(self):
        bridge = SignalEngineBridge()
        bridge._levels = [
            Level(1.1000, LevelType.R2, 0.01, 10, completed=True),
            Level(1.2000, LevelType.D3, 0.02, 11, completed=False),
        ]
        df = pd.DataFrame(
            {
                "high": [1.100, 1.105, 1.110],
                "low": [1.090, 1.095, 1.100],
                "close": [1.095, 1.100, 1.105],
                "time": [
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T01:00:00Z",
                    "2026-01-01T02:00:00Z",
                ],
            }
        )

        nearest = bridge._find_nearest_level(1.1010)
        stop_distance = bridge._estimate_stop_distance(df, 2, "long")
        confidence = bridge._calculate_confidence(nearest, 0.0015, 2)
        timestamp = bridge._get_timestamp(df, 1)

        assert nearest.level_type == LevelType.R2
        assert bridge._determine_direction(Level(1.1000, LevelType.R2, 0.01, 0), 1.0990) == "long"
        assert bridge._determine_direction(Level(1.1000, LevelType.D2, 0.01, 0), 1.1010) == "short"
        assert bridge._determine_direction(Level(1.1000, LevelType.R3, 0.01, 0), 1.0990) == "short"
        assert bridge._determine_direction(Level(1.1000, LevelType.D3, 0.01, 0), 1.1010) == "long"
        assert stop_distance > 0
        assert confidence == pytest.approx(0.60)
        assert timestamp == datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
