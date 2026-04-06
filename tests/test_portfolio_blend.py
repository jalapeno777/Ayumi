from datetime import datetime


from backtest.engine import Bar, TradeDirection, TradeOutcome
from backtest.portfolio_blend import (
    CorrelationResult,
    PortfolioBlendResult,
    StrategyEquityCurve,
    StrategySpec,
    WeightAllocation,
    _build_strategy_name,
    _build_weighted_equity,
    _compute_combined_metrics,
    _compute_equity_curve_from_trades,
    _compute_returns,
    _correlation,
    compute_correlation_matrix,
    format_portfolio_report,
    optimize_weights_equal_risk,
    optimize_weights_inverse_variance,
    optimize_weights_profit_factor,
    run_portfolio_blend,
    run_single_strategy_backtest,
)


def _make_bars(n: int = 500, base_price: float = 1.1) -> list:
    bars = []
    price = base_price
    for i in range(n):
        t = datetime(2024, 1, 1, 0, 0)
        from datetime import timedelta
        t = t + timedelta(hours=i)
        change = (i % 7 - 3) * 0.0001
        price = max(base_price * 0.9, price + change)
        bars.append(
            Bar(time=t, open=price, high=price + 0.0002, low=price - 0.0002, close=price)
        )
    return bars


class _DummyStrategy:
    def __init__(self, name: str = "Dummy"):
        self._name = name

    @property
    def name(self):
        return self._name

    def evaluate(self, state):
        return None


def test_build_strategy_name():
    assert _build_strategy_name("Grid", "EURUSD", "M15") == "Grid|EURUSD|M15"
    assert _build_strategy_name("StatArb", "XAUUSD", "H1") == "StatArb|XAUUSD|H1"


def test_compute_equity_curve_from_trades_empty():
    curve = _compute_equity_curve_from_trades([], 10000.0)
    assert curve == [10000.0]


def test_compute_equity_curve_from_trades_with_pnl():
    from backtest.engine import SimulatedTrade, ExitReason

    trades = [
        SimulatedTrade(
            entry_bar_index=0, exit_bar_index=1, direction=TradeDirection.LONG,
            entry_price=1.1, stop_loss=1.09, take_profit_1=1.11,
            take_profit_2=1.12, take_profit_3=1.13, exit_price=1.11,
            lot_size=0.1, risk_amount=50, pips=100, profit_loss=100,
            outcome=TradeOutcome.WIN, exit_reason=ExitReason.TAKE_PROFIT_1,
            entry_time=datetime(2024, 1, 1), exit_time=datetime(2024, 1, 2),
            confidence_score=0.7, confluence_count=1, rationale="test",
        ),
        SimulatedTrade(
            entry_bar_index=2, exit_bar_index=3, direction=TradeDirection.SHORT,
            entry_price=1.1, stop_loss=1.11, take_profit_1=1.09,
            take_profit_2=1.08, take_profit_3=1.07, exit_price=1.09,
            lot_size=0.1, risk_amount=50, pips=100, profit_loss=-50,
            outcome=TradeOutcome.LOSS, exit_reason=ExitReason.STOP_LOSS,
            entry_time=datetime(2024, 1, 3), exit_time=datetime(2024, 1, 4),
            confidence_score=0.6, confluence_count=1, rationale="test",
        ),
    ]
    curve = _compute_equity_curve_from_trades(trades, 10000.0)
    assert curve == [10000.0, 10100.0, 10050.0]


def test_compute_returns():
    equity = [1000, 1010, 990, 1000]
    returns = _compute_returns(equity)
    assert len(returns) == 3
    assert abs(returns[0] - 0.01) < 1e-10
    assert abs(returns[1] - (-0.019801980198)) < 1e-6
    assert abs(returns[2] - 0.010101010101) < 1e-6


def test_compute_returns_empty():
    assert _compute_returns([1000]) == []
    assert _compute_returns([]) == []


def test_correlation_identical():
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    b = [10.0, 20.0, 30.0, 40.0, 50.0]
    corr = _correlation(a, b)
    assert abs(corr - 1.0) < 1e-10


def test_correlation_opposite():
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    b = [5.0, 4.0, 3.0, 2.0, 1.0]
    corr = _correlation(a, b)
    assert abs(corr - (-1.0)) < 1e-10


def test_correlation_uncorrelated():
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    b = [1.0, -1.0, 1.0, -1.0, 1.0]
    corr = _correlation(a, b)
    assert abs(corr) < 0.5


def test_correlation_short_series():
    assert _correlation([1.0], [2.0]) == 0.0


