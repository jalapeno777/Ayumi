#!/usr/bin/env python3
"""BQ-545: Validate trend+ATR filter combination against backtest data.

This script compares a baseline MA-crossover strategy against the same
strategy wrapped with a **trend direction filter** (EMA slope) and an
**ATR volatility gate** (minimum ATR in pips).  It runs both on existing
historical data and produces a JSON comparison report.

Trend + ATR filter logic is drawn from the patterns in
``backtest/strategy_legacy.py`` — specifically:
  - ``MomentumBreakoutStrategy``: EMA crossover + ADX threshold + ATR stops
  - ``KeltnerChannelBreakoutStrategy``: EMA + ATR bands + ADX + ``atr_min_pips``
  - ``SupertrendRSIBlendStrategy``: ``atr_min_pips`` volatility gate + ADX

Baseline: Simple MA(5/13) crossover — no trend or volatility filters.
Filtered: Same MA(5/13) crossover, but signals are only taken when:
  1. EMA(50) slope confirms direction (rising for longs, falling for shorts)
  2. ATR(14) in pips >= ``atr_min_pips`` (sufficient volatility)

Usage::

    python3 scripts/validate_trend_atr_filter.py
    python3 scripts/validate_trend_atr_filter.py --data path/to/CSV
    python3 scripts/validate_trend_atr_filter.py --output report.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Project root for data discovery
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# ---------------------------------------------------------------------------
# Lightweight types (mirrors backtest.types.Bar / TradeDirection)
# Keeps the script self-contained — no heavy dependency chain.
# ---------------------------------------------------------------------------


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


@dataclass
class Bar:
    """OHLCV bar — mirrors backtest.types.Bar."""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_DATA_PATH = (
    PROJECT_ROOT / "worktrees" / "media" / "data" / "forex" / "historical" / "EURUSD_H1.csv"
)
DEFAULT_FAST_MA = 5
DEFAULT_SLOW_MA = 13
DEFAULT_TREND_EMA = 50
DEFAULT_ATR_PERIOD = 14
DEFAULT_ATR_MIN_PIPS = 5.0
DEFAULT_ADX_THRESHOLD = 20.0
DEFAULT_STARTING_BALANCE = 10_000.0
DEFAULT_RISK_PER_TRADE_PCT = 0.01

_EASTERN = ZoneInfo("America/New_York")
_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Data loading (lightweight — avoids heavy deps for simple CSVs)
# ---------------------------------------------------------------------------

def load_csv_bars(filepath: str | Path) -> list[Bar]:
    """Load OHLCV bars from a tick-data CSV with Eastern timestamps."""
    bars: list[Bar] = []
    dropped = 0
    with open(filepath) as f:
        lines = f.readlines()
    for line in lines[1:]:  # skip header
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            dt = _parse_timestamp(parts[0])
            o = float(parts[1])
            h = float(parts[2])
            lo = float(parts[3])
            c = float(parts[4])
            v = float(parts[5]) if len(parts) > 5 else 0.0
            bars.append(Bar(time=dt, open=o, high=h, low=lo, close=c, volume=v))
        except (ValueError, IndexError):
            dropped += 1
    if dropped:
        print(f"WARNING: dropped {dropped} malformed rows from {filepath}", file=sys.stderr)
    return bars


def _parse_timestamp(ts_str: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(ts_str.strip(), fmt)
            dt = dt.replace(tzinfo=_EASTERN)
            return dt.astimezone(_UTC)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {ts_str}")


# ---------------------------------------------------------------------------
# Indicator helpers (standalone — no dependency on strategy objects)
# ---------------------------------------------------------------------------

def sma(bars: list[Bar], period: int) -> float:
    if len(bars) < period:
        return 0.0
    return sum(b.close for b in bars[-period:]) / period


def ema(bars: list[Bar], period: int) -> float:
    if len(bars) < period:
        return 0.0
    multiplier = 2.0 / (period + 1)
    value = sum(b.close for b in bars[:period]) / period
    for b in bars[period:]:
        value = (b.close - value) * multiplier + value
    return value


def atr(bars: list[Bar], period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0001
    tr_sum = 0.0
    for i in range(len(bars) - period, len(bars)):
        if i > 0:
            tr = max(
                bars[i].high - bars[i].low,
                max(
                    abs(bars[i].high - bars[i - 1].close),
                    abs(bars[i].low - bars[i - 1].close),
                ),
            )
            tr_sum += tr
    return tr_sum / period


def adx(bars: list[Bar], period: int = 14) -> float | None:
    if len(bars) < period * 2 + 1:
        return None

    tr_list: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []

    for i in range(1, len(bars)):
        tr = max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - bars[i - 1].close),
            abs(bars[i].low - bars[i - 1].close),
        )
        tr_list.append(tr)

        hd = bars[i].high - bars[i - 1].high
        ld = bars[i - 1].low - bars[i].low

        plus_dm.append(hd if (hd > ld and hd > 0) else 0.0)
        minus_dm.append(ld if (ld > hd and ld > 0) else 0.0)

    if len(tr_list) < period:
        return None

    s_tr = sum(tr_list[:period])
    s_plus = sum(plus_dm[:period])
    s_minus = sum(minus_dm[:period])
    if s_tr == 0:
        return None

    dx_list: list[float] = []
    for i in range(period, len(tr_list)):
        s_tr = s_tr - s_tr / period + tr_list[i]
        s_plus = s_plus - s_plus / period + plus_dm[i]
        s_minus = s_minus - s_minus / period + minus_dm[i]
        if s_tr == 0:
            dx_list.append(0.0)
            continue
        pdi = (s_plus / s_tr) * 100
        mdi = (s_minus / s_tr) * 100
        denom = pdi + mdi
        dx_list.append(abs(pdi - mdi) / denom * 100 if denom > 0 else 0.0)

    if not dx_list:
        return None
    return sum(dx_list) / len(dx_list)


def pip_value(price: float) -> float:
    if price >= 50:
        return 0.01
    elif price >= 1:
        return 0.0001
    return 0.00000001


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------

@dataclass
class BaselineSignal:
    """MA crossover signal — no filters."""
    direction: TradeDirection
    entry: float
    fast_ma: float
    slow_ma: float


@dataclass
class FilteredSignal:
    """MA crossover signal that passed trend + ATR gates."""
    direction: TradeDirection
    entry: float
    fast_ma: float
    slow_ma: float
    trend_ema: float
    atr_pips: float
    adx_value: float | None
    filter_reason: str  # human-readable explanation


def evaluate_baseline(bars: list[Bar], fast: int, slow: int) -> BaselineSignal | None:
    """Pure MA crossover — the unfiltered baseline."""
    if len(bars) < slow + 1:
        return None
    f_ma = sma(bars, fast)
    s_ma = sma(bars, slow)
    prev_f = sma(bars[:-1], fast)
    prev_s = sma(bars[:-1], slow)
    if f_ma == 0 or s_ma == 0 or prev_f == 0 or prev_s == 0:
        return None

    bullish = prev_f <= prev_s and f_ma > s_ma
    bearish = prev_f >= prev_s and f_ma < s_ma
    if not bullish and not bearish:
        return None

    direction = TradeDirection.LONG if bullish else TradeDirection.SHORT
    return BaselineSignal(direction=direction, entry=bars[-1].close, fast_ma=f_ma, slow_ma=s_ma)


def evaluate_filtered(
    bars: list[Bar],
    fast: int,
    slow: int,
    trend_ema_period: int,
    atr_period: int,
    atr_min_pips: float,
    adx_threshold: float,
) -> FilteredSignal | None:
    """MA crossover + EMA trend confirmation + ATR volatility gate."""
    base = evaluate_baseline(bars, fast, slow)
    if base is None:
        return None

    # --- Trend filter: EMA slope must confirm direction ---
    if len(bars) < trend_ema_period + 1:
        return None  # not enough data for trend EMA
    current_trend = ema(bars, trend_ema_period)
    prev_trend = ema(bars[:-1], trend_ema_period)
    if current_trend == 0 or prev_trend == 0:
        return None

    trend_rising = current_trend > prev_trend
    trend_falling = current_trend < prev_trend

    if base.direction == TradeDirection.LONG and not trend_rising:
        return None
    if base.direction == TradeDirection.SHORT and not trend_falling:
        return None

    # --- ATR volatility gate ---
    current_atr = atr(bars, atr_period)
    a_pips = current_atr / pip_value(base.entry)
    if a_pips < atr_min_pips:
        return None

    # --- ADX confirmation (soft filter — recorded but not blocking) ---
    adx_val = adx(bars, 14)

    return FilteredSignal(
        direction=base.direction,
        entry=base.entry,
        fast_ma=base.fast_ma,
        slow_ma=base.slow_ma,
        trend_ema=current_trend,
        atr_pips=round(a_pips, 2),
        adx_value=round(adx_val, 1) if adx_val is not None else None,
        filter_reason=(
            f"MA cross + EMA({trend_ema_period}) trend confirm + "
            f"ATR({atr_period}) >= {atr_min_pips} pips"
        ),
    )


# ---------------------------------------------------------------------------
# Lightweight trade simulator
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    direction: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    pips: float
    profit_loss: float
    outcome: str
    exit_reason: str


@dataclass
class BacktestStats:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    trades: list[dict] = field(default_factory=list)


def simulate(
    bars: list[Bar],
    signal_fn: Any,
    atr_mult: float = 2.0,
    starting_balance: float = DEFAULT_STARTING_BALANCE,
    risk_pct: float = DEFAULT_RISK_PER_TRADE_PCT,
    min_bars: int = 60,
    fast: int = DEFAULT_FAST_MA,
    slow: int = DEFAULT_SLOW_MA,
    trend_ema_period: int = DEFAULT_TREND_EMA,
    atr_period: int = DEFAULT_ATR_PERIOD,
    atr_min_pips: float = DEFAULT_ATR_MIN_PIPS,
    adx_threshold: float = DEFAULT_ADX_THRESHOLD,
) -> BacktestStats:
    """Run a simple backtest simulation.

    For each bar, evaluate the signal function.  When a signal fires,
    open a trade with ATR-based stop and 2R take-profit.  Only one
    trade open at a time.  Track P&L, drawdown, and win/loss.
    """
    import inspect

    is_filtered = "atr_min_pips" in inspect.signature(signal_fn).parameters

    balance = starting_balance
    peak = starting_balance
    max_dd = 0.0

    open_trade: dict | None = None
    closed_trades: list[TradeRecord] = []

    for i in range(min_bars, len(bars)):
        window = bars[: i + 1]
        bar = bars[i]

        # --- Manage open trade ---
        if open_trade is not None:
            hit, exit_price, reason = _check_exit(open_trade, bar)
            if hit:
                pnl, pips, outcome = _close_trade(
                    open_trade, exit_price, balance, risk_pct, starting_balance
                )
                balance += pnl
                if balance > peak:
                    peak = balance
                dd = (peak - balance) / peak * 100 if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd

                closed_trades.append(
                    TradeRecord(
                        direction=open_trade["direction"].value,
                        entry_time=open_trade["entry_time"].isoformat(),
                        exit_time=bar.time.isoformat(),
                        entry_price=open_trade["entry"],
                        exit_price=exit_price,
                        stop_loss=open_trade["sl"],
                        take_profit=open_trade["tp"],
                        pips=round(pips, 1),
                        profit_loss=round(pnl, 2),
                        outcome=outcome,
                        exit_reason=reason,
                    )
                )
                open_trade = None

        # --- Check for new signal ---
        if open_trade is not None:
            continue

        if is_filtered:
            sig = signal_fn(
                window, fast, slow, trend_ema_period, atr_period, atr_min_pips, adx_threshold
            )
        else:
            sig = signal_fn(window, fast, slow)

        if sig is None:
            continue

        current_atr = atr(window, atr_period)
        if current_atr <= 0:
            current_atr = 0.0001

        entry = sig.entry
        if sig.direction == TradeDirection.LONG:
            sl = entry - current_atr * atr_mult
            tp = entry + current_atr * atr_mult * 2.0
        else:
            sl = entry + current_atr * atr_mult
            tp = entry - current_atr * atr_mult * 2.0

        open_trade = {
            "direction": sig.direction,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "entry_time": bar.time,
            "entry_bar": i,
        }

    # --- Close any remaining open trade at last close ---
    if open_trade is not None:
        last_bar = bars[-1]
        pnl, pips, outcome = _close_trade(
            open_trade, last_bar.close, balance, risk_pct, starting_balance
        )
        balance += pnl
        closed_trades.append(
            TradeRecord(
                direction=open_trade["direction"].value,
                entry_time=open_trade["entry_time"].isoformat(),
                exit_time=last_bar.time.isoformat(),
                entry_price=open_trade["entry"],
                exit_price=last_bar.close,
                stop_loss=open_trade["sl"],
                take_profit=open_trade["tp"],
                pips=round(pips, 1),
                profit_loss=round(pnl, 2),
                outcome=outcome,
                exit_reason="end_of_data",
            )
        )

    return _compute_stats(closed_trades, starting_balance, balance, max_dd)


def _check_exit(trade: dict, bar: Bar) -> tuple[bool, float, str]:
    if trade["direction"] == TradeDirection.LONG:
        if bar.low <= trade["sl"]:
            return True, trade["sl"], "stop_loss"
        if bar.high >= trade["tp"]:
            return True, trade["tp"], "take_profit"
    else:
        if bar.high >= trade["sl"]:
            return True, trade["sl"], "stop_loss"
        if bar.low <= trade["tp"]:
            return True, trade["tp"], "take_profit"
    return False, 0.0, ""


def _close_trade(
    trade: dict, exit_price: float, balance: float, risk_pct: float, starting: float
) -> tuple[float, float, str]:
    pv = pip_value(trade["entry"])
    if trade["direction"] == TradeDirection.LONG:
        pips = (exit_price - trade["entry"]) / pv
    else:
        pips = (trade["entry"] - exit_price) / pv

    risk_amount = starting * risk_pct
    sl_pips = abs(trade["entry"] - trade["sl"]) / pv
    if sl_pips == 0:
        sl_pips = 1.0
    pip_value_dollar = risk_amount / sl_pips
    pnl = pips * pip_value_dollar

    if pnl > 0.01:
        outcome = "win"
    elif pnl < -0.01:
        outcome = "loss"
    else:
        outcome = "breakeven"

    return pnl, pips, outcome


def _compute_stats(
    trades: list[TradeRecord], starting: float, ending: float, max_dd: float
) -> BacktestStats:
    if not trades:
        return BacktestStats()

    wins = [t for t in trades if t.outcome == "win"]
    losses = [t for t in trades if t.outcome == "loss"]
    total_w = sum(t.profit_loss for t in wins)
    total_l = abs(sum(t.profit_loss for t in losses))

    win_rate = len(wins) / len(trades) * 100
    profit_factor = total_w / total_l if total_l > 0 else (total_w if total_w > 0 else 0.0)
    avg_win = total_w / len(wins) if wins else 0.0
    avg_loss = total_l / len(losses) if losses else 0.0
    expectancy = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)

    return BacktestStats(
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate=round(win_rate, 2),
        profit_factor=round(profit_factor, 2),
        total_pnl=round(ending - starting, 2),
        max_drawdown_pct=round(max_dd, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        expectancy=round(expectancy, 2),
        trades=[asdict(t) for t in trades],
    )


# ---------------------------------------------------------------------------
# Statistical significance (simplified)
# ---------------------------------------------------------------------------

def statistical_significance(baseline: BacktestStats, filtered: BacktestStats) -> dict:
    """Compute basic statistical comparison.

    Uses a simple z-test on the difference in win rates with normal
    approximation.  This is a rough heuristic — proper backtest
    statistics would account for serial correlation.
    """
    n_b = baseline.total_trades
    n_f = filtered.total_trades

    if n_b == 0 or n_f == 0:
        return {
            "test": "z-test win-rate difference",
            "z_score": None,
            "p_value": None,
            "significant_at_0_05": False,
            "note": "Insufficient trades for statistical test",
        }

    p_b = baseline.win_rate / 100
    p_f = filtered.win_rate / 100

    # Pooled standard error
    p_pool = (baseline.winning_trades + filtered.winning_trades) / (n_b + n_f)
    if p_pool == 0 or p_pool == 1:
        se = 0.0
    else:
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_b + 1 / n_f))

    z = (p_f - p_b) / se if se > 0 else 0.0

    # Two-tailed p-value approximation
    p_value = 2 * (1 - _normal_cdf(abs(z)))

    return {
        "test": "z-test win-rate difference",
        "z_score": round(z, 4),
        "p_value": round(p_value, 4),
        "significant_at_0_05": p_value < 0.05,
        "note": (
            "Normal-approximation z-test on win-rate difference. "
            "Does not account for serial correlation in returns."
        ),
    }


def _normal_cdf(x: float) -> float:
    """Approximate the standard normal CDF using the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_report(
    baseline: BacktestStats,
    filtered: BacktestStats,
    data_path: str,
    bars_loaded: int,
    params: dict,
) -> dict:
    """Build the final JSON comparison report."""
    stats = statistical_significance(baseline, filtered)

    # Determine verdict
    wr_improved = filtered.win_rate > baseline.win_rate
    pf_improved = filtered.profit_factor > baseline.profit_factor
    dd_improved = filtered.max_drawdown_pct < baseline.max_drawdown_pct

    improvements = sum([wr_improved, pf_improved, dd_improved])
    if improvements >= 2 and stats["significant_at_0_05"]:
        verdict = "IMPROVES"
    elif improvements >= 2:
        verdict = "IMPROVES (not statistically significant)"
    elif improvements == 0:
        verdict = "DOES NOT IMPROVE"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "report_title": "Trend + ATR Filter Validation (BQ-545)",
        "generated_at": datetime.now(_UTC).isoformat(),
        "data_source": data_path,
        "bars_loaded": bars_loaded,
        "sample_size": {
            "baseline_trades": baseline.total_trades,
            "filtered_trades": filtered.total_trades,
        },
        "parameters": params,
        "baseline_stats": {
            "total_trades": baseline.total_trades,
            "winning_trades": baseline.winning_trades,
            "losing_trades": baseline.losing_trades,
            "win_rate": baseline.win_rate,
            "profit_factor": baseline.profit_factor,
            "total_pnl": baseline.total_pnl,
            "max_drawdown_pct": baseline.max_drawdown_pct,
            "avg_win": baseline.avg_win,
            "avg_loss": baseline.avg_loss,
            "expectancy": baseline.expectancy,
        },
        "filtered_stats": {
            "total_trades": filtered.total_trades,
            "winning_trades": filtered.winning_trades,
            "losing_trades": filtered.losing_trades,
            "win_rate": filtered.win_rate,
            "profit_factor": filtered.profit_factor,
            "total_pnl": filtered.total_pnl,
            "max_drawdown_pct": filtered.max_drawdown_pct,
            "avg_win": filtered.avg_win,
            "avg_loss": filtered.avg_loss,
            "expectancy": filtered.expectancy,
        },
        "comparison": {
            "win_rate_delta": round(filtered.win_rate - baseline.win_rate, 2),
            "profit_factor_delta": round(filtered.profit_factor - baseline.profit_factor, 2),
            "max_drawdown_delta": round(
                filtered.max_drawdown_pct - baseline.max_drawdown_pct, 2
            ),
            "trade_count_reduction": baseline.total_trades - filtered.total_trades,
        },
        "statistical_significance": stats,
        "verdict": verdict,
        "filter_description": (
            "Trend filter: EMA(50) slope must confirm trade direction "
            "(rising for longs, falling for shorts). "
            "ATR gate: ATR(14) must be >= {atr_min} pips to ensure "
            "sufficient volatility for the signal.".format(
                atr_min=params.get("atr_min_pips", DEFAULT_ATR_MIN_PIPS)
            )
        ),
        "source_references": [
            "strategy_legacy.py: MomentumBreakoutStrategy (EMA + ADX + ATR pattern)",
            "strategy_legacy.py: KeltnerChannelBreakoutStrategy (EMA + ATR + ADX pattern)",
            "strategy_legacy.py: SupertrendRSIBlendStrategy (atr_min_pips gate pattern)",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate trend+ATR filter combination against backtest data"
    )
    parser.add_argument(
        "--data",
        default=str(DEFAULT_DATA_PATH),
        help=f"Path to OHLCV CSV (default: {DEFAULT_DATA_PATH})",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output JSON file path (default: stdout)",
    )
    parser.add_argument("--fast-ma", type=int, default=DEFAULT_FAST_MA)
    parser.add_argument("--slow-ma", type=int, default=DEFAULT_SLOW_MA)
    parser.add_argument("--trend-ema", type=int, default=DEFAULT_TREND_EMA)
    parser.add_argument("--atr-period", type=int, default=DEFAULT_ATR_PERIOD)
    parser.add_argument("--atr-min-pips", type=float, default=DEFAULT_ATR_MIN_PIPS)
    parser.add_argument("--adx-threshold", type=float, default=DEFAULT_ADX_THRESHOLD)
    args = parser.parse_args()

    data_path = args.data
    if not Path(data_path).exists():
        print(f"ERROR: data file not found: {data_path}", file=sys.stderr)
        print(
            "Specify a path with --data, or ensure the default historical data exists.",
            file=sys.stderr,
        )
        return 1

    print(f"Loading bars from {data_path}...", file=sys.stderr)
    bars = load_csv_bars(data_path)
    if len(bars) < 200:
        print(f"ERROR: only {len(bars)} bars loaded — need at least 200", file=sys.stderr)
        return 1
    print(f"Loaded {len(bars)} bars.", file=sys.stderr)

    params = {
        "fast_ma": args.fast_ma,
        "slow_ma": args.slow_ma,
        "trend_ema_period": args.trend_ema,
        "atr_period": args.atr_period,
        "atr_min_pips": args.atr_min_pips,
        "adx_threshold": args.adx_threshold,
        "starting_balance": DEFAULT_STARTING_BALANCE,
        "risk_per_trade_pct": DEFAULT_RISK_PER_TRADE_PCT,
    }

    print("Running baseline backtest (MA cross, no filters)...", file=sys.stderr)
    baseline = simulate(
        bars,
        evaluate_baseline,
        fast=args.fast_ma,
        slow=args.slow_ma,
    )
    print(
        f"  Baseline: {baseline.total_trades} trades, "
        f"WR={baseline.win_rate:.1f}%, PF={baseline.profit_factor:.2f}, "
        f"MaxDD={baseline.max_drawdown_pct:.2f}%",
        file=sys.stderr,
    )

    print("Running filtered backtest (MA cross + trend EMA + ATR gate)...", file=sys.stderr)
    filtered = simulate(
        bars,
        evaluate_filtered,
        fast=args.fast_ma,
        slow=args.slow_ma,
        trend_ema_period=args.trend_ema,
        atr_period=args.atr_period,
        atr_min_pips=args.atr_min_pips,
        adx_threshold=args.adx_threshold,
    )
    print(
        f"  Filtered: {filtered.total_trades} trades, "
        f"WR={filtered.win_rate:.1f}%, PF={filtered.profit_factor:.2f}, "
        f"MaxDD={filtered.max_drawdown_pct:.2f}%",
        file=sys.stderr,
    )

    report = build_report(baseline, filtered, data_path, len(bars), params)
    report_json = json.dumps(report, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(report_json)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report_json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
