"""
Slippage-adjusted fill model for backtest execution simulation.

Provides configurable slippage estimation beyond the simple fixed-pip model
in BacktestConfig. Supports three slippage regimes:

1. **Fixed** — constant slippage in pips (baseline, backwards-compatible)
2. **Linear** — base + linear scaling with trade volume relative to ADV
3. **Square-root** — Almgren-Chriss inspired sqrt model (institutional standard)

All models optionally adjust for session liquidity and volatility regime.

References:
- docs/forex/tick-quality-comparison-2026-07.md
- docs/_archive/forex/architecture-v2.md (slippage_pips precedent)
- Almgren et al. (2005) "Direct Estimation of Equity Market Impact"
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SlippageModel(str, Enum):
    """Available slippage computation regimes."""

    FIXED = "fixed"
    LINEAR = "linear"
    SQUARE_ROOT = "sqrt"


class TradeSide(str, Enum):
    """Trade direction for asymmetric slippage application."""

    BUY = "buy"
    SELL = "sell"


# Session liquidity multipliers (empirical, from tick-quality comparison).
# Outside major sessions, slippage increases due to thinner order books.
SESSION_LIQUIDITY_FACTOR: dict[str, float] = {
    "LONDON": 1.0,
    "NY_AM": 1.0,
    "NY_PM": 1.15,
    "ASIAN": 1.3,
    "OUTSIDE": 1.6,
}

DEFAULT_SESSION_FACTOR = 1.5


def _pip_size_for_price(price: float) -> float:
    """
    Determine pip size from price magnitude.

    Mirrors the logic in backtest.types.ExecutionSimulator._get_pip_value:
    - JPY pairs (price >= 50): pip = 0.01
    - Standard FX (price >= 1): pip = 0.0001
    - Crypto/other (price < 1): pip = 0.00000001
    """
    if price >= 50:
        return 0.01
    elif price >= 1:
        return 0.0001
    else:
        return 0.00000001


@dataclass
class SlippageConfig:
    """
    Configuration for the slippage fill model.

    Attributes:
        model: Which slippage regime to use.
        base_slippage_pips: Minimum slippage applied to every trade.
        volume_coefficient: Scaling factor for volume-dependent component
            (linear: pips per ADV-fraction; sqrt: coefficient on sqrt(ADV-fraction)).
        adv_lots: Average daily volume in lots for the instrument,
            used as the denominator in volume-impact calculations.
        volatility_coefficient: Multiplier applied to current volatility
            (in pips) — higher volatility = wider slippage.
        max_slippage_pips: Hard cap to prevent pathological values.
        session_aware: Whether to apply session liquidity adjustments.
    """

    model: SlippageModel = SlippageModel.FIXED
    base_slippage_pips: float = 0.2
    volume_coefficient: float = 0.5
    adv_lots: float = 100_000.0
    volatility_coefficient: float = 0.0
    max_slippage_pips: float = 5.0
    session_aware: bool = False

    def __post_init__(self) -> None:
        if self.base_slippage_pips < 0:
            raise ValueError(
                f"base_slippage_pips must be non-negative, got {self.base_slippage_pips}"
            )
        if self.volume_coefficient < 0:
            raise ValueError(
                f"volume_coefficient must be non-negative, got {self.volume_coefficient}"
            )
        if self.max_slippage_pips <= 0:
            raise ValueError(
                f"max_slippage_pips must be positive, got {self.max_slippage_pips}"
            )
        if self.adv_lots <= 0:
            raise ValueError(f"adv_lots must be positive, got {self.adv_lots}")


@dataclass
class SlippageContext:
    """
    Market context at time of trade execution.

    All fields except price are optional — when omitted, the corresponding
    adjustment is skipped.
    """

    price: float
    side: TradeSide = TradeSide.BUY
    trade_lots: float = 1.0
    volatility_pips: Optional[float] = None
    session: Optional[str] = None

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError(f"price must be positive, got {self.price}")
        if self.trade_lots <= 0:
            raise ValueError(f"trade_lots must be positive, got {self.trade_lots}")


def compute_slippage(
    config: SlippageConfig,
    context: SlippageContext,
) -> float:
    """
    Compute slippage in price units for the given configuration and context.

    Returns the absolute slippage amount (always non-negative).
    The caller is responsible for applying direction (add for buys, subtract for sells).

    Algorithm depends on config.model:

    - FIXED: base_slippage_pips × pip_size
    - LINEAR: (base + volume_coeff × trade_lots / adv_lots × 100) × pip_size
    - SQUARE_ROOT: (base + volume_coeff × sqrt(trade_lots / adv_lots × 100)) × pip_size

    Then optionally multiply by session liquidity factor and add volatility component.

    Args:
        config: SlippageConfig with model parameters.
        context: SlippageContext with trade and market details.

    Returns:
        Slippage in price units (non-negative float).
    """
    pip_size = _pip_size_for_price(context.price)

    # --- Base + volume component (in pips) ---
    if config.model == SlippageModel.FIXED:
        slippage_pips = config.base_slippage_pips

    elif config.model == SlippageModel.LINEAR:
        volume_fraction = context.trade_lots / config.adv_lots
        volume_impact = (
            config.volume_coefficient * volume_fraction * 100
        )  # scale to pips
        slippage_pips = config.base_slippage_pips + volume_impact

    elif config.model == SlippageModel.SQUARE_ROOT:
        volume_fraction = context.trade_lots / config.adv_lots
        # Almgren-Chriss style: impact ∝ sqrt(participation rate)
        volume_impact = config.volume_coefficient * math.sqrt(
            max(volume_fraction, 0) * 100
        )
        slippage_pips = config.base_slippage_pips + volume_impact

    else:
        raise ValueError(f"Unknown slippage model: {config.model}")

    # --- Volatility adjustment ---
    if (
        config.volatility_coefficient > 0
        and context.volatility_pips is not None
        and context.volatility_pips > 0
    ):
        vol_component = config.volatility_coefficient * context.volatility_pips
        slippage_pips += vol_component

    # --- Session liquidity adjustment ---
    if config.session_aware and context.session is not None:
        factor = SESSION_LIQUIDITY_FACTOR.get(
            context.session.upper(), DEFAULT_SESSION_FACTOR
        )
        slippage_pips *= factor

    # --- Hard cap ---
    slippage_pips = min(slippage_pips, config.max_slippage_pips)

    # Convert to price units
    return slippage_pips * pip_size


def compute_slippage_pips(
    config: SlippageConfig,
    context: SlippageContext,
) -> float:
    """
    Compute slippage in pips (not price units).

    Convenience wrapper around compute_slippage that returns the result
    in pip units before conversion to price.

    Args:
        config: SlippageConfig with model parameters.
        context: SlippageContext with trade and market details.

    Returns:
        Slippage in pips (non-negative float).
    """
    pip_size = _pip_size_for_price(context.price)
    price_slippage = compute_slippage(config, context)
    return price_slippage / pip_size if pip_size > 0 else 0.0


def apply_to_trade(
    config: SlippageConfig,
    context: SlippageContext,
) -> float:
    """
    Apply slippage to a trade and return the adjusted fill price.

    For BUY orders, slippage increases the fill price (worse for buyer).
    For SELL orders, slippage decreases the fill price (worse for seller).

    Args:
        config: SlippageConfig with model parameters.
        context: SlippageContext with trade details including raw price.

    Returns:
        Adjusted fill price after slippage.

    Raises:
        ValueError: If adjusted price would be non-positive.
    """
    slippage = compute_slippage(config, context)

    if context.side == TradeSide.BUY:
        adjusted = context.price + slippage
    else:
        adjusted = context.price - slippage

    if adjusted <= 0:
        raise ValueError(
            f"Slippage-adjusted price is non-positive: {adjusted} "
            f"(price={context.price}, slippage={slippage}, side={context.side})"
        )

    return adjusted


def apply_slippage_to_price(
    price: float,
    slippage_pips: float,
    side: TradeSide = TradeSide.BUY,
) -> float:
    """
    Simple utility: apply a fixed slippage in pips to a price.

    Kept for backwards compatibility with code that just needs a quick
    fixed-pip adjustment without constructing full config/context objects.

    Args:
        price: Raw execution price.
        slippage_pips: Slippage amount in pips.
        side: Trade direction.

    Returns:
        Adjusted price.
    """
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")

    pip_size = _pip_size_for_price(price)
    slippage_price = slippage_pips * pip_size

    if side == TradeSide.BUY:
        return price + slippage_price
    else:
        result = price - slippage_price
        if result <= 0:
            raise ValueError(
                f"Adjusted price non-positive: {result} "
                f"(price={price}, slippage={slippage_price})"
            )
        return result
