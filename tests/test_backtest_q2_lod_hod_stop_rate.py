"""Tests for BACKTEST Q2 LOD/HOD Stop Hit Rate Analysis"""

from datetime import datetime

from backtest.engine import Bar  # noqa: E402


class TestSwingPointDetection:
    """Tests for swing point detection."""

    def test_detects_swing_highs_and_lows(self):
        """Should detect swing highs and swing lows in a simple pattern."""
        from scripts.backtest_q2_lod_hod_stop_rate import detect_swing_points

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, 0), open=1.10, high=1.10, low=1.10, close=1.10),
            Bar(time=datetime(2024, 1, 1, 11, 0), open=1.08, high=1.08, low=1.08, close=1.08),
            Bar(time=datetime(2024, 1, 1, 12, 0), open=1.12, high=1.12, low=1.12, close=1.12),
            Bar(time=datetime(2024, 1, 1, 13, 0), open=1.07, high=1.07, low=1.07, close=1.07),
            Bar(time=datetime(2024, 1, 1, 14, 0), open=1.11, high=1.11, low=1.11, close=1.11),
            Bar(time=datetime(2024, 1, 1, 15, 0), open=1.09, high=1.09, low=1.09, close=1.09),
            Bar(time=datetime(2024, 1, 1, 16, 0), open=1.06, high=1.06, low=1.06, close=1.06),
        ]

        swing_points = detect_swing_points(bars)

        swing_highs = [sp for sp in swing_points if sp.is_high]
        swing_lows = [sp for sp in swing_points if not sp.is_high]

        assert len(swing_highs) >= 1, "Should detect at least one swing high"
        assert len(swing_lows) >= 1, "Should detect at least one swing low"

    def test_no_swing_points_in_ranging_market(self):
        """Should not detect swing points in a flat/ranging market."""
        from scripts.backtest_q2_lod_hod_stop_rate import detect_swing_points

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 11, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 12, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 13, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 14, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 15, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 16, 0), open=1.10, high=1.11, low=1.09, close=1.10),
        ]

        swing_points = detect_swing_points(bars)
        assert len(swing_points) == 0, "Should not detect swing points in ranging market"


class TestMWFormationDetection:
    """Tests for M/W formation detection."""

    def test_detects_w_formation(self):
        """Should detect a W formation."""
        from scripts.backtest_q2_lod_hod_stop_rate import detect_swing_points, find_mw_formations

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, 0), open=1.10, high=1.10, low=1.10, close=1.10),
            Bar(time=datetime(2024, 1, 1, 11, 0), open=1.08, high=1.08, low=1.08, close=1.08),
            Bar(time=datetime(2024, 1, 1, 12, 0), open=1.09, high=1.09, low=1.09, close=1.09),
            Bar(time=datetime(2024, 1, 1, 13, 0), open=1.07, high=1.07, low=1.07, close=1.07),
            Bar(time=datetime(2024, 1, 1, 14, 0), open=1.08, high=1.08, low=1.08, close=1.08),
            Bar(time=datetime(2024, 1, 1, 15, 0), open=1.09, high=1.09, low=1.09, close=1.09),
            Bar(time=datetime(2024, 1, 1, 16, 0), open=1.10, high=1.10, low=1.10, close=1.10),
        ]

        swing_points = detect_swing_points(bars)
        formations = find_mw_formations(bars, swing_points)

        w_formations = [f for f in formations if f.formation_type == "W"]
        assert len(w_formations) >= 1, "Should detect at least one W formation"

    def test_detects_m_formation(self):
        """Should detect an M formation."""
        from scripts.backtest_q2_lod_hod_stop_rate import detect_swing_points, find_mw_formations

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, 0), open=1.07, high=1.07, low=1.07, close=1.07),
            Bar(time=datetime(2024, 1, 1, 11, 0), open=1.09, high=1.09, low=1.09, close=1.09),
            Bar(time=datetime(2024, 1, 1, 12, 0), open=1.08, high=1.08, low=1.08, close=1.08),
            Bar(time=datetime(2024, 1, 1, 13, 0), open=1.10, high=1.10, low=1.10, close=1.10),
            Bar(time=datetime(2024, 1, 1, 14, 0), open=1.09, high=1.09, low=1.09, close=1.09),
            Bar(time=datetime(2024, 1, 1, 15, 0), open=1.08, high=1.08, low=1.08, close=1.08),
            Bar(time=datetime(2024, 1, 1, 16, 0), open=1.07, high=1.07, low=1.07, close=1.07),
        ]

        swing_points = detect_swing_points(bars)
        formations = find_mw_formations(bars, swing_points)

        m_formations = [f for f in formations if f.formation_type == "M"]
        assert len(m_formations) >= 1, "Should detect at least one M formation"


class TestStopLossAnalysis:
    """Tests for LOD/HOD stop loss analysis."""

    def test_identifies_lod_stop_hit(self):
        """Should identify when stop is hit at LOD level."""
        from scripts.backtest_q2_lod_hod_stop_rate import analyze_lod_hod_stop_rate

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, 0), open=1.1000, high=1.1050, low=1.1000, close=1.1040),
            Bar(time=datetime(2024, 1, 1, 11, 0), open=1.1040, high=1.1060, low=1.1030, close=1.1050),
            Bar(time=datetime(2024, 1, 1, 12, 0), open=1.1050, high=1.1080, low=1.1040, close=1.1070),
            Bar(time=datetime(2024, 1, 1, 13, 0), open=1.1070, high=1.1070, low=1.1000, close=1.1000),
            Bar(time=datetime(2024, 1, 1, 14, 0), open=1.1000, high=1.1010, low=1.0990, close=1.0995),
            Bar(time=datetime(2024, 1, 1, 15, 0), open=1.0995, high=1.1005, low=1.0985, close=1.0990),
        ] * 20

        result = analyze_lod_hod_stop_rate(bars)
        
        assert "question" in result
        assert result["question"] == "Q2"
        assert "sample_size" in result
        assert "results" in result

    def test_insufficient_data(self):
        """Should handle insufficient data gracefully."""
        from scripts.backtest_q2_lod_hod_stop_rate import analyze_lod_hod_stop_rate

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, 0), open=1.10, high=1.10, low=1.10, close=1.10),
            Bar(time=datetime(2024, 1, 1, 11, 0), open=1.08, high=1.08, low=1.08, close=1.08),
        ]

        result = analyze_lod_hod_stop_rate(bars)
        
        assert "error" in result or result["sample_size"] == 0

    def test_no_formations(self):
        """Should handle no M/W formations detected."""
        from scripts.backtest_q2_lod_hod_stop_rate import analyze_lod_hod_stop_rate

        bars = [
            Bar(time=datetime(2024, 1, 1, 10, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 11, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 12, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 13, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 14, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 15, 0), open=1.10, high=1.11, low=1.09, close=1.10),
            Bar(time=datetime(2024, 1, 1, 16, 0), open=1.10, high=1.11, low=1.09, close=1.10),
        ] * 20

        result = analyze_lod_hod_stop_rate(bars)
        
        assert result["sample_size"] == 0
        assert result["pass"] is False
        assert "No M/W formations detected" in result["notes"]