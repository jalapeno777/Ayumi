#!/usr/bin/env python3
"""
SRMR+ Signal Drought Diagnostic

Traces which SRMR+ filters reject each bar during trading session hours.
Uses the same logic as SRMRPlusStrategy.evaluate() but with per-filter logging.
"""

import csv
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time  # noqa: F401

# ---------------------------------------------------------------------------
# Config mirrors (default SRMRPlusConfig)
# ---------------------------------------------------------------------------
ATR_PERIOD = 14
RSI_PERIOD = 14
RSI_LONG_LEVEL = 30.0
RSI_SHORT_LEVEL = 70.0
ADX_PERIOD = 14
ADX_MAX_THRESHOLD = 20.0
SESSION_RANGE_MIN_PIPS = 10.0
ENTRY_NEAR_EXTREME_PIPS = 8.0
EMA_TREND_PERIOD = 50
PIP_VALUE = 0.1  # XAUUSD pip = $0.10

# Session hours (UTC) — from config/sessions.py SessionRangeHours
LONDON_START = time(7, 0)
LONDON_END = time(11, 0)
NY_OPEN_START = time(12, 0)
NY_OPEN_END = time(15, 0)
LONDON_NY_OVERLAP_START = time(12, 0)
LONDON_NY_OVERLAP_END = time(16, 0)


def is_trading_session(bar_time):
    h = bar_time.hour
    return (
        LONDON_START.hour <= h < LONDON_END.hour
        or NY_OPEN_START.hour <= h < NY_OPEN_END.hour
        or LONDON_NY_OVERLAP_START.hour <= h < LONDON_NY_OVERLAP_END.hour
    )


def get_session_type(bar_time):
    h = bar_time.hour
    if LONDON_START.hour <= h < LONDON_END.hour:
        return "LONDON"
    if NY_OPEN_START.hour <= h < NY_OPEN_END.hour:
        return "NY_AM"
    if LONDON_NY_OVERLAP_START.hour <= h < LONDON_NY_OVERLAP_END.hour:
        return "OVERLAP"
    return "OUTSIDE"


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
def calc_atr(bars, period=14):
    if len(bars) < period + 1:
        return 0.0001
    tr_sum = 0.0
    count = 0
    for i in range(len(bars) - period, len(bars)):
        if i > 0:
            tr = max(
                bars[i]["high"] - bars[i]["low"],
                abs(bars[i]["high"] - bars[i - 1]["close"]),
                abs(bars[i]["low"] - bars[i - 1]["close"]),
            )
            tr_sum += tr
            count += 1
    return tr_sum / count if count > 0 else 0.0001


def calc_rsi(bars, period=14):
    if len(bars) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(len(bars) - period, len(bars)):
        change = bars[i]["close"] - bars[i - 1]["close"]
        gains.append(change if change > 0 else 0.0)
        losses.append(abs(change) if change < 0 else 0.0)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_adx(bars, period=14):
    if len(bars) < period * 2 + 1:
        return 0.0
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    plus_dm_list = []
    minus_dm_list = []
    tr_list = []
    for i in range(1, len(bars)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]
        plus_dm = high_diff if (high_diff > low_diff and high_diff > 0) else 0.0
        minus_dm = low_diff if (low_diff > high_diff and low_diff > 0) else 0.0
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    if len(tr_list) < period:
        return 0.0
    tr_sum = sum(tr_list[:period])
    plus_dm_sum = sum(plus_dm_list[:period])
    minus_dm_sum = sum(minus_dm_list[:period])
    if tr_sum == 0:
        return 0.0
    plus_di = (plus_dm_sum / tr_sum) * 100
    minus_di = (minus_dm_sum / tr_sum) * 100
    if plus_di + minus_di == 0:
        dx = 0.0
    else:
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    dx_list = [dx]
    for i in range(period, len(tr_list)):
        tr_sum = tr_sum - tr_sum / period + tr_list[i]
        plus_dm_sum = plus_dm_sum - plus_dm_sum / period + plus_dm_list[i]
        minus_dm_sum = minus_dm_sum - minus_dm_sum / period + minus_dm_list[i]
        if tr_sum == 0:
            dx_list.append(0.0)
            continue
        plus_di = (plus_dm_sum / tr_sum) * 100
        minus_di = (minus_dm_sum / tr_sum) * 100
        if plus_di + minus_di == 0:
            dx_list.append(0.0)
        else:
            dx_list.append(100.0 * (abs(plus_di - minus_di) / (plus_di + minus_di)))
    if len(dx_list) < period:
        return 0.0
    adx = sum(dx_list[:period]) / period
    for dx in dx_list[period:]:
        adx = (adx * (period - 1) + dx) / period
    return adx


