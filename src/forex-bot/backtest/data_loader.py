from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from .engine import Bar, BarPeriod


def _est_dst_start(year: int) -> datetime:
    march1_wd = calendar.weekday(year, 3, 1)
    days_to_sunday = (6 - march1_wd) % 7
    second_sunday = 1 + days_to_sunday + 7
    return datetime(year, 3, second_sunday, 2, 0)


def _est_dst_end(year: int) -> datetime:
    nov1_wd = calendar.weekday(year, 11, 1)
    days_to_sunday = (6 - nov1_wd) % 7
    first_sunday = 1 + days_to_sunday
    return datetime(year, 11, first_sunday, 2, 0)


def _est_to_utc(dt: datetime) -> datetime:
    if _est_dst_start(dt.year) <= dt < _est_dst_end(dt.year):
        return dt + timedelta(hours=4)
    return dt + timedelta(hours=5)


def _detect_est_timezone(first_dt: datetime) -> bool:
    if first_dt.weekday() == 6 and first_dt.hour >= 16 and first_dt.hour <= 18:
        return True
    if first_dt.hour == 17:
        return True
    return False


_UNSET: object = object()


class CsvDataLoader:
    def __init__(self, source_timezone: str | None | object = _UNSET):
        tz: str | None = None if source_timezone is _UNSET else source_timezone  # type: ignore[assignment]
        self.source_timezone = tz
        self._auto_detect = source_timezone is _UNSET

    def _convert_timezone(self, dt: datetime) -> datetime:
        tz = self.source_timezone
        if tz is None:
            return dt
        if tz.lower() in ("est", "us/eastern", "america/new_york"):
            return _est_to_utc(dt)
        return dt

    def load(self, filepath: str) -> list[Bar]:
        bars = []
        with open(filepath) as f:
            lines = f.readlines()

        first_dt: datetime | None = None

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

                if first_dt is None:
                    first_dt = dt
                    if (
                        self._auto_detect
                        and self.source_timezone is None
                        and _detect_est_timezone(dt)
                    ):
                        self.source_timezone = "est"

                dt = self._convert_timezone(dt)

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

    def load_from_string(self, csv_content: str) -> list[Bar]:
        bars = []
        lines = csv_content.strip().split("\n")

        first_dt: datetime | None = None

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

                if first_dt is None:
                    first_dt = dt
                    if (
                        self._auto_detect
                        and self.source_timezone is None
                        and _detect_est_timezone(dt)
                    ):
                        self.source_timezone = "est"

                dt = self._convert_timezone(dt)

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

    def infer_timeframe(self, bars: list[Bar]) -> BarPeriod:
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
