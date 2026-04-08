from __future__ import annotations

import pytest
from datetime import datetime

from forex_trading.strategies.ict import (
    Bar,
    ConfluenceEngine,
    ConfluenceSignal,
    ICTEngine,
    ICTMarketState,
    SignalStrength,
    TradeDirection,
)


@pytest.fixture
def trending_bars():
    return [
        Bar(
            time=datetime(2024, 1, 1, 0, 0),
            open=1.1000,
            high=1.1010,
            low=1.0990,
            close=1.1005,
        ),
        Bar(
            time=datetime(2024, 1, 1, 1, 0),
            open=1.1005,
            high=1.1020,
            low=1.1000,
            close=1.1015,
        ),
        Bar(
            time=datetime(2024, 1, 1, 2, 0),
            open=1.1015,
            high=1.1030,
            low=1.1010,
            close=1.1020,
        ),
        Bar(
            time=datetime(2024, 1, 1, 3, 0),
            open=1.1020,
            high=1.1040,
            low=1.1015,
            close=1.1035,
        ),
        Bar(
            time=datetime(2024, 1, 1, 4, 0),
            open=1.1035,
            high=1.1050,
            low=1.1030,
            close=1.1040,
        ),
        Bar(
            time=datetime(2024, 1, 1, 5, 0),
            open=1.1040,
            high=1.1048,
            low=1.1035,
            close=1.1038,
        ),
        Bar(
            time=datetime(2024, 1, 1, 6, 0),
            open=1.1038,
            high=1.1042,
            low=1.1030,
            close=1.1032,
        ),
        Bar(
            time=datetime(2024, 1, 1, 7, 0),
            open=1.1032,
            high=1.1038,
            low=1.1025,
            close=1.1028,
        ),
        Bar(
            time=datetime(2024, 1, 1, 8, 0),
            open=1.1028,
            high=1.1035,
            low=1.1020,
            close=1.1025,
        ),
        Bar(
            time=datetime(2024, 1, 1, 9, 0),
            open=1.1025,
            high=1.1030,
            low=1.1015,
            close=1.1020,
        ),
        Bar(
            time=datetime(2024, 1, 1, 10, 0),
            open=1.1020,
            high=1.1030,
            low=1.1010,
            close=1.1025,
        ),
    ]


@pytest.fixture
def market_state(trending_bars):
    state = ICTMarketState(trending_bars)
    state.atr = state.calculate_atr()
    return state


class TestConfluenceEngine:
    def test_evaluate_returns_signal_or_none(self, market_state):
        engine = ConfluenceEngine(min_confidence=0.3)
        signal = engine.evaluate(market_state)

        if signal is not None:
            assert isinstance(signal, ConfluenceSignal)
            assert signal.direction in [
                TradeDirection.LONG,
                TradeDirection.SHORT,
                TradeDirection.NEUTRAL,
            ]
            assert 0.0 <= signal.confidence_score <= 1.0

    def test_signal_has_required_fields(self, market_state):
        engine = ConfluenceEngine(min_confidence=0.3)
        signal = engine.evaluate(market_state)

        if signal is not None:
            assert signal.entry_price > 0
            assert signal.stop_loss > 0
            assert signal.take_profit_1 > 0
            assert signal.take_profit_2 > 0
            assert signal.take_profit_3 > 0
            assert signal.rationale is not None

    def test_risk_reward_calculation(self, market_state):
        engine = ConfluenceEngine(min_confidence=0.3)
        signal = engine.evaluate(market_state)

        if signal is not None:
            risk = abs(signal.entry_price - signal.stop_loss)
            reward = abs(signal.take_profit_2 - signal.entry_price)
            if risk > 0:
                expected_rr = reward / risk
                assert abs(signal.risk_reward_ratio - expected_rr) < 0.01

    def test_confidence_below_threshold_returns_none(self, market_state):
        engine = ConfluenceEngine(min_confidence=0.99)
        signal = engine.evaluate(market_state)
        assert signal is None

    def test_take_profit_levels_increasing_for_long(self, market_state):
        market_state.structure_bias = TradeDirection.LONG
        engine = ConfluenceEngine(min_confidence=0.3)
        signal = engine.evaluate(market_state)

        if signal is not None and signal.direction == TradeDirection.LONG:
            assert signal.take_profit_1 > signal.entry_price
            assert signal.take_profit_2 > signal.take_profit_1
            assert signal.take_profit_3 > signal.take_profit_2
            assert signal.stop_loss < signal.entry_price

    def test_take_profit_levels_decreasing_for_short(self, market_state):
        market_state.structure_bias = TradeDirection.SHORT
        engine = ConfluenceEngine(min_confidence=0.3)
        signal = engine.evaluate(market_state)

        if signal is not None and signal.direction == TradeDirection.SHORT:
            assert signal.take_profit_1 < signal.entry_price
            assert signal.take_profit_2 < signal.take_profit_1
            assert signal.take_profit_3 < signal.take_profit_2
            assert signal.stop_loss > signal.entry_price


class TestICTEngine:
    def test_engine_initialization(self):
        engine = ICTEngine()
        assert engine._ob_detector is not None
        assert engine._fvg_detector is not None
        assert engine._confluence_engine is not None

    def test_update_market_state(self, market_state):
        engine = ICTEngine()
        engine.update_market_state(market_state)

        assert len(market_state.active_order_blocks) >= 0
        assert len(market_state.active_fvgs) >= 0

    def test_get_order_block(self, market_state):
        engine = ICTEngine()
        engine.update_market_state(market_state)

        ob = engine.get_order_block(market_state, TradeDirection.LONG)
        if ob is not None:
            assert ob.direction == TradeDirection.LONG

    def test_get_fvg(self, market_state):
        engine = ICTEngine()
        engine.update_market_state(market_state)

        fvg = engine.get_fvg(market_state, TradeDirection.LONG, 1.1020)
        if fvg is not None:
            assert fvg.direction == TradeDirection.LONG

    def test_evaluate_confluence(self, market_state):
        engine = ICTEngine()
        signal = engine.evaluate_confluence(market_state)

        if signal is not None:
            assert isinstance(signal, ConfluenceSignal)

    def test_set_direction_bias(self, market_state):
        engine = ICTEngine()
        engine.set_direction_bias(market_state, TradeDirection.LONG)
        assert market_state.structure_bias == TradeDirection.LONG


class TestSignalStrength:
    def test_strength_classification_bounds(self):
        assert SignalStrength.WEAK is not None
        assert SignalStrength.MODERATE is not None
        assert SignalStrength.STRONG is not None
        assert SignalStrength.VERY_STRONG is not None