def find_previous_trading_day(bars, current_day):
    seen_days = set()
    for b in bars:
        d = b["time"].date()
        if d < current_day:
            seen_days.add(d)
    if not seen_days:
        return None
    return max(seen_days)


def calc_session_range(bars, session_type, reference_day):
    session_bars = []
    for b in bars:
        if b["time"].date() != reference_day:
            continue
        if get_session_type(b["time"]) == session_type:
            session_bars.append(b)
    if not session_bars:
        return 0.0, 0.0, 0.0
    high = max(b["high"] for b in session_bars)
    low = min(b["low"] for b in session_bars)
    mean = sum(b["close"] for b in session_bars) / len(session_bars)
    return high, low, mean


def get_previous_session_range(bars, current_day, current_session):
    if current_session == "LONDON":
        prev_day = find_previous_trading_day(bars, current_day)
        if prev_day is None:
            return 0.0, 0.0, 0.0
        high, low, mean = calc_session_range(bars, "LONDON", prev_day)
        if high == 0:
            high, low, mean = calc_session_range(bars, "NY_AM", prev_day)
        return high, low, mean
    if current_session == "NY_AM" or current_session == "OVERLAP":
        high, low, mean = calc_session_range(bars, "LONDON", current_day)
        if high == 0:
            prev_day = find_previous_trading_day(bars, current_day)
            if prev_day is None:
                return 0.0, 0.0, 0.0
            high, low, mean = calc_session_range(bars, "LONDON", prev_day)
        return high, low, mean
    prev_day = find_previous_trading_day(bars, current_day)
    if prev_day is None:
        return 0.0, 0.0, 0.0
    high, low, mean = calc_session_range(bars, "LONDON", prev_day)
    if high == 0:
        high, low, mean = calc_session_range(bars, "NY_AM", prev_day)
    return high, low, mean


# ---------------------------------------------------------------------------
# Main diagnostic
# ---------------------------------------------------------------------------
def load_bars(csv_path):
    bars = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(
                {
                    "time": datetime.fromisoformat(row["Datetime"].replace("+00:00", "")),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(float(row["Volume"])),
                }
            )
    return bars


