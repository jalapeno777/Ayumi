"""Unit tests for HybridPaperTrader — pure Python, no network/twisted imports."""

import sys
import types

# Stub ctrader_open_api so imports in the dependency chain don't blow up
if "ctrader_open_api" not in sys.modules:
    _ct = types.ModuleType("ctrader_open_api")
    _ct.Client = type("Client", (), {})
    _ct.TcpProtocol = None
    sys.modules["ctrader_open_api"] = _ct

from datetime import datetime, timezone

import pytest

from hybrid.paper_trader import CloseReason, HybridPaperTrader, PaperTradeResult
from hybrid.signal import HumanSignal, SignalType
from hybrid.trade_rules import TradeRulesConfig, PositionLimitConfig


def _buy_signal(pair="EURUSD", price=1.1000, sl=1.0950, tp=1.1120, ts=None):
    return HumanSignal(
        signal_type=SignalType.BUY,
        pair=pair,
        entry_price=price,
        stop_loss=sl,
        take_profit=tp,
        timestamp=ts or datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


def _sell_signal(pair="EURUSD", price=1.1000, sl=1.1050, tp=1.0880, ts=None):
    return HumanSignal(
        signal_type=SignalType.SELL,
        pair=pair,
        entry_price=price,
        stop_loss=sl,
        take_profit=tp,
        timestamp=ts or datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


class TestHybridPaperTrader:
    """Focused tests on HybridPaperTrader without network."""

    def _trader(self, **kw):
        defaults = dict(
            starting_balance=100_000,
            use_session_filter=False,
            trade_rules_config=TradeRulesConfig.ftmo(),
        )
        defaults.update(kw)
        return HybridPaperTrader(**defaults)

    def test_open_buy_position(self):
        t = self._trader()
        sig = _buy_signal()
        res = t.process_signal(sig)
        assert res.success
        assert res.position_id
        assert res.fill_price > 0
        assert len(t.get_open_positions()) == 1
        pos = t.get_position(res.position_id)
        assert pos.direction == "long"
        assert pos.is_open

    def test_open_sell_position(self):
        t = self._trader()
        res = t.process_signal(_sell_signal())
        assert res.success
        pos = t.get_position(res.position_id)
        assert pos.direction == "short"

    def test_close_at_tp_profit(self):
        t = self._trader()
        res = t.process_signal(_buy_signal(price=1.1000, tp=1.1150))
        pid = res.position_id
        # Move price up past TP
        t.update_market_prices({"EURUSD": 1.1160})
        close = t.close_position(pid, exit_price=1.1150, reason=CloseReason.TAKE_PROFIT)
        assert close.success
        assert close.pnl > 0
        assert not t.get_position(pid).is_open

    def test_close_at_sl_loss(self):
        t = self._trader()
        res = t.process_signal(_buy_signal(price=1.1000, sl=1.0960))
        pid = res.position_id
        close = t.close_position(pid, exit_price=1.0960, reason=CloseReason.STOP_LOSS)
        assert close.success
        assert close.pnl < 0

    def test_reject_max_positions(self):
        cfg = TradeRulesConfig.ftmo()
        cfg.position_limit.max_positions = 1
        t = self._trader(trade_rules_config=cfg)
        r1 = t.process_signal(_buy_signal(pair="EURUSD"))
        assert r1.success
        r2 = t.process_signal(_sell_signal(pair="GBPUSD"))
        assert not r2.success
        assert "max positions" in r2.rejection_reason.lower() or "Max" in r2.rejection_reason

    def test_reject_no_stop_loss(self):
        t = self._trader()
        sig = HumanSignal(
            signal_type=SignalType.BUY, pair="EURUSD", entry_price=1.1000,
            stop_loss=None, take_profit=1.1150,
            timestamp=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        res = t.process_signal(sig)
        assert not res.success
        assert "stop loss" in res.rejection_reason.lower()

    def test_balance_tracks_pnl(self):
        t = self._trader()
        starting = t.balance
        res = t.process_signal(_buy_signal(price=1.1000, sl=1.0950, tp=1.1120))
        pid = res.position_id
        # Price goes up 50 pips → profit
        t.close_position(pid, exit_price=1.1050, reason=CloseReason.MANUAL)
        assert t.balance > starting

    def test_stats_updated(self):
        t = self._trader()
        t.process_signal(_buy_signal())
        stats = t.get_stats()
        assert stats.total_signals_processed == 1
        assert stats.signals_accepted == 1
        assert stats.trades_executed == 1
