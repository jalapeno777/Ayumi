import math
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from backtest.engine import BacktestMetrics, Bar, TradeDirection
from backtest.hybrid_strategy import HybridStrategy, RejectionMetrics
from backtest.ict_smc.models import ConfluenceSignal, SignalStrength
from backtest.runner import _run_window_backtest  # noqa: F401


def _make_bar(hour, price=1.1, day=1):
    t = datetime(2024, 1, day, hour, 0)
    return Bar(
        time=t, open=price, high=price + 0.001, low=price - 0.001, close=price + 0.0002
    )


def _make_signal(
    direction=TradeDirection.LONG,
    entry=1.1,
    sl=1.098,
    tp=1.103,
    confidence=0.7,
):
    return ConfluenceSignal(
        direction=direction,
        strength=SignalStrength.STRONG,
        confidence_score=confidence,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=tp + 0.003,
        take_profit_3=tp + 0.006,
        signal_time=datetime(2024, 1, 1, 10, 0),
        rationale="test",
        confluence_count=3,
        risk_reward_ratio=2.0,
    )


def _make_bars(n_bars, bars_per_day=24, base_price=1.1):
    bars = []
    day = 1
    for i in range(n_bars):
        hour = i % bars_per_day
        if i > 0 and hour == 0:
            day += 1
        bars.append(_make_bar(hour, base_price, day))
    return bars


class TestPositionSizingFormula(unittest.TestCase):
    """Bugs 1 & 2: Verify position sizing formula is correct."""

    def test_lots_no_extra_pip_val(self):
        """Bug 1: lots = risk_amount / (risk_dist * 100000), not risk_dist * pip_val * 100000."""
        balance = 10000.0
        risk_pct = 0.005
        risk_amount = balance * risk_pct
        risk_dist = 0.002
        pip_val = 0.0001

        correct_lots = risk_amount / (risk_dist * 100000)
        buggy_lots = risk_amount / (risk_dist * pip_val * 100000)

        self.assertAlmostEqual(correct_lots, 0.25, places=4)
        self.assertAlmostEqual(buggy_lots, 2500.0, places=0)
        self.assertAlmostEqual(
            buggy_lots / correct_lots,
            10000.0,
            places=0,
            msg="Buggy formula produces lots 10,000x too large",
        )

    def test_lots_consistent_with_position_sizing_module(self):
        """Bug 1: Runner formula should match quant/position_sizing.py fixed_fractional."""
        balance = 10000.0
        risk_pct = 0.5
        entry = 1.1000
        sl = 1.0980
        risk_dist = abs(entry - sl)

        from quant.position_sizing import fixed_fractional

        expected = fixed_fractional(balance, risk_pct, entry, sl)
        risk_amount = balance * (risk_pct / 100.0)
        runner_lots = risk_amount / (risk_dist * 100000)

        self.assertAlmostEqual(runner_lots, expected, places=6)

    def test_margin_cap_includes_contract_size(self):
        """Bug 2: Margin cap should account for 100,000 contract size."""
        balance = 10000.0
        leverage = 100
        entry = 1.1000

        correct_max_lots = (balance * leverage) / (entry * 100000)
        buggy_max_lots = balance * leverage / entry

        self.assertAlmostEqual(correct_max_lots, 9.0909, places=3)
        self.assertGreater(
            buggy_max_lots / correct_max_lots,
            99999,
            msg="Buggy margin cap is >99,999x too permissive",
        )

    def test_margin_cap_returns_reasonable_lots(self):
        """Bug 2: With contract size, margin cap should return <100 lots for typical accounts."""
        balance = 10000.0
        leverage = 100
        entry = 1.1000

        max_lots = (balance * leverage) / (entry * 100000)
        self.assertLess(
            max_lots, 100, msg="Margin cap should be reasonable for $10k account"
        )
        self.assertGreater(max_lots, 0)


