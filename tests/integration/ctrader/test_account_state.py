"""Tests for account_state — live cTrader account-state read helpers.

All cTrader SDK and protobuf calls are mocked. No live connection is
made. Tests cover:

* :func:`get_balance` — happy path, edge cases, error mapping
* :func:`get_open_positions` — parsing, filtering, side mapping
* :func:`subscribe_balance_updates` — dispatcher install, fan-out,
  filtering, unsubscribe
* Data classes (frozen-ness, defaults)

Reference: Account-state module (BQ-1043 follow-up).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from adapters.ctrader.account_state import (  # noqa: E402
    AccountStateError,
    BalanceQueryError,
    BalanceSubscriptionError,
    BalanceUpdate,
    Position,
    get_balance,
    get_open_positions,
    read_account_snapshot,
    subscribe_balance_updates,
)

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_trader_res(
    *,
    ctid_account_id: int = 5795523,
    balance: int = 100_000_00,  # cents — $100,000.00 when moneyDigits=2
    money_digits: int = 2,
    balance_version: int = 1,
) -> MagicMock:
    """Build a duck-typed ``ProtoOATraderRes`` mock."""
    trader = MagicMock()
    trader.balance = balance
    trader.moneyDigits = money_digits
    trader.balanceVersion = balance_version
    trader.ctidTraderAccountId = ctid_account_id
    trader.depositAssetId = 1

    res = MagicMock()
    res.payloadType = 2122  # PROTO_OA_TRADER_RES
    res.ctidTraderAccountId = ctid_account_id
    res.trader = trader
    return res


def _make_reconcile_res(
    *,
    ctid_account_id: int = 5795523,
    positions: list[dict] | None = None,
) -> MagicMock:
    """Build a duck-typed ``ProtoOAReconcileRes`` mock.

    ``positions`` is a list of dicts with cTrader-style field names.
    Note: cTrader's ``price``, ``stopLoss``, ``takeProfit`` are
    protobuf ``double`` fields — i.e. real decimal values, NOT scaled
    integers. Only ``volume`` is an int64 scaled by 100_000.
    """
    pos_mocks = []
    for spec in positions or []:
        td = MagicMock()
        td.symbolId = spec.get("symbol_id", 1)
        td.volume = spec.get("volume", 100_000)
        td.tradeSide = spec.get("trade_side", 1)
        td.openTimestamp = spec.get("open_timestamp_ms", 1_700_000_000_000)
        td.label = spec.get("label", "")
        td.comment = spec.get("comment", "")

        raw = MagicMock()
        raw.positionId = spec.get("position_id", "1001")
        raw.tradeData = td
        raw.positionStatus = spec.get("position_status", 1)  # OPEN
        raw.price = spec.get("price", 1.10000)
        raw.stopLoss = spec.get("sl", 0.0)
        raw.takeProfit = spec.get("tp", 0.0)
        raw.swap = spec.get("swap", 0)
        raw.commission = spec.get("commission", 0)
        raw.usedMargin = spec.get("used_margin", 0)
        raw.moneyDigits = spec.get("money_digits", 2)
        raw.utcLastUpdateTimestamp = spec.get("update_ts_ms", 1_700_000_000_000)
        pos_mocks.append(raw)

    payload = MagicMock()
    payload.position = pos_mocks
    payload.order = []  # No orders in reconcile for our tests.

    res = MagicMock()
    res.payloadType = 2125  # PROTO_OA_RECONCILE_RES
    res.ctidTraderAccountId = ctid_account_id
    res.position = pos_mocks  # Some clients expose this directly.
    # Make `res.payload` look right for both code paths.
    res.payload = payload
    return res


def _make_trader_updated_event(
    *,
    ctid_account_id: int = 5795523,
    balance: int = 100_000_00,
    money_digits: int = 2,
) -> MagicMock:
    """Build a duck-typed ``ProtoOATraderUpdatedEvent`` envelope."""
    trader = MagicMock()
    trader.balance = balance
    trader.moneyDigits = money_digits
    trader.balanceVersion = 1
    trader.ctidTraderAccountId = ctid_account_id
    trader.depositAssetId = 1

    envelope = MagicMock()
    envelope.payloadType = 2123  # PROTO_OA_TRADER_UPDATE_EVENT
    envelope.ctidTraderAccountId = ctid_account_id
    envelope.trader = trader
    return envelope


def _make_session_client(
    response: Any = None, *, raises: Exception | None = None
) -> MagicMock:
    """Build a MagicMock shaped like CTraderSession (has ``send``)."""
    client = MagicMock()
    if raises is not None:
        client.send.side_effect = raises
    else:
        client.send.return_value = response
    return client


def _make_connection_client(response: Any = None) -> MagicMock:
    """Build a MagicMock shaped like CTraderConnection (has ``send_and_wait``)."""
    client = MagicMock(spec=["send_and_wait"])
    client.send_and_wait.return_value = response
    return client


# ── get_balance ────────────────────────────────────────────────────────────


class TestGetBalance:
    """Tests for ``get_balance``."""

    def test_returns_decimal_balance_usd(self):
        """USD account with moneyDigits=2 — balance / 100 = Decimal."""
        client = _make_session_client(
            _make_trader_res(balance=100_000_00, money_digits=2)
        )

        result = get_balance(client, 5795523)

        assert result == Decimal("100000.00")
        assert isinstance(result, Decimal)

    def test_returns_decimal_balance_jpy(self):
        """JPY account with moneyDigits=0 — balance is the integer directly."""
        client = _make_session_client(
            _make_trader_res(balance=10_000_000, money_digits=0)
        )

        result = get_balance(client, 5795523)

        assert result == Decimal("10000000")
        assert isinstance(result, Decimal)

    def test_returns_decimal_balance_high_precision(self):
        """Account with moneyDigits=8 (crypto-style) — full precision preserved."""
        client = _make_session_client(
            _make_trader_res(balance=123_456_789, money_digits=8)
        )

        result = get_balance(client, 5795523)

        assert result == Decimal("1.23456789")

    def test_zero_balance(self):
        """Zero balance is returned as Decimal('0.00') not None."""
        client = _make_session_client(_make_trader_res(balance=0, money_digits=2))

        result = get_balance(client, 5795523)

        assert result == Decimal("0.00")
        assert result is not None

    def test_uses_session_style_send(self):
        """Verify the session.send(message, client_msg_id=..., timeout=...) signature."""
        client = _make_session_client(
            _make_trader_res(balance=50_000_00, money_digits=2)
        )

        get_balance(client, 5795523, timeout=5.0)

        assert client.send.call_count == 1
        args, kwargs = client.send.call_args
        # Message is the only positional arg.
        assert len(args) == 1
        # client_msg_id is a keyword arg with the "trader_query_" prefix.
        assert "client_msg_id" in kwargs
        assert kwargs["client_msg_id"].startswith("trader_query_")
        # Timeout passes through.
        assert kwargs["timeout"] == 5.0

    def test_uses_connection_style_send_and_wait(self):
        """When client has send_and_wait (no client_msg_id attr), use it."""
        client = _make_connection_client(_make_trader_res(balance=75_000_00))

        result = get_balance(client, 5795523)

        assert result == Decimal("75000.00")
        client.send_and_wait.assert_called_once()
        args, kwargs = client.send_and_wait.call_args
        assert len(args) == 2
        assert args[1] == 10.0  # default timeout
        assert kwargs.get("prefix") == "trader_query"

    def test_uses_custom_timeout(self):
        client = _make_session_client(_make_trader_res())

        get_balance(client, 5795523, timeout=3.0)

        assert client.send.call_args.kwargs["timeout"] == 3.0

    def test_timeout_returns_none(self):
        """When send returns None (timeout), get_balance returns None."""
        client = _make_session_client(None)

        result = get_balance(client, 5795523, timeout=1.0)

        assert result is None

    def test_missing_trader_raises(self):
        """Response missing trader field → BalanceQueryError."""
        bad = MagicMock()
        bad.payloadType = 2122
        bad.trader = None

        client = _make_session_client(bad)

        with pytest.raises(BalanceQueryError, match="missing 'trader'"):
            get_balance(client, 5795523)

    def test_missing_balance_raises(self):
        trader = MagicMock()
        trader.balance = None
        trader.moneyDigits = 2
        bad = MagicMock()
        bad.payloadType = 2122
        bad.trader = trader

        client = _make_session_client(bad)

        with pytest.raises(BalanceQueryError, match="balance"):
            get_balance(client, 5795523)

    def test_missing_money_digits_raises(self):
        trader = MagicMock()
        trader.balance = 100_000_00
        trader.moneyDigits = None
        bad = MagicMock()
        bad.payloadType = 2122
        bad.trader = trader

        client = _make_session_client(bad)

        with pytest.raises(BalanceQueryError, match="moneyDigits"):
            get_balance(client, 5795523)

    def test_invalid_money_digits_raises(self):
        trader = MagicMock()
        trader.balance = 100_000_00
        trader.moneyDigits = "not a number"
        bad = MagicMock()
        bad.payloadType = 2122
        bad.trader = trader

        client = _make_session_client(bad)

        with pytest.raises(BalanceQueryError):
            get_balance(client, 5795523)

    def test_out_of_range_money_digits_raises(self):
        trader = MagicMock()
        trader.balance = 100_000_00
        trader.moneyDigits = 19  # > 18
        bad = MagicMock()
        bad.payloadType = 2122
        bad.trader = trader

        client = _make_session_client(bad)

        with pytest.raises(BalanceQueryError, match="out of range"):
            get_balance(client, 5795523)

    def test_negative_money_digits_raises(self):
        trader = MagicMock()
        trader.balance = 100_000_00
        trader.moneyDigits = -1
        bad = MagicMock()
        bad.payloadType = 2122
        bad.trader = trader

        client = _make_session_client(bad)

        with pytest.raises(BalanceQueryError):
            get_balance(client, 5795523)

    def test_balance_query_error_is_account_state_error(self):
        """BalanceQueryError inherits from AccountStateError for typed except."""
        assert issubclass(BalanceQueryError, AccountStateError)


# ── get_open_positions ─────────────────────────────────────────────────────


class TestGetOpenPositions:
    """Tests for ``get_open_positions``."""

    def test_empty_when_no_positions(self):
        client = _make_session_client(_make_reconcile_res(positions=[]))

        positions = get_open_positions(client, 5795523)

        assert positions == []

    def test_single_buy_position(self):
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1001",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert len(positions) == 1
        pos = positions[0]
        assert pos.position_id == "1001"
        assert pos.side == "BUY"
        assert pos.symbol == "SYMBOL_1"
        assert pos.volume_lots == Decimal("1.0")
        assert pos.entry_price == Decimal("1.1")
        assert pos.sl is None  # default 0 → None
        assert pos.tp is None

    def test_single_sell_position(self):
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "2002",
                        "symbol_id": 2,
                        "trade_side": 2,
                        "volume": 50_000,
                        "price": 1.30000,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert len(positions) == 1
        pos = positions[0]
        assert pos.side == "SELL"
        assert pos.symbol == "SYMBOL_2"
        assert pos.volume_lots == Decimal("0.5")  # 50_000 / 100_000

    def test_multiple_positions(self):
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                    },
                    {
                        "position_id": "2",
                        "symbol_id": 2,
                        "trade_side": 2,
                        "volume": 200_000,
                        "price": 1.30000,
                    },
                    {
                        "position_id": "3",
                        "symbol_id": 4,
                        "trade_side": 1,
                        "volume": 10_000,
                        "price": 150.000,
                    },  # USDJPY, 0.10 lots
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert len(positions) == 3
        assert [p.position_id for p in positions] == ["1", "2", "3"]
        assert [p.volume_lots for p in positions] == [
            Decimal("1.0"),
            Decimal("2.0"),
            Decimal("0.1"),
        ]
        assert [p.side for p in positions] == ["BUY", "SELL", "BUY"]

    def test_position_with_sl_and_tp(self):
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                        "sl": 1.09500,
                        "tp": 1.11000,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        pos = positions[0]
        assert pos.sl == Decimal("1.095")
        assert pos.tp == Decimal("1.11")

    def test_position_without_sl_tp_returns_none(self):
        """0 SL/TP from cTrader maps to None (not Decimal('0'))."""
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                        "sl": 0,
                        "tp": 0,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert positions[0].sl is None
        assert positions[0].tp is None

    def test_open_time_parsed_as_utc_datetime(self):
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                        "open_timestamp_ms": 1_700_000_000_000,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        ts = positions[0].open_time
        assert ts is not None
        assert ts.tzinfo is timezone.utc
        # 1_700_000_000 sec = 2023-11-14 22:13:20 UTC.
        assert ts.year == 2023
        assert ts.month == 11
        assert ts.day == 14

    def test_open_time_none_for_zero_timestamp(self):
        """cTrader sends 0 when timestamp is unset."""
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                        "open_timestamp_ms": 0,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert positions[0].open_time is None

    def test_closed_positions_filtered_out(self):
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                        "position_status": 2,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert positions == []

    def test_error_positions_filtered_out(self):
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                        "position_status": 4,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert positions == []

    def test_created_positions_kept(self):
        """POSITION_STATUS_CREATED (3) is kept — order accepted, not yet open."""
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                        "position_status": 3,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert len(positions) == 1

    def test_unknown_side_filtered_out(self):
        """tradeSide not in {BUY=1, SELL=2} → position is skipped."""
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 99,
                        "volume": 100_000,
                        "price": 1.10000,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert positions == []

    def test_missing_trade_data_filtered(self):
        """Position with no tradeData → skipped (warning logged)."""
        bad = MagicMock()
        bad.payloadType = 2125
        bad.tradeData = None
        bad.positionStatus = 1
        bad.positionId = "1"
        bad.position = [bad]
        bad.payload = MagicMock()
        bad.payload.position = [bad]
        bad.payload.order = []
        client = _make_session_client(bad)

        positions = get_open_positions(client, 5795523)

        assert positions == []

    def test_partial_volume_lots(self):
        """Volume of 12_345 units = 0.12345 lots."""
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 12_345,
                        "price": 1.10000,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert positions[0].volume_lots == Decimal("0.12345")

    def test_price_precision_preserved(self):
        """5-digit price: 1.23456 stored as float 1.23456 → Decimal preserves precision."""
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.23456,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert positions[0].entry_price == Decimal("1.23456")

    def test_unrealized_pnl_default_zero(self):
        """Position.unrealized_pnl defaults to Decimal('0') — safe default."""
        client = _make_session_client(
            _make_reconcile_res(
                positions=[
                    {
                        "position_id": "1",
                        "symbol_id": 1,
                        "trade_side": 1,
                        "volume": 100_000,
                        "price": 1.10000,
                    },
                ]
            )
        )

        positions = get_open_positions(client, 5795523)

        assert positions[0].unrealized_pnl == Decimal("0")

    def test_timeout_returns_empty_list(self):
        client = _make_session_client(None)

        positions = get_open_positions(client, 5795523, timeout=1.0)

        assert positions == []

    def test_uses_connection_send_and_wait(self):
        client = _make_connection_client(_make_reconcile_res(positions=[]))

        positions = get_open_positions(client, 5795523)

        assert positions == []
        client.send_and_wait.assert_called_once()
        assert client.send_and_wait.call_args.kwargs.get("prefix") == "reconcile"

    def test_response_without_payload_attribute(self):
        """Some clients unwrap the envelope — response has .position directly."""
        raw = MagicMock(spec=["payloadType", "ctidTraderAccountId", "position"])
        raw.payloadType = 2125
        raw.ctidTraderAccountId = 5795523
        # No payload attr — so it should fall back to direct usage.
        pos = MagicMock()
        pos.positionId = "1"
        pos.tradeData = MagicMock()
        pos.tradeData.symbolId = 1
        pos.tradeData.volume = 100_000
        pos.tradeData.tradeSide = 1
        pos.tradeData.openTimestamp = 1_700_000_000_000
        pos.positionStatus = 1
        pos.price = 1.10000
        pos.stopLoss = 0.0
        pos.takeProfit = 0.0
        raw.position = [pos]
        client = _make_session_client(raw)

        positions = get_open_positions(client, 5795523)

        assert len(positions) == 1
        assert positions[0].position_id == "1"


# ── Position dataclass ─────────────────────────────────────────────────────


class TestPositionDataclass:
    """Frozen dataclass sanity checks."""

    def test_position_is_frozen(self):
        pos = Position(
            position_id="1",
            symbol="EURUSD",
            side="BUY",
            volume_lots=Decimal("0.1"),
            entry_price=Decimal("1.1"),
            sl=None,
            tp=None,
            open_time=None,
            unrealized_pnl=Decimal("0"),
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            pos.side = "SELL"  # type: ignore[misc]

    def test_position_fields(self):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        pos = Position(
            position_id="42",
            symbol="GBPUSD",
            side="SELL",
            volume_lots=Decimal("0.5"),
            entry_price=Decimal("1.3"),
            sl=Decimal("1.31"),
            tp=Decimal("1.29"),
            open_time=ts,
            unrealized_pnl=Decimal("-100.50"),
        )

        assert pos.position_id == "42"
        assert pos.symbol == "GBPUSD"
        assert pos.side == "SELL"
        assert pos.volume_lots == Decimal("0.5")
        assert pos.entry_price == Decimal("1.3")
        assert pos.sl == Decimal("1.31")
        assert pos.tp == Decimal("1.29")
        assert pos.open_time == ts
        assert pos.unrealized_pnl == Decimal("-100.50")


# ── subscribe_balance_updates ──────────────────────────────────────────────


class TestSubscribeBalanceUpdates:
    """Tests for ``subscribe_balance_updates``."""

    def setup_method(self):
        """Reset the dispatcher registry between tests.

        Without this, dispatchers leak between tests via the
        module-level ``_BalanceDispatcher._registry``.
        """
        from adapters.ctrader.account_state import _BalanceDispatcher

        _BalanceDispatcher._registry.clear()

    def test_subscribe_installs_callback(self):
        client = MagicMock()
        received: list[BalanceUpdate] = []

        unsubscribe = subscribe_balance_updates(
            client,
            5795523,
            lambda u: received.append(u),
        )

        # The dispatcher installed itself on the client.
        assert client.setMessageReceivedCallback.call_count == 1
        # The returned unsubscribe callable works.
        assert callable(unsubscribe)

    def test_callback_invoked_on_trader_updated_event(self):
        client = MagicMock()
        received: list[BalanceUpdate] = []

        subscribe_balance_updates(client, 5795523, lambda u: received.append(u))

        # Extract the dispatcher callback the dispatcher installed.
        dispatcher_cb = client.setMessageReceivedCallback.call_args.args[0]

        # Simulate cTrader pushing a balance update.
        event = _make_trader_updated_event(balance=125_000_00, money_digits=2)
        dispatcher_cb(client, event)

        assert len(received) == 1
        assert received[0].balance == Decimal("125000.00")
        assert received[0].ctid_trader_account_id == 5795523
        assert received[0].money_digits == 2

    def test_other_payload_types_ignored(self):
        """Spot events, execution events, etc. should not trigger the callback."""
        client = MagicMock()
        received: list[BalanceUpdate] = []

        subscribe_balance_updates(client, 5795523, lambda u: received.append(u))

        dispatcher_cb = client.setMessageReceivedCallback.call_args.args[0]

        # Simulate various non-balance payloads.
        for payload_type in (2131, 2126, 2151, 2132, 2101):
            msg = MagicMock()
            msg.payloadType = payload_type
            dispatcher_cb(client, msg)

        assert received == []

    def test_wrong_account_filtered(self):
        """Updates for a different ctid account are dropped."""
        client = MagicMock()
        received: list[BalanceUpdate] = []

        subscribe_balance_updates(client, 5795523, lambda u: received.append(u))

        dispatcher_cb = client.setMessageReceivedCallback.call_args.args[0]

        # Push for account 9999999 — not 5795523.
        event = _make_trader_updated_event(
            ctid_account_id=9999999,
            balance=200_000_00,
        )
        dispatcher_cb(client, event)

        assert received == []

    def test_correct_account_delivered(self):
        client = MagicMock()
        received: list[BalanceUpdate] = []

        subscribe_balance_updates(client, 5795523, lambda u: received.append(u))

        dispatcher_cb = client.setMessageReceivedCallback.call_args.args[0]

        # Same account — should deliver.
        event = _make_trader_updated_event(
            ctid_account_id=5795523,
            balance=150_000_00,
        )
        dispatcher_cb(client, event)

        assert len(received) == 1
        assert received[0].balance == Decimal("150000.00")

    def test_jpy_balance_in_event(self):
        """JPY account (moneyDigits=0) event — balance is the integer."""
        client = MagicMock()
        received: list[BalanceUpdate] = []

        subscribe_balance_updates(client, 5795523, lambda u: received.append(u))

        dispatcher_cb = client.setMessageReceivedCallback.call_args.args[0]
        event = _make_trader_updated_event(balance=5_000_000, money_digits=0)
        dispatcher_cb(client, event)

        assert received[0].balance == Decimal("5000000")
        assert received[0].money_digits == 0

    def test_unsubscribe_stops_delivery(self):
        client = MagicMock()
        received: list[BalanceUpdate] = []

        unsubscribe = subscribe_balance_updates(
            client,
            5795523,
            lambda u: received.append(u),
        )

        dispatcher_cb = client.setMessageReceivedCallback.call_args.args[0]

        # First event — delivered.
        dispatcher_cb(client, _make_trader_updated_event(balance=100_000_00))
        assert len(received) == 1

        # Unsubscribe.
        unsubscribe()

        # Second event — must NOT be delivered.
        dispatcher_cb(client, _make_trader_updated_event(balance=200_000_00))
        assert len(received) == 1  # unchanged

    def test_duplicate_subscribe_is_noop(self):
        """Subscribing the same callback twice returns immediately (no clobber)."""
        client = MagicMock()
        received: list[BalanceUpdate] = []
        cb = lambda u: received.append(u)  # noqa: E731

        subscribe_balance_updates(client, 5795523, cb)
        # setMessageReceivedCallback was called once.
        assert client.setMessageReceivedCallback.call_count == 1

        subscribe_balance_updates(client, 5795523, cb)
        # Still only one install.
        assert client.setMessageReceivedCallback.call_count == 1

    def test_callback_exception_does_not_break_dispatcher(self):
        """A throwing callback logs and swallows; other callbacks still fire."""
        client = MagicMock()

        # Note: subscribe_balance_updates currently supports only one
        # callback at a time (singleton dispatcher). To test resilience,
        # we register the bad callback once and verify that subsequent
        # bad invocations are non-fatal.
        def bad_cb(u):
            raise RuntimeError("user code bug")

        subscribe_balance_updates(client, 5795523, bad_cb)
        dispatcher_cb = client.setMessageReceivedCallback.call_args.args[0]

        # Should NOT raise even though the callback does.
        dispatcher_cb(client, _make_trader_updated_event(balance=100_000_00))
        dispatcher_cb(client, _make_trader_updated_event(balance=200_000_00))

        # No assertion needed — test passes if no exception propagates.

    def test_missing_setMessageReceivedCallback_raises(self):
        class BadClient:
            pass

        with pytest.raises(
            BalanceSubscriptionError, match="setMessageReceivedCallback"
        ):
            subscribe_balance_updates(BadClient(), 5795523, lambda u: None)

    def test_setMessageReceivedCallback_exception_raises(self):
        client = MagicMock()
        client.setMessageReceivedCallback.side_effect = RuntimeError("boom")

        with pytest.raises(
            BalanceSubscriptionError, match="setMessageReceivedCallback failed"
        ):
            subscribe_balance_updates(client, 5795523, lambda u: None)

    def test_message_without_trader_skipped(self):
        """Defensive: event envelope with no trader subfield → no callback fire."""
        client = MagicMock()
        received: list[BalanceUpdate] = []

        subscribe_balance_updates(client, 5795523, lambda u: received.append(u))
        dispatcher_cb = client.setMessageReceivedCallback.call_args.args[0]

        bad = MagicMock()
        bad.payloadType = 2123
        bad.ctidTraderAccountId = 5795523
        bad.trader = None
        dispatcher_cb(client, bad)

        assert received == []

    def test_dispatcher_installed_exactly_once(self):
        """Two separate subscriptions on different clients — separate installs."""
        client_a = MagicMock()
        client_b = MagicMock()

        subscribe_balance_updates(client_a, 111, lambda u: None)
        subscribe_balance_updates(client_b, 222, lambda u: None)

        assert client_a.setMessageReceivedCallback.call_count == 1
        assert client_b.setMessageReceivedCallback.call_count == 1


# ── BalanceUpdate dataclass ────────────────────────────────────────────────


class TestBalanceUpdate:
    """BalanceUpdate dataclass checks."""

    def test_default_timestamp_is_recent(self):
        before = datetime.now(timezone.utc)

        update = BalanceUpdate(
            ctid_trader_account_id=5795523,
            balance=Decimal("100.00"),
            money_digits=2,
        )

        after = datetime.now(timezone.utc)
        assert before <= update.timestamp <= after

    def test_explicit_timestamp(self):
        ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        update = BalanceUpdate(
            ctid_trader_account_id=5795523,
            balance=Decimal("100.00"),
            money_digits=2,
            timestamp=ts,
        )

        assert update.timestamp == ts

    def test_is_frozen(self):
        update = BalanceUpdate(
            ctid_trader_account_id=1,
            balance=Decimal("0"),
            money_digits=2,
        )

        with pytest.raises(Exception):
            update.balance = Decimal("999")  # type: ignore[misc]


# ── read_account_snapshot ──────────────────────────────────────────────────


class TestReadAccountSnapshot:
    """Convenience helper test."""

    def test_returns_balance_and_positions(self):
        # Build a client that returns the right shape depending on msg type.
        # Simpler: use a session client and pre-program send to return
        # the trader res for the first call and reconcile res for the second.
        client = MagicMock()

        trader_res = _make_trader_res(balance=100_000_00, money_digits=2)
        reconcile_res = _make_reconcile_res(
            positions=[
                {
                    "position_id": "1",
                    "symbol_id": 1,
                    "trade_side": 1,
                    "volume": 100_000,
                    "price": 1.10000,
                },
            ]
        )
        client.send.side_effect = [trader_res, reconcile_res]

        snapshot = read_account_snapshot(client, 5795523)

        assert snapshot["balance"] == Decimal("100000.00")
        assert len(snapshot["positions"]) == 1
        assert snapshot["positions"][0].position_id == "1"
        assert "read_at" in snapshot
        assert snapshot["read_at"].tzinfo is timezone.utc

    def test_snapshot_balance_none_on_timeout(self):
        client = MagicMock()
        client.send.return_value = None  # Both calls time out.

        snapshot = read_account_snapshot(client, 5795523, timeout=0.5)

        assert snapshot["balance"] is None
        assert snapshot["positions"] == []
        assert "read_at" in snapshot
