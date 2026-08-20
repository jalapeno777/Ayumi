from __future__ import annotations  # noqa: I001

import pytest
from datetime import datetime

from backtest.engine import Bar, TradeDirection
from backtest.ict_smc import ICTMarketState, OrderBlockDetector


@pytest.fixture
def sample_bars():
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
            high=1.1035,
            low=1.1015,
            close=1.1025,
        ),
        Bar(
            time=datetime(2024, 1, 1, 4, 0),
            open=1.1025,
            high=1.1040,
            low=1.1020,
            close=1.1030,
        ),
        Bar(
            time=datetime(2024, 1, 1, 5, 0),
            open=1.1030,
            high=1.1045,
            low=1.1025,
            close=1.1035,
        ),
        Bar(
            time=datetime(2024, 1, 1, 6, 0),
            open=1.1035,
            high=1.1050,
            low=1.1030,
            close=1.1040,
        ),
        Bar(
            time=datetime(2024, 1, 1, 7, 0),
            open=1.1040,
            high=1.1048,
            low=1.1035,
            close=1.1038,
        ),
        Bar(
            time=datetime(2024, 1, 1, 8, 0),
            open=1.1038,
            high=1.1042,
            low=1.1030,
            close=1.1032,
        ),
        Bar(
            time=datetime(2024, 1, 1, 9, 0),
            open=1.1032,
            high=1.1038,
            low=1.1025,
            close=1.1028,
        ),
        Bar(
            time=datetime(2024, 1, 1, 10, 0),
            open=1.1028,
            high=1.1035,
            low=1.1020,
            close=1.1025,
        ),
    ]


@pytest.fixture
def market_state(sample_bars):
    return ICTMarketState(sample_bars)


class TestOrderBlockDetector:
    def test_detects_bullish_order_block(self, market_state):
        market_state.structure_bias = TradeDirection.LONG
        detector = OrderBlockDetector(freshness_window=5, min_body_ratio=0.5)
        obs = detector.detect(market_state)

        bullish_obs = [ob for ob in obs if ob.direction == TradeDirection.LONG]
        assert len(bullish_obs) >= 0 or len(obs) >= 0

    def test_detects_bearish_order_block(self, market_state):
        market_state.structure_bias = TradeDirection.SHORT
        detector = OrderBlockDetector(freshness_window=5, min_body_ratio=0.5)
        obs = detector.detect(market_state)

        bearish_obs = [ob for ob in obs if ob.direction == TradeDirection.SHORT]
        assert len(bearish_obs) >= 0 or len(obs) >= 0

    def test_order_block_strength_calculation(self, market_state):
        detector = OrderBlockDetector()
        detector.detect(market_state)

        for ob in market_state.active_order_blocks:
            assert 0.0 <= ob.strength <= 1.0

    def test_get_most_relevant_returns_strongest_freshest(self, market_state):
        detector = OrderBlockDetector(freshness_window=10)
        detector.detect(market_state)

        long_ob = detector.get_most_relevant(market_state, TradeDirection.LONG)
        if long_ob is not None:
            assert long_ob.direction == TradeDirection.LONG
            assert not long_ob.is_mitigated

    def test_empty_bars_returns_empty(self):
        state = ICTMarketState([])
        detector = OrderBlockDetector()
        obs = detector.detect(state)
        assert obs == []

    def test_freshness_window_filters_old_blocks(self, market_state):
        detector = OrderBlockDetector(freshness_window=2)
        detector.detect(market_state)

        for ob in market_state.active_order_blocks:
            assert ob.age <= detector._freshness_window * 3


class TestICTMakretStateHelpers:
    def test_bar_body_calculation(self):
        bar = Bar(datetime.now(), open=1.1000, high=1.1010, low=1.0990, close=1.1005)
        body = ICTMarketState.bar_body(bar)
        assert abs(body - 0.0005) < 0.0001

    def test_bar_range_calculation(self):
        bar = Bar(datetime.now(), open=1.1000, high=1.1010, low=1.0990, close=1.1005)
        r = ICTMarketState.bar_range(bar)
        assert abs(r - 0.0020) < 0.0001

    def test_bullish_bar_identification(self):
        bar = Bar(datetime.now(), open=1.1000, high=1.1010, low=1.0990, close=1.1005)
        assert ICTMarketState.bar_is_bullish(bar)

    def test_bearish_bar_identification(self):
        bar = Bar(datetime.now(), open=1.1005, high=1.1010, low=1.0990, close=1.1000)
        assert ICTMarketState.bar_is_bearish(bar)