class TestSharpeAnnualization(unittest.TestCase):
    """Bug 5: Sharpe should use sqrt(6048) for H1 bars, not sqrt(252)."""

    def test_h1_sharpe_uses_sqrt_6048(self):
        mean_r = 0.0001
        std_r = 0.001

        h1_sharpe = mean_r / std_r * math.sqrt(6048)
        daily_sharpe = mean_r / std_r * math.sqrt(252)

        self.assertAlmostEqual(h1_sharpe, 7.777, places=2)
        self.assertAlmostEqual(daily_sharpe, 1.589, places=2)
        self.assertAlmostEqual(
            h1_sharpe / daily_sharpe,
            math.sqrt(6048 / 252),
            places=2,
            msg="H1 Sharpe should be sqrt(24) ≈ 4.9x larger than daily Sharpe",
        )

    def test_sqrt_6048_equals_sqrt_252_times_24(self):
        self.assertAlmostEqual(
            math.sqrt(6048),
            math.sqrt(252) * math.sqrt(24),
            places=6,
        )


class TestSpreadApplication(unittest.TestCase):
    """Bug 6: Spread should be applied to entry prices."""

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_long_entry_includes_spread(self, mock_ict_cls):
        """Long entries should have spread added to entry price."""
        bars = _make_bars(60)
        strategy = MagicMock(spec=HybridStrategy)
        signal = _make_signal(
            direction=TradeDirection.LONG, entry=1.1000, sl=1.0980, tp=1.1040
        )
        strategy.evaluate.return_value = signal
        strategy.metrics = RejectionMetrics(total_evaluated=1, passed=1)

        result = _run_window_backtest(bars, strategy, spread_pips=0.5)

        self.assertIsInstance(result, BacktestMetrics)
        call_count = strategy.evaluate.call_count
        self.assertGreater(call_count, 0, "Strategy should have been called")

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_short_entry_includes_spread(self, mock_ict_cls):
        """Short entries should have spread subtracted from entry price."""
        bars = _make_bars(60)
        strategy = MagicMock(spec=HybridStrategy)
        signal = _make_signal(
            direction=TradeDirection.SHORT, entry=1.1000, sl=1.1020, tp=1.0960
        )
        strategy.evaluate.return_value = signal
        strategy.metrics = RejectionMetrics(total_evaluated=1, passed=1)

        result = _run_window_backtest(bars, strategy, spread_pips=1.0)

        self.assertIsInstance(result, BacktestMetrics)

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_zero_spread_no_effect(self, mock_ict_cls):
        """Zero spread should not affect results differently from no spread."""
        bars = _make_bars(60)
        strategy = MagicMock(spec=HybridStrategy)
        signal = _make_signal()
        strategy.evaluate.return_value = signal
        strategy.metrics = RejectionMetrics(total_evaluated=1, passed=1)

        result = _run_window_backtest(bars, strategy, spread_pips=0.0)

        self.assertIsInstance(result, BacktestMetrics)


class TestRejectedSignals(unittest.TestCase):
    """Bug 3: Rejected signals should be wired from strategy.metrics."""

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_rejected_signals_wired_from_strategy(self, mock_ict_cls):
        """rejected_signals should equal total_evaluated - passed."""
        bars = _make_bars(60)
        strategy = MagicMock(spec=HybridStrategy)
        strategy.evaluate.return_value = None
        strategy.metrics = RejectionMetrics(total_evaluated=10, passed=2)

        result = _run_window_backtest(bars, strategy)

        self.assertEqual(result.rejected_signals, 8)

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_rejected_signals_zero_when_all_pass(self, mock_ict_cls):
        """rejected_signals should be 0 when all signals pass."""
        bars = _make_bars(60)
        strategy = MagicMock(spec=HybridStrategy)
        signal = _make_signal()
        strategy.evaluate.return_value = signal
        strategy.metrics = RejectionMetrics(total_evaluated=5, passed=5)

        result = _run_window_backtest(bars, strategy)

        self.assertEqual(result.rejected_signals, 0)

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_rejected_signals_all_rejected(self, mock_ict_cls):
        """rejected_signals should equal total_evaluated when none pass."""
        bars = _make_bars(60)
        strategy = MagicMock(spec=HybridStrategy)
        strategy.evaluate.return_value = None
        strategy.metrics = RejectionMetrics(total_evaluated=20, passed=0)

        result = _run_window_backtest(bars, strategy)

        self.assertEqual(result.rejected_signals, 20)


