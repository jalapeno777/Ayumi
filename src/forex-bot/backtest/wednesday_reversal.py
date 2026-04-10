from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .engine import Bar
from .statistical_study import GoNoGoCriteria, StatisticalStudy, StatisticalStudyResult


@dataclass(frozen=True)
class DayReversalStats:
    total: int
    reversals: int
    rate: float
    avg_pips: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "reversals": self.reversals,
            "rate": self.rate,
            "avg_pips": self.avg_pips,
        }


class WednesdayReversalStudy(StatisticalStudy):
    MIN_REVERSAL_PIPS = 50

    def __init__(
        self,
        instrument: str = "EURUSD",
        min_reversal_pips: int = 50,
    ) -> None:
        super().__init__(
            question_id="Q3",
            instrument=instrument,
            timeframe="D1",
            go_nogo_criteria=[
                GoNoGoCriteria(
                    metric="wednesday_reversal_rate",
                    threshold=0.50,
                    operator=">=",
                    weight=1.0,
                ),
            ],
        )
        self.min_reversal_pips = min_reversal_pips

    def _pip_value(self, price: float) -> float:
        return self.pip_value(price)

    def _to_pips(self, price_diff: float, ref_price: float) -> float:
        return price_diff / self._pip_value(ref_price)

    @staticmethod
    def _count_consecutive_days(bars: list[Bar]) -> int:
        if not bars:
            return 0
        count = 1
        for i in range(1, len(bars)):
            gap_days = (bars[i].time - bars[i - 1].time).days
            if gap_days <= 3:
                count += 1
            else:
                break
        return count

    def _compute_day_stats(
        self,
        bars: list[Bar],
        target_weekday: int,
        prev_weekday: int,
    ) -> DayReversalStats:
        total = 0
        reversal_pips_list: list[float] = []

        for i in range(1, len(bars)):
            curr = bars[i]
            prev = bars[i - 1]

            gap_days = (curr.time - prev.time).days
            if gap_days > 3:
                continue

            if curr.time.weekday() != target_weekday:
                continue
            if prev.time.weekday() != prev_weekday:
                continue

            total += 1
            close_diff = abs(curr.close - prev.close)
            pips = self._to_pips(close_diff, prev.close)

            if pips >= self.min_reversal_pips:
                reversal_pips_list.append(pips)

        if total == 0:
            return DayReversalStats(total=0, reversals=0, rate=0.0, avg_pips=0.0)

        rate = len(reversal_pips_list) / total
        avg_pips = (
            sum(reversal_pips_list) / len(reversal_pips_list)
            if reversal_pips_list
            else 0.0
        )
        return DayReversalStats(
            total=total,
            reversals=len(reversal_pips_list),
            rate=round(rate, 4),
            avg_pips=round(avg_pips, 1),
        )

    def analyze(self, bars: list[Bar]) -> dict[str, Any]:
        wed = self._compute_day_stats(bars, target_weekday=2, prev_weekday=1)
        tue = self._compute_day_stats(bars, target_weekday=1, prev_weekday=0)
        thu = self._compute_day_stats(bars, target_weekday=3, prev_weekday=2)

        return {
            "sample_size": wed.total,
            "wednesday_reversal_rate": wed.rate,
            "avg_reversal_pips": wed.avg_pips,
            "vs_tuesday_rate": tue.rate,
            "vs_thursday_rate": thu.rate,
            "wednesday": wed.to_dict(),
            "tuesday": tue.to_dict(),
            "thursday": thu.to_dict(),
        }

    def run_multi_instrument(
        self,
        instruments: dict[str, list[Bar]],
        start: datetime,
        end: datetime,
    ) -> list[StatisticalStudyResult]:
        results = []
        for instrument, bars in instruments.items():
            self.instrument = instrument
            filtered = self.filter_by_date_range(bars, start, end)
            result = self.run(filtered)
            results.append(result)
        return results

    def format_summary(
        self,
        results: list[StatisticalStudyResult],
    ) -> str:
        lines: list[str] = []
        for r in results:
            res = r.results
            lines.append(f"\n=== {r.instrument} ===")
            lines.append(
                f"Wednesday: {res.get('wednesday', {}).get('reversals', 0)}/"
                f"{res.get('wednesday', {}).get('total', 0)} = "
                f"{res.get('wednesday_reversal_rate', 0):.0%} reversal rate, "
                f"avg {res.get('avg_reversal_pips', 0):.1f} pips"
            )
            lines.append(
                f"Tuesday: {res.get('tuesday', {}).get('reversals', 0)}/"
                f"{res.get('tuesday', {}).get('total', 0)} = "
                f"{res.get('vs_tuesday_rate', 0):.0%}"
            )
            lines.append(
                f"Thursday: {res.get('thursday', {}).get('reversals', 0)}/"
                f"{res.get('thursday', {}).get('total', 0)} = "
                f"{res.get('vs_thursday_rate', 0):.0%}"
            )
            lines.append(f"PASS: {r.go_nogo}")
        return "\n".join(lines)
