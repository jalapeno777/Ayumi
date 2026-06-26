import os
import pytest
from datetime import datetime, timezone
from adapters.ctrader.models import Order, Position, PositionStatus, TradeDirection
from adapters.ctrader.trade_journal import TradeJournal, JournalEntry


def _make_order(symbol="GBPUSD", direction=TradeDirection.LONG):
    from adapters.ctrader.models import OrderType

    return Order(
        order_id="ORD_001",
        symbol=symbol,
        direction=direction,
        order_type=OrderType.MARKET,
        volume=0.1,
        filled_price=1.2500,
        stop_loss=1.2450,
        take_profit=1.2600,
    )


def _make_position(symbol="GBPUSD", pnl=0.0, status=PositionStatus.OPEN):
    return Position(
        position_id="POS_001",
        symbol=symbol,
        direction=TradeDirection.LONG,
        volume=0.1,
        entry_price=1.2500,
        current_price=1.2550,
        stop_loss=1.2450,
        take_profit=1.2600,
        unrealized_pnl=pnl,
        status=status,
        closed_price=1.2550 if status == PositionStatus.CLOSED else None,
        closed_pnl=pnl,
    )


class TestTradeJournal:
    def test_log_open_and_close(self, tmp_path):
        journal = TradeJournal(log_dir=str(tmp_path))
        order = _make_order()
        position = _make_position()

        journal.log_open(
            strategy_id="srmr_gbpusd_h1",
            strategy_type="srmr_plus",
            signal_confidence=0.85,
            signal_rationale="test signal",
            order=order,
            position=position,
        )
        journal.log_close(position)

        summary = journal.get_portfolio_summary()
        assert summary["total_trades"] == 1
        assert summary["open_positions"] == 0

    def test_strategy_summary(self, tmp_path):
        journal = TradeJournal(log_dir=str(tmp_path))

        journal.log_open(
            "s1", "srmr_plus", 0.8, "test", _make_order(), _make_position()
        )
        pos1 = _make_position(pnl=100.0, status=PositionStatus.CLOSED)
        journal.log_close(pos1)

        journal.log_open(
            "s2",
            "ttc",
            0.9,
            "test2",
            _make_order(symbol="XAUUSD"),
            _make_position(symbol="XAUUSD"),
        )
        pos2 = _make_position(symbol="XAUUSD", pnl=-50.0, status=PositionStatus.CLOSED)
        journal.log_close(pos2, strategy_id="s2", strategy_type="ttc")

        s1 = journal.get_strategy_summary("s1")
        assert s1["total_trades"] == 1
        assert s1["total_pnl"] == 100.0
        assert s1["win_rate"] == 1.0

        s2 = journal.get_strategy_summary("s2")
        assert s2["total_pnl"] == -50.0
        assert s2["win_rate"] == 0.0

    def test_export_csv(self, tmp_path):
        journal = TradeJournal(log_dir=str(tmp_path))
        journal.log_open("s1", "t1", 0.8, "r", _make_order(), _make_position())
        journal.log_close(_make_position(pnl=50.0, status=PositionStatus.CLOSED))

        export_path = str(tmp_path / "export.csv")
        journal.export_csv(export_path)
        assert os.path.exists(export_path)

        with open(export_path) as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_empty_summary(self, tmp_path):
        journal = TradeJournal(log_dir=str(tmp_path))
        summary = journal.get_portfolio_summary()
        assert summary["total_trades"] == 0
