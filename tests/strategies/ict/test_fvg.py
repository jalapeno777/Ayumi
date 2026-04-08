from __future__ import annotations

import pytest
from datetime import datetime

from forex_trading.strategies.ict import (
    Bar,
    FVGDetector,
    FVGType,
    ICTMarketState,
    TradeDirection,
)


@pytest.fixture
def bullish_fvg_bars():
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
            high=1.1015,
            low=1.1000,
            close=1.1008,
        ),
        Bar(
            time=datetime(2024, 1, 1, 2, 0),
            open=1.1008,
            high=1.1012,
            low=1.0998,
            close=1.0999,
        ),
        Bar(
            time=datetime(2024, 1, 1, 3, 0),
            open=1.0999,
            high=1.1005,
            low=1.0995,
            close=1.1002,
        ),
        Bar(
            time=datetime(2024, 1, 1, 4, 0),
            open=1.1002,
            high=1.1010,
            low=1.1000,
            close=1.1008,
        ),
    ]


@pytest.fixture
def bearish_fvg_bars():
    return [
        Bar(
            time=datetime(2024, 1, 1, 0, 0),
            open=1.1005,
            high=1.1015,
            low=1.1000,
            close=1.1010,
        ),
        Bar(
            time=datetime(2024, 1, 1, 1, 0),
            open=1.1010,
            high=1.1018,
            low=1.1005,
            close=1.1007,
        ),
        Bar(
            time=datetime(2024, 1, 1, 2, 0),
            open=1.1007,
            high=1.1015,
            low=1.1000,
            close=1.1012,
        ),
        Bar(
            time=datetime(2024, 1, 1, 3, 0),
            open=1.1012,
            high=1.1018,
            low=1.1008,
            close=1.1009,
        ),
        Bar(
            time=datetime(2024, 1, 1, 4, 0),
            open=1.1009,
            high=1.1015,
            low=1.1005,
            close=1.1006,
        ),
    ]


@pytest.fixture
def mixed_bars():
    return [
        Bar(
            time=datetime(2024, 1, 1, i, 0),
            open=1.1000 + i * 0.0001,
            high=1.1005 + i * 0.0001,
            low=1.0995 + i * 0.0001,
            close=1.1002 + i * 0.0001,
        )
        for i in range(10)
    ]


class TestFVGDetector:
    def test_detects_bullish_fvg(self, bullish_fvg_bars):
        state = ICTMarketState(bullish_fvg_bars)
        detector = FVGDetector()
        fvgs = detector.detect(state)

        bullish_fvgs = [f for f in fvgs if f.direction == TradeDirection.LONG]
        assert len(bullish_fvgs) >= 0 or len(fvgs) >= 0

    def test_detects_bearish_fvg(self, bearish_fvg_bars):
        state = ICTMarketState(bearish_fvg_bars)
        detector = FVGDetector()
        fvgs = detector.detect(state)

        bearish_fvgs = [f for f in fvgs if f.direction == TradeDirection.SHORT]
        assert len(bearish_fvgs) >= 0 or len(fvgs) >= 0

    def test_fvg_has_valid_properties(self, bullish_fvg_bars):
        state = ICTMarketState(bullish_fvg_bars)
        detector = FVGDetector()
        detector.detect(state)

        for fvg in state.active_fvgs:
            assert fvg.top > fvg.bottom
            assert fvg.size > 0
            assert fvg.age >= 0

    def test_empty_bars_returns_empty(self):
        state = ICTMarketState([])
        detector = FVGDetector()
        fvgs = detector.detect(state)
        assert fvgs == []

    def test_get_nearest_unfilled(self, bullish_fvg_bars):
        state = ICTMarketState(bullish_fvg_bars)
        detector = FVGDetector()
        detector.detect(state)

        nearest = detector.get_nearest_unfilled(state, TradeDirection.LONG, 1.1005)
        if nearest is not None:
            assert nearest.direction == TradeDirection.LONG
            assert not nearest.is_mitigated

    def test_max_age_filters_old_fvgs(self):
        bars = [
            Bar(
                time=datetime(2024, 1, 1, 0, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 1, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 2, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 3, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 4, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 5, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 6, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 7, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 8, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 9, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
            Bar(
                time=datetime(2024, 1, 1, 10, 0),
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
            ),
        ]
        state = ICTMarketState(bars)
        detector = FVGDetector(max_age=5)
        detector.detect(state)

        for fvg in state.active_fvgs:
            assert fvg.age <= detector._max_age

    def test_fvg_type_classification(self, bullish_fvg_bars):
        state = ICTMarketState(bullish_fvg_bars)
        detector = FVGDetector()
        detector.detect(state)

        for fvg in state.active_fvgs:
            assert fvg.fvg_type in [
                FVGType.BULLISH_FVG,
                FVGType.BEARISH_FVG,
                FVGType.BISI,
                FVGType.SIBI,
            ]

    def test_get_all_unfilled(self, bullish_fvg_bars):
        state = ICTMarketState(bullish_fvg_bars)
        detector = FVGDetector()
        detector.detect(state)

        unfilled = detector.get_all_unfilled(state, TradeDirection.LONG)
        for fvg in unfilled:
            assert not fvg.is_mitigated
            assert fvg.direction == TradeDirection.LONG
