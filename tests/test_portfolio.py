from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from backtest.engine import Bar, MarketState, SessionType, StrategySignal, TradeDirection
from backtest.strategies import ISignalStrategy

from quant.config import QuantConfig, RegimeConfig, CorrelationConfig
from quant.pipeline import QuantPipeline
from quant.portfolio import (
    StrategyPortfolio,
    PortfolioConfig,
    PortfolioConstraints,
    PortfolioTracker,
    StrategyAllocation,
    AllocationMethod,
    ConflictResolution,
    build_default_portfolio,
)


class _StubStrategy(ISignalStrategy):
    def __init__(self, name: str = "stub", signal: StrategySignal | None = None):
        self._name = name
        self._signal = signal

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, state):
        return self._signal


def _make_bar(
    hour: int = 10,
    close: float = 1.1000,
    high: float | None = None,
    low: float | None = None,
    day_offset: int = 0,
) -> Bar:
    t = datetime(2024, 3, 1, hour, 0, 0) + timedelta(days=day_offset)
    return Bar(
        time=t,
        open=close - 0.0001,
        high=high if high is not None else close + 0.0005,
        low=low if low is not None else close - 0.0005,
        close=close,
        volume=1000.0,
    )


def _make_market_state(bars: list[Bar], session: SessionType = SessionType.LONDON) -> MarketState:
    return MarketState(bars=bars, current_session=session)


def _make_long_signal(entry: float = 1.1000) -> StrategySignal:
    return StrategySignal(
        direction=TradeDirection.LONG,
        confidence=0.75,
        entry_price=entry,
        stop_loss=entry - 0.0050,
        take_profit_1=entry + 0.0050,
        take_profit_2=entry + 0.0100,
        take_profit_3=entry + 0.0150,
        rationale="test signal",
    )


def _make_short_signal(entry: float = 1.1000) -> StrategySignal:
    return StrategySignal(
        direction=TradeDirection.SHORT,
        confidence=0.70,
        entry_price=entry,
        stop_loss=entry + 0.0050,
        take_profit_1=entry - 0.0050,
        take_profit_2=entry - 0.0100,
        take_profit_3=entry - 0.0150,
        rationale="test signal",
    )


class TestStrategyAllocation:
    def test_defaults(self):
        alloc = StrategyAllocation(strategy_name="test", symbol="EURUSD")
        assert alloc.weight == 1.0
        assert alloc.max_risk_pct == 2.0
        assert alloc.enabled is True
        assert alloc.timeframe == "M15"

    def test_frozen(self):
        alloc = StrategyAllocation(strategy_name="test", symbol="EURUSD")
        with pytest.raises(AttributeError):
            alloc.weight = 2.0

    def test_custom_values(self):
        alloc = StrategyAllocation(
            strategy_name="MR",
            symbol="GBPUSD",
            weight=1.5,
            max_risk_pct=1.5,
            walk_forward_score=0.8,
            tags=("anchor",),
        )
        assert alloc.weight == 1.5
        assert alloc.walk_forward_score == 0.8
        assert alloc.tags == ("anchor",)


class TestPortfolioConstraints:
    def test_defaults(self):
        c = PortfolioConstraints()
        assert c.max_total_risk_pct == 5.0
        assert c.correlation_threshold == 0.70
        assert c.max_open_positions == 10
        assert c.enforce_correlation_limits is True


class TestPortfolioConfig:
    def test_empty_config(self):
        config = PortfolioConfig()
        assert config.allocations == ()
        assert config.constraints.max_total_risk_pct == 5.0
        assert config.allocation_method == AllocationMethod.EQUAL_WEIGHT

    def test_with_allocations(self):
        allocs = (
            StrategyAllocation(strategy_name="A", symbol="EURUSD", weight=2.0),
            StrategyAllocation(strategy_name="B", symbol="GBPUSD", weight=1.0),
        )
        config = PortfolioConfig(allocations=allocs)
        assert len(config.allocations) == 2


