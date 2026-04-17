"""Performance reporting module.

Generates comparative performance reports across strategies.
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np
from .engine import BacktestResult


@dataclass
class PerformanceReport:
    strategy_name: str
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_trade_duration: float
    compliance_passed: bool
    violations: list


def generate_comparative_report(results: list[BacktestResult], strategy_names: list[str]) -> pd.DataFrame:
    reports = []
    for result, name in zip(results, strategy_names):
        compliance_passed = (
            result.compliance_report.get('violation_count', 0) == 0 and
            result.compliance_report.get('profit_target_reached', False)
        )
        reports.append(PerformanceReport(
            strategy_name=name,
            total_return=result.total_return,
            sharpe_ratio=result.sharpe_ratio,
            max_drawdown=result.max_drawdown,
            max_drawdown_duration=result.max_drawdown_duration,
            win_rate=result.win_rate,
            profit_factor=result.profit_factor,
            total_trades=result.total_trades,
            avg_trade_duration=result.avg_trade_duration,
            compliance_passed=compliance_passed,
            violations=[result.compliance_report.get('last_violation', 'None')]
        ))

    df = pd.DataFrame([{
        'Strategy': r.strategy_name,
        'Total Return': f"{r.total_return:.2%}",
        'Sharpe': f"{r.sharpe_ratio:.2f}",
        'Max DD': f"{r.max_drawdown:.2%}",
        'Max DD Duration': r.max_drawdown_duration,
        'Win Rate': f"{r.win_rate:.2%}",
        'Profit Factor': f"{r.profit_factor:.2f}",
        'Total Trades': r.total_trades,
        'Avg Duration (hrs)': f"{r.avg_trade_duration:.1f}",
        'Compliance': 'PASS' if r.compliance_passed else 'FAIL'
    } for r in reports])

    return df


def monte_carlo_simulation(result: BacktestResult, n_simulations: int = 1000) -> dict:
    if not result.trades:
        return {'mean_return': 0.0, 'std_return': 0.0, 'var_95': 0.0}

    returns = [t['pnl'] for t in result.trades]
    returns_array = np.array(returns)

    simulated_totals = []
    for _ in range(n_simulations):
        sampled = np.random.choice(returns_array, size=len(returns_array), replace=True)
        simulated_totals.append(np.sum(sampled))

    simulated_totals = np.array(simulated_totals)

    return {
        'mean_return': float(np.mean(simulated_totals)),
        'std_return': float(np.std(simulated_totals)),
        'var_95': float(np.percentile(simulated_totals, 5)),
        'cvar_95': float(np.mean(simulated_totals[simulated_totals <= np.percentile(simulated_totals, 5)])),
        'max_return': float(np.max(simulated_totals)),
        'min_return': float(np.min(simulated_totals)),
        'prob_of_loss': float(np.mean(simulated_totals < 0))
    }


def calculate_walk_forward_summary(wf_results: list[list[BacktestResult]], strategy_names: list[str],
                                    is_results: list[list[BacktestResult]] | None = None) -> pd.DataFrame:
    summary_data = []

    for strategy_name, oos_results in zip(strategy_names, wf_results):
        oos_sharpes = [r.sharpe_ratio for r in oos_results]
        oos_max_dds = [r.max_drawdown for r in oos_results]
        oos_win_rates = [r.win_rate for r in oos_results]
        oos_profit_factors = [r.profit_factor for r in oos_results]
        oos_total_returns = [r.total_return for r in oos_results]

        is_sharpes = []
        if is_results:
            idx = strategy_names.index(strategy_name)
            is_sharpes = [r.sharpe_ratio for r in is_results[idx]]

        avg_is_sharpe = float(np.mean(is_sharpes)) if is_sharpes else None
        avg_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else None

        if avg_is_sharpe and avg_oos_sharpe and avg_oos_sharpe != 0:
            sharpe_ratio = avg_is_sharpe / avg_oos_sharpe
        else:
            sharpe_ratio = None

        summary_data.append({
            'Strategy': strategy_name,
            'OOS Windows': len(oos_results),
            'Avg IS Sharpe': f"{avg_is_sharpe:.2f}" if avg_is_sharpe is not None else 'N/A',
            'Avg OOS Sharpe': f"{avg_oos_sharpe:.2f}" if avg_oos_sharpe is not None else 'N/A',
            'IS/OOS Sharpe Ratio': f"{sharpe_ratio:.2f}" if sharpe_ratio is not None else 'N/A',
            'Avg OOS Max DD': f"{np.mean(oos_max_dds):.2%}" if oos_max_dds else 'N/A',
            'Avg OOS Win Rate': f"{np.mean(oos_win_rates):.2%}" if oos_win_rates else 'N/A',
            'Avg OOS Profit Factor': f"{np.mean(oos_profit_factors):.2f}" if oos_profit_factors else 'N/A',
            'Avg OOS Return': f"{np.mean(oos_total_returns):.2%}" if oos_total_returns else 'N/A',
            'OOS Consistency (%)': f"{sum(1 for r in oos_total_returns if r > 0) / len(oos_total_returns) * 100:.0f}%" if oos_total_returns else 'N/A',
        })

    return pd.DataFrame(summary_data)
