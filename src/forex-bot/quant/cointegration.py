from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SpreadStats:
    mean: float = 0.0
    std: float = 0.0
    half_life: float = 0.0
    hurst_exponent: float = 0.0
    z_score: float = 0.0
    is_stationary: bool = False


@dataclass
class CointegrationResult:
    pair: tuple[str, str] = ("", "")
    p_value: float = 1.0
    coint_stat: float = 0.0
    critical_values: dict[float, float] = field(default_factory=dict)
    spread_stats: SpreadStats = field(default_factory=SpreadStats)
    is_cointegrated: bool = False
    hedge_ratio: float = 1.0
    lookback: int = 0


class CointegrationEngine:
    def __init__(self, lookback: int = 252, significance: float = 0.05):
        self.lookback = lookback
        self.significance = significance
        self._results: dict[tuple[str, str], CointegrationResult] = {}

    def test_pair(self, series_a: list[float], series_b: list[float], pair_id: tuple[str, str] = ("A", "B")) -> CointegrationResult:
        if len(series_a) < 2 or len(series_b) < 2:
            return CointegrationResult(pair=pair_id)
        return CointegrationResult(pair=pair_id)

    def get_result(self, pair_id: tuple[str, str]) -> Optional[CointegrationResult]:
        return self._results.get(pair_id)

    def scan_universe(self, prices: dict[str, list[float]]) -> list[CointegrationResult]:
        return []


class PairsSignalGenerator:
    def __init__(self, engine: CointegrationEngine, entry_z: float = 2.0, exit_z: float = 0.5):
        self.engine = engine
        self.entry_z = entry_z
        self.exit_z = exit_z

    def evaluate(self, spread: list[float], stats: Optional[SpreadStats] = None) -> Optional[str]:
        return None


def parameter_sweep(
    prices: dict[str, list[float]],
    lookbacks: list[int] | None = None,
    significances: list[float] | None = None,
) -> list[CointegrationResult]:
    if lookbacks is None:
        lookbacks = [126, 252, 504]
    if significances is None:
        significances = [0.01, 0.05, 0.10]
    return []
