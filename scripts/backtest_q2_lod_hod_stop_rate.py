#!/usr/bin/env python3
"""
BACKTEST Q2: LOD/HOD Stop Hit Rate Analysis

Question: What % of trades get stopped at LOD/HOD vs intrabar volatility?

Pass Criteria: <=40% stop loss rate with 3:1 targets

Methodology:
- For each trading session (London/NY/Asian), compute LOD and HOD
- For M/W pattern entries from Q1, check if SL was hit at LOD/HOD or intrabar
- Classify stops: exact LOD/HOD level vs intrabar spike through
- Measure slippage in pips
- Test buffer sizes (0, 2, 5, 10 pips beyond LOD/HOD)

Implements: Q2BacktestStudy(StatisticalStudy)
Framework: StatisticalStudy base class from AYUAA-641
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest.data_loader import CsvDataLoader  # noqa: E402
from backtest.engine import Bar  # noqa: E402
from backtest.pattern_detector import MWPattern, MWPatternDetector  # noqa: E402
from backtest.statistical_study import (  # noqa: E402
    GoNoGoCriteria,
    StatisticalStudy,
)


class Q2BacktestStudy(StatisticalStudy):
    SWING_LOOKBACK = 5
    MIN_DEPTH_ATR = 0.5
    MIN_BAR_SPAN = 10
    MAX_BAR_SPAN = 200
    SYMMETRY_TOLERANCE = 0.30
    ATR_PERIOD = 14
    MAX_BARS_AHEAD = 96
    BUFFER_PIPS = [0, 2, 5, 10]

    def __init__(self):
        super().__init__(
            question_id="Q2",
            instrument="EURUSD",
            timeframe="H1",
            go_nogo_criteria=[
                GoNoGoCriteria(metric="stop_loss_rate", threshold=0.40, operator="<="),
            ],
        )
        self.detector = MWPatternDetector(
            swing_lookback=self.SWING_LOOKBACK,
            symmetry_tolerance=self.SYMMETRY_TOLERANCE,
            min_depth_atr=self.MIN_DEPTH_ATR,
            min_bar_span=self.MIN_BAR_SPAN,
            max_bar_span=self.MAX_BAR_SPAN,
        )

    def analyze(self, bars: list[Bar]) -> dict:
        atr_values = self.compute_atr(bars, period=self.ATR_PERIOD)
        patterns = self.detector.detect(bars, atr_values)

        if not patterns:
            return self._empty_results()

        buffer_results = {}
        for buf in self.BUFFER_PIPS:
            buffer_results[buf] = self._analyze_with_buffer(patterns, bars, atr_values, buf)

        best_buf = min(
            buffer_results.keys(),
            key=lambda b: buffer_results[b]["stop_loss_rate"],
        )
        best = buffer_results[best_buf]

        return {
            "sample_size": len(patterns),
            "lod_hod_stop_rate": best["lod_hod_stop_rate"],
            "intrabar_spike_rate": best["intrabar_spike_rate"],
            "breakeven_rate": best["breakeven_rate"],
            "avg_stop_buffer_pips": best["avg_stop_buffer_pips"],
            "optimal_buffer_pips": best_buf,
            "stop_loss_rate": best["stop_loss_rate"],
            "buffer_comparison": {
                str(b): {
                    "stop_loss_rate": round(r["stop_loss_rate"], 4),
                    "lod_hod_stop_rate": round(r["lod_hod_stop_rate"], 4),
                }
                for b, r in buffer_results.items()
            },
        }

    def _analyze_with_buffer(
        self,
        patterns: list[MWPattern],
        bars: list[Bar],
        atr_values: list[float],
        buffer_pips: float,
    ) -> dict:
        lod_hod_stops = 0
        intrabar_spikes = 0
        breakeven_hits = 0
        total_closed = 0
        total_slippage_pips = 0.0
        slippage_count = 0

        for pattern in patterns:
            entry_idx = pattern.right_shoulder_idx + 1
            if entry_idx >= len(bars):
                continue

            entry_price = bars[entry_idx].close
            atr = atr_values[entry_idx] if entry_idx < len(atr_values) else 0.0001

            session_bars = self._get_session_bars(bars, entry_idx)

            if pattern.is_bullish:
                session_lod = min(b.low for b in session_bars)
                session_hod = max(b.high for b in session_bars)
                stop_level = session_lod - self.pip_value(buffer_pips)
            else:
                session_lod = min(b.low for b in session_bars)
                session_hod = max(b.high for b in session_bars)
                stop_level = session_hod + self.pip_value(buffer_pips)

            if pattern.is_bullish:
                risk = entry_price - stop_level
            else:
                risk = stop_level - entry_price

            if risk <= 0:
                continue

            result = self._check_stop_hit(
                bars, entry_idx, entry_price, stop_level,
                session_lod, session_hod, atr, pattern.is_bullish,
            )

            if result["outcome"] == "open":
                continue

            total_closed += 1

            if result["hit_at_lod_hod"]:
                lod_hod_stops += 1
            elif result["outcome"] == "SL":
                intrabar_spikes += 1
                if result.get("slippage_pips") is not None:
                    total_slippage_pips += result["slippage_pips"]
                    slippage_count += 1
            elif result["outcome"] == "breakeven":
                breakeven_hits += 1

        if total_closed == 0:
            return self._empty_results()

        return {
            "lod_hod_stop_rate": round(lod_hod_stops / total_closed, 4),
            "intrabar_spike_rate": round(intrabar_spikes / total_closed, 4),
            "breakeven_rate": round(breakeven_hits / total_closed, 4),
            "avg_stop_buffer_pips": round(
                total_slippage_pips / slippage_count, 2
            ) if slippage_count > 0 else 0.0,
            "stop_loss_rate": round(
                (lod_hod_stops + intrabar_spikes) / total_closed, 4
            ),
        }

    def _get_session_bars(self, bars: list[Bar], entry_idx: int) -> list[Bar]:
        entry_time = bars[entry_idx].time
        hour = entry_time.hour

        if 0 <= hour < 7:
            start_hour, end_hour = 0, 8
        elif 7 <= hour < 15:
            start_hour, end_hour = 7, 16
        else:
            start_hour, end_hour = 12, 22

        session_bars = []
        for b in bars:
            h = b.time.hour
            if start_hour <= h < end_hour and b.time.date() == entry_time.date():
                session_bars.append(b)
        return session_bars if session_bars else [bars[entry_idx]]

    def _check_stop_hit(
        self,
        bars: list[Bar],
        entry_idx: int,
        entry_price: float,
        stop_level: float,
        session_lod: float,
        session_hod: float,
        atr: float,
        is_bullish: bool,
    ) -> dict:
        tp1 = entry_price + (entry_price - stop_level) * 1

        for i in range(entry_idx + 1, min(entry_idx + self.MAX_BARS_AHEAD, len(bars))):
            bar = bars[i]

            if is_bullish:
                if bar.high >= tp1:
                    return {"outcome": "breakeven", "hit_at_lod_hod": False}

                if bar.low <= session_lod:
                    return {
                        "outcome": "SL",
                        "hit_at_lod_hod": True,
                        "slippage_pips": self.price_to_pips(session_lod, entry_price) if bar.low < session_lod else 0.0,
                    }

                if bar.low <= stop_level:
                    return {
                        "outcome": "SL",
                        "hit_at_lod_hod": False,
                        "slippage_pips": self.price_to_pips(bar.low, stop_level),
                    }
            else:
                if bar.low <= tp1:
                    return {"outcome": "breakeven", "hit_at_lod_hod": False}

                if bar.high >= session_hod:
                    return {
                        "outcome": "SL",
                        "hit_at_lod_hod": True,
                        "slippage_pips": self.price_to_pips(entry_price, session_hod) if bar.high > session_hod else 0.0,
                    }

                if bar.high >= stop_level:
                    return {
                        "outcome": "SL",
                        "hit_at_lod_hod": False,
                        "slippage_pips": self.price_to_pips(stop_level, bar.high),
                    }

        return {"outcome": "open", "hit_at_lod_hod": False}

    def _empty_results(self) -> dict:
        return {
            "sample_size": 0,
            "lod_hod_stop_rate": 0.0,
            "intrabar_spike_rate": 0.0,
            "breakeven_rate": 0.0,
            "avg_stop_buffer_pips": 0.0,
            "optimal_buffer_pips": 0,
            "stop_loss_rate": 0.0,
            "buffer_comparison": {},
        }


def main():
    data_path = Path(__file__).parent.parent / "data" / "forex" / "historical" / "EURUSD_H1.csv"
    report_path = Path(__file__).parent.parent / "reports" / "backtest_q2_lod_hod_stop_rate.json"

    loader = CsvDataLoader()
    bars = loader.load(str(data_path))

    if len(bars) < 100:
        print("Error: Insufficient EURUSD H1 data")
        sys.exit(1)

    study = Q2BacktestStudy()
    result = study.run(bars)

    print(result.to_json())
    print(f"\nResults saved to {report_path}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(str(report_path))


if __name__ == "__main__":
    main()
