#!/usr/bin/env python3
"""
Wednesday Midweek Reversal Frequency Analysis

Analyzes whether Wednesday consistently produces reversal patterns in major forex pairs.
Question Q3 from backtest questions.
"""

from datetime import datetime
from typing import List, Dict
import csv


def load_bars(filepath: str) -> List[Dict]:
    bars = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.strptime(row['Date'], '%Y-%m-%d %H:%M')
            bars.append({
                'date': dt,
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
            })
    return bars


def day_of_week(dt: datetime) -> str:
    return ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][dt.weekday()]


def pips_diff(diff: float, instrument: str) -> float:
    if instrument == 'USDJPY':
        return abs(diff) * 100
    return abs(diff) * 10000


def analyze_reversals(bars: List[Dict], instrument: str, start_date: str, end_date: str) -> Dict:
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    filtered = [b for b in bars if start <= b['date'] <= end]
    filtered.sort(key=lambda x: x['date'])

    wed_reversals = []
    tue_reversals = []
    thu_reversals = []

    wed_total = 0
    tue_total = 0
    thu_total = 0

    for i in range(1, len(filtered)):
        prev_bar = filtered[i - 1]
        curr_bar = filtered[i]

        prev_dow = day_of_week(prev_bar['date'])
        curr_dow = day_of_week(curr_bar['date'])

        close_diff = curr_bar['close'] - prev_bar['close']
        close_diff_pips = pips_diff(close_diff, instrument)

        bar_range = curr_bar['high'] - curr_bar['low']
        bar_range_pips = pips_diff(bar_range, instrument)

        if curr_dow == 'Wed':
            wed_total += 1
            if prev_dow == 'Tue':
                reversal_pips = pips_diff(abs(close_diff), instrument)
                if reversal_pips >= 50:
                    direction = 'bullish' if close_diff > 0 else 'bearish'
                    wed_reversals.append({
                        'date': curr_bar['date'].strftime('%Y-%m-%d'),
                        'close_diff': close_diff_pips,
                        'direction': direction,
                        'range': bar_range_pips,
                    })

        elif curr_dow == 'Tue':
            tue_total += 1
            if prev_dow == 'Mon':
                reversal_pips = pips_diff(abs(close_diff), instrument)
                if reversal_pips >= 50:
                    direction = 'bullish' if close_diff > 0 else 'bearish'
                    tue_reversals.append({
                        'date': curr_bar['date'].strftime('%Y-%m-%d'),
                        'close_diff': close_diff_pips,
                        'direction': direction,
                        'range': bar_range_pips,
                    })

        elif curr_dow == 'Thu':
            thu_total += 1
            if prev_dow == 'Wed':
                reversal_pips = pips_diff(abs(close_diff), instrument)
                if reversal_pips >= 50:
                    direction = 'bullish' if close_diff > 0 else 'bearish'
                    thu_reversals.append({
                        'date': curr_bar['date'].strftime('%Y-%m-%d'),
                        'close_diff': close_diff_pips,
                        'direction': direction,
                        'range': bar_range_pips,
                    })

    wed_rate = len(wed_reversals) / wed_total if wed_total > 0 else 0
    tue_rate = len(tue_reversals) / tue_total if tue_total > 0 else 0
    thu_rate = len(thu_reversals) / thu_total if thu_total > 0 else 0

    avg_wed_pips = sum(r['close_diff'] for r in wed_reversals) / len(wed_reversals) if wed_reversals else 0
    avg_tue_pips = sum(r['close_diff'] for r in tue_reversals) / len(tue_reversals) if tue_reversals else 0
    avg_thu_pips = sum(r['close_diff'] for r in thu_reversals) / len(thu_reversals) if thu_reversals else 0

    return {
        'instrument': instrument,
        'test_period': f'{start_date} to {end_date}',
        'sample_size': wed_total,
        'wednesday': {
            'total': wed_total,
            'reversals': len(wed_reversals),
            'rate': round(wed_rate, 2),
            'avg_pips': round(avg_wed_pips, 1),
            'details': wed_reversals,
        },
        'tuesday': {
            'total': tue_total,
            'reversals': len(tue_reversals),
            'rate': round(tue_rate, 2),
            'avg_pips': round(avg_tue_pips, 1),
        },
        'thursday': {
            'total': thu_total,
            'reversals': len(thu_reversals),
            'rate': round(thu_rate, 2),
            'avg_pips': round(avg_thu_pips, 1),
        },
        'pass': wed_rate >= 0.50,
    }


def main():
    data_dir = '/home/TacoPants/projects/Ayumi/worktrees/junior-dev-2/data/forex/historical'
    start = '2024-01-01'
    end = '2025-12-31'

    instruments = [
        ('EURUSD_D1.csv', 'EURUSD'),
        ('GBPUSD_D1.csv', 'GBPUSD'),
        ('USDJPY_D1.csv', 'USDJPY'),
    ]

    results = []
    for filename, instrument in instruments:
        filepath = f'{data_dir}/{filename}'
        bars = load_bars(filepath)
        result = analyze_reversals(bars, instrument, start, end)
        results.append(result)
        print(f'\n=== {instrument} ===')
        print(f'Wednesday: {result["wednesday"]["reversals"]}/{result["wednesday"]["total"]} = {result["wednesday"]["rate"]:.0%} reversal rate, avg {result["wednesday"]["avg_pips"]:.1f} pips')
        print(f'Tuesday: {result["tuesday"]["reversals"]}/{result["tuesday"]["total"]} = {result["tuesday"]["rate"]:.0%}')
        print(f'Thursday: {result["thursday"]["reversals"]}/{result["thursday"]["total"]} = {result["thursday"]["rate"]:.0%}')
        print(f'PASS: {result["pass"]}')

    eurusd = results[0]
    print('\n=== SUMMARY ===')
    print('Question: Q3')
    print(f'Test period: {start} to {end}')
    print('Instrument: EURUSD (primary)')
    print('Timeframe: D1')
    print(f'Sample size: {eurusd["sample_size"]} Wednesdays')
    print('Results:')
    print(f'  wednesday_reversal_rate: {eurusd["wednesday"]["rate"]}')
    print(f'  avg_reversal_pips: {eurusd["wednesday"]["avg_pips"]}')
    print(f'  vs_tuesday_rate: {eurusd["tuesday"]["rate"]}')
    print(f'  vs_thursday_rate: {eurusd["thursday"]["rate"]}')
    print(f'Pass: {eurusd["pass"]}')
    if eurusd["wednesday"]["details"]:
        print('Wednesday reversals:')
        for d in eurusd["wednesday"]["details"]:
            print(f'  {d["date"]}: {d["direction"]} {d["close_diff"]:.1f} pips')


if __name__ == '__main__':
    main()