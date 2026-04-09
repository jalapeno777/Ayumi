#!/usr/bin/env python3
"""
BACKTEST Q6: DXY Leading/Lagging on EURUSD H1

Question: Does DXY lead or lag EURUSD on the 1H timeframe?

Methodology:
- Uses USDJPY as a DXY proxy (direct USD strength measure)
- Aligns EURUSD and USDJPY H1 data by timestamp
- Calculates rolling correlation between USDJPY and EURUSD returns
- Identifies USDJPY level breaks (breakouts beyond N-bar high/low)
- For each USDJPY breakout, measures if EURUSD responds in the expected
  inverse direction within a response window
- Reports lead/lag statistics

Note: True DXY is a weighted index (EUR 57.6%, JPY 13.6%, GBP 11.9%, etc.).
USDJPY captures USD vs JPY strength. Since DXY ≈ f(EURUSD, USDJPY, ...),
using USDJPY avoids the circularity of inverting EURUSD to create a proxy.
"""

import json
import math
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.data_loader import CsvDataLoader
from backtest.engine import Bar


def align_bars_by_timestamp(
    eurusd_bars: list[Bar], usdjpy_bars: list[Bar]
) -> list[tuple[Bar, Bar]]:
    """Align two bar series by timestamp. Returns matched pairs."""
    usdjpy_by_time = {}
    for bar in usdjpy_bars:
        usdjpy_by_time[bar.time] = bar

    aligned = []
    for eur_bar in eurusd_bars:
        if eur_bar.time in usdjpy_by_time:
            aligned.append((eur_bar, usdjpy_by_time[eur_bar.time]))
    return aligned


def calculate_returns(prices: list[float]) -> list[float]:
    """Calculate period-over-period returns."""
    returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0:
            returns.append((prices[i] - prices[i - 1]) / prices[i - 1])
        else:
            returns.append(0.0)
    return returns


def calculate_rolling_correlation(
    series1: list[float], series2: list[float], window: int = 20
) -> list[float]:
    """Calculate rolling Pearson correlation between two aligned series."""
    correlations = []
    for i in range(window, len(series1) + 1):
        s1 = series1[i - window : i]
        s2 = series2[i - window : i]

        m1 = sum(s1) / window
        m2 = sum(s2) / window

        cov = sum((s1[j] - m1) * (s2[j] - m2) for j in range(window))
        var1 = sum((x - m1) ** 2 for x in s1)
        var2 = sum((x - m2) ** 2 for x in s2)

        denom = math.sqrt(var1 * var2) if var1 > 0 and var2 > 0 else 0.0
        correlations.append(cov / denom if denom > 0 else 0.0)
    return correlations


def identify_breakout_bars(
    aligned: list[tuple[Bar, Bar]],
    lookback: int = 20,
    atr_window: int = 14,
    breakout_multiplier: float = 1.5,
) -> list[tuple[int, str]]:
    """
    Identify USDJPY breakout bars where price breaks beyond the lookback range.

    A breakout is detected when:
    - USDJPY closes above the lookback high + (ATR * multiplier) -> UP breakout
    - USDJPY closes below the lookback low - (ATR * multiplier) -> DOWN breakout

    Returns list of (aligned_index, direction) tuples.
    """
    usdjpy_closes = [pair[1].close for pair in aligned]
    usdjpy_highs = [pair[1].high for pair in aligned]
    usdjpy_lows = [pair[1].low for pair in aligned]

    def atr(i: int) -> float:
        if i < atr_window:
            return 0.0
        total = 0.0
        for j in range(i - atr_window + 1, i + 1):
            tr = max(
                usdjpy_highs[j] - usdjpy_lows[j],
                abs(usdjpy_highs[j] - usdjpy_closes[j - 1]),
                abs(usdjpy_lows[j] - usdjpy_closes[j - 1]),
            )
            total += tr
        return total / atr_window

    breakouts = []
    min_separation = 8
    last_breakout_idx = -min_separation

    for i in range(lookback, len(aligned)):
        if i - last_breakout_idx < min_separation:
            continue

        window_high = max(usdjpy_highs[i - lookback : i])
        window_low = min(usdjpy_lows[i - lookback : i])
        current_atr = atr(i)

        if current_atr <= 0:
            continue

        threshold = current_atr * breakout_multiplier

        if usdjpy_closes[i] > window_high + threshold:
            breakouts.append((i, "UP"))
            last_breakout_idx = i
        elif usdjpy_closes[i] < window_low - threshold:
            breakouts.append((i, "DOWN"))
            last_breakout_idx = i

    return breakouts


