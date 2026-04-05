import json
from datetime import datetime, timedelta
from pathlib import Path


from backtest.engine import (
    BacktestConfig,
    BacktestMetrics,
    Bar,
    SimulatedTrade,
    TradeDirection,
    TradeOutcome,
    ExitReason,
)
from backtest.selective_pairing import (
    COMPONENT_NAMES,
    PairingConfig,
    PairingReport,
    SelectivePairingHarness,
    WindowMetrics,
    ComponentResult,
    _calculate_metrics,
    _check_trade_exit,
    _close_trade,
    _get_pip_value,
)
from backtest.runner import analyze_rolling_walk_forward
from backtest.strategies import MACrossStrategy, BBStrategy


def _make_trending_bars(n: int = 200, trend: float = 0.00005) -> list:
    bars = []
    price = 1.1000
    for i in range(n):
        hour = 8 + (i % 12)
        if hour >= 20:
            hour = 8 + (hour - 20)
        price += trend + (0.0001 * (1 if i % 3 == 0 else -1))
        noise = 0.0002
        bars.append(
            Bar(
                time=datetime(2024, 1, 1, hour, 0) + timedelta(hours=i),
                open=price - noise,
                high=price + noise * 2,
                low=price - noise * 2,
                close=price,
                volume=100,
            )
        )
    return bars


class TestGetPipValue:
    def test_jpy_pair(self):
        assert _get_pip_value(150.0) == 0.01

    def test_major_pair(self):
        assert _get_pip_value(1.1000) == 0.0001

    def test_exotic_pair(self):
        assert _get_pip_value(0.00005) == 0.00000001


class TestCheckTradeExit:
    def test_long_stop_loss_hit(self):
        bar = Bar(
            time=datetime(2024, 1, 1, 10, 0),
            open=1.09,
            high=1.095,
            low=1.085,
            close=1.09,
        )
        trade = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=-1,
            direction=TradeDirection.LONG,
            entry_price=1.10,
            stop_loss=1.088,
            take_profit_1=1.11,
            take_profit_2=1.12,
            take_profit_3=1.13,
            exit_price=0,
            lot_size=0.1,
            risk_amount=10,
            pips=0,
            profit_loss=0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=bar.time,
            exit_time=bar.time,
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )
        hit, price, reason = _check_trade_exit(trade, bar)
        assert hit is True
        assert price == 1.088
        assert reason == ExitReason.STOP_LOSS

    def test_long_tp3_hit(self):
        bar = Bar(
            time=datetime(2024, 1, 1, 10, 0),
            open=1.12,
            high=1.135,
            low=1.115,
            close=1.13,
        )
        trade = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=-1,
            direction=TradeDirection.LONG,
            entry_price=1.10,
            stop_loss=1.088,
            take_profit_1=1.11,
            take_profit_2=1.12,
            take_profit_3=1.13,
            exit_price=0,
            lot_size=0.1,
            risk_amount=10,
            pips=0,
            profit_loss=0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=bar.time,
            exit_time=bar.time,
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )
        hit, price, reason = _check_trade_exit(trade, bar)
        assert hit is True
        assert price == 1.13
        assert reason == ExitReason.TAKE_PROFIT_3

    def test_short_stop_loss_hit(self):
        bar = Bar(
            time=datetime(2024, 1, 1, 10, 0),
            open=1.115,
            high=1.12,
            low=1.11,
            close=1.115,
        )
        trade = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=-1,
            direction=TradeDirection.SHORT,
            entry_price=1.10,
            stop_loss=1.115,
            take_profit_1=1.09,
            take_profit_2=1.08,
            take_profit_3=1.07,
            exit_price=0,
            lot_size=0.1,
            risk_amount=10,
            pips=0,
            profit_loss=0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=bar.time,
            exit_time=bar.time,
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )
        hit, price, reason = _check_trade_exit(trade, bar)
        assert hit is True
        assert price == 1.115
        assert reason == ExitReason.STOP_LOSS

    def test_no_exit(self):
        bar = Bar(
            time=datetime(2024, 1, 1, 10, 0),
            open=1.095,
            high=1.105,
            low=1.092,
            close=1.10,
        )
        trade = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=-1,
            direction=TradeDirection.LONG,
            entry_price=1.10,
            stop_loss=1.088,
            take_profit_1=1.11,
            take_profit_2=1.12,
            take_profit_3=1.13,
            exit_price=0,
            lot_size=0.1,
            risk_amount=10,
            pips=0,
            profit_loss=0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=bar.time,
            exit_time=bar.time,
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )
        hit, price, reason = _check_trade_exit(trade, bar)
        assert hit is False


