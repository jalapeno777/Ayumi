#!/usr/bin/env python3
"""Tests for Wednesday reversal analysis with corrected methodology."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from datetime import datetime
from analyze_wednesday_reversals import (
    day_of_week,
    to_pips,
    pips_magnitude,
    is_reversal,
    analyze_reversals,
)


def test_day_of_week():
    assert day_of_week(datetime(2025, 10, 1)) == 'Wed'
    assert day_of_week(datetime(2025, 10, 2)) == 'Thu'
    assert day_of_week(datetime(2025, 10, 3)) == 'Fri'
    assert day_of_week(datetime(2025, 10, 6)) == 'Mon'
    assert day_of_week(datetime(2025, 10, 7)) == 'Tue'


def test_to_pips_eurusd():
    assert to_pips(0.0050, 'EURUSD') == 50.0
    assert to_pips(-0.0050, 'EURUSD') == -50.0


def test_to_pips_usdjpy():
    assert to_pips(0.50, 'USDJPY') == 50.0
    assert to_pips(-0.50, 'USDJPY') == -50.0


def test_pips_magnitude():
    assert pips_magnitude(0.0050, 'EURUSD') == 50.0
    assert pips_magnitude(-0.0050, 'EURUSD') == 50.0
    assert pips_magnitude(0.50, 'USDJPY') == 50.0


def test_is_reversal_tue_up_wed_down():
    prev_diff = 0.0060
    curr_diff = -0.0070
    result, pips = is_reversal(prev_diff, curr_diff, 'EURUSD')
    assert result is True
    assert pips == 70.0


def test_is_reversal_tue_down_wed_up():
    prev_diff = -0.0060
    curr_diff = 0.0070
    result, pips = is_reversal(prev_diff, curr_diff, 'EURUSD')
    assert result is True
    assert pips == 70.0


def test_is_not_reversal_same_direction():
    prev_diff = 0.0060
    curr_diff = 0.0070
    result, pips = is_reversal(prev_diff, curr_diff, 'EURUSD')
    assert result is False


def test_is_not_reversal_below_threshold():
    prev_diff = 0.0060
    curr_diff = -0.0030
    result, pips = is_reversal(prev_diff, curr_diff, 'EURUSD')
    assert result is False
    assert pips == 30.0


def test_is_not_reversal_zero_prev():
    prev_diff = 0.0
    curr_diff = -0.0070
    result, pips = is_reversal(prev_diff, curr_diff, 'EURUSD')
    assert result is False


def test_is_reversal_usdjpy():
    prev_diff = 0.60
    curr_diff = -0.70
    result, pips = is_reversal(prev_diff, curr_diff, 'USDJPY')
    assert result is True
    assert pips == 70.0


def test_analyze_reversals_basic():
    bars = [
        {'date': datetime(2025, 9, 29), 'open': 1.0900, 'high': 1.0950, 'low': 1.0890, 'close': 1.0900},
        {'date': datetime(2025, 9, 30), 'open': 1.0900, 'high': 1.0960, 'low': 1.0890, 'close': 1.0950},
        {'date': datetime(2025, 10, 1), 'open': 1.0950, 'high': 1.1020, 'low': 1.0940, 'close': 1.1010},
        {'date': datetime(2025, 10, 2), 'open': 1.1010, 'high': 1.1020, 'low': 1.0990, 'close': 1.1000},
        {'date': datetime(2025, 10, 3), 'open': 1.1000, 'high': 1.1010, 'low': 1.0900, 'close': 1.0910},
        {'date': datetime(2025, 10, 6), 'open': 1.0910, 'high': 1.0960, 'low': 1.0900, 'close': 1.0950},
        {'date': datetime(2025, 10, 7), 'open': 1.0950, 'high': 1.1020, 'low': 1.0940, 'close': 1.1010},
        {'date': datetime(2025, 10, 8), 'open': 1.1010, 'high': 1.1020, 'low': 1.0950, 'close': 1.0960},
        {'date': datetime(2025, 10, 9), 'open': 1.0960, 'high': 1.0970, 'low': 1.0860, 'close': 1.0870},
        {'date': datetime(2025, 10, 10), 'open': 1.0870, 'high': 1.0920, 'low': 1.0860, 'close': 1.0910},
    ]
    result = analyze_reversals(bars, 'EURUSD', '2025-09-29', '2025-10-31')

    assert result['wednesday']['total'] == 2
    assert result['tuesday']['total'] == 2
    assert result['thursday']['total'] == 2


def test_analyze_reversals_wednesday_reversal_detected():
    bars = [
        {'date': datetime(2025, 10, 6), 'open': 1.1000, 'high': 1.1050, 'low': 1.0990, 'close': 1.1000},
        {'date': datetime(2025, 10, 7), 'open': 1.1000, 'high': 1.1080, 'low': 1.0990, 'close': 1.1070},
        {'date': datetime(2025, 10, 8), 'open': 1.1070, 'high': 1.1080, 'low': 1.0990, 'close': 1.1000},
        {'date': datetime(2025, 10, 9), 'open': 1.1000, 'high': 1.1010, 'low': 1.0900, 'close': 1.0920},
        {'date': datetime(2025, 10, 10), 'open': 1.0920, 'high': 1.0960, 'low': 1.0900, 'close': 1.0950},
    ]
    result = analyze_reversals(bars, 'EURUSD', '2025-10-01', '2025-10-31')

    assert result['wednesday']['reversals'] == 1
    assert result['wednesday']['details'][0]['prev_direction'] == 'bullish'
    assert result['wednesday']['details'][0]['reversal_direction'] == 'bearish'


def test_analyze_reversals_no_reversal_same_direction():
    bars = [
        {'date': datetime(2025, 10, 6), 'open': 1.1000, 'high': 1.1050, 'low': 1.0990, 'close': 1.1000},
        {'date': datetime(2025, 10, 7), 'open': 1.1000, 'high': 1.1080, 'low': 1.0990, 'close': 1.1070},
        {'date': datetime(2025, 10, 8), 'open': 1.1070, 'high': 1.1150, 'low': 1.1060, 'close': 1.1140},
        {'date': datetime(2025, 10, 9), 'open': 1.1140, 'high': 1.1150, 'low': 1.1060, 'close': 1.1070},
        {'date': datetime(2025, 10, 10), 'open': 1.1070, 'high': 1.1080, 'low': 1.1000, 'close': 1.1020},
    ]
    result = analyze_reversals(bars, 'EURUSD', '2025-10-01', '2025-10-31')

    assert result['wednesday']['reversals'] == 0
    assert result['wednesday']['rate'] == 0


def test_analyze_reversals_pass_threshold():
    bars = []
    dates = [
        datetime(2025, 9, 29), datetime(2025, 9, 30),
        datetime(2025, 10, 1), datetime(2025, 10, 2), datetime(2025, 10, 3),
        datetime(2025, 10, 6), datetime(2025, 10, 7), datetime(2025, 10, 8),
        datetime(2025, 10, 9), datetime(2025, 10, 10),
        datetime(2025, 10, 13), datetime(2025, 10, 14), datetime(2025, 10, 15),
        datetime(2025, 10, 16), datetime(2025, 10, 17),
        datetime(2025, 10, 20), datetime(2025, 10, 21), datetime(2025, 10, 22),
        datetime(2025, 10, 23), datetime(2025, 10, 24),
        datetime(2025, 10, 27), datetime(2025, 10, 28), datetime(2025, 10, 29),
        datetime(2025, 10, 30), datetime(2025, 10, 31),
    ]
    price = 1.1000
    for d in dates:
        bars.append({
            'date': d,
            'open': price,
            'high': price + 0.0100,
            'low': price - 0.0100,
            'close': price,
        })

    for i in range(len(bars)):
        dow = day_of_week(bars[i]['date'])
        if dow == 'Tue' and i > 0:
            bars[i]['close'] = bars[i - 1]['close'] + 0.0070
        elif dow == 'Wed' and i > 0:
            bars[i]['close'] = bars[i - 1]['close'] - 0.0070

    result = analyze_reversals(bars, 'EURUSD', '2025-09-29', '2025-12-31')
    assert result['wednesday']['rate'] >= 0.50
    assert result['pass'] is True


def test_weekend_gap_skipped():
    bars = [
        {'date': datetime(2025, 10, 3), 'open': 1.1000, 'high': 1.1100, 'low': 1.0900, 'close': 1.1070},
        {'date': datetime(2025, 10, 6), 'open': 1.1070, 'high': 1.1150, 'low': 1.1060, 'close': 1.0950},
        {'date': datetime(2025, 10, 7), 'open': 1.0950, 'high': 1.1000, 'low': 1.0900, 'close': 1.1000},
    ]
    result = analyze_reversals(bars, 'EURUSD', '2025-10-01', '2025-10-31')
    assert result['wednesday']['total'] == 0
    assert result['wednesday']['reversals'] == 0


def test_wrong_adjacent_day_skipped():
    bars = [
        {'date': datetime(2025, 10, 6), 'open': 1.1000, 'high': 1.1100, 'low': 1.0900, 'close': 1.1000},
        {'date': datetime(2025, 10, 7), 'open': 1.1000, 'high': 1.1100, 'low': 1.0900, 'close': 1.1000},
        {'date': datetime(2025, 10, 8), 'open': 1.1000, 'high': 1.1150, 'low': 1.0950, 'close': 1.0950},
    ]
    result = analyze_reversals(bars, 'EURUSD', '2025-10-01', '2025-10-31')
    assert result['wednesday']['total'] == 1
    assert result['wednesday']['reversals'] == 0


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