def test_compute_correlation_matrix():
    curves = {
        "a": StrategyEquityCurve(
            strategy_name="A", pair="EURUSD", timeframe="H1",
            equity_curve=[100, 102, 104, 103, 105],
            returns=[0.02, 0.02, -0.01, 0.02],
            total_pnl=5, win_rate=50, profit_factor=1.0,
            sharpe_ratio=1.0, max_drawdown=0.01, trade_count=4,
        ),
        "b": StrategyEquityCurve(
            strategy_name="B", pair="GBPUSD", timeframe="H1",
            equity_curve=[100, 98, 96, 97, 95],
            returns=[-0.02, -0.02, 0.01, -0.02],
            total_pnl=-5, win_rate=50, profit_factor=1.0,
            sharpe_ratio=-1.0, max_drawdown=0.05, trade_count=4,
        ),
    }
    result = compute_correlation_matrix(curves)
    assert abs(result.matrix["a"]["a"] - 1.0) < 1e-10
    assert abs(result.matrix["b"]["b"] - 1.0) < 1e-10
    assert result.matrix["a"]["b"] < 0
    assert result.average_correlation > 0


def test_compute_correlation_matrix_single():
    curves = {
        "a": StrategyEquityCurve(
            strategy_name="A", pair="EURUSD", timeframe="H1",
            equity_curve=[100, 101, 102], returns=[0.01, 0.01],
            total_pnl=2, win_rate=50, profit_factor=1.0,
            sharpe_ratio=1.0, max_drawdown=0.01, trade_count=2,
        ),
    }
    result = compute_correlation_matrix(curves)
    assert result.average_correlation == 0.0
    assert result.matrix["a"]["a"] == 1.0


def test_optimize_weights_inverse_variance():
    curves = {
        "low_var": StrategyEquityCurve(
            strategy_name="LowVar", pair="EURUSD", timeframe="H1",
            equity_curve=[100, 100.5, 101, 101.5, 102],
            returns=[0.005, 0.005, 0.005, 0.005],
            total_pnl=2, win_rate=50, profit_factor=1.0,
            sharpe_ratio=2.0, max_drawdown=0.01, trade_count=4,
        ),
        "high_var": StrategyEquityCurve(
            strategy_name="HighVar", pair="GBPUSD", timeframe="H1",
            equity_curve=[100, 110, 90, 105, 95],
            returns=[0.10, -0.18, 0.17, -0.10],
            total_pnl=-5, win_rate=50, profit_factor=1.0,
            sharpe_ratio=0.0, max_drawdown=0.10, trade_count=4,
        ),
    }
    weights = optimize_weights_inverse_variance(curves)
    assert weights.method == "inverse_variance"
    assert weights.weights["low_var"] > weights.weights["high_var"]
    total = sum(weights.weights.values())
    assert abs(total - 1.0) < 1e-10


def test_optimize_weights_equal_risk():
    curves = {
        "good": StrategyEquityCurve(
            strategy_name="Good", pair="EURUSD", timeframe="H1",
            equity_curve=[100, 102, 104], returns=[0.02, 0.02],
            total_pnl=4, win_rate=60, profit_factor=1.5,
            sharpe_ratio=2.0, max_drawdown=0.02, trade_count=2,
        ),
        "bad": StrategyEquityCurve(
            strategy_name="Bad", pair="GBPUSD", timeframe="H1",
            equity_curve=[100, 99, 98], returns=[-0.01, -0.01],
            total_pnl=-2, win_rate=40, profit_factor=0.8,
            sharpe_ratio=-1.0, max_drawdown=0.02, trade_count=2,
        ),
    }
    weights = optimize_weights_equal_risk(curves)
    assert weights.method == "equal_risk"
    assert weights.weights["good"] > weights.weights["bad"]


def test_optimize_weights_profit_factor():
    curves = {
        "high_pf": StrategyEquityCurve(
            strategy_name="HighPF", pair="EURUSD", timeframe="H1",
            equity_curve=[100, 110, 120], returns=[0.10, 0.09],
            total_pnl=20, win_rate=80, profit_factor=3.0,
            sharpe_ratio=2.0, max_drawdown=0.01, trade_count=2,
        ),
        "low_pf": StrategyEquityCurve(
            strategy_name="LowPF", pair="GBPUSD", timeframe="H1",
            equity_curve=[100, 95, 90], returns=[-0.05, -0.05],
            total_pnl=-10, win_rate=30, profit_factor=0.5,
            sharpe_ratio=-2.0, max_drawdown=0.10, trade_count=2,
        ),
    }
    weights = optimize_weights_profit_factor(curves)
    assert weights.method == "profit_factor"
    assert weights.weights["high_pf"] > weights.weights["low_pf"]


