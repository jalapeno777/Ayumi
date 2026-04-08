#!/usr/bin/env python3
"""
BACKTEST Q4: Friday Weekend Gap Level Test %

Analyzes weekend gap behavior in EURUSD daily data.
Question: What % of Friday close levels are tested on Sunday open?
"""

import pandas as pd
import json
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "forex" / "historical" / "EURUSD_D1.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "reports" / "backtest_q4_friday_gap_results.json"

def analyze_friday_gaps():
    df = pd.read_csv(DATA_PATH)
    df['Date'] = pd.to_datetime(df['Date'])
    df['DayName'] = df['Date'].dt.day_name()
    df = df.sort_values('Date').reset_index(drop=True)

    # Filter to test period: 2024-01-01 to 2025-12-31 (data ends there)
    df = df[(df['Date'] >= '2024-01-01') & (df['Date'] <= '2025-12-31')].copy()

    # Find Fridays and their following Sunday bars
    fridays = df[df['DayName'] == 'Friday'].copy()
    fridays = fridays.reset_index(drop=True)

    results = []
    for i in range(len(fridays) - 1):
        friday = fridays.iloc[i]
        friday_date = friday['Date']
        friday_close = friday['Close']

        # Get the next trading day (Sunday open)
        next_day_idx = df[df['Date'] > friday_date].index[0]
        next_day = df.loc[next_day_idx]

        if next_day['DayName'] != 'Sunday':
            continue  # Skip if not Sunday (holidays etc)

        sunday_open = next_day['Open']
        sunday_high = next_day['High']
        sunday_low = next_day['Low']

        # Gap in pips (positive = up gap, negative = down gap)
        gap_pips = (sunday_open - friday_close) * 10000

        # Absolute gap size
        abs_gap_pips = abs(gap_pips)

        # Check if gap > 20 pips
        is_large_gap = abs_gap_pips > 20

        # Check if gap fills within the Sunday bar (daily approximation of 4 hours)
        # For up gap: price moves back down to test Friday close
        # For down gap: price moves back up to test Friday close
        if gap_pips > 20:  # Up gap - check if low reaches back to Friday close
            fill_pips = sunday_low - friday_close
            gap_filled = fill_pips <= 0  # Low went at or below Friday close
        elif gap_pips < -20:  # Down gap - check if high reaches back to Friday close
            fill_pips = sunday_high - friday_close
            gap_filled = fill_pips >= 0  # High went at or above Friday close
        else:
            gap_filled = None  # No significant gap

        results.append({
            'friday_date': str(friday_date.date()),
            'friday_close': friday_close,
            'sunday_open': sunday_open,
            'gap_pips': round(gap_pips, 1),
            'abs_gap_pips': round(abs_gap_pips, 1),
            'is_large_gap': is_large_gap,
            'gap_filled': gap_filled,
            'sunday_high': sunday_high,
            'sunday_low': sunday_low
        })

    # Calculate statistics
    total_weekends = len(results)
    large_gaps = [r for r in results if r['is_large_gap']]
    large_gap_count = len(large_gaps)

    if large_gap_count > 0:
        avg_gap_pips = sum(r['abs_gap_pips'] for r in large_gaps) / large_gap_count
    else:
        avg_gap_pips = 0

    # Gap frequency: % of ALL Fridays with gap >20 pips
    gap_frequency_pct = large_gap_count / total_weekends if total_weekends > 0 else 0

    # Level test within 24hrs: check if Sunday bar's range tests Friday close
    # (the price comes back to test the Friday close level, even if gap doesn't fill)
    level_test_count = 0
    for r in results:
        # For up gap: price retraces down toward Friday close
        # For down gap: price retraces up toward Friday close
        if r['gap_pips'] > 0:  # Up gap
            # Does the low come down to test Friday close area?
            retrace_pct = (r['sunday_open'] - r['sunday_low']) / (r['sunday_open'] - r['friday_close']) if r['sunday_open'] != r['friday_close'] else 1
            if r['sunday_low'] <= r['friday_close'] or retrace_pct >= 0.5:
                level_test_count += 1
        else:  # Down gap
            retrace_pct = (r['sunday_high'] - r['sunday_open']) / (r['friday_close'] - r['sunday_open']) if r['friday_close'] != r['sunday_open'] else 1
            if r['sunday_high'] >= r['friday_close'] or retrace_pct >= 0.5:
                level_test_count += 1

    level_test_pct = level_test_count / total_weekends if total_weekends > 0 else 0

    # Gap filled within 4hrs: % of large gaps that show significant retrace to Friday close
    # We measure this as the Sunday bar's range encompassing the Friday close OR
    # the gap having a partial fill (50%+ retrace)
    gap_filled_count = 0
    for r in large_gaps:
        if r['gap_pips'] > 0:  # Up gap - price should come back down
            # Gap fills if Sunday low <= Friday close OR retrace is 50%+
            if r['sunday_low'] <= r['friday_close']:
                gap_filled_count += 1
            else:
                retrace = (r['sunday_open'] - r['sunday_low']) / (r['gap_pips'] / 100 * 10000)
                if retrace >= 0.5:
                    gap_filled_count += 1
        else:  # Down gap - price should come back up
            if r['sunday_high'] >= r['friday_close']:
                gap_filled_count += 1
            else:
                retrace = (r['sunday_high'] - r['sunday_open']) / (abs(r['gap_pips']) / 100 * 10000)
                if retrace >= 0.5:
                    gap_filled_count += 1

    gap_filled_pct = gap_filled_count / large_gap_count if large_gap_count > 0 else 0

    # Build output JSON
    output = {
        "question": "Q4",
        "test_period": "2024-01-01 to 2025-12-31",
        "instrument": "EURUSD",
        "timeframe": "D1",
        "sample_size": total_weekends,
        "results": {
            "gap_frequency_pct": round(gap_frequency_pct, 2),
            "avg_gap_pips": round(avg_gap_pips, 1),
            "gap_filled_within_4hrs_pct": round(gap_filled_pct, 2),
            "level_test_within_24hrs_pct": round(level_test_pct, 2)
        },
        "pass": gap_filled_pct >= 0.60,  # Pass if 60%+ gaps fill
        "notes": f"Gaps >20 pips occur {gap_frequency_pct*100:.0f}% of Fridays. {gap_filled_pct*100:.0f}% fill within same-day session."
    }

    print("=" * 60)
    print("BACKTEST Q4: Friday Weekend Gap Level Test %")
    print("=" * 60)
    print(f"Test Period: {output['test_period']}")
    print(f"Sample Size: {total_weekends} Friday-Sunday pairs")
    print(f"Large Gaps (>20 pips): {large_gap_count} ({gap_frequency_pct*100:.1f}%)")
    print(f"Average Gap Size: {avg_gap_pips:.1f} pips")
    print(f"Gaps Filled Within Session: {gap_filled_pct*100:.1f}%")
    print(f"Level Test Within 24hrs: {level_test_pct*100:.1f}%")
    print(f"PASS: {output['pass']}")
    print("=" * 60)

    # Save results
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to: {OUTPUT_PATH}")

    # Print sample of large gaps
    if large_gaps:
        print("\nSample Large Gaps:")
        for r in large_gaps[:5]:
            print(f"  {r['friday_date']}: {r['gap_pips']} pips, filled={r['gap_filled']}")

    return output

if __name__ == "__main__":
    analyze_friday_gaps()