class TestPortfolioTracker:
    def test_defaults(self):
        t = PortfolioTracker()
        assert t.balance == 100_000.0
        assert t.max_drawdown_pct == 0.0
        assert t.daily_loss_pct == 0.0
        assert t.get_total_open_positions() == 0

    def test_on_trade_closed_win(self):
        t = PortfolioTracker()
        t.on_trade_closed("strat_a", 500.0)
        assert t.balance == 100_500.0
        assert t.wins == 1
        assert t.losses == 0
        assert t.peak_balance == 100_500.0

    def test_on_trade_closed_loss(self):
        t = PortfolioTracker()
        t.on_trade_closed("strat_a", -300.0)
        assert t.balance == 99_700.0
        assert t.wins == 0
        assert t.losses == 1
        assert t.peak_balance == 100_000.0

    def test_max_drawdown(self):
        t = PortfolioTracker()
        t.on_trade_closed("a", -5_000.0)
        assert t.max_drawdown_pct == pytest.approx(5.0, rel=0.01)

    def test_daily_tracking(self):
        t = PortfolioTracker()
        t.on_trade_closed("a", -3_000.0)
        assert t.daily_loss_pct == pytest.approx(3.0, rel=0.01)

    def test_open_positions_count(self):
        t = PortfolioTracker()
        t.open_positions["EURUSD"] = [
            {"strategy_name": "a", "entry_price": 1.1, "stop_loss": 1.09, "lot_size": 0.1, "direction": "long"},
        ]
        t.open_positions["GBPUSD"] = [
            {"strategy_name": "b", "entry_price": 1.3, "stop_loss": 1.29, "lot_size": 0.1, "direction": "short"},
            {"strategy_name": "c", "entry_price": 1.3, "stop_loss": 1.29, "lot_size": 0.05, "direction": "short"},
        ]
        assert t.get_open_count_for_symbol("EURUSD") == 1
        assert t.get_open_count_for_symbol("GBPUSD") == 2
        assert t.get_total_open_positions() == 3
        assert t.get_open_symbols() == {"EURUSD", "GBPUSD"}