class TestCloseTrade:
    def test_long_win(self):
        trade = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=-1,
            direction=TradeDirection.LONG,
            entry_price=1.10,
            stop_loss=1.09,
            take_profit_1=1.11,
            take_profit_2=1.12,
            take_profit_3=1.13,
            exit_price=0,
            lot_size=100000,
            risk_amount=50,
            pips=0,
            profit_loss=0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=datetime(2024, 1, 1, 10, 0),
            exit_time=datetime(2024, 1, 1, 10, 0),
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )
        cfg = PairingConfig(round_trip_spread=False, slippage_pips=0.0)
        _close_trade(
            trade, 1, datetime(2024, 1, 1, 11, 0), 1.12, ExitReason.TAKE_PROFIT_2, cfg
        )
        assert trade.exit_price == 1.12
        assert trade.outcome == TradeOutcome.WIN
        assert trade.profit_loss > 0

    def test_short_loss(self):
        trade = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=-1,
            direction=TradeDirection.SHORT,
            entry_price=1.10,
            stop_loss=1.11,
            take_profit_1=1.09,
            take_profit_2=1.08,
            take_profit_3=1.07,
            exit_price=0,
            lot_size=100000,
            risk_amount=50,
            pips=0,
            profit_loss=0,
            outcome=TradeOutcome.OPEN,
            exit_reason=ExitReason.STOP_LOSS,
            entry_time=datetime(2024, 1, 1, 10, 0),
            exit_time=datetime(2024, 1, 1, 10, 0),
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )
        cfg = PairingConfig(round_trip_spread=False, slippage_pips=0.0)
        _close_trade(
            trade, 1, datetime(2024, 1, 1, 11, 0), 1.11, ExitReason.STOP_LOSS, cfg
        )
        assert trade.exit_price == 1.11
        assert trade.outcome == TradeOutcome.LOSS
        assert trade.profit_loss < 0


class TestCalculateMetrics:
    def test_no_trades(self):
        metrics = _calculate_metrics([], [10000.0], 0, 10000.0, 0.0, 0.0, 10000.0)
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.ending_balance == 10000.0

    def test_with_winning_trade(self):
        trade = SimulatedTrade(
            entry_bar_index=0,
            exit_bar_index=10,
            direction=TradeDirection.LONG,
            entry_price=1.10,
            stop_loss=1.09,
            take_profit_1=1.11,
            take_profit_2=1.12,
            take_profit_3=1.13,
            exit_price=1.12,
            lot_size=100000,
            risk_amount=50,
            pips=200,
            profit_loss=190,
            outcome=TradeOutcome.WIN,
            exit_reason=ExitReason.TAKE_PROFIT_2,
            entry_time=datetime(2024, 1, 1, 10, 0),
            exit_time=datetime(2024, 1, 1, 12, 0),
            confidence_score=0.8,
            confluence_count=1,
            rationale="",
        )
        metrics = _calculate_metrics(
            [trade], [10000.0, 10190.0], 0, 10000.0, 0.0, 0.0, 10190.0
        )
        assert metrics.total_trades == 1
        assert metrics.winning_trades == 1
        assert metrics.losing_trades == 0
        assert metrics.win_rate == 100.0
        assert metrics.total_pnl == 190.0


