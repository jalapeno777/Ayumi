"""Tests for TPManager: 3-level TP system with progressive SL management."""

from __future__ import annotations

from datetime import datetime

import pytz
import pytest

from signal_engine.tp_manager import TPManager


def _long_manager(entry=1.1000, stop=1.0950, pip_size=0.0001):
    return TPManager(entry, stop, pip_size, direction="long")


def _short_manager(entry=1.1000, stop=1.1050, pip_size=0.0001):
    return TPManager(entry, stop, pip_size, direction="short")


# ── TP Level Prices ────────────────────────────────────────────────


class TestTPLevels:
    def test_long_tp1_at_1r(self):
        mgr = _long_manager()
        assert mgr.tp1_price == pytest.approx(1.1000 + 0.0050 * 1.0)

    def test_long_tp2_at_1_5r(self):
        mgr = _long_manager()
        assert mgr.tp2_price == pytest.approx(1.1000 + 0.0050 * 1.5)

    def test_long_tp3_at_2r(self):
        mgr = _long_manager()
        assert mgr.tp3_price == pytest.approx(1.1000 + 0.0050 * 2.0)

    def test_short_tp1_at_1r(self):
        mgr = _short_manager()
        assert mgr.tp1_price == 1.1000 - 0.0050 * 1.0

    def test_short_tp3_at_2r(self):
        mgr = _short_manager()
        assert mgr.tp3_price == pytest.approx(1.1000 - 0.0050 * 2.0)

    def test_position_sizes_sum_to_one(self):
        assert (
            TPManager.TP1_SIZE + TPManager.TP2_SIZE + TPManager.TP3_SIZE
            == pytest.approx(1.0)
        )


# ── Update / Hit Detection ─────────────────────────────────────────


class TestHitDetection:
    def test_no_hit(self):
        mgr = _long_manager()
        result = mgr.update(high=1.1010, low=1.0990, close=1.1005)
        assert result is None
        assert not mgr.tp1_hit

    def test_tp1_hit(self):
        mgr = _long_manager()
        result = mgr.update(high=mgr.tp1_price, low=1.0990, close=1.1000)
        assert result == "tp1"
        assert mgr.tp1_hit
        assert not mgr.tp2_hit

    def test_tp2_hit_implies_tp1(self):
        mgr = _long_manager()
        result = mgr.update(high=mgr.tp2_price, low=1.0990, close=1.1000)
        assert result == "tp2"
        assert mgr.tp1_hit
        assert mgr.tp2_hit

    def test_tp3_hit_implies_all(self):
        mgr = _long_manager()
        result = mgr.update(high=mgr.tp3_price, low=1.0990, close=1.1000)
        assert result == "tp3"
        assert mgr.tp1_hit and mgr.tp2_hit and mgr.tp3_hit

    def test_short_tp1_hit(self):
        mgr = _short_manager()
        result = mgr.update(high=1.1010, low=mgr.tp1_price, close=1.1000)
        assert result == "tp1"


# ── Progressive SL ─────────────────────────────────────────────────


class TestProgressiveSL:
    def test_initial_sl_unchanged(self):
        mgr = _long_manager()
        mgr.update(high=1.1010, low=1.0990, close=1.1005)
        assert mgr.stop == mgr.original_stop

    def test_after_tp1_sl_moved_to_breakeven(self):
        mgr = _long_manager()
        mgr.update(high=mgr.tp1_price, low=1.0990, close=1.1000)
        assert mgr.sl_moved_to_be is True
        # BE + 1 pip for long: max(original_stop, entry - 1 pip)
        assert mgr.stop == max(mgr.original_stop, mgr.entry - mgr.pip_size)

    def test_after_tp2_sl_moved_to_tp1(self):
        mgr = _long_manager()
        mgr.update(high=mgr.tp2_price, low=1.0990, close=1.1000)
        assert mgr.sl_moved_to_tp1 is True
        assert mgr.stop == mgr.tp1_price

    def test_short_after_tp1_breakeven(self):
        mgr = _short_manager()
        mgr.update(high=1.1010, low=mgr.tp1_price, close=1.1000)
        assert mgr.sl_moved_to_be is True
        assert mgr.stop == min(mgr.original_stop, mgr.entry + mgr.pip_size)

    def test_short_after_tp2_moved_to_tp1(self):
        mgr = _short_manager()
        mgr.update(high=1.1010, low=mgr.tp2_price, close=1.1000)
        assert mgr.sl_moved_to_tp1 is True


# ── Mandatory Exit ─────────────────────────────────────────────────


class TestMandatoryExit:
    def test_8am_ny_triggers_exit(self):
        dt = pytz.timezone("America/New_York").localize(datetime(2026, 1, 1, 8, 0))
        assert TPManager.should_mandatory_exit(dt) is True

    def test_7am_ny_no_exit(self):
        dt = pytz.timezone("America/New_York").localize(datetime(2026, 1, 1, 7, 0))
        assert TPManager.should_mandatory_exit(dt) is False

    def test_noon_ny_no_exit(self):
        dt = pytz.timezone("America/New_York").localize(datetime(2026, 1, 1, 12, 0))
        assert TPManager.should_mandatory_exit(dt) is False

    def test_utc_input_handled(self):
        dt = pytz.utc.localize(datetime(2026, 1, 1, 13, 0))  # 8am NY in winter
        assert TPManager.should_mandatory_exit(dt) is True

    def test_naive_datetime_handled(self):
        dt = datetime(2026, 1, 1, 13, 0)  # naive UTC
        assert TPManager.should_mandatory_exit(dt) is True
