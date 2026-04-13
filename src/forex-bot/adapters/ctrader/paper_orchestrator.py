"""Paper Trading Orchestrator — Lean Blend (5 strategies, M15).

Runs the optimized lean blend portfolio through the backtest engine for
paper trading simulation. Uses MultiStrategyBacktestEngine (not PaperTrader)
so signal-flip exits, SL/TP hits, and position management work correctly.

Strategies:
  - SRM XAUUSD, SRM USDJPY, SRM GBPUSD (session_range_mr)
  - TTC XAUUSD, TTC EURUSD (TTC signal engine)

Risk limits (FTMO buffer):
  - 4% daily DD (FTMO: 5%)
  - 7% max account DD (FTMO: 10%)
  - $10K starting balance, $1K profit target
"""

import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from backtest.engine import BacktestConfig, TradeDirection
from backtest.multi_strategy_engine import MultiStrategyBacktestEngine
from backtest.parameter_sweep.legacy_optimizer import legacy_strategy_factory
from backtest.parameter_sweep.ttc_optimizer import load_bars, ttc_strategy_factory
from signal_engine.risk_sizer import ConfidencePositionSizer

logger = logging.getLogger(__name__)


# ── Lean Blend Config (serializable for live trading later) ─────────────

@dataclass
class SRMConfig:
    strategy_type: str = "session_range_mr"
    min_confidence: float = 0.5
    session_range_min_pips: float = 25.0
    session_range_sl_fraction: float = 0.5


@dataclass
class TTCConfig:
    strategy_type: str = "ttc"
    min_confidence: float = 0.4
    min_quality_score: float = 0.4
    mw_base_confidence: float = 0.4
    rsi_divergence_boost: float = 0.1
    htf_trend_aligned_boost: float = 0.0
    htf_opposing_penalty: float = -0.1
    kill_zone_active_boost: float = -0.15
    negative_weight: float = 1.0
    swing_lookback: int = 5
    history_bars: int = 50


@dataclass
class StrategyEntry:
    name: str
    pair: str
    config: SRMConfig | TTCConfig = field(default_factory=SRMConfig)


@dataclass
class LeanBlendConfig:
    starting_balance: float = 10000.0
    spread_pips: float = 0.7
    commission_per_lot: float = 3.5
    max_daily_drawdown_pct: float = 0.04
    max_total_drawdown_pct: float = 0.07
    strategies: list[StrategyEntry] = field(default_factory=list)


# ── Optimized parameters (from Optuna walk-forward) ─────────────────────

LEAN_BLEND = LeanBlendConfig(
    strategies=[
        StrategyEntry(
            name="SRM XAUUSD", pair="XAUUSD",
            config=SRMConfig(min_confidence=0.4, session_range_min_pips=35.0, session_range_sl_fraction=0.3),
        ),
        StrategyEntry(
            name="SRM USDJPY", pair="USDJPY",
            config=SRMConfig(min_confidence=0.5, session_range_min_pips=20.0, session_range_sl_fraction=0.9),
        ),
        StrategyEntry(
            name="TTC XAUUSD", pair="XAUUSD",
            config=TTCConfig(
                min_confidence=0.5, min_quality_score=0.4, mw_base_confidence=0.45,
                rsi_divergence_boost=0.2, htf_trend_aligned_boost=0.1,
                htf_opposing_penalty=-0.05, kill_zone_active_boost=-0.15,
                negative_weight=0.25, swing_lookback=3, history_bars=50,
            ),
        ),
        StrategyEntry(
            name="TTC EURUSD", pair="EURUSD",
            config=TTCConfig(
                min_confidence=0.25, min_quality_score=0.45, mw_base_confidence=0.4,
                rsi_divergence_boost=0.1, htf_trend_aligned_boost=0.0,
                htf_opposing_penalty=-0.25, kill_zone_active_boost=-0.15,
                negative_weight=1.75, swing_lookback=7, history_bars=80,
            ),
        ),
        StrategyEntry(
            name="SRM GBPUSD", pair="GBPUSD",
            config=SRMConfig(min_confidence=0.4, session_range_min_pips=25.0, session_range_sl_fraction=0.8),
        ),
    ]
)


