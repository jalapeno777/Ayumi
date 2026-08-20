"""
Unit tests for backtest.slippage_model.

Covers:
- SlippageConfig validation
- SlippageContext validation
- FIXED model: baseline, zero slippage, max cap
- LINEAR model: scaling with volume, base + volume impact
- SQUARE_ROOT model: sqrt scaling, institutional-grade behavior
- Session liquidity adjustments
- Volatility adjustments
- apply_to_trade directionality (buy vs sell)
- apply_slippage_to_price utility
- Edge cases: JPY pairs, cross pairs, extreme values
"""

import pytest  # noqa: I001

from backtest.slippage_model import (
    SlippageConfig,
    SlippageContext,
    SlippageModel,
    TradeSide,
    compute_slippage,
    compute_slippage_pips,
    apply_to_trade,
    apply_slippage_to_price,
    _pip_size_for_price,
)


# ---------------------------------------------------------------------------
# Config / Context validation
# ---------------------------------------------------------------------------


class TestSlippageConfigValidation:
    def test_default_config(self):
        cfg = SlippageConfig()
        assert cfg.model == SlippageModel.FIXED
        assert cfg.base_slippage_pips == 0.2
        assert cfg.max_slippage_pips == 5.0

    def test_negative_base_slippage_rejected(self):
        with pytest.raises(ValueError, match="base_slippage_pips"):
            SlippageConfig(base_slippage_pips=-0.1)

    def test_negative_volume_coefficient_rejected(self):
        with pytest.raises(ValueError, match="volume_coefficient"):
            SlippageConfig(volume_coefficient=-1.0)

    def test_zero_max_slippage_rejected(self):
        with pytest.raises(ValueError, match="max_slippage_pips"):
            SlippageConfig(max_slippage_pips=0)

    def test_negative_adv_lots_rejected(self):
        with pytest.raises(ValueError, match="adv_lots"):
            SlippageConfig(adv_lots=-100)

    def test_custom_config_accepted(self):
        cfg = SlippageConfig(
            model=SlippageModel.SQUARE_ROOT,
            base_slippage_pips=0.5,
            volume_coefficient=2.0,
            adv_lots=50000,
            max_slippage_pips=10.0,
            session_aware=True,
        )
        assert cfg.model == SlippageModel.SQUARE_ROOT
        assert cfg.adv_lots == 50000


class TestSlippageContextValidation:
    def test_valid_context(self):
        ctx = SlippageContext(price=1.0850, side=TradeSide.BUY, trade_lots=2.0)
        assert ctx.price == 1.0850
        assert ctx.trade_lots == 2.0

    def test_zero_price_rejected(self):
        with pytest.raises(ValueError, match="price must be positive"):
            SlippageContext(price=0)

    def test_negative_price_rejected(self):
        with pytest.raises(ValueError, match="price must be positive"):
            SlippageContext(price=-1.0)

    def test_zero_lots_rejected(self):
        with pytest.raises(ValueError, match="trade_lots must be positive"):
            SlippageContext(price=1.0, trade_lots=0)

    def test_optional_fields_default_none(self):
        ctx = SlippageContext(price=1.0)
        assert ctx.volatility_pips is None
        assert ctx.session is None
        assert ctx.side == TradeSide.BUY  # default


# ---------------------------------------------------------------------------
# FIXED model
# ---------------------------------------------------------------------------


class TestFixedModel:
    def test_fixed_baseline_eurusd(self):
        """Standard EURUSD: 0.2 pip slippage on 1.0850 price."""
        cfg = SlippageConfig(model=SlippageModel.FIXED, base_slippage_pips=0.2)
        ctx = SlippageContext(price=1.0850)
        result = compute_slippage(cfg, ctx)
        # pip_size = 0.0001, slippage = 0.2 * 0.0001 = 0.00002
        assert result == pytest.approx(0.00002, rel=1e-6)

    def test_fixed_zero_slippage(self):
        """Zero base slippage = zero result."""
        cfg = SlippageConfig(model=SlippageModel.FIXED, base_slippage_pips=0.0)
        ctx = SlippageContext(price=1.0850)
        assert compute_slippage(cfg, ctx) == 0.0

    def test_fixed_capped_at_max(self):
        """Slippage is capped at max_slippage_pips."""
        cfg = SlippageConfig(
            model=SlippageModel.FIXED,
            base_slippage_pips=10.0,
            max_slippage_pips=3.0,
        )
        ctx = SlippageContext(price=1.0850)
        result_pips = compute_slippage_pips(cfg, ctx)
        assert result_pips == 3.0

    def test_fixed_jpy_pair(self):
        """USDJPY price ~150: pip_size = 0.01."""
        cfg = SlippageConfig(model=SlippageModel.FIXED, base_slippage_pips=0.5)
        ctx = SlippageContext(price=150.0)
        result = compute_slippage(cfg, ctx)
        assert result == pytest.approx(0.005, rel=1e-6)  # 0.5 * 0.01


