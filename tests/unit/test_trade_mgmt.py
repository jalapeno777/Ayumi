"""Tests for TradeManagementMixin."""

import pandas as pd
import pytest

from src.forex_trading.services.backtest.engine_core.base import EngineCore, Position
from src.forex_trading.services.backtest.trade_mgmt import TradeManagementMixin


class _TMHost(EngineCore, TradeManagementMixin):
    def __init__(self):
        EngineCore.__init__(self)
        TradeManagementMixin.__init__(self)


def _make_bar(close=1.1000, high=None, low=None, timestamp=None):
    if timestamp is None:
        timestamp = pd.Timestamp("2024-01-01")
    return pd.Series(
        {
            "open": close - 0.0001,
            "high": high if high is not None else close + 0.0002,
            "low": low if low is not None else close - 0.0002,
            "close": close,
            "volume": 100000,
        },
        name=timestamp,
    )


class TestTradeManagementMixin:
    def test_no_positions_no_trades_closed(self):
        host = _TMHost()
        bar = _make_bar()
        result = host.check_sl_tp(bar, pd.Timestamp("2024-01-01"))
        assert result == []

    def test_long_sl_hit(self):
        host = _TMHost()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        host.positions.append(pos)
        bar = _make_bar(low=1.0940)
        ts = pd.Timestamp("2024-01-02")
        result = host.check_sl_tp(bar, ts)
        assert len(result) == 1
        assert result[0]["reason"] == "stop_loss"
        assert len(host.positions) == 0

    def test_long_tp_hit(self):
        host = _TMHost()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        host.positions.append(pos)
        bar = _make_bar(high=1.1101)
        ts = pd.Timestamp("2024-01-02")
        result = host.check_sl_tp(bar, ts)
        assert len(result) == 1
        assert result[0]["reason"] == "take_profit"
        assert result[0]["pnl"] > 0

    def test_short_sl_hit(self):
        host = _TMHost()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="short",
            lots=0.1,
            pair="EURUSD",
            stop_loss=1.1050,
            take_profit=1.0900,
        )
        host.positions.append(pos)
        bar = _make_bar(high=1.1060)
        ts = pd.Timestamp("2024-01-02")
        result = host.check_sl_tp(bar, ts)
        assert len(result) == 1
        assert result[0]["reason"] == "stop_loss"

    def test_short_tp_hit(self):
        host = _TMHost()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="short",
            lots=0.1,
            pair="EURUSD",
            stop_loss=1.1050,
            take_profit=1.0900,
        )
        host.positions.append(pos)
        bar = _make_bar(low=1.0890)
        ts = pd.Timestamp("2024-01-02")
        result = host.check_sl_tp(bar, ts)
        assert len(result) == 1
        assert result[0]["reason"] == "take_profit"

    def test_no_sl_tp_set_no_close(self):
        host = _TMHost()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
        )
        host.positions.append(pos)
        bar = _make_bar()
        result = host.check_sl_tp(bar, pd.Timestamp("2024-01-02"))
        assert result == []
        assert len(host.positions) == 1

    def test_bar_within_range_no_close(self):
        host = _TMHost()
        pos = Position(
            entry_time=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            direction="long",
            lots=0.1,
            pair="EURUSD",
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        host.positions.append(pos)
        bar = _make_bar(high=1.1050, low=1.0960)
        result = host.check_sl_tp(bar, pd.Timestamp("2024-01-02"))
        assert result == []
