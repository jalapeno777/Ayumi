"""Tests for StrategyAdapter."""

import pytest
from orchestrator.strategy_adapter import StrategyAdapter


@pytest.fixture
def adapter():
    return StrategyAdapter()


class TestStrategyAdapter:
    def test_valid_signal(self, adapter):
        out = adapter.adapt_signal(
            "srmr",
            {
                "symbol": "EURUSD",
                "direction": "LONG",
                "entry_price": 1.0800,
                "stop_loss": 1.0790,
                "take_profit": 1.0850,
                "confidence": 0.85,
            },
        )
        assert out.strategy_id == "srmr"
        assert out.symbol == "EURUSD"
        assert out.direction == "LONG"
        assert out.entry_price == 1.0800
        assert out.confidence == 0.85

    def test_missing_symbol_raises(self, adapter):
        with pytest.raises(ValueError, match="symbol"):
            adapter.adapt_signal(
                "s1",
                {
                    "direction": "LONG",
                    "entry_price": 1.0,
                    "stop_loss": 0.99,
                },
            )

    def test_missing_direction_raises(self, adapter):
        with pytest.raises(ValueError, match="direction"):
            adapter.adapt_signal(
                "s1",
                {
                    "symbol": "EURUSD",
                    "entry_price": 1.0,
                    "stop_loss": 0.99,
                },
            )

    def test_missing_entry_price_raises(self, adapter):
        with pytest.raises(ValueError, match="entry_price"):
            adapter.adapt_signal(
                "s1",
                {
                    "symbol": "EURUSD",
                    "direction": "LONG",
                    "stop_loss": 0.99,
                },
            )

    def test_missing_stop_loss_raises(self, adapter):
        with pytest.raises(ValueError, match="stop_loss"):
            adapter.adapt_signal(
                "s1",
                {
                    "symbol": "EURUSD",
                    "direction": "LONG",
                    "entry_price": 1.0,
                },
            )

    def test_optional_defaults(self, adapter):
        out = adapter.adapt_signal(
            "s1",
            {
                "symbol": "GBPUSD",
                "direction": "SHORT",
                "entry_price": 1.2700,
                "stop_loss": 1.2720,
            },
        )
        assert out.take_profit == 0.0
        assert out.confidence == 0.5
        assert out.metadata == {}

    def test_direction_normalized(self, adapter):
        out = adapter.adapt_signal(
            "s1",
            {
                "symbol": "EURUSD",
                "direction": "long",
                "entry_price": 1.0,
                "stop_loss": 0.99,
            },
        )
        assert out.direction == "LONG"

    def test_optional_metadata(self, adapter):
        out = adapter.adapt_signal(
            "s1",
            {
                "symbol": "EURUSD",
                "direction": "LONG",
                "entry_price": 1.0,
                "stop_loss": 0.99,
                "spread": 0.0002,
                "atr": 0.001,
                "confluence_strategies": ["srmr", "bb"],
            },
        )
        assert out.metadata["spread"] == 0.0002
        assert out.metadata["atr"] == 0.001
        assert "srmr" in out.metadata["confluence_strategies"]

    def test_null_required_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.adapt_signal(
                "s1",
                {
                    "symbol": None,
                    "direction": "LONG",
                    "entry_price": 1.0,
                    "stop_loss": 0.99,
                },
            )