# ---------------------------------------------------------------------------
# LINEAR model
# ---------------------------------------------------------------------------


class TestLinearModel:
    def test_linear_small_trade_minimal_impact(self):
        """Small trade relative to ADV → close to base slippage."""
        cfg = SlippageConfig(
            model=SlippageModel.LINEAR,
            base_slippage_pips=0.2,
            volume_coefficient=0.5,
            adv_lots=100_000,
        )
        ctx = SlippageContext(price=1.0850, trade_lots=1.0)
        result_pips = compute_slippage_pips(cfg, ctx)
        # volume_fraction = 1/100000 = 0.00001
        # volume_impact = 0.5 * 0.00001 * 100 = 0.0005 pips
        # total = 0.2 + 0.0005 = 0.2005
        assert result_pips == pytest.approx(0.2005, rel=1e-4)

    def test_linear_large_trade_significant_impact(self):
        """Large trade relative to ADV → noticeable volume impact."""
        cfg = SlippageConfig(
            model=SlippageModel.LINEAR,
            base_slippage_pips=0.2,
            volume_coefficient=1.0,
            adv_lots=1000,
        )
        ctx = SlippageContext(price=1.0850, trade_lots=100.0)
        result_pips = compute_slippage_pips(cfg, ctx)
        # volume_fraction = 100/1000 = 0.1
        # volume_impact = 1.0 * 0.1 * 100 = 10 pips
        # total = 0.2 + 10 = 10.2, capped at 5.0
        assert result_pips == 5.0  # capped

    def test_linear_scales_with_lots(self):
        """Doubling lots should increase slippage."""
        cfg = SlippageConfig(
            model=SlippageModel.LINEAR,
            base_slippage_pips=0.0,
            volume_coefficient=1.0,
            adv_lots=10000,
        )
        ctx_small = SlippageContext(price=1.0850, trade_lots=10.0)
        ctx_big = SlippageContext(price=1.0850, trade_lots=20.0)
        small = compute_slippage_pips(cfg, ctx_small)
        big = compute_slippage_pips(cfg, ctx_big)
        assert big > small
        assert big == pytest.approx(small * 2, rel=1e-6)


# ---------------------------------------------------------------------------
# SQUARE_ROOT model
# ---------------------------------------------------------------------------


class TestSquareRootModel:
    def test_sqrt_small_trade(self):
        """Small trade → sqrt impact is modest."""
        cfg = SlippageConfig(
            model=SlippageModel.SQUARE_ROOT,
            base_slippage_pips=0.2,
            volume_coefficient=1.0,
            adv_lots=100_000,
        )
        ctx = SlippageContext(price=1.0850, trade_lots=1.0)
        result_pips = compute_slippage_pips(cfg, ctx)
        # volume_fraction = 1/100000 = 0.00001
        # sqrt(0.00001 * 100) = sqrt(0.001) = 0.031623
        # total = 0.2 + 0.031623 = 0.231623
        assert result_pips == pytest.approx(0.2316, rel=1e-3)

    def test_sqrt_large_trade(self):
        """Large trade → sqrt impact is meaningful but sub-linear."""
        cfg = SlippageConfig(
            model=SlippageModel.SQUARE_ROOT,
            base_slippage_pips=0.0,
            volume_coefficient=1.0,
            adv_lots=1000,
        )
        ctx = SlippageContext(price=1.0850, trade_lots=100.0)
        result_pips = compute_slippage_pips(cfg, ctx)
        # volume_fraction = 100/1000 = 0.1
        # sqrt(0.1 * 100) = sqrt(10) = 3.1623
        assert result_pips == pytest.approx(3.1623, rel=1e-3)

    def test_sqrt_sublinear_scaling(self):
        """Sqrt model scales sub-linearly: 4x volume → 2x impact."""
        cfg = SlippageConfig(
            model=SlippageModel.SQUARE_ROOT,
            base_slippage_pips=0.0,
            volume_coefficient=1.0,
            adv_lots=10000,
        )
        small = compute_slippage_pips(cfg, SlippageContext(price=1.0, trade_lots=10.0))
        big = compute_slippage_pips(cfg, SlippageContext(price=1.0, trade_lots=40.0))
        # 4x volume → 2x slippage (sqrt property)
        assert big == pytest.approx(small * 2, rel=1e-6)


