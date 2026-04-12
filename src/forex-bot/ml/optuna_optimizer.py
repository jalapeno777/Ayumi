"""§10 — Optuna-powered hyperparameter optimizer for TTSStrategy.

Uses Bayesian optimization (TPE sampler) over:
  - All positive boost weights
  - All negative boost weights and thresholds
  - Base confidence threshold
  - Per-symbol / per-timeframe

Saves completed trials to avoid re-running. Generates a full report
with per-factor importance and best config per symbol.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import optuna
import pandas as pd
from optuna.samplers import TPESampler

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from backtest.engine import Bar, TradeOutcome, get_spread_for_pair, BacktestConfig
from backtest.multi_strategy_engine import MultiStrategyBacktestEngine
from backtest.strategies import TTSStrategy
import backtest.strategies.tts_strategy as tts_module

# ── Paths ────────────────────────────────────────────────────────────────────

RESULTS_DIR = PROJECT_ROOT / "reports" / "optuna_optimizer"
STUDIES_DIR = PROJECT_ROOT / "reports" / "optuna_studies"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
STUDIES_DIR.mkdir(parents=True, exist_ok=True)

# ── Default test config ─────────────────────────────────────────────────────

DEFAULT_BT_CONFIG = dict(
    starting_balance=10_000,
    commission_per_lot=3.5,
    min_confidence=0.20,
    min_quality_score=0.25,
)

# ── All tunable boost weights ───────────────────────────────────────────────
# Format: (constant_name, default_value, min, max)

POSITIVE_BOOST_PARAMS = [
    ("RSI_DIVERGENCE_BOOST",      0.10,  0.00,  0.15),
    ("HTF_TREND_ALIGNED_BOOST",   0.10,  0.00,  0.15),
    ("SVC_AT_PEAK_BOOST",         0.10,  0.00,  0.15),
    ("CONSOLIDATION_BOOST",       0.05,  0.00,  0.10),
    ("ASIA_GAP_FAVORABLE_BOOST",  0.05,  0.00,  0.10),
    ("ILOD_IHOD_AT_BOUNDARY_BOOST", 0.05, 0.00,  0.10),
    ("VWAP_REJECTION_BOOST",      0.10,  0.00,  0.15),
    ("KILL_ZONE_ACTIVE_BOOST",   -0.05, -0.10,  0.00),
    ("MFI_BOOST",                 0.08,  0.00,  0.15),
    ("EMA_CROSS_BOOST",           0.08,  0.00,  0.15),
    ("BB_CONF_BOOST",             0.07,  0.00,  0.15),
    ("ADX_BOOST",                 0.06,  0.00,  0.12),
    ("VOLUME_SPIKE_BOOST",        0.05,  0.00,  0.10),
    ("VWAP_DISTANCE_BOOST",       0.05,  0.00,  0.10),
    ("RSI_EXTREME_BOOST",         0.06,  0.00,  0.12),
    ("EMA_EXTENSION_BOOST",       0.07,  0.00,  0.15),
    ("EMA_CLUSTER_BOOST",         0.06,  0.00,  0.12),
    ("HTF_200EMA_BOOST",          0.10,  0.00,  0.15),
    ("HTF_200EMA_PENALTY",        0.08,  0.00,  0.15),
]

NEGATIVE_BOOST_PARAMS = [
    ("RSI_OVERBOUGHT_NC",        -0.05, -0.10, -0.01),
    ("RSI_OVERSOLD_NC",          -0.05, -0.10, -0.01),
    ("HTF_COUNTER_TREND_NC",     -0.08, -0.15, -0.01),
    ("LATE_KILL_ZONE_NC",        -0.06, -0.12, -0.01),
    ("VOLUME_DIVERGENCE_NC",      -0.05, -0.10, -0.01),
    ("BB_SQUEEZE_NC",            -0.04, -0.08, -0.01),
    ("ADX_EXHAUSTION_NC",        -0.05, -0.10, -0.01),
    ("VWAP_EXTREME_DISTANCE_NC", -0.04, -0.08, -0.01),
    ("ASIA_RANGE_WIDE_NC",       -0.05, -0.10, -0.01),
    ("MFI_OVERBOUGHT_NC",        -0.04, -0.08, -0.01),
    ("MFI_OVERSOLD_NC",          -0.04, -0.08, -0.01),
]

# All patchable constants in one flat list
PATCHABLE_CONSTANTS = (
    POSITIVE_BOOST_PARAMS
    + NEGATIVE_BOOST_PARAMS
    + [("MW_BASE_CONFIDENCE", 0.30, 0.15, 0.50)]
)

# negative_weight scales all negative boosts (0=off, 1=full, 1.5=amplified)
NEGATIVE_WEIGHT_RANGE = (0.0, 1.5)
BASE_CONFIDENCE_RANGE = (0.20, 0.45)
MIN_TRADES_FOR_VALID_TRIAL = 15

# ── Data loading ────────────────────────────────────────────────────────────

def load_bars(pair: str, tf: str = "M15") -> list[Bar]:
    data_dir = PROJECT_ROOT / "data" / "forex" / "historical"
    for suffix in (f"{pair}_{tf}_2026.csv", f"{pair}_{tf}.csv"):
        csv_path = data_dir / suffix
        if csv_path.exists():
            break
    else:
        raise FileNotFoundError(f"No data for {pair}/{tf}")

    df = pd.read_csv(csv_path)
    df["time"] = pd.to_datetime(df["Date"])
    df = df.sort_values("time").reset_index(drop=True)
    return [
        Bar(
            time=row["time"].to_pydatetime(),
            open=row["Open"],
            high=row["High"],
            low=row["Low"],
            close=row["Close"],
            volume=row.get("Volume", 0),
        )
        for _, row in df.iterrows()
    ]


# ── Constants patching ──────────────────────────────────────────────────────

def _apply_trial_params(trial: optuna.Trial) -> dict[str, float]:
    """Apply all parameters from a trial to the tts_module constants."""
    applied = {}
    for name, default, lo, hi in PATCHABLE_CONSTANTS:
        value = trial.suggest_float(name, lo, hi, step=0.01)
        setattr(tts_module, name, value)
        applied[name] = value

    # negative_weight from its own range
    neg_weight = trial.suggest_float("negative_weight", *NEGATIVE_WEIGHT_RANGE, step=0.1)
    setattr(tts_module, "NEGATIVE_WEIGHT", neg_weight)
    applied["negative_weight"] = neg_weight

    return applied


def restore_defaults() -> None:
    for name, default, _, _ in PATCHABLE_CONSTANTS:
        setattr(tts_module, name, default)
    setattr(tts_module, "MW_BASE_CONFIDENCE", 0.30)
    setattr(tts_module, "NEGATIVE_WEIGHT", 1.0)


# ── Metrics ─────────────────────────────────────────────────────────────────

def trades_to_metrics(trades: list, starting_balance: float = 10_000) -> dict:
    if not trades:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "total_pnl": 0.0,
            "profit_factor": 0.0, "max_drawdown_pct": 0.0,
            "avg_win": 0.0, "avg_loss": 0.01,
            "t4_trades": 0, "t5_trades": 0,
            "skipped": "no_trades",
        }

    wins = [t for t in trades if t.outcome == TradeOutcome.WIN]
    losses = [t for t in trades if t.outcome == TradeOutcome.LOSS]
    n_wins = len(wins)
    n_losses = len(losses)
    total = len(trades)

    win_pnl = sum(t.profit_loss for t in wins)
    loss_pnl = sum(t.profit_loss for t in losses)
    avg_win = win_pnl / n_wins if n_wins else 0.0
    avg_loss = abs(loss_pnl / n_losses) if n_losses else 0.01

    balance = starting_balance
    peak = balance
    max_dd_pct = 0.0
    for t in trades:
        balance += t.profit_loss
        if balance > peak:
            peak = balance
        dd_pct = (peak - balance) / peak * 100 if peak > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    t4 = sum(1 for t in trades if getattr(t, "confidence_score", 0) >= 0.40)
    t5 = sum(1 for t in trades if getattr(t, "confidence_score", 0) >= 0.50)

    return {
        "total_trades": total,
        "wins": n_wins,
        "losses": n_losses,
        "win_rate": n_wins / total if total else 0.0,
        "total_pnl": sum(t.profit_loss for t in trades),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": win_pnl / abs(loss_pnl) if loss_pnl != 0 else float("inf"),
        "max_drawdown_pct": max_dd_pct,
        "t4_trades": t4,
        "t5_trades": t5,
        "skipped": None,
    }


# ── Objective function ──────────────────────────────────────────────────────

def build_objective(pair: str, tf: str, bars: list[Bar]) -> callable:
    spread = get_spread_for_pair(pair)

    def objective(trial: optuna.Trial) -> float:
        applied = _apply_trial_params(trial)

        try:
            bt_config = BacktestConfig(
                starting_balance=DEFAULT_BT_CONFIG["starting_balance"],
                spread_pips=spread,
                commission_per_lot=DEFAULT_BT_CONFIG["commission_per_lot"],
                pair=pair,
                min_confidence=DEFAULT_BT_CONFIG["min_confidence"],
            )
            strategy = TTSStrategy(
                symbol=pair,
                min_confidence=DEFAULT_BT_CONFIG["min_confidence"],
                min_quality_score=DEFAULT_BT_CONFIG["min_quality_score"],
            )
            engine = MultiStrategyBacktestEngine(bt_config, [strategy])
            result = engine.run_all_strategies(bars)
            trades = result[strategy.name].metrics.trades
        except Exception as e:
            restore_defaults()
            raise optuna.TrialPruned(f"Backtest error: {e}")
        finally:
            restore_defaults()

        metrics = trades_to_metrics(trades, DEFAULT_BT_CONFIG["starting_balance"])

        if metrics["total_trades"] < MIN_TRADES_FOR_VALID_TRIAL:
            raise optuna.TrialPruned(
                f"Only {metrics['total_trades']} trades "
                f"(need {MIN_TRADES_FOR_VALID_TRIAL})"
            )

        wr = metrics["win_rate"]
        pf = metrics["profit_factor"]
        pnl = metrics["total_pnl"]
        dd = max(metrics["max_drawdown_pct"], 0.1)

        if wr < 0.35:
            score = pnl * 0.3
        elif wr < 0.40:
            score = pnl * 0.7
        else:
            score = pnl * wr / (1 + dd / 100)

        if wr < 0.30 and pf < 0.80:
            raise optuna.TrialPruned(f"Poor metrics: WR={wr:.1%}, PF={pf:.2f}")

        return score

    return objective


# ── Study runner ─────────────────────────────────────────────────────────────

def run_study(
    pair: str,
    tf: str = "M15",
    n_trials: int = 100,
    timeout: Optional[int] = None,
    n_jobs: int = 1,
    seed: int = 42,
) -> dict:
    """Run Optuna optimization for one pair.

    Resumes existing study if already run — safe to interrupt and restart.
    """
    study_path = STUDIES_DIR / f"{pair}_{tf}_study.db"
    study_name = f"{pair}_{tf}_optuna"

    if study_path.exists():
        study = optuna.load_study(
            study_name=study_name,
            storage=f"sqlite:///{study_path}",
            sampler=TPESampler(seed=seed),
        )
        existing = len(study.trials)
        print(f"\n  ↪ Resuming existing study for {pair}/{tf} ({existing} trials done)")
    else:
        study = optuna.create_study(
            study_name=study_name,
            storage=f"sqlite:///{study_path}",
            sampler=TPESampler(seed=seed),
            direction="maximize",
        )
        print(f"\n  ↪ Created new study for {pair}/{tf}")

    bars = load_bars(pair, tf)
    print(f"  Loaded {len(bars)} bars for {pair}/{tf}")

    objective = build_objective(pair, tf, bars)

    print(f"  Running up to {n_trials} trials...")
    study.optimize(objective, n_trials=n_trials, timeout=timeout,
                   n_jobs=n_jobs, show_progress_bar=True)

    best = study.best_trial
    n_completed = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
    print(f"\n  ★ Best trial #{best.number} (of {n_completed} complete): score={best.value:.2f}")
    print(f"    WR: {best.user_attrs.get('wr', 'N/A')} | PF: {best.user_attrs.get('pf', 'N/A')} "
          f"| P&L: ${best.user_attrs.get('pnl', 0):.2f} | Trades: {best.user_attrs.get('trades', 0)}")

    # Re-run best params for full metrics
    print("  Re-running best params for full metrics...")
    restore_defaults()
    for name, val in best.params.items():
        setattr(tts_module, name, val)
    setattr(tts_module, "NEGATIVE_WEIGHT", best.params.get("negative_weight", 1.0))

    try:
        bt_config = BacktestConfig(
            starting_balance=DEFAULT_BT_CONFIG["starting_balance"],
            spread_pips=spread,
            commission_per_lot=DEFAULT_BT_CONFIG["commission_per_lot"],
            pair=pair,
            min_confidence=DEFAULT_BT_CONFIG["min_confidence"],
        )
        strategy = TTSStrategy(
            symbol=pair,
            min_confidence=DEFAULT_BT_CONFIG["min_confidence"],
            min_quality_score=DEFAULT_BT_CONFIG["min_quality_score"],
        )
        engine = MultiStrategyBacktestEngine(bt_config, [strategy])
        result = engine.run_all_strategies(bars)
        best_trades = result[strategy.name].metrics.trades
        best_metrics = trades_to_metrics(best_trades, DEFAULT_BT_CONFIG["starting_balance"])
    finally:
        restore_defaults()

    result_obj = {
        "pair": pair,
        "timeframe": tf,
        "n_trials_total": len(study.trials),
        "n_trials_complete": n_completed,
        "best_trial_number": best.number,
        "best_score": best.value,
        "best_params": best.params,
        "best_metrics": best_metrics,
        "completed_at": datetime.now().isoformat(),
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    result_path = RESULTS_DIR / f"{pair}_{tf}_{ts}.json"
    with open(result_path, "w") as f:
        json.dump(result_obj, f, indent=2, default=str)
    print(f"    Results saved to {result_path}")

    return result_obj


# ── Grid runner (fast exhaustive search baseline) ─────────────────────────────

def run_grid(
    pair: str,
    tf: str = "M15",
    base_values: list[float] = [0.20, 0.25, 0.30, 0.35, 0.40],
    neg_weight_values: list[float] = [0.0, 0.5, 1.0, 1.5],
) -> dict:
    """Exhaustive grid search over base_confidence × negative_weight.

    Fast complement to Optuna — useful as a baseline and for filling in
    the coarse search space before fine-tuning with Optuna.
    """
    bars = load_bars(pair, tf)
    spread = get_spread_for_pair(pair)

    results = []
    for base in base_values:
        for neg_w in neg_weight_values:
            setattr(tts_module, "MW_BASE_CONFIDENCE", base)
            setattr(tts_module, "NEGATIVE_WEIGHT", neg_w)

            try:
                bt_config = BacktestConfig(
                    starting_balance=DEFAULT_BT_CONFIG["starting_balance"],
                    spread_pips=spread,
                    commission_per_lot=DEFAULT_BT_CONFIG["commission_per_lot"],
                    pair=pair,
                    min_confidence=DEFAULT_BT_CONFIG["min_confidence"],
                )
                strategy = TTSStrategy(
                    symbol=pair,
                    min_confidence=DEFAULT_BT_CONFIG["min_confidence"],
                    min_quality_score=DEFAULT_BT_CONFIG["min_quality_score"],
                )
                engine = MultiStrategyBacktestEngine(bt_config, [strategy])
                result = engine.run_all_strategies(bars)
                trades = result[strategy.name].metrics.trades
                metrics = trades_to_metrics(trades, DEFAULT_BT_CONFIG["starting_balance"])
            except Exception as e:
                metrics = {"skipped": str(e)}
            finally:
                restore_defaults()

            row = {
                "pair": pair,
                "timeframe": tf,
                "base_confidence": base,
                "negative_weight": neg_w,
                **metrics,
            }
            results.append(row)
            trades_n = metrics.get("total_trades", 0)
            wr = metrics.get("win_rate", 0)
            pnl = metrics.get("total_pnl", 0)
            print(f"  base={base:.2f} neg_w={neg_w:.1f} → {trades_n} trades, "
                  f"WR={wr:.1%}, P&L=${pnl:.2f}")

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    result_path = RESULTS_DIR / f"{pair}_{tf}_grid_{ts}.json"
    with open(result_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Grid results saved to {result_path}")

    valid = [r for r in results if r.get("total_trades", 0) >= MIN_TRADES_FOR_VALID_TRIAL]
    if not valid:
        return {"pair": pair, "timeframe": tf, "grid_results": results}

    def score_row(r):
        wr = r.get("win_rate", 0)
        pnl = r.get("total_pnl", 0)
        dd = max(r.get("max_drawdown_pct", 0.1), 0.1)
        return pnl * wr / (1 + dd / 100) if wr >= 0.35 else pnl * 0.3

    best_row = max(valid, key=score_row)
    print(f"\n  ★ Grid best: base={best_row['base_confidence']}, "
          f"neg_w={best_row['negative_weight']}, "
          f"WR={best_row['win_rate']:.1%}, P&L=${best_row['total_pnl']:.2f}")

    return {
        "pair": pair,
        "timeframe": tf,
        "grid_results": results,
        "best_grid_row": best_row,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Optuna hyperparameter optimizer for TTSStrategy")
    parser.add_argument("--pairs", nargs="+", default=["GBPUSD", "EURUSD"],
                        help="Pairs to optimize")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--trials", type=int, default=100,
                        help="Number of Optuna trials per pair")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Timeout per pair in seconds")
    parser.add_argument("--grid-only", action="store_true",
                        help="Run only grid search (skip Optuna)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print("=" * 70)
    print("  TTSStrategy Optuna Hyperparameter Optimizer")
    print(f"  Pairs: {args.pairs} | Timeframe: {args.timeframe}")
    print(f"  Trials: {args.trials} | Seed: {args.seed}")
    print("=" * 70)

    results = {}
    for pair in args.pairs:
        t0 = time.time()
        if args.grid_only:
            r = run_grid(pair, args.timeframe)
        else:
            r = run_study(pair, args.timeframe,
                          n_trials=args.trials,
                          timeout=args.timeout,
                          seed=args.seed)
        results[pair] = r
        elapsed = time.time() - t0
        print(f"\n  {pair} done in {elapsed:.1f}s")

    # Summary
    print("\n" + "=" * 70)
    print("  FINAL SUMMARY")
    print("=" * 70)
    for pair, r in results.items():
        bm = r.get("best_metrics", {})
        bp = r.get("best_params", {})
        print(f"\n  {pair}/{args.timeframe}")
        print(f"    Trials: {r.get('n_trials_complete', 'N/A')}")
        print(f"    WR: {bm.get('win_rate', 0):.1%} | "
              f"P&L: ${bm.get('total_pnl', 0):.2f} | "
              f"PF: {bm.get('profit_factor', 0):.2f} | "
              f"DD: {bm.get('max_drawdown_pct', 0):.1f}%")
        print(f"    Trades: {bm.get('total_trades', 0)}")
        if bp:
            print(f"    Best params:")
            for k, v in sorted(bp.items()):
                print(f"      {k}: {v}")

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    summary_path = RESULTS_DIR / f"summary_{ts}.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Full summary saved to {summary_path}")


if __name__ == "__main__":
    main()
