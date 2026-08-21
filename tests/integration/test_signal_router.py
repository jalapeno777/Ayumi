from adapters.ctrader.order_manager import OrderManager, PositionSizeConfig
from adapters.ctrader.portfolio_risk_guard import PortfolioRiskGuard
from adapters.ctrader.risk_guard import FTMOConfig
from core.types import TradeDirection
from engine.protocol import CanonicalSignal
from engine.signal_router import SignalRouter


def _make_signal(strategy_id="srmr_gbpusd_h1", symbol="GBPUSD", confidence=0.85, **kwargs):
    defaults = dict(
        entry_price=1.2500,
        stop_loss=1.2450,
        take_profit_1=1.2600,
    )
    defaults.update(kwargs)
    return CanonicalSignal(
        strategy_id=strategy_id,
        symbol=symbol,
        direction=TradeDirection.LONG,
        confidence=confidence,
        **defaults,
    )


class TestSignalRouter:
    def _make_router(self, cooldown_sec=0.0):
        ftmo = FTMOConfig(
            min_risk_reward=0.0,
            daily_loss_limit_pct=0.05,
            total_drawdown_limit_pct=0.10,
            max_position_size_pct=1.0,
        )
        risk = PortfolioRiskGuard(ftmo, 100000.0)
        pos_cfg = PositionSizeConfig(
            risk_per_trade_pct=0.005,
            max_lot_size=0.1,
            min_lot_size=0.01,
            default_lot_size=0.05,
        )
        order_mgr = OrderManager(pos_cfg)
        return SignalRouter(risk, order_mgr, cooldown_sec=cooldown_sec)

    def test_route_executes_valid_signal(self):
        router = self._make_router()
        signal = _make_signal()
        result = router.route(signal)
        assert result.action == "executed"
        assert result.order is not None
        assert result.position is not None

    def test_route_dedups_same_symbol(self):
        router = self._make_router()
        router.route(_make_signal(symbol="GBPUSD"))
        result = router.route(_make_signal(strategy_id="ttc_gbpusd", symbol="GBPUSD"))
        assert result.action == "deduped"

    def test_route_allows_different_symbols(self):
        router = self._make_router()
        router.route(_make_signal(symbol="GBPUSD"))
        result = router.route(_make_signal(strategy_id="srmr_eurusd", symbol="EURUSD"))
        assert result.action == "executed"

    def test_route_cooldown(self):
        router = self._make_router(cooldown_sec=60.0)
        router.route(_make_signal(strategy_id="s1"))
        result = router.route(_make_signal(strategy_id="s1", symbol="EURUSD"))
        assert result.action == "cooldown"

    def test_route_allows_different_strategy_after_cooldown(self):
        router = self._make_router(cooldown_sec=60.0)
        router.route(_make_signal(strategy_id="s1"))
        result = router.route(_make_signal(strategy_id="s2", symbol="EURUSD"))
        assert result.action == "executed"
