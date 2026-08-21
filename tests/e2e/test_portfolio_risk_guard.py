import pytest
from adapters.ctrader.portfolio_risk_guard import PortfolioRiskGuard
from adapters.ctrader.risk_guard import FTMOConfig
from core.types import TradeDirection
from engine.protocol import CanonicalSignal


def _make_signal(strategy_id="s1", symbol="GBPUSD", confidence=0.85, **kwargs):
    defaults = dict(entry_price=1.25, stop_loss=1.245, take_profit_1=1.26)
    defaults.update(kwargs)
    return CanonicalSignal(
        strategy_id=strategy_id,
        symbol=symbol,
        direction=TradeDirection.LONG,
        confidence=confidence,
        **defaults,
    )


class TestPortfolioRiskGuard:
    def _make_guard(self, balance=100000.0):
        ftmo = FTMOConfig(
            min_risk_reward=0.0,
            daily_loss_limit_pct=0.05,
            total_drawdown_limit_pct=0.10,
        )
        return PortfolioRiskGuard(ftmo, balance)

    def test_initial_state(self):
        guard = self._make_guard()
        state = guard.get_portfolio_state()
        assert state["current_balance"] == 100000.0
        assert state["is_blocked"] is False
        assert state["per_strategy_pnl"] == {}

    def test_check_signal_allows(self):
        guard = self._make_guard()
        result = guard.check_signal(_make_signal())
        assert result.allowed is True

    def test_record_trade(self):
        guard = self._make_guard()
        guard.record_trade("srmr_gbpusd", 500.0, True)
        guard.record_trade("ttc_xauusd", -200.0, False)
        stats = guard.get_per_strategy_stats()
        assert stats["srmr_gbpusd"].pnl == 500.0
        assert stats["srmr_gbpusd"].wins == 1
        assert stats["ttc_xauusd"].pnl == -200.0
        assert stats["ttc_xauusd"].losses == 1

    def test_per_strategy_pnl_in_stats(self):
        guard = self._make_guard()
        guard.record_trade("s1", 100.0, True)
        state = guard.get_portfolio_state()
        assert state["per_strategy_pnl"]["s1"] == 100.0

    def test_circuit_breaker_via_drawdown(self):
        guard = self._make_guard(balance=100000.0)
        for _ in range(14):
            guard.record_trade("s1", -1000.0, False)
        state = guard.get_portfolio_state()
        assert state["total_drawdown_pct"] >= 0.10
        result = guard.check_trade_allowed(_make_signal(), 0.001)
        assert result.allowed is False

    def test_win_rate(self):
        guard = self._make_guard()
        guard.record_trade("s1", 100.0, True)
        guard.record_trade("s1", -50.0, False)
        guard.record_trade("s1", 200.0, True)
        stats = guard.get_per_strategy_stats()
        assert stats["s1"].win_rate == pytest.approx(2 / 3)
