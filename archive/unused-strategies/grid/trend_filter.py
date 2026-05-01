from __future__ import annotations

from dataclasses import dataclass

from .config import GridConfig, GridDirectionBias


def _calculate_adx(
    high: list[float],
    low: list[float],
    close: list[float],
    period: int = 14,
) -> float:
    n = len(close)
    if n < period + 1:
        return 0.0

    true_ranges: list[float] = []
    plus_dms: list[float] = []
    minus_dms: list[float] = []

    for i in range(1, n):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        true_ranges.append(tr)

        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    smoothed_tr = sum(true_ranges[:period])
    smoothed_plus_dm = sum(plus_dms[:period])
    smoothed_minus_dm = sum(minus_dms[:period])

    for i in range(period, len(true_ranges)):
        smoothed_tr = smoothed_tr - (smoothed_tr / period) + true_ranges[i]
        smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + plus_dms[i]
        smoothed_minus_dm = (
            smoothed_minus_dm - (smoothed_minus_dm / period) + minus_dms[i]
        )

    if smoothed_tr == 0:
        return 0.0

    plus_di = 100.0 * (smoothed_plus_dm / smoothed_tr)
    minus_di = 100.0 * (smoothed_minus_dm / smoothed_tr)
    di_sum = plus_di + minus_di

    if di_sum == 0:
        return 0.0

    return 100.0 * (abs(plus_di - minus_di) / di_sum)


def _calculate_ma_slope(close: list[float], period: int = 14) -> float:
    if len(close) < 2:
        return 0.0
    recent = close[-period:] if len(close) >= period else close
    return (recent[-1] - recent[0]) / len(recent)


class TrendFilter:
    def __init__(self, config: GridConfig):
        self._config = config
        self._tf = config.trend_filter

    def evaluate(
        self,
        high: list[float],
        low: list[float],
        close: list[float],
    ) -> TrendFilterResult:
        adx = _calculate_adx(high, low, close, self._tf.adx_period)
        slope = _calculate_ma_slope(close, self._tf.adx_period)

        if adx >= self._tf.disable_threshold:
            return TrendFilterResult(
                enabled=False,
                adx=adx,
                direction_bias=GridDirectionBias.NONE,
                active_levels_fraction=0.0,
                reason=f"ADX {adx:.1f} >= {self._tf.disable_threshold}, grid disabled",
            )

        if adx > self._tf.directional_threshold:
            if slope > 0:
                bias = GridDirectionBias.LONG
            elif slope < 0:
                bias = GridDirectionBias.SHORT
            else:
                bias = GridDirectionBias.NONE
            return TrendFilterResult(
                enabled=True,
                adx=adx,
                direction_bias=bias,
                active_levels_fraction=1.0,
                reason=f"ADX {adx:.1f}, directional bias={bias.value}",
            )

        if adx > self._tf.full_grid_threshold:
            return TrendFilterResult(
                enabled=True,
                adx=adx,
                direction_bias=GridDirectionBias.NONE,
                active_levels_fraction=self._tf.reduced_level_fraction,
                reason=f"ADX {adx:.1f}, reduced grid ({self._tf.reduced_level_fraction:.0%} levels)",
            )

        return TrendFilterResult(
            enabled=True,
            adx=adx,
            direction_bias=GridDirectionBias.NONE,
            active_levels_fraction=1.0,
            reason=f"ADX {adx:.1f} < {self._tf.full_grid_threshold}, full grid",
        )


@dataclass
class TrendFilterResult:
    enabled: bool
    adx: float
    direction_bias: GridDirectionBias
    active_levels_fraction: float
    reason: str = ""
