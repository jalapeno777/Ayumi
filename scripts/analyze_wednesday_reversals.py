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

    start = datetime(2025, 10, 1)
    end = datetime(2025, 12, 31)

    instruments = [
        ("EURUSD_D1.csv", "EURUSD"),
        ("GBPUSD_D1.csv", "GBPUSD"),
        ("USDJPY_D1.csv", "USDJPY"),
    ]

    loader = CsvDataLoader()
    study = WednesdayReversalStudy()

    all_bars: dict[str, list] = {}
    for filename, instrument in instruments:
        filepath = str(data_dir / filename)
        bars = loader.load(filepath)
        filtered = study.filter_by_date_range(bars, start, end)
        all_bars[instrument] = bars
        print(f"Loaded {len(bars)} bars for {instrument}, {len(filtered)} in range")

    results = study.run_multi_instrument(all_bars, start, end)

    for r in results:
        res = r.results
        print(f"\n=== {r.instrument} ===")
        wed = res.get("wednesday", {})
        print(
            f"Wednesday: {wed.get('reversals', 0)}/{wed.get('total', 0)} = "
            f"{res.get('wednesday_reversal_rate', 0):.0%} reversal rate, "
            f"avg {res.get('avg_reversal_pips', 0):.1f} pips"
        )
        tue = res.get("tuesday", {})
        print(
            f"Tuesday: {tue.get('reversals', 0)}/{tue.get('total', 0)} = "
            f"{res.get('vs_tuesday_rate', 0):.0%}"
        )
        thu = res.get("thursday", {})
        print(
            f"Thursday: {thu.get('reversals', 0)}/{thu.get('total', 0)} = "
            f"{res.get('vs_thursday_rate', 0):.0%}"
        )
        print(f"PASS: {r.go_nogo}")

    eurusd = results[0]
    print("\n=== EURUSD SUMMARY (primary) ===")
    print("Question: Q3")
    print(f"Test period: {eurusd.test_period_start} to {eurusd.test_period_end}")
    print(f"Instrument: {eurusd.instrument}")
    print(f"Timeframe: {eurusd.timeframe}")
    print(f"Sample size: {eurusd.sample_size} Wednesdays")
    res = eurusd.results
    print(f"  wednesday_reversal_rate: {res.get('wednesday_reversal_rate', 0)}")
    print(f"  avg_reversal_pips: {res.get('avg_reversal_pips', 0)}")
    print(f"  vs_tuesday_rate: {res.get('vs_tuesday_rate', 0)}")
    print(f"  vs_thursday_rate: {res.get('vs_thursday_rate', 0)}")
    print(f"  GBPUSD reversal rate: {results[1].results.get('wednesday_reversal_rate', 0)}")
    print(f"  USDJPY reversal rate: {results[2].results.get('wednesday_reversal_rate', 0)}")
    print(f"Pass: {eurusd.go_nogo}")

    output = {
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
            "gbpUSD_reversal_rate": results[1].results.get("wednesday_reversal_rate", 0),
            "usdJPY_reversal_rate": results[2].results.get("wednesday_reversal_rate", 0),
        },
        "pass": eurusd.go_nogo,
        "notes": eurusd.notes,
    }

    report_path = report_dir / "backtest_q3_wednesday_reversal_results.json"
    report_path.write_text(json.dumps(output, indent=2))
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
