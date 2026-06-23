"""Unit tests for TradeRulesEngine — pure Python, no network/twisted imports."""

import sys
import types

from datetime import datetime, timezone

import pytest

from hybrid.signal import HumanSignal, SignalType
from hybrid.trade_rules import (
    RuleAction,
    TradeRulesConfig,
    TradeRulesEngine,
    PositionLimitConfig,
)


@pytest.fixture(autouse=True)
def _mock_ctrader(monkeypatch):
    """Stub ctrader_open_api per-test (auto-restored by monkeypatch)."""
    _ct = types.ModuleType("ctrader_open_api")
    _ct.Client = type("Client", (), {})
    _ct.TcpProtocol = None
    monkeypatch.setitem(sys.modules, "ctrader_open_api", _ct)


def _signal(st=SignalType.BUY, pair="EURUSD", price=1.1000, sl=1.0950, tp=1.1120):
    return HumanSignal(
        signal_type=st,
        pair=pair,
        entry_price=price,
        stop_loss=sl,
        take_profit=tp,
        timestamp=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


class TestTradeRulesEngine:
    def test_accept_valid_buy(self):
        engine = TradeRulesEngine(config=TradeRulesConfig.ftmo(), starting_balance=100_000)
        result = engine.check_new_signal(_signal())
        assert result.action == RuleAction.ALLOW

    def test_accept_valid_sell(self):
        engine = TradeRulesEngine(config=TradeRulesConfig.ftmo(), starting_balance=100_000)
        result = engine.check_new_signal(_signal(st=SignalType.SELL, sl=1.1050, tp=1.0880))
        assert result.action == RuleAction.ALLOW

    def test_reject_max_positions(self):
        cfg = TradeRulesConfig.ftmo()
        cfg.position_limit.max_positions = 2
        engine = TradeRulesEngine(config=cfg, starting_balance=100_000)
        # Register 2 positions to hit the limit
        for i in range(2):
            engine.register_position(f"p{i}", 1.10, 1.09, "long", 0.1)
        result = engine.check_new_signal(_signal())
        assert result.action == RuleAction.REJECT
        assert "max positions" in result.reason.lower() or "Max" in result.reason

    def test_reject_no_stop_loss(self):
        engine = TradeRulesEngine(config=TradeRulesConfig.ftmo(), starting_balance=100_000)
        sig = HumanSignal(
            signal_type=SignalType.BUY, pair="EURUSD", entry_price=1.1000,
            stop_loss=None, take_profit=1.1150,
            timestamp=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        result = engine.check_new_signal(sig)
        assert result.action == RuleAction.REJECT
        assert "stop loss" in result.reason.lower()

    def test_reject_low_risk_reward(self):
        cfg = TradeRulesConfig.ftmo()
        cfg.min_risk_reward = 2.0
        engine = TradeRulesEngine(config=cfg, starting_balance=100_000)
        # Risk 50 pips, reward 50 pips → R:R = 1.0 < 2.0
        sig = _signal(sl=1.0950, tp=1.1050)
        result = engine.check_new_signal(sig)
        assert result.action == RuleAction.REJECT
        assert "risk" in result.reason.lower() or "reward" in result.reason.lower()

    def test_allow_close_always(self):
        engine = TradeRulesEngine(config=TradeRulesConfig.ftmo(), starting_balance=100_000)
        sig = HumanSignal(signal_type=SignalType.CLOSE, pair="EURUSD",
                          entry_price=1.0,  # required but ignored for CLOSE
                          timestamp=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc))
        result = engine.check_new_signal(sig)
        assert result.action == RuleAction.ALLOW

    def test_daily_loss_circuit_breaker(self):
        cfg = TradeRulesConfig.ftmo()
        engine = TradeRulesEngine(config=cfg, starting_balance=100_000)
        # Simulate hitting daily loss limit: -4.5% on 100k = -$4500
        now = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        engine.record_pnl(-4501.0, now=now)
        result = engine.check_new_signal(_signal(), now=now)
        assert result.action == RuleAction.REJECT
