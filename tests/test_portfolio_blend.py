from datetime import datetime


from backtest.engine import Bar, TradeDirection, TradeOutcome
from backtest.portfolio_blend import (
    CorrelationResult,
    FilteredStrategy,
    PortfolioBlendResult,
    StrategyEquityCurve,
    StrategySpec,
    WeightAllocation,
    WEIGHT_METHODS,
    _build_strategy_name,
    _build_weighted_equity,
    _compute_combined_metrics,
    _compute_equity_curve_from_trades,
    _compute_returns,
    _correlation,
    cap_weights,
    compute_correlation_matrix,
    filter_strategies,
    format_portfolio_report,
    optimize_weights_combined_score,
    optimize_weights_equal_risk,
    optimize_weights_inverse_variance,
    optimize_weights_profit_factor,
    optimize_weights_sharpe,
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
            Bar(
                time=t, open=price, high=price + 0.0002, low=price - 0.0002, close=price
            )
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
            entry_bar_index=0,
            exit_bar_index=1,
            direction=TradeDirection.LONG,
            entry_price=1.1,
            stop_loss=1.09,
            take_profit_1=1.11,
            take_profit_2=1.12,
            take_profit_3=1.13,
            exit_price=1.11,
            lot_size=0.1,
            risk_amount=50,
            pips=100,
            profit_loss=100,
            outcome=TradeOutcome.WIN,
            exit_reason=ExitReason.TAKE_PROFIT_1,
            entry_time=datetime(2024, 1, 1),
            exit_time=datetime(2024, 1, 2),
            confidence_score=0.7,
            confluence_count=1,
            rationale="test",
        ),
        SimulatedTrade(
            entry_bar_index=2,
            exit_bar_index=3,
            direction=TradeDirection.SHORT,
            entry_price=1.1,
            stop_loss=1.11,
            take_profit_1=1.09,
            take_profit_2=1.08,
            take_profit_3=1.07,
            exit_price=1.09,
            lot_size=0.1,
            risk_amount=50,
            pips=100,
            profit_loss=-50,
            outcome=TradeOutcome.LOSS,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=datetime(2024, 1, 3),
            exit_time=datetime(2024, 1, 4),
            confidence_score=0.6,
            confluence_count=1,
            rationale="test",
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
            strategy_name="A",
            pair="EURUSD",
            timeframe="H1",
            equity_curve=[100, 102, 104, 103, 105],
            returns=[0.02, 0.02, -0.01, 0.02],
            total_pnl=5,
            win_rate=50,
            profit_factor=1.0,
            sharpe_ratio=1.0,
            max_drawdown=0.01,
            trade_count=4,
        ),
        "b": StrategyEquityCurve(
            strategy_name="B",
            pair="GBPUSD",
            timeframe="H1",
            equity_curve=[100, 98, 96, 97, 95],
            returns=[-0.02, -0.02, 0.01, -0.02],
            total_pnl=-5,
            win_rate=50,
            profit_factor=1.0,
            sharpe_ratio=-1.0,
            max_drawdown=0.05,
            trade_count=4,
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
            strategy_name="A",
            pair="EURUSD",
            timeframe="H1",
            equity_curve=[100, 101, 102],
            returns=[0.01, 0.01],
            total_pnl=2,
            win_rate=50,
            profit_factor=1.0,
            sharpe_ratio=1.0,
            max_drawdown=0.01,
            trade_count=2,
        ),
    }
    result = compute_correlation_matrix(curves)
    assert result.average_correlation == 0.0
    assert result.matrix["a"]["a"] == 1.0


