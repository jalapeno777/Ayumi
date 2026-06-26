"""Tests for strategy return-None logging (T3)."""
import sys
import logging
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, "src/forex-bot")


class TestSRMRPlusLogging:
    """Verify SRMR+ strategy logs on return None paths."""

    def test_evaluate_with_insufficient_bars_logs(self, caplog):
        """Calling evaluate with too few bars should emit a debug log."""
        from strategies.srmr_plus import SRMRPlusStrategy

        strategy = SRMRPlusStrategy()
        state = MagicMock()
        state.bars = []  # insufficient bars
        state.latest_bar = None

        with caplog.at_level(logging.DEBUG, logger="strategies.srmr_plus"):
            result = strategy.evaluate(state)

        assert result is None
        # Should have logged something about insufficient bars or no bars
        assert len(caplog.records) > 0, "Expected at least one debug log on return None"

    def test_build_signal_zero_atr_logs(self, caplog):
        """_build_signal with zero ATR should log."""
        from strategies.srmr_plus import _build_signal, SRMRPlusConfig

        with caplog.at_level(logging.DEBUG, logger="strategies.srmr_plus"):
            result = _build_signal(
                direction="BUY",
                entry=1.1000,
                atr=0.0,  # zero ATR
                config=SRMRPlusConfig(),
                session_range_price=1.0990,
                adx=25.0,
                rsi=50.0,
                rationale="test",
                pip=0.0001,
            )

        assert result is None
        assert any("ATR" in r.message for r in caplog.records), \
            "Expected ATR-related log message"


class TestTTCXAUUSDLogging:
    """Verify TTC XAUUSD strategy logs on return None."""

    def test_evaluate_returns_none_with_logging(self, caplog):
        """When TTC returns None, it should log a debug message."""
        from strategies.ttc_xauusd import TTCXAUUSDStrategy

        strategy = TTCXAUUSDStrategy()
        state = MagicMock()
        state.bars = []
        state.latest_bar = None

        with caplog.at_level(logging.DEBUG, logger="strategies.ttc_xauusd"):
            result = strategy.evaluate(state)

        assert result is None
        assert len(caplog.records) > 0, "Expected at least one debug log on return None"

    def test_logger_exists(self):
        """Both strategy modules should have a logger configured."""
        import strategies.srmr_plus as srmr_mod
        import strategies.ttc_xauusd as ttc_mod

        assert hasattr(srmr_mod, 'logger'), "srmr_plus missing logger"
        assert hasattr(ttc_mod, 'logger'), "ttc_xauusd missing logger"
        assert isinstance(srmr_mod.logger, logging.Logger)
        assert isinstance(ttc_mod.logger, logging.Logger)
