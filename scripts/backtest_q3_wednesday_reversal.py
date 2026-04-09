#!/usr/bin/env python3
"""
BACKTEST Q3: Wednesday Midweek Reversal Frequency

Question: Does Wednesday consistently produce reversal patterns in major forex pairs?

Methodology:
- Load EURUSD D1 data
- For each Wednesday, determine if price reversed from the Tuesday direction
- A reversal = Wednesday close is on opposite side of Tuesday's open-to-close direction
- Compare reversal rates across Tue/Wed/Thu
- Also check reversal magnitude (>50 pips from Tuesday close)

Pass Criteria: Wednesday reversal rate >=50%
"""

import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.data_loader import CsvDataLoader
from backtest.engine import Bar

PIP_VALUE = 0.0001


def group_by_weekday(bars: list[Bar]) -> dict[int, list[Bar]]:
    """Group bars by day of week (0=Monday, 6=Sunday)."""
    by_day = {}
    for bar in bars:
        dow = bar.time.weekday()
        if dow not in by_day:
            by_day[dow] = []
        by_day[dow].append(bar)
    return by_day


def compute_bar_direction(bar: Bar) -> int:
    """Return 1 if bar closed up, -1 if closed down, 0 if flat."""
    diff = bar.close - bar.open
    if abs(diff) < PIP_VALUE * 0.1:
        return 0
    return 1 if diff > 0 else -1


def analyze_reversals(bars: list[Bar]) -> dict:
    """
    For each day, check if it reversed from the previous day's direction.
    A reversal occurs when:
    - Previous day direction != 0 (had a clear direction)
    - Current day direction is opposite
    """
    if len(bars) < 3:
        return {"error": "Insufficient data"}

    start_date = bars[0].time.strftime("%Y-%m-%d")
    end_date = bars[-1].time.strftime("%Y-%m-%d")

    pip_value = PIP_VALUE
    reversal_threshold_pips = 50

    day_stats: dict[int, dict] = {}
    for dow in range(5):
        day_stats[dow] = {
            "total": 0,
            "reversals": 0,
            "continuations": 0,
            "flat_prev": 0,
            "reversal_pips": [],
            "continuation_pips": [],
        }

    wednesday_reversal_details = []

    for i in range(1, len(bars)):
        prev_bar = bars[i - 1]
        curr_bar = bars[i]
        prev_dow = prev_bar.time.weekday()
        curr_dow = curr_bar.time.weekday()

        if curr_dow > 4:
            continue

        prev_dir = compute_bar_direction(prev_bar)
        curr_dir = compute_bar_direction(curr_bar)

        if prev_dir == 0:
            day_stats[curr_dow]["flat_prev"] += 1
            continue

        day_stats[curr_dow]["total"] += 1

        pip_move = abs(curr_bar.close - prev_bar.close) / pip_value

        if curr_dir != 0 and curr_dir != prev_dir:
            day_stats[curr_dow]["reversals"] += 1
            day_stats[curr_dow]["reversal_pips"].append(pip_move)
        else:
            day_stats[curr_dow]["continuations"] += 1
            day_stats[curr_dow]["continuation_pips"].append(pip_move)

        if curr_dow == 2 and prev_dow == 1:
            is_reversal = curr_dir != 0 and curr_dir != prev_dir
            wednesday_reversal_details.append(
                {
                    "date": curr_bar.time.strftime("%Y-%m-%d"),
                    "tue_open": prev_bar.open,
                    "tue_close": prev_bar.close,
                    "tue_dir": "up" if prev_dir == 1 else "down",
                    "wed_open": curr_bar.open,
                    "wed_close": curr_bar.close,
                    "wed_dir": "up"
                    if curr_dir == 1
                    else "down"
                    if curr_dir == -1
                    else "flat",
                    "reversal": is_reversal,
                    "pip_move": round(pip_move, 1),
                }
            )

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    results_by_day = {}
    for dow in range(5):
        stats = day_stats[dow]
        total = stats["total"]
        reversal_rate = stats["reversals"] / total if total > 0 else 0.0
        avg_rev_pips = (
            sum(stats["reversal_pips"]) / len(stats["reversal_pips"])
            if stats["reversal_pips"]
            else 0.0
        )
        big_reversals = sum(
            1 for p in stats["reversal_pips"] if p >= reversal_threshold_pips
        )
        big_reversal_rate = big_reversals / total if total > 0 else 0.0
        results_by_day[day_names[dow]] = {
            "total_days": total,
            "reversals": stats["reversals"],
            "reversal_rate": round(reversal_rate, 2),
            "avg_reversal_pips": round(avg_rev_pips, 1),
            "big_reversals_50pips": big_reversals,
            "big_reversal_rate": round(big_reversal_rate, 2),
        }

    wed = results_by_day["Wednesday"]
    passes = wed["reversal_rate"] >= 0.50

    results = {
        "question": "Q3",
        "test_period": f"{start_date} to {end_date}",
        "instrument": "EURUSD",
        "timeframe": "D1",
        "sample_size": wed["total_days"],
        "results": {
            "wednesday_reversal_rate": wed["reversal_rate"],
            "avg_reversal_pips": wed["avg_reversal_pips"],
            "vs_tuesday_rate": results_by_day["Tuesday"]["reversal_rate"],
            "vs_thursday_rate": results_by_day["Thursday"]["reversal_rate"],
        },
        "pass": passes,
        "notes": (
            f"Wednesday reversal rate: {wed['reversal_rate'] * 100:.0f}%. "
            f"Tuesday: {results_by_day['Tuesday']['reversal_rate'] * 100:.0f}%, "
            f"Thursday: {results_by_day['Thursday']['reversal_rate'] * 100:.0f}%. "
            f"Avg Wednesday reversal: {wed['avg_reversal_pips']:.1f} pips."
        ),
        "by_day": results_by_day,
        "methodology": {
            "reversal_definition": "Current day close direction opposite to previous day open-close direction",
            "data": "EURUSD D1 bars",
            "big_reversal_threshold_pips": reversal_threshold_pips,
        },
    }

    return results


def main():
    data_dir = Path(
        "/home/TacoPants/projects/Ayumi/worktrees/junior-dev-1/data/forex/historical"
    )
    eurusd_file = data_dir / "EURUSD_D1.csv"

    loader = CsvDataLoader()
    bars = loader.load(str(eurusd_file))

    if len(bars) < 30:
        print("Error: Insufficient data")
        return

    results = analyze_reversals(bars)

    output_file = Path(
        "/home/TacoPants/projects/Ayumi/worktrees/junior-dev-1/reports/backtest_q3_wednesday_reversal.json"
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, indent=2))

    print(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    main()
