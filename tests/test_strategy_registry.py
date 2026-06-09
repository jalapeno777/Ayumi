import pytest
from engine.strategy_registry import StrategySlot


class TestStrategySlot:
    def test_creation(self):
        slot = StrategySlot(
            id="srmr_gbpusd_h1",
            strategy_type="srmr_plus",
            symbol="GBPUSD",
            timeframe="H1",
            params={"session_range_min_pips": 25.0},
            min_confidence=0.40,
        )
        assert slot.id == "srmr_gbpusd_h1"
        assert slot.strategy_type == "srmr_plus"
        assert slot.enabled is True
        assert slot.weight == 1.0

    def test_disabled_slot(self):
        slot = StrategySlot(
            id="bb_eurusd_h1",
            strategy_type="bb_rsi",
            symbol="EURUSD",
            timeframe="H1",
            params={},
            min_confidence=0.45,
            enabled=False,
        )
        assert slot.enabled is False

    def test_frozen(self):
        slot = StrategySlot(
            id="test",
            strategy_type="test",
            symbol="EURUSD",
            timeframe="H1",
            params={},
            min_confidence=0.5,
        )
        with pytest.raises(AttributeError):
            slot.enabled = False
