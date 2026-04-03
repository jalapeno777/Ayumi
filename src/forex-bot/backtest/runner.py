#!/usr/bin/env python3
"""
Baseline Strategy Backtest Runner

Runs backtests for all 5 baseline strategies:
- MA Crossover
- Bollinger Band Mean Reversion
- RSI Divergence
- S/R Breakout
- Momentum ROC

Usage:
    python -m backtest.runner [data_file] [timeframe]

Examples:
    python -m backtest.runner                          # Use EURUSD_H1.csv default
    python -m backtest.runner /path/to/data.csv H1    # Custom data and timeframe
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest import (
    BacktestConfig,
    CsvDataLoader,
    MACrossStrategy,
    BBStrategy,
    RSIStrategy,
    SRBreakoutStrategy,
    ROCMStrategy,
    MultiStrategyConfig,
    MultiStrategyBacktestEngine,
    AmalgamationConfig,
    AmalgamatedBacktestEngine,
    VotingMethod,
    ConfidenceMethod,
    SessionType,
    EnhancedBacktestEngine,
    TradeManagementConfig,
)


DEFAULT_DATA_FILE = "/home/TacoPants/projects/Ayumi/data/forex/historical/EURUSD_H1.csv"


def run_individual_backtests(bars, config):
    strategies = [
        MACrossStrategy(fast_period=5, slow_period=13, atr_multiplier=2.0),
        BBStrategy(period=20, std_dev=2.0),
        RSIStrategy(period=14, oversold=35, overbought=65),
        SRBreakoutStrategy(lookback=50, confirmation_bars=1, breakout_threshold=0.0001),
        ROCMStrategy(period=12, roc_threshold=0.3),
    ]

    engine = MultiStrategyBacktestEngine(config, strategies)
    results = engine.run_all_strategies(bars)

    print("\n" + "=" * 70)
    print("          INDIVIDUAL BASELINE STRATEGY BACKTEST RESULTS")
    print("=" * 70)

    for name, result in results.items():
        m = result.metrics
        print(f"\n### {name}")
        print(f"   Trades:        {m.total_trades}")
        print(f"   Win Rate:      {m.win_rate:.1f}%")
        print(f"   P&L:          ${m.total_pnl:.2f} ({m.total_pnl_pct:.2f}%)")
        print(f"   Profit Factor: {m.profit_factor:.2f}")
        print(f"   Sharpe:        {m.sharpe_ratio:.2f}")
        print(f"   Max DD:        {m.max_drawdown_pct:.2f}%")
        print(f"   Expectancy:   ${m.expectancy:.2f}")

    return results


def run_combined_backtest(bars, config):
    strategies = [
        MACrossStrategy(),
        BBStrategy(),
        ROCMStrategy()
    ]

    multi_config = MultiStrategyConfig(
        min_combined_confidence=0.50
    )

    engine = MultiStrategyBacktestEngine(config, strategies, multi_config)
    individual, combined = engine.run_combined_strategies(strategies, bars)

    print("\n" + "=" * 70)
    print("          COMBINED STRATEGY BACKTEST RESULTS (MA + BB + ROC)")
    print("=" * 70)

    m = combined
    print(f"\n### Combined (MA Crossover + Bollinger Band + ROC Momentum)")
    print(f"   Trades:        {m.total_trades}")
    print(f"   Win Rate:      {m.win_rate:.1f}%")
    print(f"   P&L:          ${m.total_pnl:.2f} ({m.total_pnl_pct:.2f}%)")
    print(f"   Profit Factor: {m.profit_factor:.2f}")
    print(f"   Sharpe:        {m.sharpe_ratio:.2f}")
    print(f"   Max DD:        {m.max_drawdown_pct:.2f}%")
    print(f"   Expectancy:   ${m.expectancy:.2f}")

    return individual, combined


def analyze_walk_forward(bars, config, train_ratio=0.7):
    split_idx = int(len(bars) * train_ratio)
    train_bars = bars[:split_idx]
    test_bars = bars[split_idx:]

    print("\n" + "=" * 70)
    print("          WALK-FORWARD VALIDATION")
    print("=" * 70)
    print(f"\nTraining period: {train_bars[0].time} to {train_bars[-1].time}")
    print(f"Testing period:   {test_bars[0].time} to {test_bars[-1].time}")
    print(f"Train bars:      {len(train_bars)}")
    print(f"Test bars:       {len(test_bars)}")

    strategies = [
        MACrossStrategy(),
        BBStrategy(),
        RSIStrategy(),
        SRBreakoutStrategy(),
        ROCMStrategy(),
    ]

    engine = MultiStrategyBacktestEngine(config, strategies)

    print("\n### Training Period Results")
    train_results = engine.run_all_strategies(train_bars)
    for name, result in train_results.items():
        m = result.metrics
        print(f"   {name}: Trades={m.total_trades}, WinRate={m.win_rate:.1f}%, PF={m.profit_factor:.2f}, P&L=${m.total_pnl:.2f}")

    print("\n### Testing Period Results")
    test_results = engine.run_all_strategies(test_bars)
    for name, result in test_results.items():
        m = result.metrics
        print(f"   {name}: Trades={m.total_trades}, WinRate={m.win_rate:.1f}%, PF={m.profit_factor:.2f}, P&L=${m.total_pnl:.2f}")

    return train_results, test_results


def run_amalgamation_backtest(bars, config):
    strategies = [
        MACrossStrategy(fast_period=5, slow_period=13, atr_multiplier=2.0),
        BBStrategy(period=20, std_dev=2.0),
        RSIStrategy(period=14, oversold=35, overbought=65),
        SRBreakoutStrategy(lookback=50, confirmation_bars=1, breakout_threshold=0.0001),
        ROCMStrategy(period=12, roc_threshold=0.3),
    ]

    configs = [
        ("Weighted+Confluence", AmalgamationConfig(
            voting_method=VotingMethod.WEIGHTED,
            confidence_method=ConfidenceMethod.CONFLUENCE,
            min_combined_confidence=0.45,
            min_confluence=2,
            confluence_bonus=0.10,
            session_filter_enabled=True,
        )),
        ("Weighted+Mean", AmalgamationConfig(
            voting_method=VotingMethod.WEIGHTED,
            confidence_method=ConfidenceMethod.MEAN,
            min_combined_confidence=0.45,
            min_confluence=2,
            session_filter_enabled=True,
        )),
        ("Confluence+Confluence", AmalgamationConfig(
            voting_method=VotingMethod.CONFLUENCE,
            confidence_method=ConfidenceMethod.CONFLUENCE,
            min_combined_confidence=0.45,
            min_confluence=3,
            confluence_bonus=0.15,
            session_filter_enabled=True,
        )),
        ("NoSessionFilter", AmalgamationConfig(
            voting_method=VotingMethod.WEIGHTED,
            confidence_method=ConfidenceMethod.CONFLUENCE,
            min_combined_confidence=0.40,
            min_confluence=2,
            confluence_bonus=0.10,
            session_filter_enabled=False,
        )),
    ]

    print("\n" + "=" * 70)
    print("       AMALGAMATION ENGINE BACKTEST RESULTS")
    print("=" * 70)

    for label, amal_config in configs:
        engine = AmalgamatedBacktestEngine(config, strategies, amal_config)
        metrics = engine.run(bars)
        print(f"\n### Config: {label}")
        print(f"   Trades:        {metrics.total_trades}")
        print(f"   Win Rate:      {metrics.win_rate:.1f}%")
        print(f"   P&L:          ${metrics.total_pnl:.2f} ({metrics.total_pnl_pct:.2f}%)")
        print(f"   Profit Factor: {metrics.profit_factor:.2f}")
        print(f"   Sharpe:        {metrics.sharpe_ratio:.2f}")
        print(f"   Max DD:        {metrics.max_drawdown_pct:.2f}%")
        print(f"   Expectancy:   ${metrics.expectancy:.2f}")
        print(f"   Rejected:      {metrics.rejected_signals}")

    return configs


def run_enhanced_ab_comparison(bars, config):
    strategies = [
        MACrossStrategy(fast_period=5, slow_period=13, atr_multiplier=2.0),
        BBStrategy(period=20, std_dev=2.0),
        RSIStrategy(period=14, oversold=35, overbought=65),
        SRBreakoutStrategy(lookback=50, confirmation_bars=1, breakout_threshold=0.0001),
        ROCMStrategy(period=12, roc_threshold=0.3),
    ]

    tm_configs = [
        ("Conservative", TradeManagementConfig.conservative()),
        ("Aggressive", TradeManagementConfig.aggressive()),
        ("FTMO", TradeManagementConfig.ftmo()),
    ]

    print("\n" + "=" * 70)
    print("       A/B BACKTEST: BASELINE vs ENHANCED TRADE MANAGEMENT")
    print("=" * 70)

    baseline_engine = MultiStrategyBacktestEngine(config, strategies)
    baseline_results = baseline_engine.run_all_strategies(bars)

    for label, tm_config in tm_configs:
        print(f"\n{'─' * 70}")
        print(f"  Enhanced Config: {label}")
        print(f"{'─' * 70}")

        enhanced_engine = EnhancedBacktestEngine(config, strategies, tm_config)
        enhanced_results = enhanced_engine.run_all_strategies(bars)

        print(f"\n  {'Strategy':<30} {'Metric':<18} {'Baseline':>10} {'Enhanced':>10} {'Delta':>10}")
        print(f"  {'─' * 78}")

        for strategy in strategies:
            name = strategy.name
            if name not in baseline_results or name not in enhanced_results:
                continue

            bm = baseline_results[name].metrics
            em = enhanced_results[name].metrics

            comparisons = [
                ("Trades", f"{bm.total_trades}", f"{em.total_trades}",
                 f"{em.total_trades - bm.total_trades:+d}"),
                ("Win Rate %", f"{bm.win_rate:.1f}", f"{em.win_rate:.1f}",
                 f"{em.win_rate - bm.win_rate:+.1f}"),
                ("Profit Factor", f"{bm.profit_factor:.2f}", f"{em.profit_factor:.2f}",
                 f"{em.profit_factor - bm.profit_factor:+.2f}"),
                ("P&L $", f"{bm.total_pnl:.2f}", f"{em.total_pnl:.2f}",
                 f"{em.total_pnl - bm.total_pnl:+.2f}"),
                ("Sharpe", f"{bm.sharpe_ratio:.2f}", f"{em.sharpe_ratio:.2f}",
                 f"{em.sharpe_ratio - bm.sharpe_ratio:+.2f}"),
                ("Max DD %", f"{bm.max_drawdown_pct:.2f}", f"{em.max_drawdown_pct:.2f}",
                 f"{em.max_drawdown_pct - bm.max_drawdown_pct:+.2f}"),
                ("Expectancy $", f"{bm.expectancy:.2f}", f"{em.expectancy:.2f}",
                 f"{em.expectancy - bm.expectancy:+.2f}"),
                ("Avg R:R", f"{bm.avg_risk_reward:.2f}", f"{em.avg_risk_reward:.2f}",
                 f"{em.avg_risk_reward - bm.avg_risk_reward:+.2f}"),
            ]

            for metric_name, b_val, e_val, delta in comparisons:
                print(f"  {name:<30} {metric_name:<18} {b_val:>10} {e_val:>10} {delta:>10}")

    return tm_configs


def main():
    data_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATA_FILE
    timeframe = sys.argv[2] if len(sys.argv) > 2 else "H1"

    if not os.path.exists(data_file):
        print(f"Error: Data file not found: {data_file}")
        sys.exit(1)

    print(f"\nLoading data from: {data_file}")
    loader = CsvDataLoader()
    bars = loader.load(data_file)
    print(f"Loaded {len(bars)} bars")
    print(f"Period: {bars[0].time} to {bars[-1].time}")

    inferred_tf = loader.infer_timeframe(bars)
    print(f"Inferred timeframe: H1 (approx {inferred_tf.minutes} min)")

    config = BacktestConfig(
        starting_balance=10000.0,
        risk_per_trade_pct=0.01,
        max_daily_drawdown_pct=0.02,
        max_total_drawdown_pct=0.05,
        spread_pips=0.5,
        commission_per_lot=3.5,
        leverage=100,
        min_confidence=0.45,
        min_bars_before_signal=30,
        max_open_trades=1
    )

    run_individual_backtests(bars, config)

    run_combined_backtest(bars, config)

    run_amalgamation_backtest(bars, config)

    run_enhanced_ab_comparison(bars, config)

    analyze_walk_forward(bars, config)

    print("\n" + "=" * 70)
    print("                    BACKTEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()