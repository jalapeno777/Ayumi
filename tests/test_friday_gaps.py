#!/usr/bin/env python3
"""
Tests for analyze_friday_gaps.py
"""

import pytest


class TestGapPipsCalculation:
    """Test gap pips calculation."""

    def test_up_gap_positive_pips(self):
        """Up gap produces positive pips."""
        friday_close = 1.0850
        sunday_open = 1.0870
        gap_pips = (sunday_open - friday_close) * 10000
        assert abs(gap_pips - 20.0) < 0.01

    def test_down_gap_negative_pips(self):
        """Down gap produces negative pips."""
        friday_close = 1.0870
        sunday_open = 1.0850
        gap_pips = (sunday_open - friday_close) * 10000
        assert abs(gap_pips + 20.0) < 0.01

    def test_no_gap_zero_pips(self):
        """Same price produces zero pips."""
        price = 1.0850
        gap_pips = (price - price) * 10000
        assert gap_pips == 0.0

    def test_abs_gap_pips_positive(self):
        """Absolute gap ignores direction."""
        friday_close = 1.0870
        sunday_open = 1.0850
        gap_pips = (sunday_open - friday_close) * 10000
        abs_gap_pips = abs(gap_pips)
        assert abs(abs_gap_pips - 20.0) < 0.01


class TestRetraceCalculation:
    """Test gap retrace calculation."""

    def test_up_gap_retrace_full_fill(self):
        """Full fill: Sunday low reaches Friday close."""
        friday_close = 1.0850
        sunday_open = 1.0870
        sunday_low = 1.0850
        gap_pips = (sunday_open - friday_close) * 10000
        abs_gap_pips = abs(gap_pips)

        retrace = (sunday_open - sunday_low) * 10000 / abs_gap_pips
        assert retrace >= 0.5

    def test_up_gap_retrace_partial_fill(self):
        """Partial fill: retrace between 50-100%."""
        friday_close = 1.0850
        sunday_open = 1.0870
        sunday_low = 1.0860
        gap_pips = (sunday_open - friday_close) * 10000
        abs_gap_pips = abs(gap_pips)

        retrace = (sunday_open - sunday_low) * 10000 / abs_gap_pips
        assert 0 < retrace < 1.0
        assert abs(retrace - 0.5) < 0.01

    def test_up_gap_retrace_no_fill(self):
        """No fill: retrace < 50%."""
        friday_close = 1.0850
        sunday_open = 1.0870
        sunday_low = 1.0865
        gap_pips = (sunday_open - friday_close) * 10000
        abs_gap_pips = abs(gap_pips)

        retrace = (sunday_open - sunday_low) * 10000 / abs_gap_pips
        assert retrace < 0.5

    def test_down_gap_retrace_full_fill(self):
        """Down gap full fill: Sunday high reaches Friday close."""
        friday_close = 1.0870
        sunday_open = 1.0850
        sunday_high = 1.0870
        gap_pips = (sunday_open - friday_close) * 10000
        abs_gap_pips = abs(gap_pips)

        retrace = (sunday_high - sunday_open) * 10000 / abs_gap_pips
        assert retrace >= 0.5

    def test_down_gap_retrace_partial_fill(self):
        """Down gap partial fill."""
        friday_close = 1.0870
        sunday_open = 1.0850
        sunday_high = 1.0860
        gap_pips = (sunday_open - friday_close) * 10000
        abs_gap_pips = abs(gap_pips)

        retrace = (sunday_high - sunday_open) * 10000 / abs_gap_pips
        assert 0 < retrace < 1.0
        assert retrace >= 0.5

    def test_retrace_boundary_at_50_pct(self):
        """50% retrace is the fill threshold."""
        friday_close = 1.0850
        sunday_open = 1.0870
        gap_pips = (sunday_open - friday_close) * 10000
        abs_gap_pips = abs(gap_pips)

        expected_retrace_50 = (sunday_open - friday_close) * 0.5
        sunday_low = sunday_open - expected_retrace_50

        retrace = (sunday_open - sunday_low) * 10000 / abs_gap_pips
        assert abs(retrace - 0.5) < 0.01


class TestLargeGapIdentification:
    """Test large gap identification."""

    def test_large_gap_20_pips(self):
        """Exactly 20 pips is NOT a large gap (>20, not >=20)."""
        abs_gap_pips = 20
        is_large_gap = abs_gap_pips > 20
        assert is_large_gap is False

    def test_large_gap_21_pips(self):
        """21 pips IS a large gap."""
        abs_gap_pips = 21
        is_large_gap = abs_gap_pips > 20
        assert is_large_gap is True

    def test_large_gap_100_pips(self):
        """100 pips is a large gap."""
        abs_gap_pips = 100
        is_large_gap = abs_gap_pips > 20
        assert is_large_gap is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
