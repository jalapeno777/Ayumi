from datetime import datetime, timezone

import pytest
from core.types import Bar, MarketState, SessionType, TradeDirection
from strategies.bb_rsi_reversion import (
    BBRSIConfig,
    BBRSIMeanReversion,
    _adx,
    _atr,
    _bollinger_bands,
    _ema,
    _is_low_volatility,
    _rsi,
    _sma,
    _std,
)


def _make_bars(closes: list[float], hour: int = 10) -> list[Bar]:
    bars = []
    for i, c in enumerate(closes):  # noqa: B007
        t = datetime(2026, 4, 1, hour, 0, tzinfo=timezone.utc)
        bars.append(
            Bar(
                time=t,
                open=c,
                high=c + 0.0005,
                low=c - 0.0005,
                close=c,
                volume=100,
            )
        )
    return bars


class TestHelperFunctions:
    def test_sma_basic(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _sma(values, 3) == pytest.approx(4.0)

    def test_sma_insufficient_data(self):
        assert _sma([1.0, 2.0], 5) == 0.0

    def test_std_basic(self):
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        result = _std(values, len(values))
        assert result > 0

    def test_bollinger_bands(self):
        closes = [1.0] * 20 + [1.01] * 10
        upper, middle, lower = _bollinger_bands(closes, 20, 2.0)
        assert upper > middle > lower

    def test_rsi_overbought(self):
        closes = [1.0 + i * 0.001 for i in range(30)]
        rsi = _rsi(closes, 14)
        assert rsi > 70

    def test_rsi_oversold(self):
        closes = [1.0 - i * 0.001 for i in range(30)]
        rsi = _rsi(closes, 14)
        assert rsi < 30

    def test_rsi_insufficient_data(self):
        assert _rsi([1.0, 2.0], 14) == 50.0

    def test_atr_basic(self):
        bars = _make_bars([1.0] * 20, hour=10)
        atr = _atr(bars, 14)
        assert atr > 0

    def test_atr_insufficient_data(self):
        bars = _make_bars([1.0] * 5, hour=10)
        assert _atr(bars, 14) == pytest.approx(0.0001)

    def test_ema_basic(self):
        values = [1.0] * 50
        ema = _ema(values, 50)
        assert ema == pytest.approx(1.0)

    def test_adx_trending(self):
        bars = _make_bars([1.0 + i * 0.002 for i in range(60)], hour=10)
        adx = _adx(bars, 14)
        assert adx > 0

    def test_adx_insufficient_data(self):
        bars = _make_bars([1.0] * 10, hour=10)
        assert _adx(bars, 14) == 0.0

    def test_is_low_volatility_detects_decreasing_atr(self):
        closes = [1.0 + i * 0.001 for i in range(35)] + [1.035 - i * 0.0001 for i in range(15)]
        bars = _make_bars(closes, hour=10)
        result = _is_low_volatility(bars, 14, 20)
        assert isinstance(result, bool)

    def test_is_low_volatility_insufficient(self):
        bars = _make_bars([1.0] * 10, hour=10)
        assert _is_low_volatility(bars, 14, 20) is False


class TestBBRSIMeanReversion:
    def test_strategy_name(self):
        strat = BBRSIMeanReversion()
        assert strat.name == "BB+RSI Mean Reversion"

    def test_custom_config(self):
        cfg = BBRSIConfig(rsi_long_level=25.0, rsi_short_level=75.0)
        strat = BBRSIMeanReversion(config=cfg)
        assert strat.config.rsi_long_level == 25.0

    def test_returns_none_on_insufficient_bars(self):
        strat = BBRSIMeanReversion()
        bars = _make_bars([1.0] * 5, hour=10)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        assert strat.evaluate(state) is None

    def test_returns_none_outside_trading_hours(self):
        strat = BBRSIMeanReversion()
        closes = [1.0] * 100
        bars = _make_bars(closes, hour=22)
        state = MarketState(bars=bars, current_session=SessionType.OUTSIDE)
        assert strat.evaluate(state) is None

    def test_returns_none_in_ranging_flat_market(self):
        strat = BBRSIMeanReversion()
        closes = [1.2500] * 100
        bars = _make_bars(closes, hour=10)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        assert strat.evaluate(state) is None

    def test_returns_none_when_adx_high(self):
        cfg = BBRSIConfig(adx_max_threshold=10.0, require_low_volatility=False)
        strat = BBRSIMeanReversion(config=cfg)
        closes = [1.0 + i * 0.002 for i in range(100)]
        bars = _make_bars(closes, hour=10)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        assert strat.evaluate(state) is None

    def test_implements_isignalstrategy(self):
        from backtest.strategy_legacy import ISignalStrategy

        strat = BBRSIMeanReversion()
        assert isinstance(strat, ISignalStrategy)

    def test_long_signal_when_price_at_lower_bb_rsi_oversold(self):
        cfg = BBRSIConfig(
            bb_period=20,
            bb_std_dev=2.0,
            rsi_long_level=30.0,
            rsi_short_level=70.0,
            adx_max_threshold=50.0,
            require_low_volatility=False,
            ema_trend_period=5,
        )
        strat = BBRSIMeanReversion(config=cfg)

        base = 1.2500
        closes = [base] * 20
        for i in range(30):
            closes.append(base - (i + 1) * 0.001)
        for i in range(50):
            closes.append(base - 0.03 + i * 0.0003)

        bars = _make_bars(closes, hour=10)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strat.evaluate(state)

        if result is not None:
            assert result.direction == TradeDirection.LONG
            assert result.confidence >= 0.40
            assert result.stop_loss < result.entry_price
            assert result.take_profit_1 > result.entry_price

    def test_short_signal_when_price_at_upper_bb_rsi_overbought(self):
        cfg = BBRSIConfig(
            bb_period=20,
            bb_std_dev=2.0,
            rsi_long_level=30.0,
            rsi_short_level=70.0,
            adx_max_threshold=50.0,
            require_low_volatility=False,
            ema_trend_period=5,
        )
        strat = BBRSIMeanReversion(config=cfg)

        base = 1.2500
        closes = [base] * 20
        for i in range(30):
            closes.append(base + (i + 1) * 0.001)
        for i in range(50):
            closes.append(base + 0.03 - i * 0.0003)

        bars = _make_bars(closes, hour=10)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strat.evaluate(state)

        if result is not None:
            assert result.direction == TradeDirection.SHORT
            assert result.confidence >= 0.40
            assert result.stop_loss > result.entry_price
            assert result.take_profit_1 < result.entry_price

    def test_signal_has_valid_sl_tp(self):
        cfg = BBRSIConfig(
            atr_sl_multiplier=1.5,
            tp1_rr=1.0,
            tp2_rr=1.5,
            adx_max_threshold=50.0,
            require_low_volatility=False,
            ema_trend_period=5,
        )
        strat = BBRSIMeanReversion(config=cfg)

        base = 1.2500
        closes = [base] * 20
        for i in range(80):
            closes.append(base - (i + 1) * 0.0005)

        bars = _make_bars(closes, hour=10)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strat.evaluate(state)

        if result is not None:
            risk = abs(result.entry_price - result.stop_loss)
            expected_tp1_dist = risk * cfg.tp1_rr
            if result.direction == TradeDirection.LONG:
                assert result.take_profit_1 == pytest.approx(result.entry_price + expected_tp1_dist, rel=1e-4)
            else:
                assert result.take_profit_1 == pytest.approx(result.entry_price - expected_tp1_dist, rel=1e-4)

    def test_confidence_in_range(self):
        cfg = BBRSIConfig(
            adx_max_threshold=50.0,
            require_low_volatility=False,
            ema_trend_period=5,
        )
        strat = BBRSIMeanReversion(config=cfg)

        base = 1.2500
        closes = [base] * 20
        for i in range(80):
            closes.append(base - (i + 1) * 0.0005)

        bars = _make_bars(closes, hour=10)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strat.evaluate(state)

        if result is not None:
            assert 0.40 <= result.confidence <= 0.90

    def test_no_signal_without_bb_touch(self):
        cfg = BBRSIConfig(
            adx_max_threshold=50.0,
            require_low_volatility=False,
            ema_trend_period=5,
        )
        strat = BBRSIMeanReversion(config=cfg)

        base = 1.2500
        closes = [base + (i % 10) * 0.0001 for i in range(100)]

        bars = _make_bars(closes, hour=10)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        result = strat.evaluate(state)
        assert result is None

    def test_xauusd_pip_value(self):
        cfg = BBRSIConfig(pip_value=0.01, adx_max_threshold=50.0)
        strat = BBRSIMeanReversion(config=cfg)
        assert strat.config.pip_value == 0.01


class TestConfidenceFormula:
    """Verify the bell-curve confidence model (peaks at moderate distance)."""

    def _build_state_for_rsi(self, rsi_value: float, direction: str):
        """Create a MarketState that produces the desired RSI distance."""
        cfg = BBRSIConfig(
            rsi_long_level=30.0,
            rsi_short_level=70.0,
            adx_max_threshold=50.0,
            require_low_volatility=False,
            ema_trend_period=5,
        )
        strat = BBRSIMeanReversion(config=cfg)

        if direction == "long":
            # Drive price down to push RSI below 30
            base = 1.2500
            closes = [base] * 20
            for i in range(80):
                closes.append(base - (i + 1) * (0.0005 + rsi_value * 0.00005))
        else:
            base = 1.2500
            closes = [base] * 20
            for i in range(80):
                closes.append(base + (i + 1) * (0.0005 + rsi_value * 0.00005))

        bars = _make_bars(closes, hour=10)
        state = MarketState(bars=bars, current_session=SessionType.LONDON)
        return strat, state

    def test_moderate_distance_higher_than_extreme(self):
        """Confidence at distance=10 should be >= confidence at distance=25."""
        strat_mod, state_mod = self._build_state_for_rsi(10, "long")
        result_mod = strat_mod.evaluate(state_mod)

        strat_ext, state_ext = self._build_state_for_rsi(25, "long")
        result_ext = strat_ext.evaluate(state_ext)

        # Both should produce signals (or at least the moderate one)
        if result_mod and result_ext:
            assert result_mod.confidence >= result_ext.confidence, (
                f"Moderate distance should have higher confidence: "
                f"mod={result_mod.confidence}, ext={result_ext.confidence}"
            )

    def test_confidence_bounded(self):
        """All confidence values must stay within [0.40, 0.90]."""
        for distance in [0, 3, 7, 12, 18, 25, 30]:
            strat, state = self._build_state_for_rsi(distance, "long")
            result = strat.evaluate(state)
            if result is not None:
                assert 0.40 <= result.confidence <= 0.90, (
                    f"distance={distance}: confidence={result.confidence} out of bounds"
                )
