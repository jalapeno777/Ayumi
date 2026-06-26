from datetime import datetime, timezone

import pytest

from hybrid.signal import HumanSignal, SignalSource, SignalType


class TestSignalType:
    def test_buy_value(self):
        assert SignalType.BUY == "buy"

    def test_sell_value(self):
        assert SignalType.SELL == "sell"

    def test_close_value(self):
        assert SignalType.CLOSE == "close"

    def test_all_values(self):
        assert set(SignalType) == {SignalType.BUY, SignalType.SELL, SignalType.CLOSE}


class TestSignalSource:
    def test_manual_value(self):
        assert SignalSource.MANUAL == "manual"

    def test_web_value(self):
        assert SignalSource.WEB == "web"

    def test_api_value(self):
        assert SignalSource.API == "api"


class TestHumanSignalCreation:
    def test_create_buy_signal_minimal(self):
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1000,
        )
        assert signal.signal_type == SignalType.BUY
        assert signal.pair == "EUR/USD"
        assert signal.entry_price == 1.1000
        assert signal.stop_loss is None
        assert signal.take_profit is None
        assert signal.confidence is None
        assert signal.source == SignalSource.MANUAL
        assert signal.timestamp.tzinfo == timezone.utc

    def test_create_sell_signal_full(self):
        ts = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)
        signal = HumanSignal(
            signal_type=SignalType.SELL,
            pair="GBP/USD",
            entry_price=1.2600,
            stop_loss=1.2650,
            take_profit=1.2450,
            confidence=0.8,
            source=SignalSource.API,
            timestamp=ts,
        )
        assert signal.signal_type == SignalType.SELL
        assert signal.pair == "GBP/USD"
        assert signal.entry_price == 1.2600
        assert signal.stop_loss == 1.2650
        assert signal.take_profit == 1.2450
        assert signal.confidence == 0.8
        assert signal.source == SignalSource.API
        assert signal.timestamp == ts

    def test_create_close_signal_no_price_required(self):
        signal = HumanSignal(
            signal_type=SignalType.CLOSE,
            pair="EUR/USD",
        )
        assert signal.entry_price == 0.0
        assert signal.signal_type == SignalType.CLOSE


class TestHumanSignalValidation:
    def test_empty_pair_raises(self):
        with pytest.raises(ValueError, match="pair must not be empty"):
            HumanSignal(signal_type=SignalType.BUY, pair="", entry_price=1.1)

    def test_negative_confidence_raises(self):
        with pytest.raises(ValueError, match="confidence must be between"):
            HumanSignal(
                signal_type=SignalType.BUY,
                pair="EUR/USD",
                entry_price=1.1,
                confidence=-0.1,
            )

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValueError, match="confidence must be between"):
            HumanSignal(
                signal_type=SignalType.BUY,
                pair="EUR/USD",
                entry_price=1.1,
                confidence=1.5,
            )

    def test_zero_entry_price_raises_for_buy(self):
        with pytest.raises(ValueError, match="entry_price must be positive"):
            HumanSignal(
                signal_type=SignalType.BUY,
                pair="EUR/USD",
                entry_price=0.0,
            )

    def test_negative_entry_price_raises(self):
        with pytest.raises(ValueError, match="entry_price must be positive"):
            HumanSignal(
                signal_type=SignalType.SELL,
                pair="EUR/USD",
                entry_price=-1.0,
            )

    def test_negative_stop_loss_raises(self):
        with pytest.raises(ValueError, match="stop_loss must be positive"):
            HumanSignal(
                signal_type=SignalType.BUY,
                pair="EUR/USD",
                entry_price=1.1,
                stop_loss=-0.5,
            )

    def test_negative_take_profit_raises(self):
        with pytest.raises(ValueError, match="take_profit must be positive"):
            HumanSignal(
                signal_type=SignalType.BUY,
                pair="EUR/USD",
                entry_price=1.1,
                take_profit=-0.5,
            )

    def test_close_signal_allows_zero_entry(self):
        signal = HumanSignal(signal_type=SignalType.CLOSE, pair="EUR/USD")
        assert signal.entry_price == 0.0


class TestHumanSignalProperties:
    def test_has_stop_loss_true(self):
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1,
            stop_loss=1.09,
        )
        assert signal.has_stop_loss is True

    def test_has_stop_loss_false(self):
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1,
        )
        assert signal.has_stop_loss is False

    def test_has_take_profit_true(self):
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1,
            take_profit=1.12,
        )
        assert signal.has_take_profit is True

    def test_has_take_profit_false(self):
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1,
        )
        assert signal.has_take_profit is False

    def test_to_direction_str_buy(self):
        signal = HumanSignal(
            signal_type=SignalType.BUY, pair="EUR/USD", entry_price=1.1
        )
        assert signal.to_direction_str() == "long"

    def test_to_direction_str_sell(self):
        signal = HumanSignal(
            signal_type=SignalType.SELL, pair="EUR/USD", entry_price=1.1
        )
        assert signal.to_direction_str() == "short"

    def test_to_direction_str_close(self):
        signal = HumanSignal(signal_type=SignalType.CLOSE, pair="EUR/USD")
        assert signal.to_direction_str() == "neutral"
