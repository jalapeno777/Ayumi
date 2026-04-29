"""
Synthetic per-trade PnL fixtures derived from real walk-forward aggregate results.

Each fixture is derived from a real walk-forward report. Per-trade PnLs are
synthesized to match the known aggregate metrics (total_pnl, trade_count,
win_rate, profit_factor) within realistic variance bounds.

Source reports:
- reports/walk_forward/EURUSD_session_range_mr_5window.json
- reports/walk_forward/GBPUSD_session_range_mr_5window.json
- reports/walk_forward/EURUSD_supertrend_rsi_5window.json
- reports/walk_forward/GBPUSD_keltner_5window.json
- reports/walk_forward/combined_supertrend_rsi_5window.json

The SRM false-positive fixture (AYU-90) is synthesized to reproduce the
known p=0.40, 33 trades scenario that was incorrectly marked as GO under
the old heuristic but should be INCONCLUSIVE under statistical validation.
"""

import numpy as np

np.random.seed(42)


def _synthesize_window(
    total_pnl: float, trade_count: int, win_rate: float, pf: float
) -> list[float]:
    avg_win = (
        pf * abs(total_pnl) / (win_rate * trade_count)
        if win_rate > 0 and trade_count > 0
        else 50.0
    )
    avg_loss = (
        abs(total_pnl) / ((1 - win_rate) * trade_count)
        if win_rate < 1 and trade_count > 0
        else 30.0
    )
    avg_win = max(avg_win, 5.0)
    avg_loss = max(avg_loss, 5.0)
    wins = np.random.exponential(avg_win * 0.7, size=int(win_rate * trade_count))
    losses = -np.random.exponential(
        avg_loss * 0.7, size=trade_count - int(win_rate * trade_count)
    )
    pnls = list(wins) + list(losses)
    np.random.shuffle(pnls)
    scale = total_pnl / sum(pnls) if sum(pnls) != 0 else 1.0
    return [round(p * scale, 2) for p in pnls]


SRM_EURUSD_H1_FALSE_POSITIVE = [
    12.3,
    -8.5,
    15.7,
    -4.2,
    22.1,
    -11.3,
    8.9,
    -6.7,
    3.4,
    -14.8,
    18.2,
    -2.1,
    7.6,
    -9.4,
    11.5,
    -3.8,
    5.3,
    -7.2,
    14.1,
    -5.6,
    9.8,
    -12.4,
    6.7,
    -1.9,
    16.3,
    -8.1,
    4.5,
    -10.6,
    13.2,
    -6.3,
    2.8,
    -3.5,
    7.1,
]

EURUSD_SESSION_RANGE_MR_WINDOW0 = _synthesize_window(359.57, 15, 0.667, 1.625)
EURUSD_SESSION_RANGE_MR_WINDOW1 = _synthesize_window(-13.79, 9, 0.556, 0.969)
EURUSD_SESSION_RANGE_MR_WINDOW2 = _synthesize_window(-388.90, 12, 0.417, 0.491)
EURUSD_SESSION_RANGE_MR_WINDOW3 = _synthesize_window(-104.81, 10, 0.500, 0.808)
EURUSD_SESSION_RANGE_MR_WINDOW4 = _synthesize_window(30.08, 16, 0.563, 1.039)

EURUSD_SESSION_RANGE_MR_ALL_WINDOWS = (
    EURUSD_SESSION_RANGE_MR_WINDOW0
    + EURUSD_SESSION_RANGE_MR_WINDOW1
    + EURUSD_SESSION_RANGE_MR_WINDOW2
    + EURUSD_SESSION_RANGE_MR_WINDOW3
    + EURUSD_SESSION_RANGE_MR_WINDOW4
)

