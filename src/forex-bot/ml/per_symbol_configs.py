"""Auto-generated per-symbol, per-timeframe optimal configs.

Generated: 20260411_2016 by ml/per_symbol_optimizer.py
Grid: 5 symbols × 8 config variants × M15 timeframe

TTSStrategy should read from this at initialization:
    from ml.per_symbol_configs import PER_SYMBOL_CONFIGS, DEFAULT_SYMBOL_CONFIG
    config = PER_SYMBOL_CONFIGS.get(symbol, {}).get(timeframe, DEFAULT_SYMBOL_CONFIG)
"""
from __future__ import annotations

DEFAULT_SYMBOL_CONFIG = {
    "base_confidence": 0.30,
    "kz_penalty": -0.05,
    "htf_penalty": -0.15,
    "top_confluences": [],
}

PER_SYMBOL_CONFIGS = {
    "EURUSD": {
        "M15": {
            "base_confidence": 0.25,
            "kz_penalty": -0.05,
            "htf_penalty": -0.15,
            "top_confluences": [],
            # Note: Only 15 trades — insufficient data for ML.
            # Low base reduces exposure. Needs more data before optimizing further.
        },
    },
    "GBPUSD": {
        "M15": {
            "base_confidence": 0.25,
            "kz_penalty": 0.0,
            "htf_penalty": -0.15,
            "top_confluences": [
                "confidence_score",
                "rsi_divergence",
                "htf_trend_aligned",
                "svc_at_peak",
                "consolidation",
            ],
            # Best config: G_low_base_no_kz
            # P&L: $115.97 | WR: 50.0% | DD: 0.4% | PF: 1.66 | 20 trades
            # Removing KZ penalty helps — GBPUSD doesn't need kill zone filtering.
        },
    },
    "USDJPY": {
        "M15": {
            "base_confidence": 0.30,
            "kz_penalty": -0.10,
            "htf_penalty": -0.15,
            "top_confluences": [
                "confidence_score",
                "htf_trend_aligned",
                "kill_zone_active",
                "vwap_rejection",
                "rsi_divergence",
            ],
            # Best config: E_strong_kz
            # P&L: $7.98 | WR: 52.0% | DD: 1.2% | PF: 1.02 | 25 trades
            # Stronger KZ penalty needed — USDJPY benefits from kill zone filtering.
        },
    },
    "GBPJPY": {
        "M15": {
            "base_confidence": 0.30,
            "kz_penalty": 0.0,
            "htf_penalty": -0.15,
            "top_confluences": [
                "htf_trend_aligned",
                "confidence_score",
                "vwap_rejection",
                "kill_zone_active",
                "rsi_divergence",
            ],
            # Best config: D_no_kz
            # P&L: -$5.87 | WR: 52.2% | DD: 2.1% | PF: 0.99 | 23 trades
            # Nearly breakeven. No KZ penalty needed. HTF trend is #1 feature.
        },
    },
    "XAUUSD": {
        "M15": {
            "base_confidence": 0.25,
            "kz_penalty": -0.05,
            "htf_penalty": -0.15,
            "top_confluences": [
                "confidence_score",
                "htf_trend_aligned",
                "kill_zone_active",
                "vwap_rejection",
                "rsi_divergence",
            ],
            # Best config: C_low_base
            # P&L: -$3.28 | WR: 44.1% | DD: 2.4% | PF: 0.99 | 34 trades
            # Nearly breakeven. Low base reduces exposure. Kill zone is #2 feature.
        },
    },
}