class TestPairingConfig:
    def test_defaults(self):
        cfg = PairingConfig()
        assert cfg.risk_per_trade_pct == 0.005
        assert cfg.max_open_trades == 3
        assert cfg.sl_atr_multiplier == 1.5
        assert cfg.min_confidence == 0.55
        assert "london" in cfg.allow_entry_sessions
        assert "ny_am" in cfg.allow_entry_sessions
        assert "ny_pm" in cfg.allow_entry_sessions

    def test_custom(self):
        cfg = PairingConfig(risk_per_trade_pct=0.01, max_open_trades=5)
        assert cfg.risk_per_trade_pct == 0.01
        assert cfg.max_open_trades == 5


class TestComponentResult:
    def test_from_metrics(self):
        m = BacktestMetrics(
            starting_balance=10000.0,
            ending_balance=10500.0,
            total_pnl=500.0,
            total_pnl_pct=0.05,
            win_rate=60.0,
            total_trades=50,
            winning_trades=30,
            losing_trades=18,
            breakeven_trades=2,
            avg_win=25.0,
            avg_loss=15.0,
            largest_win=100.0,
            largest_loss=50.0,
            profit_factor=2.5,
            max_drawdown_pct=3.0,
            max_drawdown_dollar=300.0,
            max_daily_loss_dollar=100.0,
            sharpe_ratio=1.5,
            avg_risk_reward=1.67,
            expectancy=12.0,
            avg_holding_bars=20.0,
            equity_curve=[10000.0, 10500.0],
            trades=[],
            total_spread_cost=0.0,
            total_commission_cost=0.0,
            rejected_signals=0,
        )
        cr = ComponentResult.from_metrics("test_comp", m)
        assert cr.component == "test_comp"
        assert cr.win_rate == 60.0
        assert cr.profit_factor == 2.5
        assert cr.total_pnl == 500.0


class TestComponentNames:
    def test_has_all_components(self):
        expected = {
            "structure",
            "order_block",
            "fvg",
            "liquidity_sweep",
            "premium_discount",
            "h4_context",
        }
        assert set(COMPONENT_NAMES) == expected

    def test_pair_count(self):
        from itertools import combinations

        pairs = list(combinations(COMPONENT_NAMES, 2))
        assert len(pairs) == 15


class TestSelectivePairingHarness:
    def test_init_defaults(self):
        harness = SelectivePairingHarness()
        assert harness.config.risk_per_trade_pct == 0.005

    def test_init_custom_config(self):
        cfg = PairingConfig(risk_per_trade_pct=0.01)
        harness = SelectivePairingHarness(cfg)
        assert harness.config.risk_per_trade_pct == 0.01

    def test_run_individual_returns_all_components(self):
        bars = _make_trending_bars(200)
        harness = SelectivePairingHarness()
        results = harness.run_individual(bars)
        assert set(results.keys()) == set(COMPONENT_NAMES)
        for comp_name, cr in results.items():
            assert isinstance(cr, ComponentResult)
            assert cr.component == comp_name
            assert cr.total_trades >= 0

    def test_run_pairs_returns_all_pairs(self):
        from itertools import combinations

        bars = _make_trending_bars(200)
        harness = SelectivePairingHarness()
        results = harness.run_pairs(bars)
        expected_pairs = {f"{a}+{b}" for a, b in combinations(COMPONENT_NAMES, 2)}
        assert set(results.keys()) == expected_pairs

    def test_run_walk_forward_returns_correct_windows(self):
        bars = _make_trending_bars(600)
        harness = SelectivePairingHarness()
        windows = harness.run_walk_forward(bars, n_windows=3)
        assert len(windows) == 3
        for w in windows:
            assert isinstance(w, WindowMetrics)
            assert w.train_bars > 0
            assert w.test_bars > 0

    def test_run_walk_forward_single_window(self):
        bars = _make_trending_bars(300)
        harness = SelectivePairingHarness()
        windows = harness.run_walk_forward(bars, n_windows=1)
        assert len(windows) == 1

    def test_walk_forward_too_few_bars(self):
        bars = _make_trending_bars(50)
        harness = SelectivePairingHarness()
        windows = harness.run_walk_forward(bars, n_windows=1)
        assert len(windows) == 1
        assert windows[0].train_bars == 0

    def test_session_filtering(self):
        asian_only_bars = []
        price = 1.10
        for i in range(200):
            price += 0.00005
            asian_only_bars.append(
                Bar(
                    time=datetime(2024, 1, 1, 2, 0) + timedelta(hours=i),
                    open=price - 0.0002,
                    high=price + 0.0003,
                    low=price - 0.0003,
                    close=price,
                    volume=100,
                )
            )
        harness = SelectivePairingHarness()
        results = harness.run_individual(asian_only_bars)
        for comp, cr in results.items():
            assert cr.total_trades == 0, (
                f"{comp} should have no trades in Asian-only bars"
            )

    def test_full_report_structure(self):
        bars = _make_trending_bars(300)
        harness = SelectivePairingHarness()
        report = harness.run_full_report(bars, n_windows=2)
        assert isinstance(report, PairingReport)
        assert "risk_per_trade_pct" in report.config
        assert len(report.windows) == 2
        assert len(report.aggregate_components) == len(COMPONENT_NAMES)
        assert len(report.aggregate_pairs) == 15

    def test_full_report_json_output(self, tmp_path):
        bars = _make_trending_bars(200)
        harness = SelectivePairingHarness()
        output = str(tmp_path / "report.json")
        harness.run_full_report(bars, n_windows=1, output_path=output)
        assert Path(output).exists()
        data = json.loads(Path(output).read_text())
        assert "config" in data
        assert "windows" in data
        assert "aggregate_components" in data
        assert "aggregate_pairs" in data

    def test_custom_config_affects_trades(self):
        bars = _make_trending_bars(200)
        strict_cfg = PairingConfig(min_confidence=0.99)
        loose_cfg = PairingConfig(min_confidence=0.30)
        strict = SelectivePairingHarness(strict_cfg)
        loose = SelectivePairingHarness(loose_cfg)
        strict_results = strict.run_individual(bars)
        loose_results = loose.run_individual(bars)
        strict_total = sum(cr.total_trades for cr in strict_results.values())
        loose_total = sum(cr.total_trades for cr in loose_results.values())
        assert loose_total >= strict_total