def test_build_weighted_equity_empty():
    weights = WeightAllocation(weights={}, method="test")
    curve = _build_weighted_equity({}, weights, 10000.0)
    assert curve == [10000.0]


def test_build_weighted_equity_single():
    curves = {
        "a": StrategyEquityCurve(
            strategy_name="A", pair="EURUSD", timeframe="H1",
            equity_curve=[100, 102, 104, 103, 105],
            returns=[0.02, 0.02, -0.01, 0.02],
            total_pnl=5, win_rate=50, profit_factor=1.0,
            sharpe_ratio=1.0, max_drawdown=0.01, trade_count=4,
        ),
    }
    weights = WeightAllocation(weights={"a": 1.0}, method="test")
    curve = _build_weighted_equity(curves, weights, 100.0)
    assert len(curve) == 5
    assert curve[0] == 100.0
    assert curve[1] > 100.0


def test_build_weighted_equity_multiple():
    curves = {
        "a": StrategyEquityCurve(
            strategy_name="A", pair="EURUSD", timeframe="H1",
            equity_curve=[100, 102, 104],
            returns=[0.02, 0.02],
            total_pnl=4, win_rate=50, profit_factor=1.0,
            sharpe_ratio=1.0, max_drawdown=0.01, trade_count=2,
        ),
        "b": StrategyEquityCurve(
            strategy_name="B", pair="GBPUSD", timeframe="H1",
            equity_curve=[100, 101, 99],
            returns=[0.01, -0.02],
            total_pnl=-1, win_rate=50, profit_factor=1.0,
            sharpe_ratio=0.0, max_drawdown=0.02, trade_count=2,
        ),
    }
    weights = WeightAllocation(weights={"a": 0.6, "b": 0.4}, method="test")
    curve = _build_weighted_equity(curves, weights, 100.0)
    assert len(curve) == 3
    assert curve[0] == 100.0
    assert curve[1] > 100.0


def test_compute_combined_metrics():
    curve = [10000, 10200, 10100, 10300, 10500]
    metrics = _compute_combined_metrics(curve, 10000.0)
    assert metrics.starting_balance == 10000.0
    assert metrics.ending_balance == 10500.0
    assert metrics.total_pnl == 500.0
    assert metrics.total_pnl_pct == 0.05


def test_compute_combined_metrics_flat():
    curve = [10000, 10000, 10000]
    metrics = _compute_combined_metrics(curve, 10000.0)
    assert metrics.total_pnl == 0.0
    assert metrics.sharpe_ratio == 0.0


def test_format_portfolio_report():
    curves = {
        "a": StrategyEquityCurve(
            strategy_name="Grid", pair="EURUSD", timeframe="M15",
            equity_curve=[10000, 10200, 10100, 10300, 10500],
            returns=[0.02, -0.01, 0.02, 0.02],
            total_pnl=500, win_rate=75.0, profit_factor=2.0,
            sharpe_ratio=1.5, max_drawdown=0.02, trade_count=4,
        ),
    }
    correlation = CorrelationResult(matrix={"a": {"a": 1.0}}, average_correlation=0.0)
    weights = WeightAllocation(weights={"a": 1.0}, method="equal")
    combined = _compute_combined_metrics([10000, 10200, 10100, 10300, 10500], 10000)

    result = PortfolioBlendResult(
        individual_results=curves,
        correlation=correlation,
        weights=weights,
        combined_equity_curve=[10000, 10200, 10100, 10300, 10500],
        combined_metrics=combined,
        ftmo_passed=True,
        ftmo_criteria={"win_rate": True, "profit_factor": True, "sharpe_ratio": True},
    )
    report = format_portfolio_report(result)
    assert "PORTFOLIO BLEND TEST REPORT" in report
    assert "Grid" in report
    assert "FTMO PASS" in report


def test_run_single_strategy_backtest():
    bars = _make_bars(200)
    strategy = _DummyStrategy("NoSignal")
    metrics = run_single_strategy_backtest(strategy, bars, "EURUSD", 10000.0)
    assert metrics.total_trades == 0
    assert metrics.starting_balance == 10000.0


def test_run_portfolio_blend_no_specs():
    result = run_portfolio_blend([], initial_balance=10000.0, n_walk_forward_windows=0)
    assert len(result.individual_results) == 0
    assert result.correlation.average_correlation == 0.0


def test_run_portfolio_blend_with_dummy():
    spec = StrategySpec(
        name="Dummy",
        factory=_DummyStrategy,
        pair="EURUSD",
        timeframe="H1",
        data_path="/nonexistent/path.csv",
    )
    result = run_portfolio_blend(
        [spec], initial_balance=10000.0, n_walk_forward_windows=0
    )
    assert len(result.individual_results) == 0