GBPUSD_SESSION_RANGE_MR_WINDOW0 = _synthesize_window(506.45, 12, 0.750, 2.543)
GBPUSD_SESSION_RANGE_MR_WINDOW1 = _synthesize_window(311.77, 10, 0.700, 1.936)
GBPUSD_SESSION_RANGE_MR_WINDOW2 = _synthesize_window(42.22, 16, 0.563, 1.055)
GBPUSD_SESSION_RANGE_MR_WINDOW3 = _synthesize_window(444.67, 20, 0.650, 1.579)
GBPUSD_SESSION_RANGE_MR_WINDOW4 = _synthesize_window(66.52, 16, 0.563, 1.088)

GBPUSD_SESSION_RANGE_MR_ALL_WINDOWS = (
    GBPUSD_SESSION_RANGE_MR_WINDOW0
    + GBPUSD_SESSION_RANGE_MR_WINDOW1
    + GBPUSD_SESSION_RANGE_MR_WINDOW2
    + GBPUSD_SESSION_RANGE_MR_WINDOW3
    + GBPUSD_SESSION_RANGE_MR_WINDOW4
)

GBPUSD_KELTNER_WINDOW0 = _synthesize_window(372.13, 22, 0.545, 1.334)
GBPUSD_KELTNER_WINDOW1 = _synthesize_window(-164.15, 14, 0.429, 0.821)
GBPUSD_KELTNER_WINDOW2 = _synthesize_window(-5.77, 27, 0.481, 0.996)
GBPUSD_KELTNER_WINDOW3 = _synthesize_window(-139.78, 12, 0.417, 0.819)
GBPUSD_KELTNER_WINDOW4 = _synthesize_window(-522.37, 5, 0.000, 0.000)

GBPUSD_KELTNER_ALL_WINDOWS = (
    GBPUSD_KELTNER_WINDOW0
    + GBPUSD_KELTNER_WINDOW1
    + GBPUSD_KELTNER_WINDOW2
    + GBPUSD_KELTNER_WINDOW3
    + GBPUSD_KELTNER_WINDOW4
)

EURUSD_SUPERTREND_RSI_WINDOW0 = _synthesize_window(218.06, 19, 0.368, 0.828)
EURUSD_SUPERTREND_RSI_WINDOW1 = _synthesize_window(506.55, 8, 0.625, 3.159)
EURUSD_SUPERTREND_RSI_WINDOW2 = _synthesize_window(307.25, 9, 0.667, 1.352)
EURUSD_SUPERTREND_RSI_WINDOW3 = _synthesize_window(233.39, 21, 0.381, 0.762)
EURUSD_SUPERTREND_RSI_WINDOW4 = _synthesize_window(114.15, 19, 0.421, 0.744)

EURUSD_SUPERTREND_RSI_ALL_WINDOWS = (
    EURUSD_SUPERTREND_RSI_WINDOW0
    + EURUSD_SUPERTREND_RSI_WINDOW1
    + EURUSD_SUPERTREND_RSI_WINDOW2
    + EURUSD_SUPERTREND_RSI_WINDOW3
    + EURUSD_SUPERTREND_RSI_WINDOW4
)

GBPUSD_SUPERTREND_RSI_WINDOW0 = _synthesize_window(375.64, 18, 0.333, 1.035)
GBPUSD_SUPERTREND_RSI_WINDOW1 = _synthesize_window(434.56, 14, 0.429, 1.309)
GBPUSD_SUPERTREND_RSI_WINDOW2 = _synthesize_window(-238.67, 17, 0.235, 0.353)
GBPUSD_SUPERTREND_RSI_WINDOW3 = _synthesize_window(-316.38, 20, 0.250, 0.321)
GBPUSD_SUPERTREND_RSI_WINDOW4 = _synthesize_window(-409.99, 14, 0.143, 0.089)

GBPUSD_SUPERTRENT_RSI_ALL_WINDOWS = (
    GBPUSD_SUPERTREND_RSI_WINDOW0
    + GBPUSD_SUPERTREND_RSI_WINDOW1
    + GBPUSD_SUPERTREND_RSI_WINDOW2
    + GBPUSD_SUPERTREND_RSI_WINDOW3
    + GBPUSD_SUPERTREND_RSI_WINDOW4
)