def diagnose_bar(bars, idx):
    """Return (rejection_reason, details_dict) for bar at idx."""
    latest = bars[idx]
    state_bars = bars[: idx + 1]

    min_required = max(ATR_PERIOD + RSI_PERIOD + 2, ADX_PERIOD * 2 + 1, EMA_TREND_PERIOD + 1)
    if len(state_bars) < min_required:
        return "insufficient_bars", {"have": len(state_bars), "need": min_required}

    if not is_trading_session(latest["time"]):
        return "outside_session", {"hour": latest["time"].hour}

    current_session = get_session_type(latest["time"])
    current_day = latest["time"].date()

    session_high, session_low, session_mean = get_previous_session_range(state_bars, current_day, current_session)
    if session_high == 0:
        return "no_prev_session_range", {"day": str(current_day), "session": current_session}

    session_range_price = session_high - session_low
    session_range_width = session_range_price / PIP_VALUE
    if session_range_width < SESSION_RANGE_MIN_PIPS:
        return "session_range_too_narrow", {
            "width_pips": session_range_width,
            "min_pips": SESSION_RANGE_MIN_PIPS,
        }

    adx = calc_adx(state_bars, ADX_PERIOD)
    if adx > ADX_MAX_THRESHOLD:
        return "adx_too_high", {"adx": adx, "max": ADX_MAX_THRESHOLD}

    atr = calc_atr(state_bars, ATR_PERIOD)
    if atr <= 0:
        return "atr_zero_neg", {"atr": atr}

    rsi = calc_rsi(state_bars, RSI_PERIOD)
    if rsi is None:
        return "rsi_none", {}

    price = latest["close"]
    entry_near_extreme_price = ENTRY_NEAR_EXTREME_PIPS * PIP_VALUE

    # LONG conditions
    near_low = price <= session_low + entry_near_extreme_price
    rsi_long_ok = rsi < RSI_LONG_LEVEL
    rsi_trend_long_ok = rsi < 50.0

    # SHORT conditions
    near_high = price >= session_high - entry_near_extreme_price
    rsi_short_ok = rsi > RSI_SHORT_LEVEL
    rsi_trend_short_ok = rsi > 50.0

    if near_low and rsi_long_ok and rsi_trend_long_ok:
        return "SIGNAL_LONG", {
            "price": price,
            "session_low": session_low,
            "rsi": rsi,
            "adx": adx,
            "range_pips": session_range_width,
        }

    if near_high and rsi_short_ok and rsi_trend_short_ok:
        return "SIGNAL_SHORT", {
            "price": price,
            "session_high": session_high,
            "rsi": rsi,
            "adx": adx,
            "range_pips": session_range_width,
        }

    # If we get here, report which sub-conditions failed
    return "no_entry_condition", {
        "price": price,
        "session_low": session_low,
        "session_high": session_high,
        "rsi": rsi,
        "adx": adx,
        "range_pips": session_range_width,
        "near_low": near_low,
        "near_high": near_high,
        "rsi_long_ok": rsi_long_ok,
        "rsi_short_ok": rsi_short_ok,
        "rsi_trend_long_ok": rsi_trend_long_ok,
        "rsi_trend_short_ok": rsi_trend_short_ok,
        "dist_from_low_pips": (price - session_low) / PIP_VALUE,
        "dist_from_high_pips": (session_high - price) / PIP_VALUE,
    }


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "data/forex/historical/XAUUSD_M15_fresh.csv"
    bars = load_bars(csv_path)
    print(f"Loaded {len(bars)} bars from {csv_path}")
    print(f"Date range: {bars[0]['time']} to {bars[-1]['time']}")
    print()

    # Analyze last N bars
    n = min(len(bars), int(sys.argv[2]) if len(sys.argv) > 2 else 2000)
    start = len(bars) - n

    rejection_counts = Counter()
    no_entry_details = defaultdict(list)
    signal_count = 0

    for i in range(start, len(bars)):
        reason, details = diagnose_bar(bars, i)
        rejection_counts[reason] += 1

        if reason.startswith("SIGNAL"):
            signal_count += 1
        elif reason == "no_entry_condition":
            # Track which sub-conditions fail
            for key in [
                "near_low",
                "near_high",
                "rsi_long_ok",
                "rsi_short_ok",
                "rsi_trend_long_ok",
                "rsi_trend_short_ok",
            ]:
                no_entry_details[key].append(details[key])

            # Also track RSI distribution and distance from extremes
            no_entry_details["rsi_values"].append(details["rsi"])
            no_entry_details["adx_values"].append(details["adx"])
            no_entry_details["dist_from_low"].append(details["dist_from_low_pips"])
            no_entry_details["dist_from_high"].append(details["dist_from_high_pips"])

    total = min(len(bars), n)
    print(f"=== SRMR+ Filter Rejection Analysis (last {total} bars) ===")
    print()
    print(f"Total bars analyzed: {total}")
    print(f"Signals generated: {signal_count}")
    print()
    print("Rejection breakdown:")
    for reason, count in rejection_counts.most_common():
        pct = 100 * count / total
        print(f"  {reason:30s} {count:6d} ({pct:5.1f}%)")

    print()
    # Only look at bars that passed all filters except entry conditions
    no_entry_count = rejection_counts.get("no_entry_condition", 0)
    if no_entry_count > 0:
        print(f"=== 'No entry condition' sub-filter analysis ({no_entry_count} bars) ===")
        print()

        for key in ["near_low", "near_high", "rsi_long_ok", "rsi_short_ok", "rsi_trend_long_ok", "rsi_trend_short_ok"]:
            vals = no_entry_details[key]
            true_count = sum(1 for v in vals if v)
            print(f"  {key:25s} True: {true_count:5d}/{len(vals)} ({100 * true_count / len(vals):.1f}%)")

        print()
        rsi_vals = no_entry_details["rsi_values"]
        adx_vals = no_entry_details["adx_values"]
        dist_low = no_entry_details["dist_from_low"]
        dist_high = no_entry_details["dist_from_high"]

        if rsi_vals:
            print(f"  RSI distribution (bars in session, passed upstream filters):")  # noqa: F541
            print(f"    min={min(rsi_vals):.1f}  max={max(rsi_vals):.1f}  mean={sum(rsi_vals) / len(rsi_vals):.1f}")
            rsi_below_30 = sum(1 for r in rsi_vals if r < 30)
            rsi_above_70 = sum(1 for r in rsi_vals if r > 70)
            rsi_30_70 = sum(1 for r in rsi_vals if 30 <= r <= 70)
            print(f"    <30 (oversold): {rsi_below_30}  |  >70 (overbought): {rsi_above_70}  |  30-70: {rsi_30_70}")

        if adx_vals:
            print(f"  ADX distribution (these bars):")  # noqa: F541
            print(f"    min={min(adx_vals):.1f}  max={max(adx_vals):.1f}  mean={sum(adx_vals) / len(adx_vals):.1f}")

        if dist_low:
            print(f"  Distance from session low (pips):")  # noqa: F541
            print(f"    min={min(dist_low):.1f}  max={max(dist_low):.1f}  mean={sum(dist_low) / len(dist_low):.1f}")
            within_8_low = sum(1 for d in dist_low if d <= 8.0)
            print(
                f"    Within 8 pips of low: {within_8_low}/{len(dist_low)} ({100 * within_8_low / len(dist_low):.1f}%)"
            )

        if dist_high:
            print(f"  Distance from session high (pips):")  # noqa: F541
            print(f"    min={min(dist_high):.1f}  max={max(dist_high):.1f}  mean={sum(dist_high) / len(dist_high):.1f}")
            within_8_high = sum(1 for d in dist_high if d <= 8.0)
            print(
                f"    Within 8 pips of high: {within_8_high}/{len(dist_high)} ({100 * within_8_high / len(dist_high):.1f}%)"  # noqa: E501
            )  # noqa: E501

    # Also compute signal rate per day for recent data
    print()
    print("=== Signal rate per day (last 30 days of data) ===")
    daily_signals = defaultdict(lambda: {"evals": 0, "signals": 0})
    last_30_days_start = len(bars) - min(len(bars), 2880)  # ~30 days of M15 bars

    for i in range(last_30_days_start, len(bars)):
        reason, _ = diagnose_bar(bars, i)
        day = bars[i]["time"].date()
        daily_signals[day]["evals"] += 1
        if reason.startswith("SIGNAL"):
            daily_signals[day]["signals"] += 1

    for day in sorted(daily_signals.keys()):
        d = daily_signals[day]
        print(f"  {day}  evals={d['evals']:3d}  signals={d['signals']}")


if __name__ == "__main__":
    main()
