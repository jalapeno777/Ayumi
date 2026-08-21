from __future__ import annotations

from datetime import datetime, timedelta

from backtest.engine import (
    BacktestConfig,
    BacktestMetrics,
    Bar,
    MarketState,
    StrategySignal,
    TradeDirection,
)
from backtest.portfolio_blend import (
    CorrelationResult,
    SignalRecord,
    StrategyInventoryResult,
    compute_signal_correlation,
    inventory_strategies_on_data,
    select_least_correlated,
)
from backtest.strategy_legacy import ISignalStrategy


def _make_bar(close: float, idx: int = 0) -> Bar:
    base = datetime(2024, 1, 1, 0, 0) + timedelta(hours=idx)
    return Bar(
        time=base,
        open=close - 0.0001,
        high=close + 0.0002,
        low=close - 0.0002,
        close=close,
        volume=1000,
    )


def _make_bars(n: int, base_close: float = 1.1000) -> list[Bar]:
    bars = []
    price = base_close
    for i in range(n):
        import random

        random.seed(i + 42)
        price += (random.random() - 0.5) * 0.001  # noqa: S311
        bars.append(_make_bar(price, i))
    return bars


class _AlwaysLong(ISignalStrategy):
    @property
    def name(self) -> str:
        return "AlwaysLong"

    def evaluate(self, state: MarketState) -> StrategySignal | None:
        bars = state.bars
        if len(bars) < 31:
            return None
        bar = bars[-1]
        return StrategySignal(
            direction=TradeDirection.LONG,
            confidence=0.6,
            entry_price=bar.close,
            stop_loss=bar.close - 0.005,
            take_profit_1=bar.close + 0.005,
            take_profit_2=bar.close + 0.01,
            take_profit_3=bar.close + 0.015,
            rationale="always long",
        )


class _AlwaysShort(ISignalStrategy):
    @property
    def name(self) -> str:
        return "AlwaysShort"

    def evaluate(self, state: MarketState) -> StrategySignal | None:
        bars = state.bars
        if len(bars) < 31:
            return None
        bar = bars[-1]
        return StrategySignal(
            direction=TradeDirection.SHORT,
            confidence=0.6,
            entry_price=bar.close,
            stop_loss=bar.close + 0.005,
            take_profit_1=bar.close - 0.005,
            take_profit_2=bar.close - 0.01,
            take_profit_3=bar.close - 0.015,
            rationale="always short",
        )


class _NeverSignal(ISignalStrategy):
    @property
    def name(self) -> str:
        return "NeverSignal"

    def evaluate(self, state: MarketState) -> StrategySignal | None:
        return None


def _make_inventory_result(
    name: str,
    signals: list[SignalRecord],
    pf: float = 1.5,
    wr: float = 55.0,
    sharpe: float = 0.8,
    dd: float = 3.0,
) -> StrategyInventoryResult:
    return StrategyInventoryResult(
        strategy_name=name,
        metrics=BacktestMetrics(
            starting_balance=10000.0,
            ending_balance=10000.0,
            total_pnl=0.0,
            total_pnl_pct=0.0,
            win_rate=wr,
            total_trades=len(signals),
            winning_trades=int(len(signals) * wr / 100),
            losing_trades=int(len(signals) * (100 - wr) / 100),
            breakeven_trades=0,
            avg_win=10.0,
            avg_loss=-5.0,
            largest_win=20.0,
            largest_loss=-10.0,
            profit_factor=pf,
            max_drawdown_pct=dd,
            max_drawdown_dollar=300.0,
            max_daily_loss_dollar=100.0,
            sharpe_ratio=sharpe,
            avg_risk_reward=2.0,
            expectancy=5.0,
            avg_holding_bars=10.0,
            equity_curve=[10000.0],
            trades=[],
            total_spread_cost=0.0,
            total_commission_cost=0.0,
            rejected_signals=0,
        ),
        signals=signals,
    )


class TestInventoryStrategies:
    def test_inventory_runs_all_strategies(self):
        bars = _make_bars(200)
        factories = {
            "AlwaysLong": _AlwaysLong,
            "AlwaysShort": _AlwaysShort,
        }
        results = inventory_strategies_on_data(factories, bars, "EURUSD")
        assert "AlwaysLong" in results
        assert "AlwaysShort" in results

    def test_inventory_skips_never_signal(self):
        bars = _make_bars(200)
        factories = {
            "NeverSignal": _NeverSignal,
            "AlwaysLong": _AlwaysLong,
        }
        results = inventory_strategies_on_data(factories, bars, "EURUSD")
        assert "AlwaysLong" in results
        assert "NeverSignal" in results

    def test_inventory_records_signals(self):
        bars = _make_bars(200)
        factories = {"AlwaysLong": _AlwaysLong}
        results = inventory_strategies_on_data(factories, bars, "EURUSD")
        inv = results["AlwaysLong"]
        assert len(inv.signals) > 0
        assert all(s.direction == 1 for s in inv.signals)


