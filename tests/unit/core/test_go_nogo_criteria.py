from __future__ import annotations

import pytest
from quant.go_nogo_criteria import (
    CANONICAL_AGGREGATE,
    CANONICAL_PER_WINDOW,
    AggregateCheck,
    AggregateCriteria,
    FullGoNoGoResult,
    PerWindowCheck,
    PerWindowCriteria,
    evaluate_aggregate,
    evaluate_full,
    evaluate_window,
)


class TestPerWindowCriteria:
    def test_default_thresholds(self):
        c = PerWindowCriteria()
        assert c.min_trades == 5
        assert c.win_rate == 0.55
        assert c.profit_factor == 1.0
        assert c.total_pnl == 0.0
        assert c.max_drawdown == 0.10

    def test_all_pass(self):
        c = CANONICAL_PER_WINDOW
        r = c.evaluate(
            trade_count=10,
            win_rate=0.60,
            profit_factor=1.5,
            total_pnl=100.0,
            max_drawdown=0.05,
        )
        assert r.passed is True
        assert all(check.passed for check in r.checks.values())

    def test_all_fail(self):
        c = CANONICAL_PER_WINDOW
        r = c.evaluate(
            trade_count=2,
            win_rate=0.40,
            profit_factor=0.5,
            total_pnl=-100.0,
            max_drawdown=0.50,
        )
        assert r.passed is False
        assert all(not check.passed for check in r.checks.values())

    def test_min_trades_boundary(self):
        c = CANONICAL_PER_WINDOW
        r_at = c.evaluate(5, 0.60, 1.5, 100.0, 0.05)
        r_below = c.evaluate(4, 0.60, 1.5, 100.0, 0.05)
        assert r_at.passed is True
        assert r_below.passed is False

    def test_win_rate_strict(self):
        c = CANONICAL_PER_WINDOW
        r_at = c.evaluate(10, 0.55, 1.5, 100.0, 0.05)
        r_above = c.evaluate(10, 0.5501, 1.5, 100.0, 0.05)
        assert r_at.passed is False
        assert r_above.passed is True

    def test_profit_factor_strict(self):
        c = CANONICAL_PER_WINDOW
        r_at = c.evaluate(10, 0.60, 1.0, 100.0, 0.05)
        r_above = c.evaluate(10, 0.60, 1.0001, 100.0, 0.05)
        assert r_at.passed is False
        assert r_above.passed is True

    def test_max_drawdown_strict(self):
        c = CANONICAL_PER_WINDOW
        r_at = c.evaluate(10, 0.60, 1.5, 100.0, 0.10)
        r_below = c.evaluate(10, 0.60, 1.5, 100.0, 0.0999)
        assert r_at.passed is False
        assert r_below.passed is True

    def test_total_pnl_strict(self):
        c = CANONICAL_PER_WINDOW
        r_at = c.evaluate(10, 0.60, 1.5, 0.0, 0.05)
        r_above = c.evaluate(10, 0.60, 1.5, 0.01, 0.05)
        assert r_at.passed is False
        assert r_above.passed is True

    def test_one_fail_causes_overall_fail(self):
        c = CANONICAL_PER_WINDOW
        r = c.evaluate(
            trade_count=10,
            win_rate=0.40,
            profit_factor=1.5,
            total_pnl=100.0,
            max_drawdown=0.05,
        )
        assert r.passed is False
        assert r.checks["win_rate"].passed is False
        assert r.checks["profit_factor"].passed is True

    def test_custom_criteria(self):
        custom = PerWindowCriteria(
            min_trades=20,
            win_rate=0.50,
            profit_factor=1.5,
            total_pnl=0.0,
            max_drawdown=0.05,
        )
        r = custom.evaluate(
            trade_count=15,
            win_rate=0.55,
            profit_factor=1.5,
            total_pnl=100.0,
            max_drawdown=0.05,
        )
        assert r.passed is False
        assert r.checks["min_trades"].passed is False

    def test_check_details(self):
        c = CANONICAL_PER_WINDOW
        r = c.evaluate(3, 0.40, 0.5, -50.0, 0.20)
        check = r.checks["win_rate"]
        assert isinstance(check, PerWindowCheck)
        assert check.metric == "win_rate"
        assert check.value == 0.40
        assert check.threshold == 0.55
        assert check.operator == ">"


