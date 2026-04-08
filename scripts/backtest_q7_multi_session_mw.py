#!/usr/bin/env python3
"""
BACKTEST Q7: Multi-Session M/W Formation Frequency

Question: How often do multi-session M/W formations appear vs single-session?

What We Want:
- % of M/W formations that span 2+ sessions (multi-session)
- % that complete within a single session
- Win rate comparison between single vs. multi-session formations

Pass Criteria: N/A (descriptive analysis)
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
    breakout_pct: float = 0.005
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

        w_condition = (
            pt1.is_high and not pt2.is_high and pt3.is_high and not pt4.is_high and pt5.is_high
        )

        m_condition = (
            not pt1.is_high and pt2.is_high and not pt3.is_high and pt4.is_high and not pt5.is_high
        )

        if not w_condition and not m_condition:
            continue

        if w_condition:
            w_price_condition = (
                pt1.price > pt3.price > pt5.price and
                abs(pt1.price - pt3.price) / pt3.price > min_swing_pct and
                abs(pt3.price - pt5.price) / pt5.price > min_swing_pct
            )
            if w_price_condition:
                sessions = {pt1.session, pt2.session, pt3.session, pt4.session, pt5.session}
                formations.append(MWFormation(
                    points=[pt1, pt2, pt3, pt4, pt5],
                    formation_type="W",
                    sessions=sessions
                ))

        if m_condition:
            m_price_condition = (
                pt1.price < pt3.price < pt5.price and
                abs(pt3.price - pt1.price) / pt1.price > min_swing_pct and
                abs(pt5.price - pt3.price) / pt3.price > min_swing_pct
            )
            if m_price_condition:
                sessions = {pt1.session, pt2.session, pt3.session, pt4.session, pt5.session}
                formations.append(MWFormation(
                    points=[pt1, pt2, pt3, pt4, pt5],
                    formation_type="M",
                    sessions=sessions
                ))

    return formations


def determine_trade_outcome(
    bars: list[Bar],
    formation: MWFormation,
    atr: float
) -> tuple[str, float]:
    last_point = formation.points[-1]
    entry_idx = last_point.index + 1

    if entry_idx >= len(bars):
        return "skip", 0.0

    entry_price = bars[entry_idx].close

    if formation.formation_type == "W":
        entry_direction = 1
        stop = last_point.price - atr * 1.5
        tp1 = entry_price + (entry_price - stop) * 1
        tp2 = entry_price + (entry_price - stop) * 2
        tp3 = entry_price + (entry_price - stop) * 3
    else:
        entry_direction = -1
        stop = last_point.price + atr * 1.5
        tp1 = entry_price - (stop - entry_price) * 1
        tp2 = entry_price - (stop - entry_price) * 2
        tp3 = entry_price - (stop - entry_price) * 3

    for i in range(entry_idx, min(entry_idx + 96, len(bars))):
        bar = bars[i]

        if entry_direction == 1:
            if bar.high >= tp3:
                return "L3", tp3
            elif bar.high >= tp2:
                return "L2", tp2
            elif bar.high >= tp1:
                return "L1", tp1
            elif bar.low <= stop:
                return "SL", stop
        else:
            if bar.low <= tp3:
                return "L3", tp3
            elif bar.low <= tp2:
                return "L2", tp2
            elif bar.low <= tp1:
                return "L1", tp1
            elif bar.high >= stop:
                return "SL", stop

    return "open", 0.0


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


def analyze_multi_session_mw(bars: list[Bar]) -> dict:
    if len(bars) < 100:
        return {"error": "Insufficient data"}

    swing_points = detect_swing_points(bars)
    formations = find_mw_formations(bars, swing_points)

    if not formations:
        return {
            "question": "Q7",
            "test_period": "N/A",
            "instrument": "EURUSD",
            "timeframe": "H1",
            "sample_size": 0,
            "results": {},
            "pass": True,
            "notes": "No M/W formations detected"
        }

    atr = calculate_atr(bars)

    single_session_count = sum(1 for f in formations if not f.is_multi_session)
    multi_session_count = sum(1 for f in formations if f.is_multi_session)
    total = len(formations)

    single_session_pct = single_session_count / total if total > 0 else 0.0
    multi_session_pct = multi_session_count / total if total > 0 else 0.0

    single_session_wins = 0
    single_session_losses = 0
    multi_session_wins = 0
    multi_session_losses = 0

    total_sessions = 0
    for f in formations:
        total_sessions += len(f.sessions)

    avg_sessions_per_formation = total_sessions / total if total > 0 else 1.0

    outcomes = {"L1": 0, "L2": 0, "L3": 0, "SL": 0, "BE": 0, "open": 0}

    for f in formations:
        outcome, _ = determine_trade_outcome(bars, f, atr)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

        is_win = outcome in ("L1", "L2", "L3")
        is_loss = outcome == "SL"

        if f.is_multi_session:
            if is_win:
                multi_session_wins += 1
            elif is_loss:
                multi_session_losses += 1
        else:
            if is_win:
                single_session_wins += 1
            elif is_loss:
                single_session_losses += 1

    single_total = single_session_wins + single_session_losses
    multi_total = multi_session_wins + multi_session_losses

    single_session_win_rate = (
        single_session_wins / single_total if single_total > 0 else 0.0
    )
    multi_session_win_rate = (
        multi_session_wins / multi_total if multi_total > 0 else 0.0
    )

    start_date = bars[0].time.strftime("%Y-%m-%d")
    end_date = bars[-1].time.strftime("%Y-%m-%d")

    results = {
        "question": "Q7",
        "test_period": f"{start_date} to {end_date}",
        "instrument": "EURUSD",
        "timeframe": "H1",
        "sample_size": total,
        "results": {
            "multi_session_pct": round(multi_session_pct, 2),
            "single_session_pct": round(single_session_pct, 2),
            "multi_session_win_rate": round(multi_session_win_rate, 2),
            "single_session_win_rate": round(single_session_win_rate, 2),
            "avg_sessions_per_formation": round(avg_sessions_per_formation, 2),
            "total_formations": total,
            "multi_session_count": multi_session_count,
            "single_session_count": single_session_count,
            "outcomes": outcomes
        },
        "pass": True,
        "notes": (
            f"{multi_session_pct*100:.0f}% of M/Ws span 2+ sessions. "
            f"Multi-session win rate: {multi_session_win_rate*100:.0f}%. "
            f"Single-session win rate: {single_session_win_rate*100:.0f}%. "
            f"Avg {avg_sessions_per_formation:.1f} sessions per formation."
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

    results = analyze_multi_session_mw(bars)

    output_file = Path("/home/TacoPants/projects/Ayumi/worktrees/junior-dev-1/reports/backtest_q7_multi_session_mw.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, indent=2))

    print(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    main()