class TestSignalCorrelation:
    def test_identical_strategies_high_correlation(self):
        signals = [SignalRecord(bar_index=i, direction=1, confidence=0.6) for i in range(0, 200, 5)]
        inv = {
            "StratA": _make_inventory_result("StratA", signals),
            "StratB": _make_inventory_result("StratB", signals),
        }
        corr = compute_signal_correlation(inv, 200)
        val = corr.matrix["StratA"]["StratB"]
        assert val > 0.9

    def test_opposite_strategies_negative_correlation(self):
        signals_long = [SignalRecord(bar_index=i, direction=1, confidence=0.6) for i in range(0, 200, 5)]
        signals_short = [SignalRecord(bar_index=i, direction=-1, confidence=0.6) for i in range(0, 200, 5)]
        inv = {
            "Long": _make_inventory_result("Long", signals_long),
            "Short": _make_inventory_result("Short", signals_short),
        }
        corr = compute_signal_correlation(inv, 200)
        val = corr.matrix["Long"]["Short"]
        assert val < -0.9

    def test_uncorrelated_strategies_near_zero(self):
        import random

        random.seed(123)
        signals_a = [
            SignalRecord(
                bar_index=i,
                direction=random.choice([-1, 0, 1]),  # noqa: S311
                confidence=0.6,  # noqa: S311
            )
            for i in range(0, 200, 3)
        ]
        random.seed(456)
        signals_b = [
            SignalRecord(
                bar_index=i,
                direction=random.choice([-1, 0, 1]),  # noqa: S311
                confidence=0.6,  # noqa: S311
            )
            for i in range(0, 200, 4)
        ]
        inv = {
            "A": _make_inventory_result("A", signals_a),
            "B": _make_inventory_result("B", signals_b),
        }
        corr = compute_signal_correlation(inv, 200)
        val = abs(corr.matrix["A"]["B"])
        assert val < 0.5


class TestSelectLeastCorrelated:
    def test_basic_selection(self):
        signals_a = [SignalRecord(bar_index=i, direction=1, confidence=0.6) for i in range(0, 200, 10)]
        signals_b = [SignalRecord(bar_index=i, direction=-1, confidence=0.6) for i in range(0, 200, 12)]
        inv = {
            "A": _make_inventory_result("A", signals_a, sharpe=1.0),
            "B": _make_inventory_result("B", signals_b, sharpe=0.8),
        }
        corr = CorrelationResult(
            matrix={"A": {"A": 1.0, "B": -0.3}, "B": {"A": -0.3, "B": 1.0}},
            average_correlation=0.3,
        )
        result = select_least_correlated(inv, corr, max_strategies=4)
        assert len(result.selected) <= 4
        assert "A" in result.selected
        assert "B" in result.selected

    def test_skips_high_correlation(self):
        signals_a = [SignalRecord(bar_index=i, direction=1, confidence=0.6) for i in range(0, 200, 10)]
        signals_b = [SignalRecord(bar_index=i, direction=1, confidence=0.6) for i in range(0, 200, 10)]
        inv = {
            "A": _make_inventory_result("A", signals_a, sharpe=1.0),
            "B": _make_inventory_result("B", signals_b, sharpe=0.9),
        }
        corr = CorrelationResult(
            matrix={"A": {"A": 1.0, "B": 0.95}, "B": {"A": 0.95, "B": 1.0}},
            average_correlation=0.95,
        )
        result = select_least_correlated(inv, corr, max_strategies=4, max_pairwise_corr=0.5)
        assert len(result.selected) == 1
        assert "A" in result.selected
        assert "B" not in result.selected
        assert len(result.skipped) == 1

    def test_filters_negative_edge(self):
        signals = [SignalRecord(bar_index=i, direction=1, confidence=0.6) for i in range(0, 200, 10)]
        inv = {
            "Good": _make_inventory_result("Good", signals, pf=1.5, wr=55.0),
            "Bad": _make_inventory_result("Bad", signals, pf=0.5, wr=30.0),
        }
        corr = CorrelationResult(
            matrix={
                "Good": {"Good": 1.0, "Bad": 0.1},
                "Bad": {"Good": 0.1, "Bad": 1.0},
            },
            average_correlation=0.1,
        )
        result = select_least_correlated(inv, corr, max_strategies=4)
        assert "Good" in result.selected
        assert "Bad" not in result.selected


class TestPortfolioBacktestIntegration:
    def test_combined_backtest_runs(self):
        from backtest.multi_strategy_engine import MultiStrategyBacktestEngine

        bars = _make_bars(200)
        config = BacktestConfig(
            starting_balance=10000.0,
            spread_pips=0.5,
            commission_per_lot=3.5,
            pair="EURUSD",
            max_open_trades=3,
            risk_per_trade_pct=0.005,
            max_daily_drawdown_pct=0.03,
            max_total_drawdown_pct=0.05,
        )
        strategies = [_AlwaysLong(), _AlwaysShort()]
        engine = MultiStrategyBacktestEngine(config, strategies)
        individual, combined = engine.run_combined_strategies(strategies, bars)
        assert "AlwaysLong" in individual
        assert "AlwaysShort" in individual
        assert combined.total_trades >= 0