class TestAggregateCriteria:
    def test_default_thresholds(self):
        c = AggregateCriteria()
        assert c.min_total_trades == 50
        assert c.min_windows_passed == 3
        assert c.min_total_windows == 3
        assert c.p_value_threshold == 0.10

    def test_all_pass(self):
        c = CANONICAL_AGGREGATE
        r = c.evaluate(
            total_trades=100,
            windows_passed=3,
            total_windows=5,
        )
        assert r.passed is True

    def test_all_fail(self):
        c = CANONICAL_AGGREGATE
        r = c.evaluate(
            total_trades=10,
            windows_passed=0,
            total_windows=3,
        )
        assert r.passed is False

    def test_min_total_trades_boundary(self):
        c = CANONICAL_AGGREGATE
        r_at = c.evaluate(50, 3, 5)
        r_below = c.evaluate(49, 3, 5)
        assert r_at.passed is True
        assert r_below.passed is False

    def test_min_windows_passed_boundary(self):
        # Default min_windows_passed is 3 (3-of-5 rule, corrected 2026-07-08).
        c = CANONICAL_AGGREGATE
        r_at = c.evaluate(100, 3, 5)
        r_below = c.evaluate(100, 2, 5)
        assert r_at.passed is True
        assert r_below.passed is False

    def test_min_total_windows_boundary(self):
        # Default min_windows_passed is 3, so windows_passed must be 3 to
        # isolate the min_total_windows boundary check.
        c = CANONICAL_AGGREGATE
        r_at = c.evaluate(100, 3, 3)
        r_below = c.evaluate(100, 3, 2)
        assert r_at.passed is True
        assert r_below.passed is False

    def test_p_value_check(self):
        c = CANONICAL_AGGREGATE
        r_pass = c.evaluate(100, 3, 5, p_value=0.05)
        r_fail = c.evaluate(100, 3, 5, p_value=0.15)
        assert r_pass.passed is True
        assert r_fail.passed is False
        assert r_fail.checks["p_value"].passed is False

    def test_p_value_none_skipped(self):
        c = CANONICAL_AGGREGATE
        r = c.evaluate(100, 3, 5, p_value=None)
        assert r.passed is True
        assert "p_value" not in r.checks

    def test_custom_criteria(self):
        custom = AggregateCriteria(
            min_total_trades=50,
            min_windows_passed=4,
            min_total_windows=5,
        )
        r = custom.evaluate(total_trades=100, windows_passed=3, total_windows=5)
        assert r.passed is False
        assert r.checks["min_windows_passed"].passed is False

    def test_check_details(self):
        c = CANONICAL_AGGREGATE
        r = c.evaluate(10, 0, 3)
        check = r.checks["min_total_trades"]
        assert isinstance(check, AggregateCheck)
        assert check.metric == "min_total_trades"
        assert check.value == 10.0
        assert check.threshold == 50.0
        assert check.operator == ">="


class TestConvenienceFunctions:
    def test_evaluate_window_defaults_to_canonical(self):
        r = evaluate_window(
            trade_count=10,
            win_rate=0.60,
            profit_factor=1.5,
            total_pnl=100.0,
            max_drawdown=0.05,
        )
        assert r.passed is True

    def test_evaluate_window_custom_criteria(self):
        custom = PerWindowCriteria(
            min_trades=20,
            win_rate=0.50,
            profit_factor=1.5,
            total_pnl=0.0,
            max_drawdown=0.05,
        )
        r = evaluate_window(10, 0.60, 1.5, 100.0, 0.05, criteria=custom)
        assert r.passed is False

    def test_evaluate_aggregate_defaults_to_canonical(self):
        r = evaluate_aggregate(
            total_trades=100,
            windows_passed=3,
            total_windows=5,
        )
        assert r.passed is True

    def test_evaluate_aggregate_custom_criteria(self):
        custom = AggregateCriteria(min_total_trades=50, min_windows_passed=4, min_total_windows=5)
        r = evaluate_aggregate(100, 3, 5, criteria=custom)
        assert r.passed is False

    def test_evaluate_full_go(self):
        windows = [
            {
                "trade_count": 10,
                "win_rate": 0.60,
                "profit_factor": 1.5,
                "total_pnl": 100.0,
                "max_drawdown": 0.05,
            },
            {
                "trade_count": 10,
                "win_rate": 0.60,
                "profit_factor": 1.5,
                "total_pnl": 100.0,
                "max_drawdown": 0.05,
            },
            {
                "trade_count": 30,
                "win_rate": 0.60,
                "profit_factor": 1.5,
                "total_pnl": 100.0,
                "max_drawdown": 0.05,
            },
        ]
        r = evaluate_full(windows)
        assert isinstance(r, FullGoNoGoResult)
        assert r.go is True
        assert r.windows_passed == 3
        assert r.total_windows == 3
        assert r.total_trades == 50
        assert len(r.per_window) == 3
        assert r.aggregate is not None

    def test_evaluate_full_nogo(self):
        windows = [
            {
                "trade_count": 3,
                "win_rate": 0.40,
                "profit_factor": 0.5,
                "total_pnl": -100.0,
                "max_drawdown": 0.50,
            },
            {
                "trade_count": 3,
                "win_rate": 0.40,
                "profit_factor": 0.5,
                "total_pnl": -100.0,
                "max_drawdown": 0.50,
            },
            {
                "trade_count": 10,
                "win_rate": 0.60,
                "profit_factor": 1.5,
                "total_pnl": 100.0,
                "max_drawdown": 0.05,
            },
        ]
        r = evaluate_full(windows)
        assert r.go is False
        assert r.windows_passed == 1

    def test_evaluate_full_empty(self):
        r = evaluate_full([])
        assert r.go is False
        assert r.total_windows == 0
        assert r.total_trades == 0

    def test_evaluate_full_missing_keys_use_defaults(self):
        windows = [
            {
                "trade_count": 10,
                "win_rate": 0.60,
                "profit_factor": 1.5,
                "total_pnl": 100.0,
            },
        ]
        r = evaluate_full(windows)
        assert r.per_window[0].passed is False