def measure_lead_lag(
    aligned: list[tuple[Bar, Bar]],
    breakouts: list[tuple[int, str]],
    response_window: int = 8,
) -> dict:
    """
    For each USDJPY breakout, measure if EURUSD responds in the expected
    inverse direction within the response window.

    USDJPY UP (USD strengthens) -> expect EURUSD DOWN
    USDJPY DOWN (USD weakens) -> expect EURUSD UP

    Returns lead/lag statistics.
    """
    eurusd_closes = [pair[0].close for pair in aligned]

    dxy_leads_count = 0
    no_response_count = 0
    opposite_response_count = 0
    delays = []

    for breakout_idx, direction in breakouts:
        if breakout_idx >= len(aligned) - response_window - 1:
            continue

        eur_before = eurusd_closes[breakout_idx]
        if eur_before <= 0:
            continue

        expected_eur_direction = -1 if direction == "UP" else 1

        responded = False
        for offset in range(1, response_window + 1):
            future_idx = breakout_idx + offset
            if future_idx >= len(eurusd_closes):
                break

            eur_future = eurusd_closes[future_idx]
            move_pct = (eur_future - eur_before) / eur_before

            if abs(move_pct) < 0.0003:
                continue

            actual_direction = 1 if move_pct > 0 else -1

            if actual_direction == expected_eur_direction:
                delays.append(offset)
                dxy_leads_count += 1
                responded = True
                break
            else:
                opposite_response_count += 1
                responded = True
                break

        if not responded:
            no_response_count += 1

    total = dxy_leads_count + opposite_response_count + no_response_count
    return {
        "dxy_leads_count": dxy_leads_count,
        "opposite_response_count": opposite_response_count,
        "no_response_count": no_response_count,
        "total_breakouts": total,
        "delays": delays,
    }


def calculate_cross_correlation(
    series1: list[float], series2: list[float], max_lag: int = 10
) -> dict:
    """
    Calculate cross-correlation at various lags to measure lead/lag timing.

    Positive lag = series1 leads series2 by that many periods.
    Negative lag = series2 leads series1.
    """
    results = {}
    for lag in range(-max_lag, max_lag + 1):
        n = len(series1) - abs(lag)
        if n < 50:
            results[lag] = 0.0
            continue

        if lag >= 0:
            s1 = series1[lag:]
            s2 = series2[:n]
        else:
            s1 = series1[:n]
            s2 = series2[-lag:]

        m1 = sum(s1) / n
        m2 = sum(s2) / n
        cov = sum((s1[j] - m1) * (s2[j] - m2) for j in range(n))
        var1 = sum((x - m1) ** 2 for x in s1)
        var2 = sum((x - m2) ** 2 for x in s2)
        denom = math.sqrt(var1 * var2) if var1 > 0 and var2 > 0 else 0.0
        results[lag] = cov / denom if denom > 0 else 0.0

    return results