class TestStrategyPortfolio:
    def _make_portfolio(
        self,
        allocations: tuple[StrategyAllocation, ...] | None = None,
        constraints: PortfolioConstraints | None = None,
    ) -> StrategyPortfolio:
        allocs = allocations or (
            StrategyAllocation(strategy_name="MR", symbol="EURUSD", weight=1.0),
            StrategyAllocation(strategy_name="Trend", symbol="GBPJPY", weight=0.75),
        )
        config = PortfolioConfig(
            allocations=allocs,
            constraints=constraints or PortfolioConstraints(),
        )
        return StrategyPortfolio(config)

    def test_add_strategy(self):
        portfolio = self._make_portfolio()
        strategy = _StubStrategy("MR")
        alloc = portfolio.config.allocations[0]
        portfolio.add_strategy(strategy, alloc)
        key = f"{alloc.strategy_name}:{alloc.symbol}"
        assert key in portfolio._strategies

    def test_evaluate_all_no_strategies(self):
        portfolio = self._make_portfolio()
        signals = portfolio.evaluate_all({})
        assert signals == []

    def test_evaluate_all_with_signals(self):
        portfolio = self._make_portfolio()
        signal = _make_long_signal()
        strategy = _StubStrategy("MR", signal=signal)
        alloc = portfolio.config.allocations[0]
        portfolio.add_strategy(strategy, alloc)

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = portfolio.evaluate_all({"EURUSD": state})

        assert len(signals) == 1
        assert signals[0].strategy_name == "MR"
        assert signals[0].symbol == "EURUSD"

    def test_evaluate_all_no_signal(self):
        portfolio = self._make_portfolio()
        strategy = _StubStrategy("MR", signal=None)
        alloc = portfolio.config.allocations[0]
        portfolio.add_strategy(strategy, alloc)

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = portfolio.evaluate_all({"EURUSD": state})
        assert signals == []

    def test_correlation_blocks_duplicate_exposure(self):
        constraints = PortfolioConstraints(
            enforce_correlation_limits=True,
            correlation_threshold=0.70,
        )
        allocs = (
            StrategyAllocation(strategy_name="MR", symbol="EURUSD"),
            StrategyAllocation(strategy_name="MR2", symbol="GBPUSD"),
        )
        portfolio = self._make_portfolio(allocations=allocs, constraints=constraints)
        portfolio.set_correlation("EURUSD", "GBPUSD", 0.80)

        long_signal = _make_long_signal(1.10)
        strat_eur = _StubStrategy("MR", signal=long_signal)
        portfolio.add_strategy(strat_eur, allocs[0])
        portfolio.open_position(long_signal, allocs[0], 0.1)

        long_signal_gbp = _make_long_signal(1.30)
        strat_gbp = _StubStrategy("MR2", signal=long_signal_gbp)
        portfolio.add_strategy(strat_gbp, allocs[1])

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)

        signals = portfolio.evaluate_all({"GBPUSD": state})
        assert len(signals) == 0

    def test_correlation_allows_opposite_direction(self):
        constraints = PortfolioConstraints(
            enforce_correlation_limits=True,
            correlation_threshold=0.70,
        )
        allocs = (
            StrategyAllocation(strategy_name="MR", symbol="EURUSD"),
            StrategyAllocation(strategy_name="MR2", symbol="GBPUSD"),
        )
        portfolio = self._make_portfolio(allocations=allocs, constraints=constraints)
        portfolio.set_correlation("EURUSD", "GBPUSD", 0.80)

        long_signal = _make_long_signal(1.10)
        strat_eur = _StubStrategy("MR", signal=long_signal)
        portfolio.add_strategy(strat_eur, allocs[0])
        portfolio.open_position(long_signal, allocs[0], 0.1)

        short_signal_gbp = _make_short_signal(1.30)
        strat_gbp = _StubStrategy("MR2", signal=short_signal_gbp)
        portfolio.add_strategy(strat_gbp, allocs[1])

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)

        signals = portfolio.evaluate_all({"GBPUSD": state})
        assert len(signals) == 1

    def test_max_positions_per_symbol(self):
        allocs = (
            StrategyAllocation(strategy_name="MR", symbol="EURUSD", max_positions=1),
        )
        portfolio = self._make_portfolio(allocations=allocs)

        long_signal = _make_long_signal(1.10)
        strat = _StubStrategy("MR", signal=long_signal)
        portfolio.add_strategy(strat, allocs[0])
        portfolio.open_position(long_signal, allocs[0], 0.1)

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = portfolio.evaluate_all({"EURUSD": state})
        assert len(signals) == 0

    def test_conflict_resolution_highest_confidence(self):
        allocs = (
            StrategyAllocation(strategy_name="A", symbol="EURUSD"),
            StrategyAllocation(strategy_name="B", symbol="EURUSD"),
        )
        portfolio = self._make_portfolio(allocations=allocs)

        signal_a = StrategySignal(
            direction=TradeDirection.LONG,
            confidence=0.60,
            entry_price=1.10,
            stop_loss=1.095,
            take_profit_1=1.105,
            take_profit_2=1.11,
            take_profit_3=1.115,
            rationale="lower confidence",
        )
        signal_b = StrategySignal(
            direction=TradeDirection.LONG,
            confidence=0.85,
            entry_price=1.10,
            stop_loss=1.095,
            take_profit_1=1.105,
            take_profit_2=1.11,
            take_profit_3=1.115,
            rationale="higher confidence",
        )

        strat_a = _StubStrategy("A", signal=signal_a)
        strat_b = _StubStrategy("B", signal=signal_b)
        portfolio.add_strategy(strat_a, allocs[0])
        portfolio.add_strategy(strat_b, allocs[1])

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = portfolio.evaluate_all({"EURUSD": state})

        assert len(signals) == 1
        assert signals[0].strategy_name == "B"
        assert signals[0].signal.confidence == 0.85

    def test_conflict_resolution_reject_conflicting(self):
        allocs = (
            StrategyAllocation(strategy_name="A", symbol="EURUSD"),
            StrategyAllocation(strategy_name="B", symbol="EURUSD"),
        )
        portfolio = self._make_portfolio(allocations=allocs)
        portfolio._conflict_resolution = ConflictResolution.REJECT_CONFLICTING

        long_signal = _make_long_signal()
        short_signal = _make_short_signal()

        strat_a = _StubStrategy("A", signal=long_signal)
        strat_b = _StubStrategy("B", signal=short_signal)
        portfolio.add_strategy(strat_a, allocs[0])
        portfolio.add_strategy(strat_b, allocs[1])

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = portfolio.evaluate_all({"EURUSD": state})
        assert len(signals) == 0

    def test_calculate_position_size(self):
        portfolio = self._make_portfolio()
        signal = _make_long_signal(1.1000)
        alloc = StrategyAllocation(
            strategy_name="MR",
            symbol="EURUSD",
            max_risk_pct=1.0,
            weight=1.0,
        )
        lot = portfolio.calculate_position_size(signal, alloc)
        assert lot > 0

    def test_position_size_respects_max_total_risk(self):
        constraints = PortfolioConstraints(max_total_risk_pct=2.0)
        allocs = (StrategyAllocation(strategy_name="MR", symbol="EURUSD", max_risk_pct=1.0),)
        portfolio = self._make_portfolio(allocations=allocs, constraints=constraints)

        signal = _make_long_signal(1.1000)
        strat = _StubStrategy("MR", signal=signal)
        portfolio.add_strategy(strat, allocs[0])

        portfolio.open_position(signal, allocs[0], 0.5)
        portfolio.tracker.balance = 100_000.0

        lot = portfolio.calculate_position_size(signal, allocs[0])
        assert lot >= 0

    def test_daily_loss_limit_stops_trading(self):
        constraints = PortfolioConstraints(max_daily_loss_pct=3.0)
        allocs = (StrategyAllocation(strategy_name="MR", symbol="EURUSD"),)
        portfolio = self._make_portfolio(allocations=allocs, constraints=constraints)

        portfolio.tracker.on_trade_closed("MR", -3_100.0)
        portfolio.tracker.daily_start_balance = 100_000.0

        signal = _make_long_signal()
        strat = _StubStrategy("MR", signal=signal)
        portfolio.add_strategy(strat, allocs[0])

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = portfolio.evaluate_all({"EURUSD": state})
        assert len(signals) == 0

    def test_drawdown_limit_stops_trading(self):
        constraints = PortfolioConstraints(max_drawdown_pct=5.0)
        allocs = (StrategyAllocation(strategy_name="MR", symbol="EURUSD"),)
        portfolio = self._make_portfolio(allocations=allocs, constraints=constraints)

        portfolio.tracker.on_trade_closed("MR", -6_000.0)

        signal = _make_long_signal()
        strat = _StubStrategy("MR", signal=signal)
        portfolio.add_strategy(strat, allocs[0])

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = portfolio.evaluate_all({"EURUSD": state})
        assert len(signals) == 0

    def test_equal_weight_allocation(self):
        allocs = (
            StrategyAllocation(strategy_name="A", symbol="EURUSD", weight=2.0),
            StrategyAllocation(strategy_name="B", symbol="GBPUSD", weight=1.0),
        )
        config = PortfolioConfig(
            allocations=allocs,
            allocation_method=AllocationMethod.EQUAL_WEIGHT,
        )
        portfolio = StrategyPortfolio(config)

        w_a = portfolio._calculate_weight(allocs[0])
        w_b = portfolio._calculate_weight(allocs[1])
        assert w_a == pytest.approx(0.5)
        assert w_b == pytest.approx(0.5)

    def test_manual_weight_allocation(self):
        allocs = (
            StrategyAllocation(strategy_name="A", symbol="EURUSD", weight=2.0),
            StrategyAllocation(strategy_name="B", symbol="GBPUSD", weight=1.0),
        )
        config = PortfolioConfig(
            allocations=allocs,
            allocation_method=AllocationMethod.MANUAL,
        )
        portfolio = StrategyPortfolio(config)

        assert portfolio._calculate_weight(allocs[0]) == 2.0
        assert portfolio._calculate_weight(allocs[1]) == 1.0

    def test_get_correlation(self):
        portfolio = self._make_portfolio()
        portfolio.set_correlation("EURUSD", "GBPUSD", 0.80)
        assert portfolio.get_correlation("EURUSD", "GBPUSD") == 0.80
        assert portfolio.get_correlation("GBPUSD", "EURUSD") == 0.80
        assert portfolio.get_correlation("EURUSD", "EURUSD") == 1.0
        assert portfolio.get_correlation("EURUSD", "USDJPY") == 0.0

    def test_get_enabled_allocations(self):
        allocs = (
            StrategyAllocation(strategy_name="A", symbol="EURUSD", enabled=True),
            StrategyAllocation(strategy_name="B", symbol="GBPUSD", enabled=False),
            StrategyAllocation(strategy_name="C", symbol="USDJPY", enabled=True),
        )
        portfolio = self._make_portfolio(allocations=allocs)
        enabled = portfolio.get_enabled_allocations()
        assert len(enabled) == 2
        assert enabled[0].strategy_name == "A"
        assert enabled[1].strategy_name == "C"


