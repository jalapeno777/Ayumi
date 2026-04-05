from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SizingMode(Enum):
    FIXED_FRACTIONAL = "fixed_fractional"
    KELLY = "kelly"
    DYNAMIC = "dynamic"


class RegimeFilterMode(Enum):
    FILTER_EXTREME = "filter_extreme"
    FILTER_HIGH_AND_EXTREME = "filter_high_and_extreme"
    NONE = "none"


@dataclass(frozen=True)
class RegimeConfig:
    enabled: bool = True
    filter_mode: RegimeFilterMode = RegimeFilterMode.FILTER_EXTREME
    min_confidence: float = 0.4
    atr_lookback: int = 50
    adx_period: int = 14


@dataclass(frozen=True)
class CorrelationConfig:
    enabled: bool = True
    window: int = 50
    threshold: float = 0.7
    pairs: tuple[str, ...] = (
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
    )


@dataclass(frozen=True)
class PositionSizingConfig:
    enabled: bool = True
    mode: SizingMode = SizingMode.FIXED_FRACTIONAL
    risk_pct: float = 1.0
    dynamic_min_multiplier: float = 0.5
    dynamic_max_multiplier: float = 1.5
    dynamic_loss_reduction: float = 0.1
    dynamic_win_increase: float = 0.1
    dynamic_max_streak_impact: float = 0.5


@dataclass(frozen=True)
class WalkForwardConfig:
    enabled: bool = True
    n_windows: int = 3
    train_ratio: float = 0.7
    val_ratio: float = 0.15
    overlap_ratio: float = 0.2


@dataclass(frozen=True)
class QuantConfig:
    regime: RegimeConfig = RegimeConfig()
    correlation: CorrelationConfig = CorrelationConfig()
    position_sizing: PositionSizingConfig = PositionSizingConfig()
    walk_forward: WalkForwardConfig = WalkForwardConfig()

    @classmethod
    def paper_trading(cls) -> QuantConfig:
        return cls(
            regime=RegimeConfig(
                enabled=True,
                filter_mode=RegimeFilterMode.FILTER_HIGH_AND_EXTREME,
                min_confidence=0.5,
            ),
            correlation=CorrelationConfig(
                enabled=True,
                threshold=0.6,
            ),
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.FIXED_FRACTIONAL,
                risk_pct=0.5,
            ),
            walk_forward=WalkForwardConfig(
                enabled=False,
            ),
        )

    @classmethod
    def ftmo(cls) -> QuantConfig:
        return cls(
            regime=RegimeConfig(
                enabled=True,
                filter_mode=RegimeFilterMode.FILTER_EXTREME,
                min_confidence=0.4,
            ),
            correlation=CorrelationConfig(
                enabled=True,
                threshold=0.7,
            ),
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.DYNAMIC,
                risk_pct=1.0,
                dynamic_min_multiplier=0.5,
                dynamic_max_multiplier=1.5,
                dynamic_loss_reduction=0.15,
                dynamic_win_increase=0.1,
                dynamic_max_streak_impact=0.4,
            ),
            walk_forward=WalkForwardConfig(
                enabled=True,
                n_windows=5,
            ),
        )

    @classmethod
    def disabled(cls) -> QuantConfig:
        return cls(
            regime=RegimeConfig(enabled=False),
            correlation=CorrelationConfig(enabled=False),
            position_sizing=PositionSizingConfig(enabled=False),
            walk_forward=WalkForwardConfig(enabled=False),
        )
