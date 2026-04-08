#!/usr/bin/env python3
"""
BACKTEST Q2: LOD/HOD Stop Hit Rate Analysis

Question: What % of trades get stopped at LOD/HOD vs intrabar volatility?

What We Want:
- % of trades stopped at the LOD/HOD level specifically
- % stopped inside the candle (intrabar spike through)
- Average slippage when stop is hit
- Optimal stop buffer (pips beyond LOD/HOD?)

Pass Criteria: ≤40% stop loss rate with 3:1 targets
"""

import json
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.data_loader import CsvDataLoader  # noqa: E402
from backtest.engine import Bar, SessionType, determine_session  # noqa: E402


class SwingPoint:
    def __init__(self, index: int, price: float, is_high: bool, time: datetime, session: SessionType):
        self.index = index
        self.price = price
        self.is_high = is_high
        self.time = time
        self.session = session


class MWFormation:
    def __init__(self, points: list[SwingPoint], formation_type: str, sessions: set[SessionType]):
        self.points = points
        self.formation_type = formation_type
        self.sessions = sessions
        self.is_multi_session = len(sessions) > 1


def detect_swing_points(bars: list[Bar], lookback: int = 5) -> list[SwingPoint]:
    swing_points = []
    for i in range(lookback, len(bars) - lookback):
        is_swing_high = True
        is_swing_low = True

        for j in range(1, lookback + 1):
            if bars[i].high <= bars[i - j].high or bars[i].high <= bars[i + j].high:
                is_swing_high = False
            if bars[i].low >= bars[i - j].low or bars[i].low >= bars[i + j].low:
                is_swing_low = False

        if is_swing_high:
            swing_points.append(SwingPoint(
                index=i,
                price=bars[i].high,
                is_high=True,
                time=bars[i].time,
                session=determine_session(bars[i].time)
            ))
        elif is_swing_low:
            swing_points.append(SwingPoint(
                index=i,
                price=bars[i].low,
                is_high=False,
                time=bars[i].time,
                session=determine_session(bars[i].time)
            ))

    return swing_points


def find_mw_formations(
    bars: list[Bar],
    swing_points: list[SwingPoint],
    min_swing_pct: float = 0.003,
) -> list[MWFormation]:
    formations = []
    
    if len(swing_points) < 5:
        return formations

    for i in range(len(swing_points) - 4):
        pt1 = swing_points[i]
        pt2 = swing_points[i + 1]
        pt3 = swing_points[i + 2]
        pt4 = swing_points[i + 3]
        pt5 = swing_points[i + 4]

        if not pt1.is_high and not pt2.is_high and not pt3.is_high and not pt4.is_high and not pt5.is_high:
            continue

        w_condition = (
            pt1.price > pt3.price > pt5.price and
            abs(pt1.price - pt3.price) / pt3.price > min_swing_pct and
            abs(pt3.price - pt5.price) / pt5.price > min_swing_pct
        )

        if w_condition:
            sessions = {pt1.session, pt3.session, pt5.session}
            formations.append(MWFormation(
                points=[pt1, pt2, pt3, pt4, pt5],
                formation_type="W",
                sessions=sessions
            ))

        m_condition = (
            pt1.price < pt3.price < pt5.price and
            abs(pt3.price - pt1.price) / pt1.price > min_swing_pct and
            abs(pt5.price - pt3.price) / pt3.price > min_swing_pct
        )

        if m_condition:
            sessions = {pt1.session, pt3.session, pt5.session}
            formations.append(MWFormation(
                points=[pt1, pt2, pt3, pt4, pt5],
                formation_type="M",
                sessions=sessions
            ))

    return formations


def calculate_atr(bars: list[Bar], period: int = 14) -> float:
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