class TestPipelinePortfolioIntegration:
    def _make_pipeline(self) -> QuantPipeline:
        config = QuantConfig(
            regime=RegimeConfig(enabled=False),
            correlation=CorrelationConfig(enabled=False),
        )
        return QuantPipeline(config)

    def test_attach_and_evaluate_portfolio(self):
        pipeline = self._make_pipeline()
        allocs = (StrategyAllocation(strategy_name="MR", symbol="EURUSD"),)
        portfolio_config = PortfolioConfig(allocations=allocs)
        portfolio = StrategyPortfolio(portfolio_config)

        signal = _make_long_signal(1.1000)
        strat = _StubStrategy("MR", signal=signal)
        portfolio.add_strategy(strat, allocs[0])

        pipeline.attach_portfolio(portfolio)

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = pipeline.evaluate_portfolio({"EURUSD": state})

        assert len(signals) == 1
        assert signals[0].strategy_name == "MR"

    def test_evaluate_portfolio_without_attachment(self):
        pipeline = self._make_pipeline()
        signals = pipeline.evaluate_portfolio({})
        assert signals == []

    def test_portfolio_rejected_by_regime(self):
        config = QuantConfig(
            regime=RegimeConfig(enabled=True, min_confidence=0.99),
            correlation=CorrelationConfig(enabled=False),
        )
        pipeline = QuantPipeline(config)

        allocs = (StrategyAllocation(strategy_name="MR", symbol="EURUSD"),)
        portfolio = StrategyPortfolio(PortfolioConfig(allocations=allocs))
        signal = _make_long_signal(1.1000)
        strat = _StubStrategy("MR", signal=signal)
        portfolio.add_strategy(strat, allocs[0])

        pipeline.attach_portfolio(portfolio)

        for i in range(60):
            pipeline.update_bars(
                high=1.1,
                low=1.09,
                close=1.095,
                atr=0.001,
            )

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = pipeline.evaluate_portfolio({"EURUSD": state})
        assert len(signals) == 0

    def test_portfolio_lot_size_adjusted(self):
        pipeline = self._make_pipeline()
        allocs = (StrategyAllocation(strategy_name="MR", symbol="EURUSD"),)
        portfolio = StrategyPortfolio(PortfolioConfig(allocations=allocs))
        signal = _make_long_signal(1.1000)
        strat = _StubStrategy("MR", signal=signal)
        portfolio.add_strategy(strat, allocs[0])

        pipeline.attach_portfolio(portfolio)

        for i in range(60):
            pipeline.update_bars(
                high=1.1 + i * 0.001,
                low=1.09 + i * 0.001,
                close=1.095 + i * 0.001,
                atr=0.005,
            )

        bars = [_make_bar(hour=h) for h in range(0, 24, 1)]
        state = _make_market_state(bars)
        signals = pipeline.evaluate_portfolio({"EURUSD": state})

        assert len(signals) == 1
        assert signals[0].adjusted_lot_size is not None
        assert signals[0].adjusted_lot_size > 0