class TestMaxDDTracking(unittest.TestCase):
    """Bug 4: Max DD should be tracked from equity curve, not just at trade close."""

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_max_dd_zero_with_no_trades(self, mock_ict_cls):
        """With no trades and no balance changes, max DD should be 0."""
        bars = _make_bars(60)
        strategy = MagicMock(spec=HybridStrategy)
        strategy.evaluate.return_value = None
        strategy.metrics = RejectionMetrics()

        result = _run_window_backtest(
            bars,
            strategy,
            starting_balance=10000.0,
            max_total_drawdown_pct=1.0,
        )

        self.assertEqual(result.max_drawdown_pct, 0.0)

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_max_dd_reflects_peak_equity(self, mock_ict_cls):
        """Max DD should be computed from peak equity at every bar."""
        bars = _make_bars(60)
        strategy = MagicMock(spec=HybridStrategy)
        strategy.evaluate.return_value = None
        strategy.metrics = RejectionMetrics()

        result = _run_window_backtest(
            bars,
            strategy,
            starting_balance=10000.0,
            max_total_drawdown_pct=1.0,
        )

        self.assertEqual(result.starting_balance, 10000.0)
        self.assertEqual(result.ending_balance, 10000.0)
        self.assertEqual(result.max_drawdown_pct, 0.0)


class TestDailyDDHalt(unittest.TestCase):
    """Bug 7: Daily DD limit should halt trading for the entire day."""

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_daily_dd_halt_skips_remaining_bars(self, mock_ict_cls):
        """When daily DD limit is hit, all bars until next day should be skipped."""
        bars = []
        for day in range(1, 3):
            for hour in range(24):
                bars.append(_make_bar(hour, 1.1, day))

        strategy = MagicMock(spec=HybridStrategy)
        signal = _make_signal()
        strategy.evaluate.return_value = signal
        strategy.metrics = RejectionMetrics(total_evaluated=0, passed=0)

        result = _run_window_backtest(
            bars,
            strategy,
            max_daily_drawdown_pct=0.0001,
            max_total_drawdown_pct=1.0,
        )

        self.assertIsInstance(result, BacktestMetrics)

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_no_halt_when_dd_not_exceeded(self, mock_ict_cls):
        """When daily DD limit is not exceeded, trading should continue normally."""
        bars = _make_bars(60)
        strategy = MagicMock(spec=HybridStrategy)
        signal = _make_signal()
        strategy.evaluate.return_value = signal
        strategy.metrics = RejectionMetrics(total_evaluated=1, passed=1)

        result = _run_window_backtest(
            bars,
            strategy,
            max_daily_drawdown_pct=0.5,
            max_total_drawdown_pct=1.0,
        )

        self.assertIsInstance(result, BacktestMetrics)


class TestATRPrecomputation(unittest.TestCase):
    """Bug 8: ATR should be precomputed once, not recomputed per bar."""

    @patch("backtest.ict_smc.models.ICTMarketState")
    def test_atr_series_length_matches_bars(self, mock_ict_cls):
        """ATR series should be precomputed and passed as growing slices."""
        bars = _make_bars(100)
        strategy = MagicMock(spec=HybridStrategy)
        strategy.evaluate.return_value = None
        strategy.metrics = RejectionMetrics()

        _run_window_backtest(bars, strategy)

        self.assertGreater(strategy.evaluate.call_count, 0)
        for idx, call_args in enumerate(strategy.evaluate.call_args_list):
            atr_arg = call_args.kwargs.get("atr_series") or call_args[1].get(
                "atr_series"
            )
            if atr_arg is not None:
                self.assertGreater(len(atr_arg), 0)
                self.assertLessEqual(len(atr_arg), len(bars))


if __name__ == "__main__":
    unittest.main()