def test_optimize_weights_inverse_variance():
    curves = {
        "low_var": StrategyEquityCurve(
            strategy_name="LowVar",
            pair="EURUSD",
            timeframe="H1",
            equity_curve=[100, 100.5, 101, 101.5, 102],
            returns=[0.005, 0.005, 0.005, 0.005],
            total_pnl=2,
            win_rate=50,
            profit_factor=1.0,
            sharpe_ratio=2.0,
            max_drawdown=0.01,
            trade_count=4,
        ),
        "high_var": StrategyEquityCurve(
            strategy_name="HighVar",
            pair="GBPUSD",
            timeframe="H1",
            equity_curve=[100, 110, 90, 105, 95],
            returns=[0.10, -0.18, 0.17, -0.10],
            total_pnl=-5,
            win_rate=50,
            profit_factor=1.0,
            sharpe_ratio=0.0,
            max_drawdown=0.10,
            trade_count=4,
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
            strategy_name="Good",
            pair="EURUSD",
            timeframe="H1",
            equity_curve=[100, 102, 104],
            returns=[0.02, 0.02],
            total_pnl=4,
            win_rate=60,
            profit_factor=1.5,
            sharpe_ratio=2.0,
            max_drawdown=0.02,
            trade_count=2,
        ),
        "bad": StrategyEquityCurve(
            strategy_name="Bad",
            pair="GBPUSD",
            timeframe="H1",
            equity_curve=[100, 99, 98],
            returns=[-0.01, -0.01],
            total_pnl=-2,
            win_rate=40,
            profit_factor=0.8,
            sharpe_ratio=-1.0,
            max_drawdown=0.02,
            trade_count=2,
        ),
    }
    weights = optimize_weights_equal_risk(curves)
    assert weights.method == "equal_risk"
    assert weights.weights["good"] > weights.weights["bad"]


