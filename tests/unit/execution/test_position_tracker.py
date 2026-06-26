"""Tests for PositionTracker — position tracking and cTrader reconciliation.

All network / SDK calls are mocked. No real cTrader connection is made.

Reference: BQ-1043 Phase 3c.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from adapters.ctrader.protocols import Position, PositionStatus
from adapters.ctrader.position_tracker import PositionTracker


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_mock_session(reconcile_response=None):
    """Return a MagicMock session with a canned reconcile response."""
    session = MagicMock()
    session.send.return_value = reconcile_response
    return session


def _make_reconcile_response(positions):
    """Build a duck-typed ProtoOAReconcileRes mock.

    ``positions`` is a list of dicts with keys matching cTrader field names.
    """
    payload = MagicMock()

    pos_mocks = []
    for p in positions:
        td = MagicMock()
        td.symbolId = p.get("symbol_id", 1)
        td.volume = p.get("volume", 100_000)
        td.tradeSide = p.get("trade_side", 1)

        raw = MagicMock()
        raw.positionId = p.get("position_id", "1")
        raw.tradeData = td
        raw.price = p.get("price", 1.1000)
        raw.stopLoss = p.get("sl", 0)
        raw.takeProfit = p.get("tp", 0)

        pos_mocks.append(raw)

    payload.position = pos_mocks

    response = MagicMock()
    response.payload = payload
    return response


# ── Tests ──────────────────────────────────────────────────────────────────


class TestPositionTracker:
    """Unit tests for PositionTracker."""

    def test_open_position(self):
        """on_position_opened adds a position; get_open_positions returns it."""
        tracker = PositionTracker(session=_make_mock_session())

        tracker.on_position_opened(
            position_id=1001,
            symbol="GBPUSD",
            direction="BUY",
            volume=0.10,
            entry_price=1.3000,
        )

        positions = tracker.get_open_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.position_id == "1001"
        assert pos.symbol == "GBPUSD"
        assert pos.direction == "BUY"
        assert pos.volume == pytest.approx(0.10)
        assert pos.entry_price == pytest.approx(1.3000)
        assert pos.status == PositionStatus.OPEN

    def test_close_position(self):
        """Open then close → get_open_positions is empty."""
        tracker = PositionTracker(session=_make_mock_session())

        tracker.on_position_opened(
            position_id=2002, symbol="EURUSD", direction="SELL",
            volume=0.05, entry_price=1.1000,
        )
        assert len(tracker.get_open_positions()) == 1

        tracker.on_position_closed(position_id=2002, pnl=15.50)
        assert len(tracker.get_open_positions()) == 0

    def test_update_prices(self):
        """update_prices patches current_price and computes PnL."""
        tracker = PositionTracker(session=_make_mock_session())

        tracker.on_position_opened(
            position_id=3003, symbol="EURUSD", direction="BUY",
            volume=0.10, entry_price=1.1000,
        )

        tracker.update_prices({"EURUSD": 1.1050})

        pos = tracker.get_position(3003)
        assert pos is not None
        assert pos.current_price == pytest.approx(1.1050)
        # BUY 0.10 lot at 1.1000 → 1.1050 = +50 pips
        # 0.10 * 100_000 * (1.1050 - 1.1000) = 50.0
        assert pos.pnl == pytest.approx(50.0)

    def test_get_position_by_id(self):
        """get_position returns the right one by ID."""
        tracker = PositionTracker(session=_make_mock_session())

        tracker.on_position_opened(
            position_id=4001, symbol="USDJPY", direction="BUY",
            volume=0.20, entry_price=150.00,
        )
        tracker.on_position_opened(
            position_id=4002, symbol="GBPUSD", direction="SELL",
            volume=0.15, entry_price=1.2800,
        )

        pos = tracker.get_position(4002)
        assert pos is not None
        assert pos.symbol == "GBPUSD"
        assert pos.direction == "SELL"

        missing = tracker.get_position(9999)
        assert missing is None

    def test_pnl_calculation(self):
        """Verify PnL math for a BUY position."""
        tracker = PositionTracker(session=_make_mock_session())

        tracker.on_position_opened(
            position_id=5001, symbol="EURUSD", direction="BUY",
            volume=1.0, entry_price=1.1000,
        )

        tracker.update_prices({"EURUSD": 1.1050})

        pos = tracker.get_position(5001)
        assert pos is not None
        # 1.0 lot * 100_000 * (1.1050 - 1.1000) = 500
        assert pos.pnl == pytest.approx(500.0)

        # SELL direction should be opposite
        tracker.on_position_opened(
            position_id=5002, symbol="EURUSD", direction="SELL",
            volume=1.0, entry_price=1.1000,
        )
        tracker.update_prices({"EURUSD": 1.1050})

        pos_short = tracker.get_position(5002)
        assert pos_short is not None
        # SELL: (1.1000 - 1.1050) * 100_000 = -500
        assert pos_short.pnl == pytest.approx(-500.0)

    def test_reconcile_no_discrepancies(self):
        """Mock session returns matching position → empty discrepancy list."""
        # Local tracker has position 6001
        tracker = PositionTracker(session=_make_mock_session())

        tracker.on_position_opened(
            position_id=6001, symbol="EURUSD", direction="BUY",
            volume=1.0, entry_price=1.1000,
        )

        # cTrader returns the same position
        ctrader_resp = _make_reconcile_response([
            {"position_id": "6001", "price": 1.1000, "volume": 100_000},
        ])
        tracker._session.send.return_value = ctrader_resp

        discrepancies = tracker.reconcile_with_ctrader()
        assert discrepancies == []

    def test_reconcile_finds_extra_ctrader_position(self):
        """cTrader has a position we don't track locally → discrepancy."""
        tracker = PositionTracker(session=_make_mock_session())

        # Locally we track position 7001
        tracker.on_position_opened(
            position_id=7001, symbol="EURUSD", direction="BUY",
            volume=1.0, entry_price=1.1000,
        )

        # cTrader returns position 7001 (known) + 7002 (unknown)
        ctrader_resp = _make_reconcile_response([
            {"position_id": "7001", "price": 1.1000, "volume": 100_000},
            {"position_id": "7002", "price": 1.2500, "volume": 100_000,
             "symbol_id": 2},
        ])
        tracker._session.send.return_value = ctrader_resp

        discrepancies = tracker.reconcile_with_ctrader()
        assert len(discrepancies) == 1
        assert discrepancies[0].position_id == "7002"
