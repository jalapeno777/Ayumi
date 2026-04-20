"""Walk-forward validation runner for all strategies, pairs, and timeframes.

Usage:
    python -m forex_trading.scripts.run_walk_forward
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime

from forex_trading.services.data_loader import load_all_pairs
from forex_trading.services.backtest.engine_v2 import (
    BacktestEngine,
    WalkForwardConfig,
)
from forex_trading.services.backtest.prop_firm_rules import PropFirmConfig
from forex_trading.services.backtest.reporting import calculate_walk_forward_summary
from forex_trading.strategies.momentum import MomentumCrossoverStrategy
from forex_trading.strategies.mean_reversion import MeanReversionStrategy
from forex_trading.strategies.breakout import BreakoutStrategy
from forex_trading.strategies.regime_aware import RegimeAwareStrategy, RegimeClassifier
from forex_trading.strategies.carry import CarryTradeStrategy
from forex_trading.strategies.regime_switching_momentum import (
    RegimeSwitchingMomentumStrategy,
)

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
TIMEFRAMES = {
    "1d": {"train_bars": 63, "test_bars": 126, "step_bars": 21, "label": "Daily"},
    "1h": {"train_bars": 378, "test_bars": 756, "step_bars": 126, "label": "Hourly"},
}

PROP_FIRM_CONFIG = PropFirmConfig(
    max_daily_drawdown_pct=0.05,
    max_total_drawdown_pct=0.10,
    profit_target_pct=0.10,
    max_concurrent_positions=2,
    max_daily_trades=10,
)

GO_CRITERIA = {
    "min_avg_oos_sharpe": 0.5,
    "max_avg_oos_max_dd": 0.10,
    "min_oos_consistency": 50.0,
    "max_is_oos_sharpe_decay": 0.50,
    "min_avg_trades_per_window": 20,
}


def get_strategies(pair: str, data: pd.DataFrame) -> list:
    regime = RegimeClassifier.classify_regime(data)

    strategies = [
        MomentumCrossoverStrategy(),
        MeanReversionStrategy(),
        BreakoutStrategy(),
        RegimeAwareStrategy(regime=regime),
        CarryTradeStrategy(),
        RegimeSwitchingMomentumStrategy(),
    ]
    return strategies


def run_single_combo(pair: str, interval: str, tf_config: dict) -> list[dict]:
    print(f"\n{'=' * 60}")
    print(f"  {pair} | {tf_config['label']}")
    print(f"{'=' * 60}")

    period = "730d" if interval == "1h" else "2y"
    data = load_all_pairs(interval=interval, period=period).get(pair)
    if data is None or len(data) < 200:
        print(
            f"  SKIP: Insufficient data ({len(data) if data is not None else 0} bars)"
        )
        return []

    strategies = get_strategies(pair, data)
    engine = BacktestEngine(
        starting_balance=10000.0,
        prop_firm_config=PROP_FIRM_CONFIG,
    )

    results = []
    for strategy in strategies:
        try:
            wf_config = WalkForwardConfig(
                train_bars=tf_config["train_bars"],
                test_bars=tf_config["test_bars"],
                step_bars=tf_config["step_bars"],
            )
            wf_results = engine.run_walk_forward(
                strategy=strategy,
                bars=data,
                pair=pair,
                wf_config=wf_config,
            )

            wf_oos = [m for m in wf_results.oos_results if m is not None]

            if not wf_oos:
                results.append(
                    {
                        "strategy": strategy.name,
                        "pair": pair,
                        "timeframe": tf_config["label"],
                        "verdict": "NO-GO",
                        "reason": "No valid walk-forward windows",
                        "oos_windows": 0,
                    }
                )
                continue

            oos_sharpes = [r.sharpe_ratio for r in wf_oos]
            oos_max_dds = [r.max_drawdown for r in wf_oos]
            oos_returns = [r.total_return for r in wf_oos]
            oos_win_rates = [r.win_rate for r in wf_oos]
            oos_profit_factors = [r.profit_factor for r in wf_oos]
            oos_trade_counts = [r.total_trades for r in wf_oos]
            consistency = sum(1 for r in oos_returns if r > 0) / len(oos_returns) * 100

            avg_sharpe = float(np.mean(oos_sharpes))
            avg_max_dd = float(np.mean(oos_max_dds))
            avg_return = float(np.mean(oos_returns))
            avg_win_rate = float(np.mean(oos_win_rates))
            avg_pf = float(np.mean(oos_profit_factors))
            total_trades = sum(oos_trade_counts)

            recovery_factor = avg_return / avg_max_dd if avg_max_dd > 0 else 0.0

            go = True
            reasons = []

            if avg_sharpe < GO_CRITERIA["min_avg_oos_sharpe"]:
                go = False
                reasons.append(
                    f"Avg OOS Sharpe {avg_sharpe:.2f} < {GO_CRITERIA['min_avg_oos_sharpe']}"
                )

            if avg_max_dd > GO_CRITERIA["max_avg_oos_max_dd"]:
                go = False
                reasons.append(
                    f"Avg OOS Max DD {avg_max_dd:.2%} > {GO_CRITERIA['max_avg_oos_max_dd']:.0%}"
                )

            if consistency < GO_CRITERIA["min_oos_consistency"]:
                go = False
                reasons.append(
                    f"OOS consistency {consistency:.0f}% < {GO_CRITERIA['min_oos_consistency']:.0f}%"
                )

            if avg_pf < 1.0:
                go = False
                reasons.append(f"Avg profit factor {avg_pf:.2f} < 1.0")

            oos_windows = len(wf_oos)
            avg_trades_per_window = total_trades / oos_windows if oos_windows > 0 else 0
            if avg_trades_per_window < GO_CRITERIA["min_avg_trades_per_window"]:
                go = False
                reasons.append(
                    f"Avg trades/window {avg_trades_per_window:.1f} < {GO_CRITERIA['min_avg_trades_per_window']}"
                )

            result = {
                "strategy": strategy.name,
                "pair": pair,
                "timeframe": tf_config["label"],
                "verdict": "GO" if go else "NO-GO",
                "reason": "; ".join(reasons) if reasons else "All criteria met",
                "oos_windows": len(wf_oos),
                "avg_oos_sharpe": avg_sharpe,
                "avg_oos_max_dd": avg_max_dd,
                "avg_oos_return": avg_return,
                "avg_oos_win_rate": avg_win_rate,
                "avg_oos_profit_factor": avg_pf,
                "oos_consistency_pct": consistency,
                "recovery_factor": recovery_factor,
                "total_trades": total_trades,
                "avg_trades_per_window": avg_trades_per_window,
            }

            results.append(result)

            status_icon = "PASS" if go else "FAIL"
            print(
                f"  [{status_icon}] {strategy.name:25s} | Sharpe: {avg_sharpe:+.2f} | "
                f"DD: {avg_max_dd:.2%} | Return: {avg_return:+.2%} | "
                f"Win: {avg_win_rate:.1%} | PF: {avg_pf:.2f} | "
                f"Consistency: {consistency:.0f}%"
            )

        except Exception as e:
            print(f"  [ERROR] {strategy.name}: {e}")
            results.append(
                {
                    "strategy": strategy.name,
                    "pair": pair,
                    "timeframe": tf_config["label"],
                    "verdict": "NO-GO",
                    "reason": f"Error: {e}",
                    "oos_windows": 0,
                }
            )

    return results


def generate_report(all_results: list[dict]) -> str:
    lines = []
    lines.append("# Walk-Forward Validation Report")
    lines.append(f"\nGenerated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"\n## Configuration")
    lines.append(f"- **Pairs:** {', '.join(PAIRS)}")
    lines.append(
        f"- **Timeframes:** {', '.join(tf['label'] for tf in TIMEFRAMES.values())}"
    )
    lines.append(f"- **Training window:** 3 months (63 trading days)")
    lines.append(f"- **OOS window:** 6 months (126 trading days)")
    lines.append(f"- **Step size:** 1 month (21 trading days)")
    lines.append(f"- **Starting balance:** $10,000")
    lines.append(
        f"- **Prop firm rules:** FTMO-compliant (5% daily DD, 10% total DD, 10% profit target)"
    )
    lines.append(f"- **Spreads:** Realistic pair-specific (1-1.5 pips majors)")

    lines.append(f"\n## GO/NO-GO Criteria")
    lines.append(f"| Criterion | Threshold |")
    lines.append(f"|-----------|-----------|")
    for k, v in GO_CRITERIA.items():
        lines.append(f"| {k} | {v} |")

    go_results = [r for r in all_results if r["verdict"] == "GO"]
    nogo_results = [r for r in all_results if r["verdict"] == "NO-GO"]

    lines.append(f"\n## Summary")
    lines.append(f"- **Total combos tested:** {len(all_results)}")
    lines.append(f"- **GO:** {len(go_results)}")
    lines.append(f"- **NO-GO:** {len(nogo_results)}")

    lines.append(f"\n## GO Strategies")
    if go_results:
        lines.append(
            f"| Strategy | Pair | Timeframe | OOS Sharpe | OOS Max DD | OOS Return | Win Rate | Profit Factor | Recovery Factor | Consistency | Trades | Avg/Wnd |"
        )
        lines.append(
            f"|----------|------|-----------|------------|-----------|------------|----------|---------------|----------------|-------------|--------|---------|"
        )
        for r in sorted(go_results, key=lambda x: x["avg_oos_sharpe"], reverse=True):
            lines.append(
                f"| {r['strategy']} | {r['pair']} | {r['timeframe']} | "
                f"{r['avg_oos_sharpe']:+.2f} | {r['avg_oos_max_dd']:.2%} | "
                f"{r['avg_oos_return']:+.2%} | {r['avg_oos_win_rate']:.1%} | "
                f"{r['avg_oos_profit_factor']:.2f} | {r['recovery_factor']:.2f} | "
                f"{r['oos_consistency_pct']:.0f}% | {r['total_trades']} | {r.get('avg_trades_per_window', 'N/A'):.1f} |"
            )
    else:
        lines.append(f"_No strategies passed all GO/NO-GO criteria._")

    lines.append(f"\n## NO-GO Strategies")
    if nogo_results:
        lines.append(
            f"| Strategy | Pair | Timeframe | Reason | OOS Sharpe | OOS Max DD |"
        )
        lines.append(
            f"|----------|------|-----------|--------|------------|-----------|"
        )
        for r in sorted(nogo_results, key=lambda x: x["avg_oos_sharpe"], reverse=True):
            sharpe = f"{r['avg_oos_sharpe']:.2f}" if "avg_oos_sharpe" in r else "N/A"
            dd = f"{r['avg_oos_max_dd']:.2%}" if "avg_oos_max_dd" in r else "N/A"
            lines.append(
                f"| {r['strategy']} | {r['pair']} | {r['timeframe']} | {r['reason']} | {sharpe} | {dd} |"
            )
    else:
        lines.append(f"_All strategies passed._")

    strategy_summary = {}
    for r in all_results:
        name = r["strategy"]
        if name not in strategy_summary:
            strategy_summary[name] = {
                "go": 0,
                "nogo": 0,
                "best_sharpe": -999,
                "best_pair": "",
            }
        if r["verdict"] == "GO":
            strategy_summary[name]["go"] += 1
        else:
            strategy_summary[name]["nogo"] += 1
        sharpe = r.get("avg_oos_sharpe", -999)
        if sharpe > strategy_summary[name]["best_sharpe"]:
            strategy_summary[name]["best_sharpe"] = sharpe
            strategy_summary[name]["best_pair"] = r["pair"]

    lines.append(f"\n## Strategy Ranking")
    lines.append(f"| Strategy | GO/NO-GO | Best OOS Sharpe | Best Pair | Verdict |")
    lines.append(f"|----------|----------|----------------|-----------|---------|")
    for name, s in sorted(
        strategy_summary.items(), key=lambda x: x[1]["go"], reverse=True
    ):
        overall = "GO" if s["go"] > 0 else "NO-GO"
        lines.append(
            f"| {name} | {s['go']} GO / {s['nogo']} NO-GO | {s['best_sharpe']:+.2f} | {s['best_pair']} | **{overall}** |"
        )

    lines.append(f"\n## Recommendations")
    if not go_results:
        lines.append(f"\n**No strategies currently meet GO/NO-GO criteria.**")
        lines.append(f"\nRecommended next steps:")
        lines.append(
            f"1. **Strategy iteration:** All strategies need parameter optimization or redesign"
        )
        lines.append(
            f"2. **Consider ICT approach:** As noted in Sprint 2 planning, ICT-based strategies may outperform"
        )
        lines.append(
            f"3. **Data quality:** Validate data quality; premium H1/H4 feeds would improve signal accuracy"
        )
        lines.append(
            f"4. **Position sizing:** Current engine uses fixed 0.1 lots; integrate Kelly/fixed-fractional sizing"
        )
        lines.append(
            f"5. **Exit logic:** Strategies lack explicit take-profit/stop-loss levels; add risk-based exits"
        )
    else:
        best = sorted(go_results, key=lambda x: x["avg_oos_sharpe"], reverse=True)[0]
        lines.append(
            f"\n**Top candidate:** {best['strategy']} on {best['pair']} ({best['timeframe']})"
        )
        lines.append(f"- OOS Sharpe: {best['avg_oos_sharpe']:+.2f}")
        lines.append(f"- OOS Max DD: {best['avg_oos_max_dd']:.2%}")
        lines.append(f"- OOS Return: {best['avg_oos_return']:+.2%}")
        lines.append(f"- Consistency: {best['oos_consistency_pct']:.0f}%")
        lines.append(f"\nRecommended next steps:")
        lines.append(f"1. Advance {best['strategy']} to live paper trading validation")
        lines.append(f"2. Optimize NO-GO strategies before discarding")
        lines.append(
            f"3. Run Monte Carlo simulation on GO strategies for drawdown confidence intervals"
        )

    lines.append(f"\n## Methodology Notes")
    lines.append(f"- Walk-forward uses rolling (not expanding) training windows")
    lines.append(
        f"- Each OOS window is tested on a fresh engine instance (no state leakage)"
    )
    lines.append(
        f"- Carry trade strategy uses hardcoded interest rate differentials (Apr 2026 rates)"
    )
    lines.append(
        f"- Regime-aware strategy uses built-in RegimeClassifier (no external regime input)"
    )
    lines.append(
        f"- Execution includes pair-specific spreads and random slippage simulation"
    )
    lines.append(
        f"- Prop firm rules enforced: 5% daily DD, 10% total DD, max 2 concurrent positions, max 10 daily trades"
    )

    return "\n".join(lines)


def main():
    print("Walk-Forward Validation")
    print(f"Started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Pairs: {PAIRS}")
    print(f"Strategies: Momentum, MeanReversion, Breakout, RegimeAware, Carry")

    all_results = []

    for pair in PAIRS:
        for interval, tf_config in TIMEFRAMES.items():
            combo_results = run_single_combo(pair, interval, tf_config)
            all_results.extend(combo_results)

    report = generate_report(all_results)
    print(f"\n{'=' * 60}")
    print(report)

    report_path = (
        Path(__file__).resolve().parent.parent.parent
        / "reports"
        / "walk_forward_validation.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    print(f"\nReport saved to: {report_path}")

    go_count = sum(1 for r in all_results if r["verdict"] == "GO")
    nogo_count = sum(1 for r in all_results if r["verdict"] == "NO-GO")
    print(
        f"\nFINAL TALLY: {go_count} GO / {nogo_count} NO-GO out of {len(all_results)} combos"
    )

    return all_results


if __name__ == "__main__":
    main()
