"""Backtest strategies package."""

# Load ISignalStrategy + legacy strategies FIRST (no circular deps with tts_strategy)
from ..strategy_legacy import (
    ISignalStrategy,
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

__all__ = [
    "TTSStrategy",
    "ISignalStrategy",
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
