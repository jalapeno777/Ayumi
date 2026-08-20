"""Tests for session-aware spread modelling.

Rewritten for post-refactor API (card 99a4d28d).
- ExecutionSimulator/SPREAD_TABLE removed → use SpreadModel/RealisticSpreadModel
- config.sessions → core.types.SessionType + engine.base.determine_session
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime, timezone


from core.spread import RealisticSpreadModel, SpreadModel
from engine.base import determine_session


class TestSpreadModel:
    def test_basic_spread(self):
        model = SpreadModel(spread_pips=1.5, slippage_pips=0.5)
        assert model.spread_pips == 1.5
        assert model.slippage_pips == 0.5

    def test_realistic_spread_creation(self):
        model = RealisticSpreadModel(default_spread_pips=1.0, slippage_pips=0.3)
        assert model is not None


class TestSessionDetection:
    """Tests for session-aware spread variation via determine_session."""

    def test_london_session(self):
        dt = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
        session = determine_session(dt)
        assert session == "london"

    def test_ny_am_session(self):
        dt = datetime(2024, 1, 1, 13, 0, tzinfo=timezone.utc)
        session = determine_session(dt)
        assert session == "ny_am"

    def test_asian_session(self):
        dt = datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc)
        session = determine_session(dt)
        assert session == "asian"

    def test_outside_session(self):
        dt = datetime(2024, 1, 1, 22, 0, tzinfo=timezone.utc)
        session = determine_session(dt)
        assert session == "outside"

    def test_handles_naive_datetime(self):
        """determine_session converts naive to UTC."""
        dt = datetime(2024, 1, 1, 9, 0)  # naive
        session = determine_session(dt)
        assert session == "london"
