from datetime import datetime, timezone

import pytest
from core.types import TradeDirection
from engine.protocol import CanonicalSignal


class TestCanonicalSignal:
    def test_basic_creation(self):
        signal = CanonicalSignal(
            strategy_id="srmr_gbpusd_h1",
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            confidence=0.85,
            entry_price=1.2500,
            stop_loss=1.2450,
            take_profit_1=1.2600,
        )
        assert signal.strategy_id == "srmr_gbpusd_h1"
        assert signal.symbol == "GBPUSD"
        assert signal.direction == TradeDirection.LONG
        assert signal.confidence == 0.85
        assert signal.take_profit_2 is None
        assert signal.take_profit_3 is None
        assert signal.metadata == {}

    def test_frozen(self):
        signal = CanonicalSignal(
            strategy_id="test",
            symbol="EURUSD",
            direction=TradeDirection.SHORT,
            confidence=0.5,
            entry_price=1.1,
            stop_loss=1.105,
            take_profit_1=1.09,
        )
        with pytest.raises(AttributeError):
            signal.confidence = 0.9

    def test_optional_tps(self):
        signal = CanonicalSignal(
            strategy_id="test",
            symbol="XAUUSD",
            direction=TradeDirection.LONG,
            confidence=0.6,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit_1=2010.0,
            take_profit_2=2020.0,
            take_profit_3=2030.0,
        )
        assert signal.take_profit_2 == 2020.0
        assert signal.take_profit_3 == 2030.0

    def test_default_timestamp(self):
        before = datetime.now(timezone.utc)
        signal = CanonicalSignal(
            strategy_id="test",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            confidence=0.5,
            entry_price=1.0,
            stop_loss=0.99,
            take_profit_1=1.01,
        )
        after = datetime.now(timezone.utc)
        assert before <= signal.timestamp <= after

    def test_metadata(self):
        signal = CanonicalSignal(
            strategy_id="test",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            confidence=0.5,
            entry_price=1.0,
            stop_loss=0.99,
            take_profit_1=1.01,
            metadata={"is_volatile": True, "gate_passed": True},
        )
        assert signal.metadata["is_volatile"] is True