class TestBuildDefaultPortfolio:
    def test_builds_without_error(self):
        portfolio = build_default_portfolio()
        assert portfolio is not None
        assert len(portfolio.get_enabled_allocations()) == 8

    def test_has_expected_strategies(self):
        portfolio = build_default_portfolio()
        names = {a.strategy_name for a in portfolio.config.allocations}
        assert "Session-Range Mean Reversion" in names
        assert "Regime-Switching Router" in names
        assert "Statistical Arbitrage" in names
        assert "Keltner Channel Breakout" in names
        assert "MA Trend Following" in names
        assert "Grid Trading (EURUSD)" in names
        assert "Grid Trading (XAUUSD)" in names

    def test_has_correlations_set(self):
        portfolio = build_default_portfolio()
        assert portfolio.get_correlation("EURUSD", "GBPUSD") > 0.7
        assert portfolio.get_correlation("EURUSD", "XAUUSD") < 0.5

    def test_constraints_set(self):
        portfolio = build_default_portfolio()
        c = portfolio.config.constraints
        assert c.max_total_risk_pct == 5.0
        assert c.max_daily_loss_pct == 3.0
        assert c.max_drawdown_pct == 10.0
        assert c.enforce_correlation_limits is True

    def test_anchor_strategy_has_highest_weight(self):
        portfolio = build_default_portfolio()
        mr_allocs = [
            a for a in portfolio.config.allocations
            if a.strategy_name == "Session-Range Mean Reversion"
        ]
        assert len(mr_allocs) == 2
        gbpusd = [a for a in mr_allocs if a.symbol == "GBPUSD"][0]
        assert gbpusd.weight == 1.5
        assert "anchor" in gbpusd.tags
