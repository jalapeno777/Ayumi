from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum


class GridDirectionBias(Enum):
    NONE = "none"
    LONG = "long"
    SHORT = "short"


class LotSizingMode(Enum):
    DECREASING = "decreasing"
    UNIFORM = "uniform"


@dataclass(frozen=True)
class TrendFilterConfig:
    adx_period: int = 14
    full_grid_threshold: float = 20.0
    reduced_grid_threshold: float = 30.0
    directional_threshold: float = 30.0
    disable_threshold: float = 40.0
    reduced_level_fraction: float = 0.5


@dataclass(frozen=True)
class RiskConfig:
    equity_stop_pct: float = 0.05
    max_open_positions: int = 10
    max_daily_loss_pct: float = 0.03
    max_correlated_positions: int = 3


@dataclass
class GridConfig:
    symbol: str = "EURUSD"
    grid_spacing: float = 0.0015
    levels_per_side: int = 5
    base_lot: float = 0.1
    lot_sizes: list[float] = field(default_factory=lambda: [0.10, 0.08, 0.06, 0.05, 0.04])
    lot_sizing_mode: LotSizingMode = LotSizingMode.DECREASING
    take_profit_pips: float = 10.0
    trend_filter: TrendFilterConfig = field(default_factory=TrendFilterConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    pip_value: float = 0.0001
    contract_size: float = 100000.0
    spread: float = 0.0

    def __post_init__(self):
        if self.spread == 0.0:
            logging.getLogger(__name__).warning(
                "GridConfig spread is 0.0 — P&L calculations will assume cost-free trading"
            )

    @classmethod
    def eurusd(cls) -> GridConfig:
        return cls(
            symbol="EURUSD",
            grid_spacing=0.0015,
            levels_per_side=5,
            pip_value=0.0001,
            contract_size=100000.0,
            spread=0.00005,
        )

    @classmethod
    def xauusd(cls) -> GridConfig:
        return cls(
            symbol="XAUUSD",
            grid_spacing=12.0,
            levels_per_side=5,
            base_lot=0.01,
            lot_sizes=[0.01, 0.008, 0.006, 0.005, 0.004],
            pip_value=0.01,
            contract_size=100.0,
            spread=0.30,
        )

    @classmethod
    def ftmo(cls, symbol: str = "EURUSD") -> GridConfig:
        if symbol.upper() == "XAUUSD":
            base = cls.xauusd()
            risk = RiskConfig(
                equity_stop_pct=0.05,
                max_open_positions=3,
                max_daily_loss_pct=0.015,
                max_correlated_positions=2,
            )
        else:
            base = cls.eurusd()
            risk = RiskConfig(
                equity_stop_pct=0.05,
                max_open_positions=3,
                max_daily_loss_pct=0.015,
                max_correlated_positions=2,
            )
        return cls(
            symbol=base.symbol,
            grid_spacing=base.grid_spacing,
            levels_per_side=base.levels_per_side,
            base_lot=base.base_lot,
            lot_sizes=base.lot_sizes,
            pip_value=base.pip_value,
            contract_size=base.contract_size,
            spread=base.spread,
            risk=risk,
            trend_filter=TrendFilterConfig(
                adx_period=14,
                full_grid_threshold=20.0,
                reduced_grid_threshold=30.0,
                directional_threshold=30.0,
                disable_threshold=40.0,
                reduced_level_fraction=0.5,
            ),
        )

    def spacing_in_pips(self) -> float:
        return self.grid_spacing / self.pip_value

    def lot_for_level(self, level_index: int) -> float:
        if self.lot_sizing_mode == LotSizingMode.UNIFORM:
            return self.base_lot
        if level_index < len(self.lot_sizes):
            return self.lot_sizes[level_index]
        return self.lot_sizes[-1] if self.lot_sizes else self.base_lot