# ---------------------------------------------------------------------------
# Session and volatility adjustments
# ---------------------------------------------------------------------------


class TestSessionAdjustment:
    def test_london_session_no_penalty(self):
        """London session = factor 1.0 (no increase)."""
        cfg = SlippageConfig(
            model=SlippageModel.FIXED,
            base_slippage_pips=1.0,
            session_aware=True,
        )
        ctx = SlippageContext(price=1.0850, session="LONDON")
        result_pips = compute_slippage_pips(cfg, ctx)
        assert result_pips == pytest.approx(1.0, rel=1e-6)

    def test_outside_session_increased(self):
        """Outside session = factor 1.6."""
        cfg = SlippageConfig(
            model=SlippageModel.FIXED,
            base_slippage_pips=1.0,
            session_aware=True,
        )
        ctx = SlippageContext(price=1.0850, session="OUTSIDE")
        result_pips = compute_slippage_pips(cfg, ctx)
        assert result_pips == pytest.approx(1.6, rel=1e-6)

    def test_asian_session_factor(self):
        """Asian session = factor 1.3."""
        cfg = SlippageConfig(
            model=SlippageModel.FIXED,
            base_slippage_pips=1.0,
            session_aware=True,
        )
        ctx = SlippageContext(price=1.0850, session="ASIAN")
        result_pips = compute_slippage_pips(cfg, ctx)
        assert result_pips == pytest.approx(1.3, rel=1e-6)

    def test_session_unaware_ignores_session(self):
        """When session_aware=False, session has no effect."""
        cfg = SlippageConfig(
            model=SlippageModel.FIXED,
            base_slippage_pips=1.0,
            session_aware=False,
        )
        ctx = SlippageContext(price=1.0850, session="OUTSIDE")
        result_pips = compute_slippage_pips(cfg, ctx)
        assert result_pips == pytest.approx(1.0, rel=1e-6)


class TestVolatilityAdjustment:
    def test_volatility_adds_to_slippage(self):
        """Volatility component is added to base slippage."""
        cfg = SlippageConfig(
            model=SlippageModel.FIXED,
            base_slippage_pips=0.5,
            volatility_coefficient=0.1,
        )
        ctx = SlippageContext(price=1.0850, volatility_pips=2.0)
        result_pips = compute_slippage_pips(cfg, ctx)
        # base 0.5 + vol_coeff * vol = 0.5 + 0.1 * 2.0 = 0.7
        assert result_pips == pytest.approx(0.7, rel=1e-6)

    def test_zero_volatility_coefficient_ignores_volatility(self):
        """volatility_coefficient=0 → volatility input has no effect."""
        cfg = SlippageConfig(
            model=SlippageModel.FIXED,
            base_slippage_pips=0.5,
            volatility_coefficient=0.0,
        )
        ctx = SlippageContext(price=1.0850, volatility_pips=10.0)
        result_pips = compute_slippage_pips(cfg, ctx)
        assert result_pips == pytest.approx(0.5, rel=1e-6)


# ---------------------------------------------------------------------------
# apply_to_trade
# ---------------------------------------------------------------------------


