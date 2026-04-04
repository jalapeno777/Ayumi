from datetime import datetime
from typing import List
from .engine import Bar, BarPeriod


class CsvDataLoader:
    def load(self, filepath: str) -> List[Bar]:
        bars = []
        with open(filepath, "r") as f:
            lines = f.readlines()

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue

            try:
                dt = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
                open_price = float(parts[1])
                high = float(parts[2])
                low = float(parts[3])
                close = float(parts[4])
                volume = float(parts[5]) if len(parts) > 5 else 0.0

                bar = Bar(
                    time=dt,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
                bars.append(bar)
            except (ValueError, IndexError):
                continue

        return bars

    def load_from_string(self, csv_content: str) -> List[Bar]:
        bars = []
        lines = csv_content.strip().split("\n")

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue

            try:
                dt = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
                open_price = float(parts[1])
                high = float(parts[2])
                low = float(parts[3])
                close = float(parts[4])
                volume = float(parts[5]) if len(parts) > 5 else 0.0

                bar = Bar(
                    time=dt,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
                bars.append(bar)
            except (ValueError, IndexError):
                continue

        return bars

    def infer_timeframe(self, bars: List[Bar]) -> BarPeriod:
        if len(bars) < 2:
            return BarPeriod(60)

        time_diffs = []
        for i in range(1, min(len(bars), 10)):
            diff = (bars[i].time - bars[i - 1].time).total_seconds() / 60
            time_diffs.append(diff)

        avg_diff = sum(time_diffs) / len(time_diffs) if time_diffs else 60

        if avg_diff <= 20:
            return BarPeriod(15)
        elif avg_diff <= 60:
            return BarPeriod(60)
        elif avg_diff <= 300:
            return BarPeriod(240)
        else:
            return BarPeriod(1440)