class TestAnalyzeRollingWalkForward:
    def test_basic_rolling(self):
        bars = _make_trending_bars(900)
        config = BacktestConfig(min_bars_before_signal=10)
        strategies = [MACrossStrategy(), BBStrategy()]
        results = analyze_rolling_walk_forward(bars, config, strategies, n_windows=3)
        assert len(results) == 3
        for w in results:
            assert "train_results" in w
            assert "test_results" in w
            assert w["train_bars"] > 0

    def test_custom_run_fn(self):
        bars = _make_trending_bars(200)
        config = BacktestConfig()
        call_count = 0

        def mock_run(bars_subset, cfg, strats):
            nonlocal call_count
            call_count += 1
            return {
                "mock": BacktestMetrics(
                    starting_balance=10000,
                    ending_balance=10000,
                    total_pnl=0,
                    total_pnl_pct=0,
                    win_rate=0,
                    total_trades=0,
                    winning_trades=0,
                    losing_trades=0,
                    breakeven_trades=0,
                    avg_win=0,
                    avg_loss=0,
                    largest_win=0,
                    largest_loss=0,
                    profit_factor=0,
                    max_drawdown_pct=0,
                    max_drawdown_dollar=0,
                    max_daily_loss_dollar=0,
                    sharpe_ratio=0,
                    avg_risk_reward=0,
                    expectancy=0,
                    avg_holding_bars=0,
                    equity_curve=[10000],
                    trades=[],
                    total_spread_cost=0,
                    total_commission_cost=0,
                    rejected_signals=0,
                )
            }

        results = analyze_rolling_walk_forward(
            bars, config, [], n_windows=2, run_fn=mock_run
        )
        assert call_count == 4
        assert len(results) == 2

    def test_insufficient_bars_window(self):
        bars = _make_trending_bars(50)
        config = BacktestConfig()
        strategies = [MACrossStrategy()]
        results = analyze_rolling_walk_forward(bars, config, strategies, n_windows=1)
        assert len(results) == 1
        assert results[0].get("error") == "Insufficient bars for window"