def analyze_lod_hod_stop_rate(bars: list[Bar]) -> dict:
    if len(bars) < 100:
        return {"error": "Insufficient data"}

    swing_points = detect_swing_points(bars)
    formations = find_mw_formations(bars, swing_points)

    if not formations:
        return {
            "question": "Q2",
            "test_period": "N/A",
            "instrument": "EURUSD",
            "timeframe": "H1",
            "sample_size": 0,
            "results": {},
            "pass": False,
            "notes": "No M/W formations detected"
        }

    atr = calculate_atr(bars)

    stop_outcomes = {
        "lod_hod": 0,
        "intrabar_spike": 0,
        "breakeven": 0,
        "target_hit": 0,
        "open": 0
    }
    
    slippage_pips = []
    
    for formation in formations:
        last_point = formation.points[-1]
        entry_idx = last_point.index + 1

        if entry_idx >= len(bars):
            stop_outcomes["open"] += 1
            continue

        entry_price = bars[entry_idx].close

        if formation.formation_type == "W":
            entry_direction = 1
            stop = last_point.price - atr * 1.5
            risk = entry_price - stop
            if risk <= 0:
                continue
            tp1 = entry_price + risk * 1
            tp2 = entry_price + risk * 2
            tp3 = entry_price + risk * 3
        else:
            entry_direction = -1
            stop = last_point.price + atr * 1.5
            risk = stop - entry_price
            if risk <= 0:
                continue
            tp1 = entry_price - risk * 1
            tp2 = entry_price - risk * 2
            tp3 = entry_price - risk * 3

        outcome = None
        stop_hit_bar = None
        stop_hit_price = None
        
        for i in range(entry_idx, min(entry_idx + 96, len(bars))):
            bar = bars[i]

            if entry_direction == 1:
                if bar.high >= tp1:
                    outcome = "target_hit"
                    break
                elif bar.high >= tp2:
                    outcome = "target_hit"
                    break
                elif bar.high >= tp3:
                    outcome = "target_hit"
                    break
                elif bar.low <= stop:
                    outcome = "stop_hit"
                    stop_hit_bar = bar
                    stop_hit_price = stop
                    break
            else:
                if bar.low <= tp1:
                    outcome = "target_hit"
                    break
                elif bar.low <= tp2:
                    outcome = "target_hit"
                    break
                elif bar.low <= tp3:
                    outcome = "target_hit"
                    break
                elif bar.high >= stop:
                    outcome = "stop_hit"
                    stop_hit_bar = bar
                    stop_hit_price = stop
                    break

        if outcome is None:
            outcome = "open"
            stop_outcomes["open"] += 1
        elif outcome == "target_hit":
            stop_outcomes["target_hit"] += 1
        elif outcome == "stop_hit":
            if stop_hit_bar is not None:
                if entry_direction == 1:
                    lod_price = stop_hit_bar.low
                    hod_price = stop_hit_bar.high
                    if lod_price <= stop:
                        if abs(stop - lod_price) < 0.0001:
                            stop_outcomes["lod_hod"] += 1
                            slippage = abs(stop_hit_price - lod_price) * 10000
                            slippage_pips.append(slippage)
                        else:
                            stop_outcomes["intrabar_spike"] += 1
                            slippage = abs(stop_hit_price - lod_price) * 10000
                            slippage_pips.append(slippage)
                    else:
                        stop_outcomes["intrabar_spike"] += 1
                        slippage = abs(stop_hit_price - lod_price) * 10000
                        slippage_pips.append(slippage)
                else:
                    lod_price = stop_hit_bar.low
                    hod_price = stop_hit_bar.high
                    if hod_price >= stop:
                        if abs(stop - hod_price) < 0.0001:
                            stop_outcomes["lod_hod"] += 1
                            slippage = abs(stop_hit_price - hod_price) * 10000
                            slippage_pips.append(slippage)
                        else:
                            stop_outcomes["intrabar_spike"] += 1
                            slippage = abs(stop_hit_price - hod_price) * 10000
                            slippage_pips.append(slippage)
                    else:
                        stop_outcomes["intrabar_spike"] += 1
                        slippage = abs(stop_hit_price - lod_price) * 10000
                        slippage_pips.append(slippage)
            else:
                stop_outcomes["breakeven"] += 1
        else:
            stop_outcomes["breakeven"] += 1

    sample_size = len(formations)
    total_stop_hits = stop_outcomes["lod_hod"] + stop_outcomes["intrabar_spike"]
    total_closed = sum(v for k, v in stop_outcomes.items() if k != "open")
    
    lod_hod_stop_rate = stop_outcomes["lod_hod"] / total_closed if total_closed > 0 else 0.0
    intrabar_spike_rate = stop_outcomes["intrabar_spike"] / total_closed if total_closed > 0 else 0.0
    breakeven_rate = stop_outcomes["breakeven"] / total_closed if total_closed > 0 else 0.0
    
    avg_slippage = sum(slippage_pips) / len(slippage_pips) if slippage_pips else 0.0
    
    optimal_buffer = avg_slippage * 1.2 if slippage_pips else 5.0
    
    stop_loss_rate = total_stop_hits / total_closed if total_closed > 0 else 0.0
    pass_criteria_met = stop_loss_rate <= 0.40

    start_date = bars[0].time.strftime("%Y-%m-%d")
    end_date = bars[-1].time.strftime("%Y-%m-%d")

    results = {
        "question": "Q2",
        "test_period": f"{start_date} to {end_date}",
        "instrument": "EURUSD",
        "timeframe": "H1",
        "sample_size": sample_size,
        "results": {
            "lod_hod_stop_rate": round(lod_hod_stop_rate, 2),
            "intrabar_spike_rate": round(intrabar_spike_rate, 2),
            "breakeven_rate": round(breakeven_rate, 2),
            "avg_stop_buffer_pips": round(avg_slippage, 2),
            "optimal_buffer_pips": round(optimal_buffer, 2)
        },
        "pass": pass_criteria_met,
        "notes": (
            f"{lod_hod_stop_rate*100:.0f}% stopped at LOD/HOD, "
            f"{intrabar_spike_rate*100:.0f}% intrabar spike. "
            f"Avg slippage: {avg_slippage:.1f} pips. "
            f"Optimal buffer: {optimal_buffer:.1f} pips. "
            f"Sample: {sample_size} formations."
        )
    }

    return results


def main():
    data_dir = Path("/home/TacoPants/projects/Ayumi/worktrees/junior-dev-1/data/forex/historical")
    eurusd_file = data_dir / "EURUSD_H1.csv"

    loader = CsvDataLoader()
    bars = loader.load(str(eurusd_file))

    if len(bars) < 100:
        print("Error: Insufficient EURUSD H1 data")
        return

    results = analyze_lod_hod_stop_rate(bars)

    output_file = Path("/home/TacoPants/projects/Ayumi/worktrees/junior-dev-1/reports/backtest_q2_lod_hod_stop_rate.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, indent=2))

    print(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    main()