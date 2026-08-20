"""Backtest strategies package."""

# Import the formal ABC first (no circular deps)
from .isignal_strategy import ISignalStrategy, Tick, StrategyConfig  # noqa: I001

# Load legacy strategies (ISignalStrategy re-exported from line above)
from ..strategy_legacy import (
    MACrossStrategy,
    BBStrategy,
    RSIStrategy,
    SRBreakoutStrategy,
    ROCMStrategy,
    MomentumBreakoutStrategy,
    CommodityTrendStrategy,
    CommodityMeanReversionStrategy,
    SupertrendRSIBlendStrategy,
    KeltnerChannelBreakoutStrategy,
    HighConvictionStrategy,
    RegimeSwitchingRouter,
    RegimeRouterConfig,
    DEFAULT_LOD_HOD_STOP_BUFFER_PIPS,
    apply_lod_hod_stop_buffer,
)

# TTSStrategy loaded last — depends on ISignalStrategy being already defined
from .tts_strategy import TTSStrategy
from .scalper_strategy import ScalperStrategy

__all__ = [
    "ISignalStrategy",
    "Tick",
    "StrategyConfig",
    "TTSStrategy",
    "ScalperStrategy",
    "MACrossStrategy",
    "BBStrategy",
    "RSIStrategy",
    "SRBreakoutStrategy",
    "ROCMStrategy",
    "MomentumBreakoutStrategy",
    "CommodityTrendStrategy",
    "CommodityMeanReversionStrategy",
    "SupertrendRSIBlendStrategy",
    "KeltnerChannelBreakoutStrategy",
    "HighConvictionStrategy",
    "RegimeSwitchingRouter",
    "RegimeRouterConfig",
    "DEFAULT_LOD_HOD_STOP_BUFFER_PIPS",
    "apply_lod_hod_stop_buffer",
]
