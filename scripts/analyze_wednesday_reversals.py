#!/usr/bin/env python3
"""Run Q3 Wednesday Midweek Reversal analysis against historical data."""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "forex-bot"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backtest.data_loader import CsvDataLoader
from backtest.wednesday_reversal import WednesdayReversalStudy


def main() -> None:
    data_dir = Path(__file__).resolve().parent.parent / "data" / "forex" / "historical"
    report_dir = Path(__file__).resolve().parent.parent / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    start = datetime(2023, 1, 1)
    end = datetime(2025, 12, 31)

    instruments = [
        ("EURUSD_D1.csv", "EURUSD"),
        ("GBPUSD_D1.csv", "GBPUSD"),
        ("USDJPY_D1.csv", "USDJPY"),
    ]

    loader = CsvDataLoader()

    all_bars: dict[str, list] = {}
    for filename, instrument in instruments:
        filepath = str(data_dir / filename)
        bars = loader.load(filepath)
        all_bars[instrument] = bars
        print(f"Loaded {len(bars)} bars for {instrument}")

    study = WednesdayReversalStudy()
    results = study.run_multi_instrument(all_bars, start, end)

    for r in results:
        res = r.results
        wed = res.get("wednesday", {})
        tue = res.get("tuesday", {})
        thu = res.get("thursday", {})
        print(f"\n=== {r.instrument} ===")
        print(
            f"Wed: {wed.get('reversals', 0)}/{wed.get('total', 0)} "
            f"= {res.get('wednesday_reversal_rate', 0):.1%} reversal rate, "
            f"avg {res.get('avg_reversal_pips', 0):.1f} pips"
        )
        print(
            f"Tue: {tue.get('reversals', 0)}/{tue.get('total', 0)} "
            f"= {res.get('vs_tuesday_rate', 0):.1%}"
        )
        print(
            f"Thu: {thu.get('reversals', 0)}/{thu.get('total', 0)} "
            f"= {res.get('vs_thursday_rate', 0):.1%}"
        )
        print(f"PASS (Wed >= 50%): {r.go_nogo}")

    eurusd = results[0]
    res = eurusd.results
    summary = {
        "question": "Q3",
        "test_period": f"{start.date()} to {end.date()}",
        "instrument": "EURUSD",
        "timeframe": "D1",
        "sample_size": eurusd.sample_size,
        "results": {
            "wednesday_reversal_rate": res.get("wednesday_reversal_rate", 0),
            "avg_reversal_pips": res.get("avg_reversal_pips", 0),
            "vs_tuesday_rate": res.get("vs_tuesday_rate", 0),
            "vs_thursday_rate": res.get("vs_thursday_rate", 0),
            "gbpusd_wed_rate": results[1].results.get("wednesday_reversal_rate", 0),
            "usdjpy_wed_rate": results[2].results.get("wednesday_reversal_rate", 0),
        },
        "pass": eurusd.go_nogo,
        "notes": (
            f"Direction-corrected reversal rate in EURUSD: "
            f"{res.get('wednesday_reversal_rate', 0):.1%} "
            f"({res.get('wednesday', {}).get('reversals', 0)}/"
            f"{res.get('wednesday', {}).get('total', 0)}). "
            f"Tue: {res.get('vs_tuesday_rate', 0):.1%}, "
            f"Thu: {res.get('vs_thursday_rate', 0):.1%}. "
            f"GBPUSD: {results[1].results.get('wednesday_reversal_rate', 0):.1%}, "
            f"USDJPY: {results[2].results.get('wednesday_reversal_rate', 0):.1%}."
        ),
    }

    print("\n=== SUMMARY JSON ===")
    print(json.dumps(summary, indent=2))

    report_path = report_dir / "backtest_q3_wednesday_reversal_results.json"
    report_path.write_text(json.dumps(summary, indent=2))
    print(f"\nResults saved to {report_path}")


if __name__ == "__main__":
    main()
