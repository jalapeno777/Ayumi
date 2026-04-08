#!/usr/bin/env python3
"""
BACKTEST Q1: 3:1 R&R on EURUSD H1 M/W Formation

Question: Does EURUSD H1 M/W pattern actually produce 3:1 consistently?

What We Want:
- % of trades that hit 3:1 minimum
- Average R:R across all M/W signals
- % of trades that hit L1 (minimum target)
- % of trades that hit L2 (expected target)
- % of trades that hit L3 (rare extension)
- Overall sample size

Pass Criteria: ≥60% of trades hitting 3:1 or better
"""

import json
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.data_loader import CsvDataLoader
from backtest.engine import Bar, SessionType, determine_session


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


def analyze_3_to_1_rr(bars: list[Bar]) -> dict:
    if len(bars) < 100:
        return {"error": "Insufficient data"}

    swing_points = detect_swing_points(bars)
    formations = find_mw_formations(bars, swing_points)

    if not formations:
        return {
            "question": "Q1",
            "test_period": "N/A",
            "instrument": "EURUSD",
            "timeframe": "H1",
            "sample_size": 0,
            "results": {},
            "pass": False,
            "notes": "No M/W formations detected"
        }

    atr = calculate_atr(bars)

    outcomes = {"L1": 0, "L2": 0, "L3": 0, "SL": 0, "open": 0}
    rr_ratios = []
    trades_with_3_1_or_better = 0
    total_closed_trades = 0

    for formation in formations:
        last_point = formation.points[-1]
        entry_idx = last_point.index + 1

        if entry_idx >= len(bars):
            outcomes["open"] = outcomes.get("open", 0) + 1
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
        for i in range(entry_idx, min(entry_idx + 96, len(bars))):
            bar = bars[i]

            if entry_direction == 1:
                if bar.low <= tp3:
                    outcome = "L3"
                    rr_ratios.append(3.0)
                    break
                elif bar.low <= tp2:
                    outcome = "L2"
                    rr_ratios.append(2.0)
                    break
                elif bar.low <= tp1:
                    outcome = "L1"
                    rr_ratios.append(1.0)
                    break
                elif bar.high >= stop:
                    outcome = "SL"
                    rr_ratios.append(0.0)
                    break
            else:
                if bar.high >= tp3:
                    outcome = "L3"
                    rr_ratios.append(3.0)
                    break
                elif bar.high >= tp2:
                    outcome = "L2"
                    rr_ratios.append(2.0)
                    break
                elif bar.high >= tp1:
                    outcome = "L1"
                    rr_ratios.append(1.0)
                    break
                elif bar.low <= stop:
                    outcome = "SL"
                    rr_ratios.append(0.0)
                    break

        if outcome is None:
            outcome = "open"
            rr_ratios.append(0.0)

        outcomes[outcome] = outcomes.get(outcome, 0) + 1

        if outcome != "open":
            total_closed_trades += 1
            if rr_ratios[-1] >= 3.0:
                trades_with_3_1_or_better += 1

    sample_size = len(formations)
    total_closed = sum(v for k, v in outcomes.items() if k != "open")

    l1_hit_rate = outcomes.get("L1", 0) / total_closed if total_closed > 0 else 0.0
    l2_hit_rate = outcomes.get("L2", 0) / total_closed if total_closed > 0 else 0.0
    l3_hit_rate = outcomes.get("L3", 0) / total_closed if total_closed > 0 else 0.0
    stop_loss_rate = outcomes.get("SL", 0) / total_closed if total_closed > 0 else 0.0
    rr_3_1_hit_rate = trades_with_3_1_or_better / total_closed if total_closed > 0 else 0.0
    average_rr = sum(rr_ratios) / len(rr_ratios) if rr_ratios else 0.0

    start_date = bars[0].time.strftime("%Y-%m-%d")
    end_date = bars[-1].time.strftime("%Y-%m-%d")

    pass_criteria_met = rr_3_1_hit_rate >= 0.60

    results = {
        "question": "Q1",
        "test_period": f"{start_date} to {end_date}",
        "instrument": "EURUSD",
        "timeframe": "H1",
        "sample_size": sample_size,
        "results": {
            "rr_3_1_hit_rate": round(rr_3_1_hit_rate, 2),
            "average_rr": round(average_rr, 2),
            "l1_hit_rate": round(l1_hit_rate, 2),
            "l2_hit_rate": round(l2_hit_rate, 2),
            "l3_hit_rate": round(l3_hit_rate, 2),
            "stop_loss_rate": round(stop_loss_rate, 2)
        },
        "pass": pass_criteria_met,
        "notes": (
            f"{rr_3_1_hit_rate*100:.0f}% of trades hit 3:1 or better. "
            f"Average R:R was {average_rr:.2f}. "
            f"Sample size: {sample_size} M/W formations. "
            f"Pass criteria: ≥60% at 3:1."
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

    results = analyze_3_to_1_rr(bars)

    output_file = Path("/home/TacoPants/projects/Ayumi/worktrees/junior-dev-1/reports/backtest_q1_3_to_1_rr.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, indent=2))

    print(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    main()