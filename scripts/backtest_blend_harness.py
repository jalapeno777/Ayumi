#!/usr/bin/env python3
"""Backtest Blend Harness — production-fidelity backtest without cTrader.

Drives the BlendForwardTestEngine evaluation loop using precomputed bars
from DuckDB instead of a live cTrader connection.  Constructs the same
component pipeline as ``launch_blend_forward_test.py`` but skips
``engine.start()`` and manually feeds bars through the evaluation loop.

This enables offline validation of the blend strategy without cTrader
connectivity, market hours, or demo account dependencies.

Usage::

    python3 scripts/backtest_blend_harness.py [options]

Options:
    --start DATE        Backtest start date (YYYY-MM-DD)
    --end DATE          Backtest end date (YYYY-MM-DD)
    --symbol SYM        Symbol to backtest (default: XAUUSD)
    --costs             Apply trading costs (spread, commission, slippage)
    --spread FLOAT      Spread in price units with --costs (default: 2.5)
    --commission FLOAT  Commission per lot USD with --costs (default: 3.5)
    --slippage FLOAT    Slippage in price units with --costs (default: 0.2)
    --db-path PATH      Override DuckDB path (default: data/ayumi_market.duckdb)
    --output PATH       Output JSON results path (default: data/backtest_results.json)
    --verbose           Enable DEBUG logging
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # F821 fix (card 9cdbfd0a): type-only import for the compute_stats annotation;
    # runtime loading is dynamic via importlib (see _load_module below).
    from forward_test.blend_runner import BlendForwardTestRunner

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))

logger = logging.getLogger("ayumi.backtest_harness")

# ── Import blend pipeline from launch script ─────────────────────────────────
# The BlendForwardTestEngine, CorrelationGate, RegimeGate, HeartbeatTracker,
# and supporting constants live in launch_blend_forward_test.py at module
# level.  We import them dynamically so the backtest harness always uses
# the production class definitions without duplicating code.

_spec = importlib.util.spec_from_file_location(
    "_launch_blend",
    str(PROJECT_ROOT / "scripts" / "launch_blend_forward_test.py"),
)
_launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_launch)

BlendForwardTestEngine = _launch.BlendForwardTestEngine
CorrelationGate = _launch.CorrelationGate
RegimeGate = _launch.RegimeGate
HeartbeatTracker = _launch.HeartbeatTracker
STRATEGY_ID_MAP = _launch.STRATEGY_ID_MAP
STRATEGY_TIMEFRAMES = _launch.STRATEGY_TIMEFRAMES
build_blend_runner = _launch.build_blend_runner

from adapters.ctrader.forward_test_engine import ForwardTestConfig
from adapters.ctrader.risk_guard import FTMOConfig
from common.logging_config import setup_logging
from core.types import Bar, BarPeriod
from strategies.donchian_atr_trend_v2 import (
    DonchianATRConfig,
    DonchianATRTrendV2Strategy,
)
from strategies.dual_tf_squeeze_pro import (
    DualTFSqueezeProConfig,
    DualTFSqueezeProStrategy,
)
from strategies.killzone_momentum import (
    KillzoneMomentumConfig,
    KillzoneMomentumStrategy,
)
from strategies.london_breakout_retest import (
    LondonBreakoutConfig,
    LondonBreakoutRetestStrategy,
)
from strategies.srmr_plus import SRMRPlusConfig, SRMRPlusStrategy
from strategies.ttc_xauusd import TTCXAUUSDStrategy

# ── DuckDB bar loading ────────────────────────────────────────────────────────


def load_bars_from_duckdb(
    db_path: str,
    symbol: str,
    timeframe: str,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> list[Bar]:
    """Load OHLCV bars from DuckDB and convert to ``Bar`` objects.

    DuckDB ``bars`` table columns:
        symbol, timeframe, timestamp_utc (seconds), open, high, low,
        close, volume, spread_pips
    """
    period = BarPeriod.H1() if timeframe == "H1" else BarPeriod.M15()

    query = (
        "SELECT timestamp_utc, open, high, low, close, volume, spread_pips "
        "FROM bars WHERE symbol = ? AND timeframe = ?"
    )
    params: list = [symbol, timeframe]
    if start_ts is not None:
        query += " AND timestamp_utc >= ?"
        params.append(start_ts)
    if end_ts is not None:
        query += " AND timestamp_utc <= ?"
        params.append(end_ts)
    query += " ORDER BY timestamp_utc ASC"

    con = duckdb.connect(db_path, read_only=True)
    try:
        rows = con.execute(query, params).fetchall()
    finally:
        con.close()

    bars = []
    for ts, o, h, l, c, vol, sp in rows:
        bars.append(
            Bar(
                time=datetime.fromtimestamp(ts, tz=timezone.utc),
                open=o,
                high=h,
                low=l,
                close=c,
                volume=vol,
                period=period,
                spread_pips=sp,
            )
        )
    logger.info("Loaded %d %s %s bars from %s", len(bars), symbol, timeframe, db_path)
    return bars


# ── Statistics computation ───────────────────────────────────────────────────


def compute_stats(
    paper_trader,
    blend_runner: BlendForwardTestRunner,
    commission_per_lot: float = 0.0,
    position_strategy_map: dict | None = None,
) -> dict:
    """Compute backtest performance statistics from PaperTrader state.

    Returns a dict with PF, net P&L, max drawdown, win rate, trade count,
    and per-strategy contribution breakdown.

    ``position_strategy_map`` maps position_id → strategy_id (populated by
    the patched _route_signal during the backtest eval loop).
    """
    if position_strategy_map is None:
        position_strategy_map = {}

    om = paper_trader._order_manager
    all_positions = list(om._positions.values())

    # Separate closed and open positions
    closed = [p for p in all_positions if p.status.is_closed]
    open_positions = [p for p in all_positions if not p.status.is_closed]

    # Apply commission adjustment to each closed trade
    trades = []
    for p in closed:
        pnl = p.closed_pnl - (abs(p.volume) * commission_per_lot)
        strategy_id = position_strategy_map.get(p.position_id, "unknown")
        trades.append(
            {
                "strategy_id": strategy_id,
                "symbol": p.symbol,
                "direction": p.direction.value
                if hasattr(p.direction, "value")
                else str(p.direction),
                "volume": p.volume,
                "entry_price": p.entry_price,
                "exit_price": p.closed_price or 0.0,
                "pnl": pnl,
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                "closed_at": p.closed_at.isoformat() if p.closed_at else None,
            }
        )

    # Core metrics
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    net_pnl = gross_profit - gross_loss
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] < 0)
    total_trades = len(trades)
    win_rate = wins / total_trades if total_trades > 0 else 0.0

    # Max drawdown (peak-to-trough on cumulative P&L curve)
    peak = 0.0
    max_dd = 0.0
    cumulative = 0.0
    for t in sorted(trades, key=lambda x: x["closed_at"] or ""):
        cumulative += t["pnl"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Per-strategy breakdown
    per_strategy: dict[str, dict] = defaultdict(
        lambda: {"trades": 0, "pnl": 0.0, "wins": 0}
    )
    for t in trades:
        sid = t["strategy_id"]
        per_strategy[sid]["trades"] += 1
        per_strategy[sid]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            per_strategy[sid]["wins"] += 1

    strategy_stats = {}
    for sid, s in sorted(per_strategy.items()):
        strategy_stats[sid] = {
            "trades": s["trades"],
            "pnl": round(s["pnl"], 2),
            "win_rate": round(s["wins"] / s["trades"], 4) if s["trades"] else 0.0,
        }

    # Open positions (unrealized)
    open_unrealized = sum(p.unrealized_pnl for p in open_positions)

    # Compute true realized P&L from closed positions (including commission)
    true_realized = sum(t["pnl"] for t in trades)
    true_final_balance = (
        paper_trader._starting_balance + true_realized + open_unrealized
    )

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(pf, 4) if pf != float("inf") else pf,
        "net_pnl": round(net_pnl, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "max_drawdown": round(max_dd, 2),
        "open_positions": len(open_positions),
        "open_unrealized": round(open_unrealized, 2),
        "starting_balance": paper_trader._starting_balance,
        "final_balance": round(true_final_balance, 2),
        "per_strategy": strategy_stats,
    }


# ── Main backtest ────────────────────────────────────────────────────────────


def run_backtest(args: argparse.Namespace) -> dict:
    """Run the full backtest and return results dict."""
    symbol = args.symbol.upper()
    symbols = [symbol]

    # ── Parse date range ──────────────────────────────────────────────────
    start_ts = None
    end_ts = None
    if args.start:
        start_ts = int(
            datetime.strptime(args.start, "%Y-%m-%d")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    if args.end:
        end_ts = int(
            datetime.strptime(args.end, "%Y-%m-%d")
            .replace(tzinfo=timezone.utc)
            .timestamp()
            + 86399  # end of day
        )

    # ── Load bars from DuckDB ─────────────────────────────────────────────
    db_path = args.db_path or str(PROJECT_ROOT / "data" / "ayumi_market.duckdb")
    m15_bars = load_bars_from_duckdb(db_path, symbol, "M15", start_ts, end_ts)
    h1_bars = load_bars_from_duckdb(db_path, symbol, "H1", start_ts, end_ts)

    if not m15_bars:
        logger.error("No M15 bars found for %s in the specified date range", symbol)
        return {"error": "no_m15_bars"}
    if not h1_bars:
        logger.error("No H1 bars found for %s in the specified date range", symbol)
        return {"error": "no_h1_bars"}

    # ── Construct strategies (same as launch_blend_forward_test.py main()) ──
    strategies = [
        KillzoneMomentumStrategy(config=KillzoneMomentumConfig()),
        TTCXAUUSDStrategy(),
        DualTFSqueezeProStrategy(config=DualTFSqueezeProConfig()),
        DonchianATRTrendV2Strategy(config=DonchianATRConfig()),
        SRMRPlusStrategy(config=SRMRPlusConfig(symbol=symbol)),
        LondonBreakoutRetestStrategy(config=LondonBreakoutConfig()),
    ]

    active_names = {s.name for s in strategies}
    active_strategy_timeframes = {
        k: v for k, v in STRATEGY_TIMEFRAMES.items() if k in active_names
    }
    active_strategy_id_map = {
        k: v for k, v in STRATEGY_ID_MAP.items() if k in active_names
    }

    logger.info("Strategy pool: %s", [s.name for s in strategies])

    # ── Reset stale risk state ───────────────────────────────────────────
    # The blend runner loads risk_state_blend.json on start(), which may
    # contain stale open_risk from a previous live/session run.  This would
    # block all new signals (open_risk + new > max).  Delete before run.
    state_path = PROJECT_ROOT / "data" / "risk_state_blend.json"
    if state_path.exists():
        state_path.unlink()
        logger.info("Cleared stale risk state: %s", state_path)

    # ── Build blend runner ────────────────────────────────────────────────
    blend_runner = build_blend_runner()

    # Verify clean risk state after construction
    if hasattr(blend_runner, "_sizer") and blend_runner._sizer:
        open_risk = blend_runner._sizer._open_risk
        if open_risk > 0:
            logger.warning("Resetting non-zero open_risk after build: $%.2f", open_risk)
            blend_runner._sizer._open_positions.clear()
            blend_runner._sizer._position_symbols.clear()
        logger.info(
            "Blend runner sizer open_risk: $%.2f", blend_runner._sizer._open_risk
        )

    # Override spread for XAUUSD if --costs
    if args.costs:
        blend_runner._config["spread_pips"][symbol] = args.spread

    correlation_gate = CorrelationGate()
    regime_gate = RegimeGate()
    heartbeat = HeartbeatTracker(interval=500)

    # ── Build engine config ───────────────────────────────────────────────
    config = ForwardTestConfig(
        symbol=symbol,
        symbols=symbols,
        starting_balance=10_000.0,
        min_confidence=0.30,
        max_bars_per_symbol=500,
        min_bars_for_evaluation=55,
        live_mode=False,
        execution_mode="paper",
        strategy_timeframes=active_strategy_timeframes,
        bar_period_minutes=15,
        preload_bar_count=200,
    )

    # ── Build dummy credentials (paper mode — never used) ─────────────────
    from adapters.ctrader.models import cTraderCredentials

    credentials = cTraderCredentials(
        host="",
        port=0,
        use_ssl=False,
        username="",
        password="",
        sender_comp_id="",
        target_comp_id="",
        sender_sub_id="",
    )

    # ── Create engine ─────────────────────────────────────────────────────
    engine = BlendForwardTestEngine(
        config=config,
        strategies=strategies,
        ftmo_config=FTMOConfig(min_risk_reward=0.0),
        credentials=credentials,
        blend_runner=blend_runner,
        correlation_gate=correlation_gate,
        heartbeat=heartbeat,
        strategy_id_map=active_strategy_id_map,
        regime_gate=regime_gate,
        blend_mode=True,
    )

    # ── Build internal components WITHOUT starting the feed ───────────────
    # _build_components() creates PaperTrader, cTraderLiveAdapter,
    # TradeLogger, and PositionMonitor.  In paper mode (live_mode=False)
    # it skips OpenApiSpotFeed construction entirely.
    engine._build_components()

    # Mark engine as running so internal guards pass
    engine._running = True
    engine._start_time = datetime.now(timezone.utc)
    engine._preload_complete = True

    # Configure slippage model if --costs
    if args.costs and engine._paper_trader:
        om = engine._paper_trader._order_manager
        # For XAUUSD, pip_value = 0.01 ($0.01 per pip)
        om._slippage_model.base_pips = 0.0
        om._slippage_model.random_pips = 0.0
        om._slippage_model.pip_value = args.slippage  # interpret as price units

    paper_trader = engine._paper_trader

    # ── Strategy tracking via patched _route_signal ──────────────────────
    # The production _route_signal constructs a new CTraderTradeSignal
    # (exec_signal) without carrying strategy_id, so positions lose their
    # strategy attribution.  We patch the method to capture position_id →
    # strategy_id mapping by comparing open positions before/after each
    # signal routing.

    position_strategy_map: dict[str, str] = {}
    _orig_route = engine._route_signal

    def _tracked_route(signal, strategy_name):
        sid = active_strategy_id_map.get(
            strategy_name, strategy_name.lower().replace(" ", "_")
        )
        pos_before = set()
        if engine._paper_trader:
            pos_before = set(engine._paper_trader._order_manager._positions.keys())
        _orig_route(signal, strategy_name)
        if engine._paper_trader:
            pos_after = set(engine._paper_trader._order_manager._positions.keys())
            for pid in pos_after - pos_before:
                position_strategy_map[pid] = sid

    engine._route_signal = _tracked_route

    logger.info(
        "Engine constructed. PaperTrader balance: $%.2f", paper_trader._starting_balance
    )
    logger.info(
        "Strategies in live_adapter: %s", list(engine._live_adapter._strategies.keys())
    )
    logger.info(
        "Adapters: %s",
        [k for k in engine._live_adapter._adapters.keys() if symbol in k],
    )

    # ── Drive evaluation loop ─────────────────────────────────────────────
    # Merge M15 and H1 bars into a single chronological event stream.
    # Each event is (timeframe_label, bar).  When multiple events share
    # the same timestamp, H1 bars are processed before M15 bars (H1
    # closes before M15 evaluation sees the updated H1 window).
    m15_key = f"{symbol}:15"
    h1_key = f"{symbol}:60"

    events: list[tuple[str, Bar]] = []
    for bar in m15_bars:
        events.append(("M15", bar))
    for bar in h1_bars:
        events.append(("H1", bar))
    events.sort(key=lambda x: (x[1].time, 0 if x[0] == "H1" else 1))

    # Determine spread for price updates
    spread_price = args.spread if args.costs else 0.0

    bars_processed = 0
    signals_evaluated = 0
    h1_idx = 0
    m15_idx = 0

    for tf_label, bar in events:
        key = h1_key if tf_label == "H1" else m15_key

        # Append bar to engine's bar store (respecting max_bars limit)
        if key not in engine._bars:
            engine._bars[key] = []
        engine._bars[key].append(bar)
        if len(engine._bars[key]) > config.max_bars_per_symbol:
            engine._bars[key] = engine._bars[key][-config.max_bars_per_symbol :]

        # Update paper trader prices (for open position TP/SL checks)
        close = bar.close
        bid = close - spread_price / 2 if spread_price > 0 else close
        ask = close + spread_price / 2 if spread_price > 0 else close
        paper_trader.update_market_prices(
            {symbol: close},
            bids={symbol: bid},
            asks={symbol: ask},
        )

        # Set engine spread from bar data or --costs override
        bar_spread = getattr(bar, "spread_pips", 0.0)
        if args.costs:
            engine._current_spread = spread_price
        elif bar_spread > 0:
            # Convert bar spread_pips to approximate price units
            engine._current_spread = bar_spread * 0.01  # rough pip→price for XAUUSD
        else:
            engine._current_spread = 0.0

        # Trigger evaluation
        engine._bar_completed[key] = True
        engine._evaluate_strategies(symbol)
        engine._bar_completed[key] = False

        bars_processed += 1
        if bars_processed % 5000 == 0:
            stats = paper_trader.get_stats()
            logger.info(
                "Progress: %d/%d events | trades=%d | balance=$%.2f",
                bars_processed,
                len(events),
                stats.trades_executed,
                paper_trader._current_balance,
            )

    logger.info("Evaluation complete: %d events processed", bars_processed)

    # ── Compute and return results ────────────────────────────────────────
    commission = args.commission if args.costs else 0.0
    results = compute_stats(
        paper_trader,
        blend_runner,
        commission_per_lot=commission,
        position_strategy_map=position_strategy_map,
    )
    results["symbol"] = symbol
    results["bars_processed"] = bars_processed
    results["m15_bars"] = len(m15_bars)
    results["h1_bars"] = len(h1_bars)
    results["costs_applied"] = args.costs
    if args.costs:
        results["cost_params"] = {
            "spread": args.spread,
            "commission_per_lot": args.commission,
            "slippage": args.slippage,
        }
    results["date_range"] = {
        "start": m15_bars[0].time.isoformat(),
        "end": m15_bars[-1].time.isoformat(),
    }

    # ── Print summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  BACKTEST RESULTS — {symbol}")
    print("=" * 60)
    print(
        f"  Date Range:     {results['date_range']['start'][:10]} → {results['date_range']['end'][:10]}"
    )
    print(
        f"  Bars Processed: {bars_processed:,} ({len(m15_bars):,} M15 + {len(h1_bars):,} H1)"
    )
    print(f"  Total Trades:   {results['total_trades']}")
    print(
        f"  Win Rate:       {results['win_rate']:.1%} ({results['wins']}W / {results['losses']}L)"
    )
    print(f"  Profit Factor:  {results['profit_factor']:.4f}")
    print(f"  Net P&L:        ${results['net_pnl']:,.2f}")
    print(f"  Gross Profit:   ${results['gross_profit']:,.2f}")
    print(f"  Gross Loss:     ${results['gross_loss']:,.2f}")
    print(f"  Max Drawdown:   ${results['max_drawdown']:,.2f}")
    print(f"  Final Balance:  ${results['final_balance']:,.2f}")
    print(
        f"  Open Positions: {results['open_positions']} (unrealized: ${results['open_unrealized']:,.2f})"
    )
    if results["costs_applied"]:
        cp = results["cost_params"]
        print(
            f"  Costs:          spread={cp['spread']}, commission=${cp['commission_per_lot']}/lot, slippage={cp['slippage']}"
        )

    print("\n  Per-Strategy Contribution:")
    print("  " + "-" * 56)
    print(f"  {'Strategy':<30} {'Trades':>7} {'P&L':>12} {'Win Rate':>10}")
    print("  " + "-" * 56)
    for sid, s in results["per_strategy"].items():
        print(f"  {sid:<30} {s['trades']:>7} ${s['pnl']:>10,.2f} {s['win_rate']:>9.1%}")
    print("=" * 60)

    # ── Save JSON output ──────────────────────────────────────────────────
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("Results saved to %s", output_path)

    # ── Cleanup ───────────────────────────────────────────────────────────
    blend_runner.stop()

    return results


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Backtest Blend Harness — production-fidelity backtest without cTrader"
    )
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--symbol", default="XAUUSD", help="Symbol (default: XAUUSD)")
    parser.add_argument("--costs", action="store_true", help="Apply trading costs")
    parser.add_argument(
        "--spread", type=float, default=2.5, help="Spread in price units (default: 2.5)"
    )
    parser.add_argument(
        "--commission",
        type=float,
        default=3.5,
        help="Commission per lot USD (default: 3.5)",
    )
    parser.add_argument(
        "--slippage",
        type=float,
        default=0.2,
        help="Slippage in price units (default: 0.2)",
    )
    parser.add_argument("--db-path", default=None, help="Override DuckDB path")
    parser.add_argument(
        "--output", default="data/backtest_results.json", help="Output JSON path"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=level)

    results = run_backtest(args)
    if "error" in results:
        sys.exit(1)


if __name__ == "__main__":
    main()