class TestBackwardCompatibility:
    def test_canonical_matches_original_walk_forward_thresholds(self):
        c = CANONICAL_PER_WINDOW
        assert c.min_trades == 5
        assert c.win_rate == 0.55
        assert c.profit_factor == 1.0
        assert c.total_pnl == 0.0
        assert c.max_drawdown == 0.10

    def test_canonical_aggregate_matches_walk_forward_runner(self):
        c = CANONICAL_AGGREGATE
        assert c.min_windows_passed == 3
        assert c.min_total_windows == 3

    def test_walk_forward_default_3_of_5(self):
        # Default rule: 3-of-5 windows must pass. 2 of 3 is below the bar
        # and must be rejected by the canonical aggregate criteria.
        r_below = evaluate_aggregate(
            total_trades=50,
            windows_passed=2,
            total_windows=3,
        )
        assert r_below.passed is False

        r_at = evaluate_aggregate(
            total_trades=50,
            windows_passed=3,
            total_windows=5,
        )
        assert r_at.passed is True

    def test_3_of_5_passes(self):
        windows = [
            {
                "trade_count": 25,
                "win_rate": 0.60,
                "profit_factor": 1.5,
                "total_pnl": 100.0,
                "max_drawdown": 0.05,
            },
            {
                "trade_count": 25,
                "win_rate": 0.60,
                "profit_factor": 1.5,
                "total_pnl": 100.0,
                "max_drawdown": 0.05,
            },
            {
                "trade_count": 25,
                "win_rate": 0.60,
                "profit_factor": 1.5,
                "total_pnl": 100.0,
                "max_drawdown": 0.05,
            },
            {
                "trade_count": 3,
                "win_rate": 0.40,
                "profit_factor": 0.5,
                "total_pnl": -100.0,
                "max_drawdown": 0.50,
            },
            {
                "trade_count": 3,
                "win_rate": 0.40,
                "profit_factor": 0.5,
                "total_pnl": -100.0,
                "max_drawdown": 0.50,
            },
        ]
        r = evaluate_full(windows)
        assert r.windows_passed == 3
        assert r.go is True


class TestFrozenDataclasses:
    def test_per_window_criteria_frozen(self):
        c = CANONICAL_PER_WINDOW
        with pytest.raises(AttributeError):
            c.min_trades = 10

    def test_aggregate_criteria_frozen(self):
        c = CANONICAL_AGGREGATE
        with pytest.raises(AttributeError):
            c.min_total_trades = 100

    def test_per_window_check_frozen(self):
        c = CANONICAL_PER_WINDOW
        r = c.evaluate(10, 0.60, 1.5, 100.0, 0.05)
        check = r.checks["win_rate"]
        with pytest.raises(AttributeError):
            check.passed = False

    def test_aggregate_check_frozen(self):
        c = CANONICAL_AGGREGATE
        r = c.evaluate(100, 3, 5)
        check = r.checks["min_total_trades"]
        with pytest.raises(AttributeError):
            check.passed = False