class TestApplyToTrade:
    def test_buy_increases_price(self):
        """Buy slippage makes fill price worse (higher)."""
        cfg = SlippageConfig(model=SlippageModel.FIXED, base_slippage_pips=1.0)
        ctx = SlippageContext(price=1.0850, side=TradeSide.BUY)
        adjusted = apply_to_trade(cfg, ctx)
        assert adjusted > 1.0850
        # 1.0 pip * 0.0001 = 0.0001
        assert adjusted == pytest.approx(1.0851, rel=1e-6)

    def test_sell_decreases_price(self):
        """Sell slippage makes fill price worse (lower)."""
        cfg = SlippageConfig(model=SlippageModel.FIXED, base_slippage_pips=1.0)
        ctx = SlippageContext(price=1.0850, side=TradeSide.SELL)
        adjusted = apply_to_trade(cfg, ctx)
        assert adjusted < 1.0850
        assert adjusted == pytest.approx(1.0849, rel=1e-6)

    def test_symmetric_slippage(self):
        """Same magnitude for buy and sell."""
        cfg = SlippageConfig(model=SlippageModel.FIXED, base_slippage_pips=2.0)
        buy_ctx = SlippageContext(price=1.0850, side=TradeSide.BUY)
        sell_ctx = SlippageContext(price=1.0850, side=TradeSide.SELL)
        buy_adj = apply_to_trade(cfg, buy_ctx)
        sell_adj = apply_to_trade(cfg, sell_ctx)
        deviation = abs((1.0850 - buy_adj) - (sell_adj - 1.0850))
        assert deviation < 1e-10

    def test_jpy_pair_apply(self):
        """USDJPY pair uses correct pip size."""
        cfg = SlippageConfig(model=SlippageModel.FIXED, base_slippage_pips=1.0)
        ctx = SlippageContext(price=150.00, side=TradeSide.BUY)
        adjusted = apply_to_trade(cfg, ctx)
        # pip_size = 0.01, slippage = 1.0 * 0.01 = 0.01
        assert adjusted == pytest.approx(150.01, rel=1e-6)


# ---------------------------------------------------------------------------
# apply_slippage_to_price utility
# ---------------------------------------------------------------------------


class TestApplySlippageToPrice:
    def test_buy_utility(self):
        result = apply_slippage_to_price(1.0850, 1.0, TradeSide.BUY)
        assert result == pytest.approx(1.0851, rel=1e-6)

    def test_sell_utility(self):
        result = apply_slippage_to_price(1.0850, 1.0, TradeSide.SELL)
        assert result == pytest.approx(1.0849, rel=1e-6)

    def test_zero_slippage_returns_price(self):
        result = apply_slippage_to_price(1.0850, 0.0, TradeSide.BUY)
        assert result == 1.0850

    def test_invalid_price_rejected(self):
        with pytest.raises(ValueError, match="price must be positive"):
            apply_slippage_to_price(0, 1.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_pip_size_helper_standard_fx(self):
        assert _pip_size_for_price(1.0850) == 0.0001

    def test_pip_size_helper_jpy(self):
        assert _pip_size_for_price(150.0) == 0.01

    def test_pip_size_helper_sub_unit(self):
        assert _pip_size_for_price(0.5) == 0.00000001

    def test_combined_session_and_volatility(self):
        """Session + volatility adjustments stack."""
        cfg = SlippageConfig(
            model=SlippageModel.FIXED,
            base_slippage_pips=0.5,
            volatility_coefficient=0.2,
            session_aware=True,
        )
        ctx = SlippageContext(
            price=1.0850,
            session="OUTSIDE",
            volatility_pips=3.0,
        )
        result_pips = compute_slippage_pips(cfg, ctx)
        # base 0.5 + vol 0.2*3.0 = 1.1 → 1.1 * 1.6 (OUTSIDE) = 1.76
        assert result_pips == pytest.approx(1.76, rel=1e-4)

    def test_xauusd_pair_pip_size(self):
        """XAUUSD ~2000: price >= 50, pip_size = 0.01."""
        cfg = SlippageConfig(model=SlippageModel.FIXED, base_slippage_pips=0.5)
        ctx = SlippageContext(price=2050.0)
        result = compute_slippage(cfg, ctx)
        assert result == pytest.approx(0.005, rel=1e-6)
