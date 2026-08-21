"""Tests for cTrader interface protocols (Phase 0.5).

Verifies that:
1. Concrete stubs satisfy the Protocol interfaces (structural typing).
2. ``@runtime_checkable`` ``isinstance`` checks pass.
3. ``OrderResult`` covers all ``OrderStatus`` transitions.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from adapters.ctrader.protocols import (
    Bar,
    MarketFeedProtocol,
    OrderGatewayProtocol,
    OrderResult,
    OrderStatus,
    Position,
    SessionProtocol,
    SessionState,
    Tick,
    TradeSide,
)

# ── Stub implementations ─────────────────────────────────────────────────────


class _StubMarketFeed:
    """Minimal stub satisfying MarketFeedProtocol."""

    def start(self, auto_subscribe: list[str] | None = None) -> bool:
        return True

    def stop(self) -> None:
        pass

    @property
    def is_running(self) -> bool:
        return True

    @property
    def is_connected(self) -> bool:
        return True

    @property
    def ticks_received(self) -> int:
        return 0

    @property
    def bars_built(self) -> int:
        return 0

    def subscribe(self, symbol_name: str) -> bool:
        return True

    def unsubscribe(self, symbol_name: str) -> bool:
        return True

    def get_tick(self, symbol_name: str) -> Tick | None:
        return None

    def get_all_ticks(self) -> dict[str, Tick]:
        return {}

    def get_spread(self, symbol_name: str) -> float | None:
        return None

    def resolve_symbol_id(self, name: str) -> int:
        return 1

    def fetch_trendbars(self, symbol: str, period_minutes: int, count: int) -> list[Bar]:
        return []

    def on_tick(self, callback) -> None:
        pass

    def register_callback(self, event_name: str, fn) -> None:
        pass

    def get_health(self) -> dict:
        return {}


class _StubOrderGateway:
    """Minimal stub satisfying OrderGatewayProtocol."""

    def send_market_order(
        self,
        symbol_id: int,
        side: TradeSide,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        comment: str = "",
    ) -> OrderResult:
        return OrderResult(status=OrderStatus.FILLED, order_id="test-1")

    def cancel_order(self, order_id: int) -> bool:
        return True

    def amend_position(
        self,
        position_id: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> bool:
        return True

    def close_position(self, position_id: int, volume: float) -> bool:
        return True

    def reconcile(self) -> list[Position]:
        return []


class _StubSession:
    """Minimal stub satisfying SessionProtocol."""

    @property
    def is_operational(self) -> bool:
        return True

    @property
    def state(self) -> SessionState:
        return SessionState.SUBSCRIBED

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def send(self, message, client_msg_id: str, timeout: float = 30.0):
        return None


# ── Tests ────────────────────────────────────────────────────────────────────


class TestProtocolStructuralTyping:
    """Protocols use structural typing — stubs don't need to inherit."""

    def test_market_feed_stub_is_instance(self):
        """_StubMarketFeed satisfies MarketFeedProtocol via isinstance."""
        feed = _StubMarketFeed()
        assert isinstance(feed, MarketFeedProtocol)

    def test_order_gateway_stub_is_instance(self):
        """_StubOrderGateway satisfies OrderGatewayProtocol via isinstance."""
        gw = _StubOrderGateway()
        assert isinstance(gw, OrderGatewayProtocol)

    def test_session_stub_is_instance(self):
        """_StubSession satisfies SessionProtocol via isinstance."""
        session = _StubSession()
        assert isinstance(session, SessionProtocol)


class TestOrderResultStatusCoverage:
    """OrderResult must represent every OrderStatus transition."""

    @pytest.mark.parametrize("status", list(OrderStatus))
    def test_order_result_can_hold_status(self, status: OrderStatus):
        """Every OrderStatus value can be set on an OrderResult."""
        result = OrderResult(status=status)
        assert result.status is status

    def test_filled_result_carries_price_and_volume(self):
        result = OrderResult(
            status=OrderStatus.FILLED,
            order_id="ord-42",
            filled_price=1.08500,
            filled_volume=0.01,
            execution_time_ms=250,
        )
        assert result.status is OrderStatus.FILLED
        assert result.filled_price == pytest.approx(1.08500)
        assert result.filled_volume == pytest.approx(0.01)

    def test_rejected_result_carries_error(self):
        result = OrderResult(
            status=OrderStatus.REJECTED,
            error_code="INVALID_VOLUME",
            error_message="Volume below minimum",
        )
        assert result.status is OrderStatus.REJECTED
        assert result.error_code == "INVALID_VOLUME"

    def test_timeout_result(self):
        result = OrderResult(
            status=OrderStatus.TIMEOUT,
            execution_time_ms=30_000,
        )
        assert result.status is OrderStatus.TIMEOUT
        assert result.execution_time_ms == 30_000


class TestDataclassImmutability:
    """Frozen dataclasses are hashable and immutable."""

    def test_tick_is_frozen(self):
        t = Tick(
            symbol="EURUSD",
            bid=1.0850,
            ask=1.0851,
            timestamp=datetime(2026, 6, 16, tzinfo=timezone.utc),
        )
        with pytest.raises(AttributeError):
            t.bid = 1.0900  # type: ignore[misc]

    def test_order_result_is_frozen(self):
        r = OrderResult(status=OrderStatus.FILLED)
        with pytest.raises(AttributeError):
            r.status = OrderStatus.REJECTED  # type: ignore[misc]

    def test_tick_spread_and_mid(self):
        t = Tick(
            symbol="GBPUSD",
            bid=1.2700,
            ask=1.2702,
            timestamp=datetime(2026, 6, 16, tzinfo=timezone.utc),
        )
        assert t.spread == pytest.approx(0.0002)
        assert t.mid == pytest.approx(1.2701)
