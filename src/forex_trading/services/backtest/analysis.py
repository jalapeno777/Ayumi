"""Comprehensive strategy backtest and comparison module.

Runs backtests with walk-forward analysis and generates comparative reports.
"""
import pandas as pd
import numpy as np
from typing import Optional
from .engine import BacktestEngine, BacktestConfig, BacktestResult
from .prop_firm_rules import PropFirmConfig
from .reporting import generate_comparative_report, monte_carlo_simulation, calculate_walk_forward_summary


class StrategyBacktester:
    def __init__(self, starting_balance: float = 10000.0, prop_firm_config: Optional[PropFirmConfig] = None):
        self.starting_balance = starting_balance
        self.prop_firm_config = prop_firm_config or PropFirmConfig()

    def backtest_single(self, data: pd.DataFrame, strategy, pair: str = "EURUSD") -> BacktestResult:
        config = BacktestConfig(
            starting_balance=self.starting_balance,
            prop_firm_config=self.prop_firm_config
        )
        engine = BacktestEngine(config)
        return engine.run(data, strategy, pair)

    def backtest_with_walk_forward(
        self, data: pd.DataFrame, strategy, train_bars: int = 63, test_bars: int = 126,
        step_bars: int = 21, pair: str = "EURUSD"
    ) -> tuple[list[BacktestResult], list[BacktestResult]]:
        config = BacktestConfig(
            starting_balance=self.starting_balance,
            prop_firm_config=self.prop_firm_config
        )

        is_results = []
        oos_results = []
        train_start = 0

        while train_start + train_bars + test_bars <= len(data):
            train_end = train_start + train_bars
            test_start = train_end
            test_end = test_start + test_bars

            train_data = data.iloc[train_start:train_end]
            test_data = data.iloc[test_start:test_end]

            train_engine = BacktestEngine(config)
            is_result = train_engine.run(train_data, strategy, pair)
            is_results.append(is_result)

            test_engine = BacktestEngine(config)
            oos_result = test_engine.run(test_data, strategy, pair)
            oos_results.append(oos_result)

            train_start += step_bars

        return is_results, oos_results

    def compare_strategies(
        self, data: pd.DataFrame, strategies: list, pair: str = "EURUSD"
    ) -> pd.DataFrame:
        results = []
        for strategy in strategies:
            result = self.backtest_single(data, strategy, pair)
            results.append(result)

        return generate_comparative_report(results, [s.name for s in strategies])

    def run_monte_carlo(self, result: BacktestResult, n_simulations: int = 1000) -> dict:
        return monte_carlo_simulation(result, n_simulations)


def run_full_backtest_suite(
    data: pd.DataFrame,
    strategies: list,
    pair: str = "EURUSD",
    starting_balance: float = 10000.0
) -> dict:
    backtester = StrategyBacktester(starting_balance=starting_balance)

    comparative_df = backtester.compare_strategies(data, strategies, pair)

    wf_summary = None
    if len(data) > 100:
        wf_oos_results = []
        wf_is_results = []
        for strategy in strategies:
            is_res, oos_res = backtester.backtest_with_walk_forward(data, strategy, pair=pair)
            wf_is_results.append(is_res)
            wf_oos_results.append(oos_res)
        wf_summary = calculate_walk_forward_summary(wf_oos_results, [s.name for s in strategies], wf_is_results)

    mc_results = {}
    for strategy in strategies:
        result = backtester.backtest_single(data, strategy, pair)
        mc_results[strategy.name] = backtester.run_monte_carlo(result)

    return {
        'comparative_report': comparative_df,
        'walk_forward_summary': wf_summary,
        'monte_carlo_results': mc_results
    }