def analyze_dxy_leading_lagging(aligned: list[tuple[Bar, Bar]]) -> dict:
    """Main analysis: DXY (USDJPY proxy) leading/lagging EURUSD."""
    if len(aligned) < 500:
        return {"error": "Insufficient aligned data"}

    eurusd_closes = [pair[0].close for pair in aligned]
    usdjpy_closes = [pair[1].close for pair in aligned]

    start_date = aligned[0][0].time.strftime("%Y-%m-%d")
    end_date = aligned[-1][0].time.strftime("%Y-%m-%d")

    eurusd_returns = calculate_returns(eurusd_closes)
    usdjpy_returns = calculate_returns(usdjpy_closes)

    overall_corr = calculate_rolling_correlation(
        usdjpy_returns, eurusd_returns, window=len(usdjpy_returns)
    )
    avg_correlation = overall_corr[0] if overall_corr else 0.0

    cross_corr = calculate_cross_correlation(usdjpy_returns, eurusd_returns, max_lag=10)

    best_leading_lag = 0
    best_leading_corr = abs(cross_corr.get(0, 0.0))
    for lag, corr in cross_corr.items():
        if lag > 0 and abs(corr) > best_leading_corr:
            best_leading_corr = abs(corr)
            best_leading_lag = lag

    breakouts = identify_breakout_bars(aligned, lookback=20, atr_window=14, breakout_multiplier=1.5)
    lead_lag_stats = measure_lead_lag(aligned, breakouts, response_window=8)

    total_decisive = lead_lag_stats["dxy_leads_count"] + lead_lag_stats["opposite_response_count"]
    dxy_leads_pct = (
        lead_lag_stats["dxy_leads_count"] / total_decisive
        if total_decisive > 0
        else 0.5
    )

    avg_delay = (
        sum(lead_lag_stats["delays"]) / len(lead_lag_stats["delays"])
        if lead_lag_stats["delays"]
        else 0.0
    )

    results = {
        "question": "Q6",
        "test_period": f"{start_date} to {end_date}",
        "instrument": "EURUSD",
        "timeframe": "H1",
        "sample_size": lead_lag_stats["total_breakouts"],
        "results": {
            "correlation_coefficient": round(avg_correlation, 2),
            "dxy_leads_pct": round(dxy_leads_pct, 2),
            "avg_delay_candles": round(avg_delay, 1),
            "dxy_first_break_confirms": dxy_leads_pct >= 0.70,
            "usdjpy_proxy_note": (
                "USDJPY used as DXY proxy (direct USD strength measure). "
                "Avoids circularity of inverting EURUSD."
            ),
        },
        "pass": dxy_leads_pct >= 0.70,
        "notes": (
            f"Using USDJPY as DXY proxy. DXY leads EURUSD on "
            f"{dxy_leads_pct*100:.0f}% of breakouts. "
            f"Correlation: {avg_correlation:.2f}. "
            f"Avg delay: {avg_delay:.1f} candles. "
            f"Best leading lag from cross-correlation: {best_leading_lag} candles "
            f"(corr={best_leading_corr:.2f}). "
            f"Total breakouts analyzed: {lead_lag_stats['total_breakouts']}."
        ),
        "methodology": {
            "dxy_proxy": "USDJPY (direct USD strength measure)",
            "breakout_detection": "ATR-based (lookback=20, multiplier=1.5)",
            "response_window": 8,
            "min_breakout_separation": 8,
            "data_alignment": "Timestamp-matched EURUSD + USDJPY H1 bars",
        },
    }

    return results


def main():
    data_dir = Path("/home/TacoPants/projects/Ayumi/worktrees/junior-dev-1/data/forex/historical")
    eurusd_file = data_dir / "EURUSD_H1.csv"
    usdjpy_file = data_dir / "USDJPY_H1.csv"

    loader = CsvDataLoader()
    eurusd_bars = loader.load(str(eurusd_file))
    usdjpy_bars = loader.load(str(usdjpy_file))

    if len(eurusd_bars) < 500 or len(usdjpy_bars) < 500:
        print("Error: Insufficient data")
        return

    aligned = align_bars_by_timestamp(eurusd_bars, usdjpy_bars)
    print(f"Aligned bars: {len(aligned)} (EURUSD: {len(eurusd_bars)}, USDJPY: {len(usdjpy_bars)})")

    results = analyze_dxy_leading_lagging(aligned)

    output_file = Path("/home/TacoPants/projects/Ayumi/worktrees/junior-dev-1/reports/backtest_q6_dxy_leading_lagging.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, indent=2))

    print(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    main()