def _build_strategy(entry: StrategyEntry):
    """Instantiate a strategy from its config entry."""
    cfg = entry.config
    if isinstance(cfg, SRMConfig):
        params = {
            "min_confidence": cfg.min_confidence,
            "session_range_min_pips": cfg.session_range_min_pips,
            "session_range_sl_fraction": cfg.session_range_sl_fraction,
        }
        return legacy_strategy_factory(cfg.strategy_type, params, symbol=entry.pair, timeframe="M15")
    elif isinstance(cfg, TTCConfig):
        params = {
            "min_confidence": cfg.min_confidence,
            "min_quality_score": cfg.min_quality_score,
            "mw_base_confidence": cfg.mw_base_confidence,
            "rsi_divergence_boost": cfg.rsi_divergence_boost,
            "htf_trend_aligned_boost": cfg.htf_trend_aligned_boost,
            "htf_opposing_penalty": cfg.htf_opposing_penalty,
            "kill_zone_active_boost": cfg.kill_zone_active_boost,
            "negative_weight": cfg.negative_weight,
            "swing_lookback": cfg.swing_lookback,
            "history_bars": cfg.history_bars,
        }
        return ttc_strategy_factory(params, symbol=entry.pair, timeframe="M15")
    else:
        raise ValueError(f"Unknown config type: {type(cfg)}")