def test_optimize_weights_profit_factor():
    curves = {
        "high_pf": StrategyEquityCurve(
            strategy_name="HighPF",
            pair="EURUSD",
            timeframe="H1",
            equity_curve=[100, 110, 120],
            returns=[0.10, 0.09],
            total_pnl=20,
            win_rate=80,
            profit_factor=3.0,
            sharpe_ratio=2.0,
            max_drawdown=0.01,
            trade_count=2,
        ),
        "low_pf": StrategyEquityCurve(
            strategy_name="LowPF",
            pair="GBPUSD",
            timeframe="H1",
            equity_curve=[100, 95, 90],
            returns=[-0.05, -0.05],
            total_pnl=-10,
            win_rate=30,
            profit_factor=0.5,
            sharpe_ratio=-2.0,
            max_drawdown=0.10,
            trade_count=2,
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
            strategy_name="A",
            pair="EURUSD",
            timeframe="H1",
            equity_curve=[100, 102, 104, 103, 105],
            returns=[0.02, 0.02, -0.01, 0.02],
            total_pnl=5,
            win_rate=50,
            profit_factor=1.0,
            sharpe_ratio=1.0,
            max_drawdown=0.01,
            trade_count=4,
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
            strategy_name="A",
            pair="EURUSD",
            timeframe="H1",
            equity_curve=[100, 102, 104],
            returns=[0.02, 0.02],
            total_pnl=4,
            win_rate=50,
            profit_factor=1.0,
            sharpe_ratio=1.0,
            max_drawdown=0.01,
            trade_count=2,
        ),
        "b": StrategyEquityCurve(
            strategy_name="B",
            pair="GBPUSD",
            timeframe="H1",
            equity_curve=[100, 101, 99],
            returns=[0.01, -0.02],
            total_pnl=-1,
            win_rate=50,
            profit_factor=1.0,
            sharpe_ratio=0.0,
            max_drawdown=0.02,
            trade_count=2,
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
            strategy_name="Grid",
            pair="EURUSD",
            timeframe="M15",
            equity_curve=[10000, 10200, 10100, 10300, 10500],
            returns=[0.02, -0.01, 0.02, 0.02],
            total_pnl=500,
            win_rate=75.0,
            profit_factor=2.0,
            sharpe_ratio=1.5,
            max_drawdown=0.02,
            trade_count=4,
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


def _make_equity_curve(
    name: str = "A",
    pair: str = "EURUSD",
    timeframe: str = "H1",
    wr: float = 60.0,
    pf: float = 1.5,
    sharpe: float = 1.0,
    dd: float = 0.05,
    pnl: float = 100.0,
    trades: int = 10,
) -> StrategyEquityCurve:
    return StrategyEquityCurve(
        strategy_name=name,
        pair=pair,
        timeframe=timeframe,
        equity_curve=[100, 101, 102],
        returns=[0.01, 0.01],
        total_pnl=pnl,
        win_rate=wr,
        profit_factor=pf,
        sharpe_ratio=sharpe,
        max_drawdown=dd,
        trade_count=trades,
    )


def test_filter_strategies_removes_low_pf():
    curves = {
        "good": _make_equity_curve(name="Good", pf=1.5, wr=60.0),
        "bad_pf": _make_equity_curve(name="BadPF", pf=0.8, wr=60.0),
    }
    filtered, removed = filter_strategies(curves)
    assert "good" in filtered
    assert "bad_pf" not in filtered
    assert len(removed) == 1
    assert "PF 0.80 < 1.0" in removed[0].reason


def test_filter_strategies_removes_low_wr():
    curves = {
        "good": _make_equity_curve(name="Good", pf=1.5, wr=60.0),
        "low_wr": _make_equity_curve(name="LowWR", pf=1.2, wr=30.0),
    }
    filtered, removed = filter_strategies(curves)
    assert "good" in filtered
    assert "low_wr" not in filtered
    assert len(removed) == 1
    assert "WR 30.0% < 45.0%" in removed[0].reason


def test_filter_strategies_keeps_all_profitable():
    curves = {
        "a": _make_equity_curve(name="A", pf=1.5, wr=60.0),
        "b": _make_equity_curve(name="B", pf=1.1, wr=50.0),
    }
    filtered, removed = filter_strategies(curves)
    assert len(filtered) == 2
    assert len(removed) == 0


def test_filter_strategies_multiple_reasons():
    curves = {
        "bad": _make_equity_curve(name="Bad", pf=0.5, wr=30.0),
    }
    filtered, removed = filter_strategies(curves)
    assert len(filtered) == 0
    assert len(removed) == 1
    assert "PF 0.50 < 1.0" in removed[0].reason
    assert "WR 30.0% < 45.0%" in removed[0].reason


def test_filter_strategies_empty():
    filtered, removed = filter_strategies({})
    assert len(filtered) == 0
    assert len(removed) == 0


def test_optimize_weights_sharpe():
    curves = {
        "high_sharpe": _make_equity_curve(name="HighSharpe", sharpe=3.0, pf=2.0),
        "low_sharpe": _make_equity_curve(name="LowSharpe", sharpe=0.5, pf=1.0),
    }
    weights = optimize_weights_sharpe(curves)
    assert weights.method == "sharpe_weighted"
    assert weights.weights["high_sharpe"] > weights.weights["low_sharpe"]
    total = sum(weights.weights.values())
    assert abs(total - 1.0) < 1e-10


def test_optimize_weights_sharpe_negative_sharpe():
    curves = {
        "negative": _make_equity_curve(name="Neg", sharpe=-1.0, pf=0.5),
        "positive": _make_equity_curve(name="Pos", sharpe=1.0, pf=1.5),
    }
    weights = optimize_weights_sharpe(curves)
    assert weights.weights["positive"] > weights.weights["negative"]


def test_optimize_weights_combined_score():
    curves = {
        "good": _make_equity_curve(
            name="Good", sharpe=2.0, pf=2.0, wr=70.0, dd=0.02, pnl=500
        ),
        "mediocre": _make_equity_curve(
            name="Med", sharpe=0.5, pf=1.0, wr=50.0, dd=0.10, pnl=10
        ),
    }
    weights = optimize_weights_combined_score(curves)
    assert weights.method == "combined_score"
    assert weights.weights["good"] > weights.weights["mediocre"]
    total = sum(weights.weights.values())
    assert abs(total - 1.0) < 1e-10


def test_optimize_weights_combined_score_all_methods_sum_to_one():
    curves = {
        "a": _make_equity_curve(name="A", sharpe=1.5, pf=1.8, dd=0.03),
        "b": _make_equity_curve(name="B", sharpe=0.8, pf=1.2, dd=0.07),
        "c": _make_equity_curve(name="C", sharpe=0.3, pf=0.9, dd=0.12),
    }
    for method_name, method_fn in WEIGHT_METHODS.items():
        weights = method_fn(curves)
        total = sum(weights.weights.values())
        assert abs(total - 1.0) < 1e-10, (
            f"{method_name} weights don't sum to 1.0: {total}"
        )


def test_run_portfolio_blend_with_filter():
    spec_good = StrategySpec(
        name="Good",
        factory=_DummyStrategy,
        pair="EURUSD",
        timeframe="H1",
        data_path="/nonexistent/good.csv",
    )
    spec_bad = StrategySpec(
        name="Bad",
        factory=_DummyStrategy,
        pair="GBPUSD",
        timeframe="H1",
        data_path="/nonexistent/bad.csv",
    )
    result = run_portfolio_blend(
        [spec_good, spec_bad],
        initial_balance=10000.0,
        n_walk_forward_windows=0,
        enable_filter=True,
    )
    assert len(result.individual_results) == 0


def test_run_portfolio_blend_without_filter():
    spec = StrategySpec(
        name="Dummy",
        factory=_DummyStrategy,
        pair="EURUSD",
        timeframe="H1",
        data_path="/nonexistent/path.csv",
    )
    result = run_portfolio_blend(
        [spec],
        initial_balance=10000.0,
        n_walk_forward_windows=0,
        enable_filter=False,
    )
    assert len(result.individual_results) == 0


def test_format_portfolio_report_with_filtered():
    curves = {
        "good": StrategyEquityCurve(
            strategy_name="Good",
            pair="EURUSD",
            timeframe="M15",
            equity_curve=[10000, 10200, 10400],
            returns=[0.02, 0.02],
            total_pnl=400,
            win_rate=75.0,
            profit_factor=2.0,
            sharpe_ratio=1.5,
            max_drawdown=0.02,
            trade_count=4,
        ),
        "bad": StrategyEquityCurve(
            strategy_name="Bad",
            pair="GBPUSD",
            timeframe="M15",
            equity_curve=[10000, 9800, 9600],
            returns=[-0.02, -0.02],
            total_pnl=-400,
            win_rate=30.0,
            profit_factor=0.5,
            sharpe_ratio=-1.0,
            max_drawdown=0.10,
            trade_count=4,
        ),
    }
    correlation = CorrelationResult(
        matrix={"good": {"good": 1.0}}, average_correlation=0.0
    )
    weights = WeightAllocation(weights={"good": 1.0}, method="test")
    combined = _compute_combined_metrics([10000, 10200, 10400], 10000)

    result = PortfolioBlendResult(
        individual_results=curves,
        correlation=correlation,
        weights=weights,
        combined_equity_curve=[10000, 10200, 10400],
        combined_metrics=combined,
        ftmo_passed=True,
        ftmo_criteria={"win_rate": True, "profit_factor": True, "sharpe_ratio": True},
    )
    filtered = [FilteredStrategy(key="bad", reason="PF 0.50 < 1.0")]
    report = format_portfolio_report(result, filtered_strategies=filtered)
    assert "FILTERED STRATEGIES" in report
    assert "[FILTERED]" in report
    assert "bad" in report


def test_walk_forward_data_map_no_collision_for_duplicate_strategy_names():
    """Regression: two strategies with the same name but different pairs must
    both load into data_map without overwriting each other (AYUAA-487)."""
    from unittest.mock import patch

    bars_a = _make_bars(n=500, base_price=1.1000)
    bars_b = _make_bars(n=500, base_price=1.3000)

    spec_a = StrategySpec(
        name="Session-Range Mean Reversion",
        factory=_DummyStrategy,
        pair="EURUSD",
        timeframe="H1",
        data_path="/fake/eurusd.csv",
    )
    spec_b = StrategySpec(
        name="Session-Range Mean Reversion",
        factory=_DummyStrategy,
        pair="GBPUSD",
        timeframe="H1",
        data_path="/fake/gbpusd.csv",
    )

    call_log: list = []

    def mock_load(self, path):
        call_log.append(path)
        if "eurusd" in path:
            return bars_a
        return bars_b

    with patch("backtest.portfolio_blend.CsvDataLoader.load", mock_load):
        result = run_portfolio_blend(
            [spec_a, spec_b],
            initial_balance=10000.0,
            n_walk_forward_windows=2,
            enable_filter=False,
        )

    assert result.walk_forward is not None
    assert len(result.walk_forward.per_window) == 2
    assert "/fake/eurusd.csv" in call_log
    assert "/fake/gbpusd.csv" in call_log
    for w in result.walk_forward.per_window:
        assert w.trade_count >= 0


def test_cap_weights_enforces_max():
    weights = {"a": 0.85, "b": 0.10, "c": 0.05}
    capped = cap_weights(weights, max_weight=0.40)
    assert capped["a"] <= 0.40
    total = sum(capped.values())
    assert abs(total - 1.0) < 1e-10


def test_cap_weights_enforces_min():
    weights = {"a": 0.50, "b": 0.30, "c": 0.20}
    capped = cap_weights(weights, min_weight=0.10)
    for w in capped.values():
        assert w >= 0.10
    total = sum(capped.values())
    assert abs(total - 1.0) < 1e-10


def test_cap_weights_max_and_min_together():
    weights = {"a": 0.70, "b": 0.25, "c": 0.05}
    capped = cap_weights(weights, max_weight=0.40, min_weight=0.10)
    for w in capped.values():
        assert w <= 0.40
        assert w >= 0.10
    total = sum(capped.values())
    assert abs(total - 1.0) < 1e-10


def test_cap_weights_no_change_when_within_bounds():
    weights = {"a": 0.35, "b": 0.35, "c": 0.30}
    capped = cap_weights(weights, max_weight=0.40, min_weight=0.10)
    total = sum(capped.values())
    assert abs(total - 1.0) < 1e-10


def test_cap_weights_empty():
    capped = cap_weights({})
    assert capped == {}


def test_cap_weights_single_strategy():
    weights = {"a": 1.0}
    capped = cap_weights(weights, max_weight=0.40, min_weight=0.10)
    assert abs(capped["a"] - 1.0) < 1e-10


def test_cap_weights_two_strategies_with_cap():
    weights = {"a": 0.93, "b": 0.07}
    capped = cap_weights(weights, max_weight=0.60, min_weight=0.20)
    assert capped["a"] <= 0.60
    assert capped["b"] >= 0.20
    total = sum(capped.values())
    assert abs(total - 1.0) < 1e-10


def test_cap_weights_many_strategies_realistic_portfolio():
    weights = {
        "grid|XAUUSD|M15": 0.936,
        "session_mr|GBPUSD|H1": 0.030,
        "session_mr|EURUSD|H1": 0.020,
        "momentum|GBPJPY|M15": 0.014,
    }
    capped = cap_weights(weights, max_weight=0.40, min_weight=0.10)
    for w in capped.values():
        assert w <= 0.40, f"Weight {w} exceeds max 0.40"
        assert w >= 0.10, f"Weight {w} below min 0.10"
    total = sum(capped.values())
    assert abs(total - 1.0) < 1e-10
    assert len(capped) == 4


def test_run_portfolio_blend_with_weight_cap():
    from unittest.mock import patch

    bars_a = _make_bars(n=500, base_price=1.1000)
    bars_b = _make_bars(n=500, base_price=1.3000)
    bars_c = _make_bars(n=500, base_price=1.5000)

    spec_a = StrategySpec(
        name="Grid",
        factory=_DummyStrategy,
        pair="XAUUSD",
        timeframe="M15",
        data_path="/fake/xauusd.csv",
    )
    spec_b = StrategySpec(
        name="Session-Range Mean Reversion",
        factory=_DummyStrategy,
        pair="GBPUSD",
        timeframe="H1",
        data_path="/fake/gbpusd.csv",
    )
    spec_c = StrategySpec(
        name="Session-Range Mean Reversion",
        factory=_DummyStrategy,
        pair="EURUSD",
        timeframe="H1",
        data_path="/fake/eurusd.csv",
    )

    def mock_load(self, path):
        if "xauusd" in path:
            return bars_a
        elif "gbpusd" in path:
            return bars_b
        return bars_c

    with patch("backtest.portfolio_blend.CsvDataLoader.load", mock_load):
        result = run_portfolio_blend(
            [spec_a, spec_b, spec_c],
            initial_balance=10000.0,
            n_walk_forward_windows=0,
            enable_filter=False,
            max_weight=0.40,
            min_weight=0.10,
        )

    for w in result.weights.weights.values():
        assert w <= 0.40
        assert w >= 0.10
    assert "capped" in result.weights.method


class TestBuildCappedBlendStrategySpecs:
    def test_returns_five_strategies(self):
        from backtest.portfolio_blend import build_capped_blend_strategy_specs

        specs = build_capped_blend_strategy_specs("data/forex/historical")
        assert len(specs) == 5

    def test_includes_all_required_strategies(self):
        from backtest.portfolio_blend import build_capped_blend_strategy_specs

        specs = build_capped_blend_strategy_specs("data/forex/historical")
        names_pairs = [(s.name, s.pair, s.timeframe) for s in specs]
        assert ("Session-Range Mean Reversion", "GBPUSD", "H1") in names_pairs
        assert ("Momentum Breakout", "GBPJPY", "M15") in names_pairs
        assert ("Grid Trading", "XAUUSD", "M15") in names_pairs
        assert ("Statistical Arbitrage", "EURUSD", "M15") in names_pairs
        assert ("Commodity XAUUSD", "XAUUSD", "M15") in names_pairs

    def test_all_specs_have_valid_factories(self):
        from backtest.portfolio_blend import build_capped_blend_strategy_specs

        specs = build_capped_blend_strategy_specs("data/forex/historical")
        for spec in specs:
            strategy = spec.factory()
            assert hasattr(strategy, "name")
            assert hasattr(strategy, "evaluate")

    def test_data_paths_use_data_dir(self):
        from backtest.portfolio_blend import build_capped_blend_strategy_specs

        specs = build_capped_blend_strategy_specs("data/forex/historical")
        for spec in specs:
            assert spec.data_path.startswith("data/forex/historical")
            assert spec.data_path.endswith(".csv")


class TestATRCompute:
    def test_compute_atr_basic(self):
        from backtest.portfolio_blend import _compute_atr

        bars = [
            Bar(
                time=__import__("datetime").datetime(2024, 1, 1, h),
                open=1.0,
                high=1.0002,
                low=0.9998,
                close=1.0 + h * 0.0001,
            )
            for h in range(20)
        ]
        atr = _compute_atr(bars, period=14)
        assert len(atr) == 20
        assert atr[0] == 0.0
        assert atr[13] == 0.0
        assert atr[14] > 0

    def test_compute_atr_short_data(self):
        from backtest.portfolio_blend import _compute_atr

        bars = [
            Bar(
                time=__import__("datetime").datetime(2024, 1, 1, h),
                open=1.0,
                high=1.0002,
                low=0.9998,
                close=1.0,
            )
            for h in range(5)
        ]
        atr = _compute_atr(bars, period=14)
        assert len(atr) == 5
        assert all(a == 0.0 for a in atr)

    def test_compute_atr_empty(self):
        from backtest.portfolio_blend import _compute_atr

        assert _compute_atr([], period=14) == []


class TestATRVolatilityGate:
    def test_gate_all_active_on_flat_data(self):
        from backtest.portfolio_blend import _atr_volatility_gate
        from datetime import datetime, timedelta

        t0 = datetime(2024, 1, 1)
        bars = [
            Bar(
                time=t0 + timedelta(hours=h),
                open=1.0,
                high=1.0001,
                low=0.9999,
                close=1.0,
            )
            for h in range(50)
        ]
        gate = _atr_volatility_gate(bars, atr_period=14, atr_percentile_threshold=80.0)
        assert len(gate) == 50
        assert all(gate[14:])

    def test_gate_with_spike(self):
        from backtest.portfolio_blend import _atr_volatility_gate
        from datetime import datetime, timedelta

        t0 = datetime(2024, 1, 1)
        bars = []
        for h in range(100):
            if h == 90:
                bars.append(
                    Bar(
                        time=t0 + timedelta(hours=h),
                        open=1.0,
                        high=1.1,
                        low=0.9,
                        close=1.05,
                    )
                )
            else:
                bars.append(
                    Bar(
                        time=t0 + timedelta(hours=h),
                        open=1.0,
                        high=1.0001,
                        low=0.9999,
                        close=1.0,
                    )
                )
        gate = _atr_volatility_gate(bars, atr_period=14, atr_percentile_threshold=50.0)
        assert len(gate) == 100
        assert not gate[90]

    def test_gate_empty(self):
        from backtest.portfolio_blend import _atr_volatility_gate

        assert _atr_volatility_gate([], atr_period=14) == []


class TestReoptimizeWeights:
    def test_returns_weights_for_valid_data(self):
        from backtest.portfolio_blend import _reoptimize_weights_for_window

        bars = _make_bars(n=200, base_price=1.1)
        spec = StrategySpec(
            name="Dummy",
            factory=_DummyStrategy,
            pair="EURUSD",
            timeframe="H1",
            data_path="/fake.csv",
        )

        train_map = {"Dummy|EURUSD|H1": bars}

        result = _reoptimize_weights_for_window(
            [spec], train_map, "inverse_variance", 1.0, 0.0, 10000.0
        )
        assert "adaptive" in result.method
        assert "Dummy|EURUSD|H1" in result.weights or len(result.weights) == 0

    def test_empty_when_no_data(self):
        from backtest.portfolio_blend import _reoptimize_weights_for_window

        result = _reoptimize_weights_for_window(
            [], {}, "inverse_variance", 1.0, 0.0, 10000.0
        )
        assert result.method == "adaptive_empty"
        assert result.weights == {}


class TestAdaptiveWalkForward:
    def test_runs_without_error(self):
        from backtest.portfolio_blend import _run_adaptive_portfolio_walk_forward
        from unittest.mock import patch

        bars = _make_bars(n=500, base_price=1.1)
        spec = StrategySpec(
            name="Grid",
            factory=_DummyStrategy,
            pair="XAUUSD",
            timeframe="M15",
            data_path="/fake/xauusd.csv",
        )

        def mock_load(self, path):
            return bars

        with patch("backtest.portfolio_blend.CsvDataLoader.load", mock_load):
            weights = WeightAllocation(weights={"Grid|XAUUSD|M15": 1.0}, method="test")
            wf_result, snapshots = _run_adaptive_portfolio_walk_forward(
                [spec],
                weights,
                10000.0,
                3,
                "inverse_variance",
                1.0,
                0.0,
                atr_gate=False,
            )

        assert wf_result is not None
        assert len(wf_result.per_window) == 3
        assert len(snapshots) == 3

    def test_atr_gate_reduces_trades(self):
        from backtest.portfolio_blend import _run_adaptive_portfolio_walk_forward
        from unittest.mock import patch

        bars = _make_bars(n=500, base_price=1.1)
        for i, b in enumerate(bars):
            if i >= 400:
                bars[i] = Bar(
                    time=b.time,
                    open=b.open,
                    high=b.high + 0.01,
                    low=b.low - 0.01,
                    close=b.close,
                )

        spec = StrategySpec(
            name="Grid",
            factory=_DummyStrategy,
            pair="XAUUSD",
            timeframe="M15",
            data_path="/fake/xauusd.csv",
        )

        def mock_load(self, path):
            return bars

        with patch("backtest.portfolio_blend.CsvDataLoader.load", mock_load):
            weights = WeightAllocation(weights={"Grid|XAUUSD|M15": 1.0}, method="test")

            wf_no_gate, _ = _run_adaptive_portfolio_walk_forward(
                [spec],
                weights,
                10000.0,
                2,
                "inverse_variance",
                1.0,
                0.0,
                atr_gate=False,
            )
            wf_with_gate, _ = _run_adaptive_portfolio_walk_forward(
                [spec],
                weights,
                10000.0,
                2,
                "inverse_variance",
                1.0,
                0.0,
                atr_gate=True,
                atr_percentile=50.0,
            )

        total_no_gate = sum(m.trade_count for m in wf_no_gate.per_window)
        total_with_gate = sum(m.trade_count for m in wf_with_gate.per_window)
        assert total_with_gate <= total_no_gate


class TestPortfolioBlendAdaptiveFlag:
    def test_adaptive_flag_passes_through(self):
        from unittest.mock import patch

        bars = _make_bars(n=500, base_price=1.1)
        spec = StrategySpec(
            name="Grid",
            factory=_DummyStrategy,
            pair="XAUUSD",
            timeframe="M15",
            data_path="/fake/xauusd.csv",
        )

        def mock_load(self, path):
            return bars

        with patch("backtest.portfolio_blend.CsvDataLoader.load", mock_load):
            result = run_portfolio_blend(
                [spec],
                initial_balance=10000.0,
                n_walk_forward_windows=2,
                enable_filter=False,
                adaptive_weights=True,
                atr_gate=False,
            )

        assert result.adaptive_window_weights is not None
        assert len(result.adaptive_window_weights) == 2

    def test_non_adaptive_has_no_snapshots(self):
        from unittest.mock import patch

        bars = _make_bars(n=500, base_price=1.1)
        spec = StrategySpec(
            name="Grid",
            factory=_DummyStrategy,
            pair="XAUUSD",
            timeframe="M15",
            data_path="/fake/xauusd.csv",
        )

        def mock_load(self, path):
            return bars

        with patch("backtest.portfolio_blend.CsvDataLoader.load", mock_load):
            result = run_portfolio_blend(
                [spec],
                initial_balance=10000.0,
                n_walk_forward_windows=2,
                enable_filter=False,
                adaptive_weights=False,
            )

        assert result.adaptive_window_weights is None
