from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .regime import VolatilityThresholds


class SizingMode(Enum):
    FIXED_FRACTIONAL = "fixed_fractional"
    KELLY = "kelly"
    DYNAMIC = "dynamic"


@dataclass
class RegimeConfig:
    enabled: bool = True
    min_confidence: float = 0.5
    block_extreme_volatility: bool = True
    volatility_thresholds: VolatilityThresholds = field(
        default_factory=VolatilityThresholds
    )


@dataclass
class CorrelationConfig:
    enabled: bool = True
    pairs: list[str] = field(default_factory=list)
    window: int = 50
    threshold: float = 0.7
    max_correlated_exposure: float = 0.3


@dataclass
class PositionSizingConfig:
    enabled: bool = True
    mode: SizingMode = SizingMode.FIXED_FRACTIONAL
    risk_pct: float = 1.0
    max_streak_impact: float = 0.5
    loss_reduction: float = 0.1
    win_increase: float = 0.1
    min_multiplier: float = 0.5
    max_multiplier: float = 1.5


@dataclass
class WalkForwardConfig:
    enabled: bool = False
    n_windows: int = 3
    train_ratio: float = 0.7
    val_ratio: float = 0.15
    overlap_ratio: float = 0.2


@dataclass
class QuantConfig:
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    correlation: CorrelationConfig = field(default_factory=CorrelationConfig)
    position_sizing: PositionSizingConfig = field(default_factory=PositionSizingConfig)
    walk_forward: WalkForwardConfig = field(default_factory=WalkForwardConfig)

    @property
    def regime_enabled(self) -> bool:
        return self.regime.enabled

    @property
    def correlation_enabled(self) -> bool:
        return self.correlation.enabled

    @property
    def position_sizing_enabled(self) -> bool:
        return self.position_sizing.enabled

    @property
    def walk_forward_enabled(self) -> bool:
        return self.walk_forward.enabled

    @classmethod
    def paper_trading(cls) -> QuantConfig:
        return cls(
            regime=RegimeConfig(
                enabled=True,
                min_confidence=0.5,
                block_extreme_volatility=True,
            ),
            correlation=CorrelationConfig(
                enabled=True,
                window=50,
                threshold=0.7,
            ),
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.FIXED_FRACTIONAL,
                risk_pct=1.0,
            ),
            walk_forward=WalkForwardConfig(enabled=False),
        )

    @classmethod
    def ftmo(cls) -> QuantConfig:
        return cls(
            regime=RegimeConfig(
                enabled=True,
                min_confidence=0.6,
                block_extreme_volatility=True,
                volatility_thresholds=VolatilityThresholds(
                    low=20.0,
                    normal=70.0,
                    high=85.0,
                ),
            ),
            correlation=CorrelationConfig(
                enabled=True,
                window=50,
                threshold=0.6,
                max_correlated_exposure=0.2,
            ),
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.DYNAMIC,
                risk_pct=0.5,
                max_streak_impact=0.3,
                loss_reduction=0.15,
                win_increase=0.05,
                min_multiplier=0.5,
                max_multiplier=1.2,
            ),
            walk_forward=WalkForwardConfig(
                enabled=True,
                n_windows=5,
                train_ratio=0.7,
                val_ratio=0.15,
                overlap_ratio=0.2,
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