def run_paper_trading(blend_config: LeanBlendConfig | None = None) -> dict:
    """Run the paper trading orchestrator and return summary dict."""
    blend = blend_config or LEAN_BLEND

    # Build strategies
    strategies = []
    pair_names = []
    for entry in blend.strategies:
        print(f"  Building {entry.name} ({entry.pair})...")
        strat = _build_strategy(entry)
        strategies.append(strat)
        pair_names.append(entry.pair)

    # Backtest config with FTMO risk limits
    bt_config = BacktestConfig(
        starting_balance=blend.starting_balance,
        spread_pips=blend.spread_pips,
        commission_per_lot=blend.commission_per_lot,
        max_daily_drawdown_pct=blend.max_daily_drawdown_pct,
        max_total_drawdown_pct=blend.max_total_drawdown_pct,
    )

    # Risk sizer
    risk_sizer = ConfidencePositionSizer(account_size=blend.starting_balance)

    # Load bars per pair and run each strategy with its own bars
    print(f"\nRunning {len(strategies)} strategies through backtest engine...")
    pair_bars_cache: dict[str, list] = {}
    results = {}
    for entry, strat in zip(blend.strategies, strategies):
        pair = entry.pair
        if pair not in pair_bars_cache:
            print(f"  Loading {pair} bars...")
            pair_bars_cache[pair] = load_bars(pair, "M15")[-6000:]
        bars = pair_bars_cache[pair]
        print(f"  Running {entry.name} on {len(bars)} bars...")
        engine = MultiStrategyBacktestEngine(
            config=bt_config,
            strategies=[strat],
            risk_sizer=risk_sizer,
        )
        strat_results = engine.run_all_strategies(bars)
        # Use entry.name to avoid key collisions (e.g. two SRM strategies
        # both named "ConfluenceWrapped(Session-Range Mean Reversion)")
        for _key, _val in strat_results.items():
            results[entry.name] = _val

    # ── Compile summary ──────────────────────────────────────────────────
    all_trades = []
    per_strategy = {}
    total_pnl = 0.0
    total_trades = 0
    total_wins = 0
    long_pnl = 0.0
    short_pnl = 0.0
    long_trades = 0
    short_trades = 0

    for name, result in results.items():
        metrics = result.metrics
        trades = metrics.trades
        all_trades.extend(trades)
        total_pnl += metrics.total_pnl
        total_trades += metrics.total_trades
        total_wins += metrics.winning_trades
        for t in trades:
            if t.direction == TradeDirection.LONG:
                long_pnl += t.profit_loss
                long_trades += 1
            else:
                short_pnl += t.profit_loss
                short_trades += 1
        per_strategy[name] = {
            "pnl": metrics.total_pnl,
            "trades": metrics.total_trades,
            "win_rate": metrics.win_rate,
            "avg_win": metrics.avg_win,
            "avg_loss": metrics.avg_loss,
        }

    # Monthly breakdown
    monthly: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    for t in all_trades:
        key = t.exit_time.strftime("%Y-%m")
        monthly[key]["pnl"] += t.profit_loss
        monthly[key]["trades"] += 1
        if t.profit_loss > 0:
            monthly[key]["wins"] += 1

    # Max drawdown estimate from all trades
    peak = blend.starting_balance
    max_dd = 0.0
    balance = blend.starting_balance
    for t in sorted(all_trades, key=lambda x: x.exit_time):
        balance += t.profit_loss
        if balance > peak:
            peak = balance
        dd = (peak - balance) / peak
        if dd > max_dd:
            max_dd = dd

    win_rate = (total_wins / total_trades * 100) if total_trades else 0.0

    # Date range
    if all_trades:
        first_trade = min(all_trades, key=lambda x: x.exit_time)
        last_trade = max(all_trades, key=lambda x: x.exit_time)
        days = (last_trade.exit_time - first_trade.exit_time).days or 1
    else:
        days = 1

    # Time to $1K estimate
    daily_pnl = total_pnl / days if days > 0 else 0
    days_to_target = int(1000 / daily_pnl) if daily_pnl > 0 else float("inf")

    # FTMO assessment
    daily_dd_pct = bt_config.max_daily_drawdown_pct
    total_dd_pct = max_dd
    ftmo_daily_ok = total_dd_pct < 0.05
    ftmo_total_ok = total_dd_pct < 0.10

    # ── Print summary ────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("  PAPER TRADING SUMMARY — LEAN BLEND PORTFOLIO")
    print("=" * 64)

    print(f"\n  Total PnL:           ${total_pnl:,.2f}")
    print(f"  Win Rate:            {win_rate:.1f}%")
    print(f"  Total Trades:        {total_trades}")
    print(f"  Max Drawdown:        {total_dd_pct:.2%}")
    print(f"  Trading Period:      {days} days")
    print(f"  Avg Daily PnL:       ${daily_pnl:,.2f}")
    print(f"  Days to $1K target:  {days_to_target}" if days_to_target != float("inf") else "  Days to $1K target:  N/A (no profit)")

    print(f"\n  Long:  {long_trades} trades, ${long_pnl:,.2f}")
    print(f"  Short: {short_trades} trades, ${short_pnl:,.2f}")

    print(f"\n  FTMO Assessment:")
    print(f"    Max DD {total_dd_pct:.2%} vs 5% daily limit: {'✅ PASS' if ftmo_daily_ok else '❌ FAIL'}")
    print(f"    Max DD {total_dd_pct:.2%} vs 10% total limit: {'✅ PASS' if ftmo_total_ok else '❌ FAIL'}")

    print(f"\n  Per-Strategy Breakdown:")
    print(f"  {'Strategy':<16} {'PnL':>10} {'Trades':>7} {'WR':>7} {'Avg Win':>9} {'Avg Loss':>9}")
    print(f"  {'-'*60}")
    for name, s in per_strategy.items():
        print(f"  {name:<16} ${s['pnl']:>8,.2f} {s['trades']:>7} {s['win_rate']:>6.1f}% ${s['avg_win']:>7,.2f} ${s['avg_loss']:>8,.2f}")

    print(f"\n  Monthly Breakdown:")
    print(f"  {'Month':<10} {'PnL':>10} {'Trades':>7} {'WR':>7}")
    print(f"  {'-'*36}")
    for month in sorted(monthly.keys()):
        m = monthly[month]
        wr = (m["wins"] / m["trades"] * 100) if m["trades"] else 0
        print(f"  {month:<10} ${m['pnl']:>8,.2f} {m['trades']:>7} {wr:>6.1f}%")

    print("\n" + "=" * 64)

    return {
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "max_drawdown_pct": total_dd_pct,
        "days": days,
        "daily_pnl": daily_pnl,
        "days_to_1k": days_to_target,
        "per_strategy": per_strategy,
        "monthly": dict(monthly),
        "long_pnl": long_pnl,
        "short_pnl": short_pnl,
        "ftmo_pass": ftmo_daily_ok and ftmo_total_ok,
    }


# Backwards compat for old CLI
class PaperOrchestrator:
    def __init__(self, starting_balance=10_000.0, log_dir=None):
        self.blend = LeanBlendConfig(starting_balance=starting_balance)
        if log_dir:
            import os
            os.makedirs(log_dir, exist_ok=True)

    def run(self):
        return run_paper_trading(self.blend)
