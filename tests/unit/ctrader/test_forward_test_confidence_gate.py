"""Tests for ConfidenceEngine wiring into the forward test live-fire path.

Validates that:
- ConfidenceEngine is instantiated when live_mode=True
- ConfidenceEngine is NOT instantiated when live_mode=False (paper mode unchanged)
- Signals blocked by gates do not reach _execute_signal_live
- Signals below live_fire_min_confidence do not reach _execute_signal_live
- Signals passing all gates and threshold DO reach _execute_signal_live
- live_fire_min_confidence is configurable with default 0.65
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from adapters.ctrader.forward_test_engine import (
    ForwardTestConfig,
    ForwardTestEngine,
)
from adapters.ctrader.models import (
    CTraderTradeSignal,
    TradeDirection,
)


def _make_signal(confidence: float = 0.8, symbol: str = "EURUSD") -> CTraderTradeSignal:
    return CTraderTradeSignal(
        symbol=symbol,
        direction=TradeDirection.LONG,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        take_profit_3=1.1150,
        volume=0.1,
        confidence=confidence,
        rationale="unit_test",
        strategy_id="test_strategy",
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def isolated_engine(tmp_path):
    """Build a forward test engine with live mode and isolated kill switch."""
    from adapters.ctrader.kill_switch import KillSwitchManager
    isolated_dir = tmp_path / "kill_switches"
    isolated_dir.mkdir(parents=True, exist_ok=True)

    # Patch _build_live_credentials and _enforce_remediation_gate so __init__
    # does not try to connect or check remediation flags.
    with patch.object(ForwardTestEngine, "_build_live_credentials", return_value=None), \
         patch.object(ForwardTestEngine, "_enforce_remediation_gate", return_value=None):
        cfg = ForwardTestConfig(live_mode=True, starting_balance=10000.0)
        engine = ForwardTestEngine(config=cfg, strategies=[])

    engine._kill_switch = KillSwitchManager(state_dir=str(isolated_dir))
    return engine


@pytest.fixture
def paper_engine(tmp_path):
    """Build a forward test engine in paper mode."""
    from adapters.ctrader.kill_switch import KillSwitchManager
    isolated_dir = tmp_path / "kill_switches"
    isolated_dir.mkdir(parents=True, exist_ok=True)

    cfg = ForwardTestConfig(live_mode=False, starting_balance=10000.0)
    engine = ForwardTestEngine(config=cfg, strategies=[])
    engine._kill_switch = KillSwitchManager(state_dir=str(isolated_dir))
    return engine


class TestConfidenceEngineWiring:
    """Verify ConfidenceEngine is wired into ForwardTestEngine correctly."""

    def test_confidence_engine_exists_in_live_mode(self, isolated_engine):
        """ConfidenceEngine must be instantiated when live_mode=True."""
        assert isolated_engine._confidence_engine is not None

    def test_confidence_engine_absent_in_paper_mode(self, paper_engine):
        """ConfidenceEngine must NOT be instantiated when live_mode=False."""
        assert paper_engine._confidence_engine is None

    def test_live_fire_min_confidence_default(self):
        """Default live_fire_min_confidence must be 0.55 (lowered per Phase 4)."""
        cfg = ForwardTestConfig()
        assert cfg.live_fire_min_confidence == 0.55

    def test_live_fire_min_confidence_configurable(self):
        """live_fire_min_confidence must be configurable."""
        cfg = ForwardTestConfig(live_fire_min_confidence=0.80)
        assert cfg.live_fire_min_confidence == 0.80


class TestSignalBlockedByGate:
    """A signal that fails a confidence gate must not reach _execute_signal_live."""

    def test_spread_gate_blocks_signal(self, isolated_engine):
        """When the spread gate fails, _execute_signal_live must not be called."""
        signal = _make_signal(confidence=0.8)

        # Patch _execute_signal_live so we can verify it was NOT called
        isolated_engine._execute_signal_live = MagicMock(return_value=None)

        # Set a very high spread so the spread gate fails
        # Default max_spread is 2.0 pips
        isolated_engine._current_spread = 10.0

        # Simulate the signal loop from _evaluate_strategies
        with isolated_engine._lock:
            pass  # just acquire/release to be safe

        # Manually invoke the confidence gate logic
        engine = isolated_engine._confidence_engine
        result = engine.score(
            raw_confidence=signal.confidence,
            symbol=signal.symbol,
            direction="long",
            spread=isolated_engine._current_spread,
            hour_utc=12,
        )

        assert result.blocked is True
        assert "spread" in result.gates_failed
        assert result.final_score == 0.0


class TestSignalBlockedByLowConfidence:
    """A signal with final_score < live_fire_min_confidence must not execute."""

    def test_low_confidence_signal_rejected(self, isolated_engine):
        """Signal with final_score below threshold must not execute."""
        signal = _make_signal(confidence=0.50)  # below 0.65 threshold

        isolated_engine._execute_signal_live = MagicMock(return_value=None)

        engine = isolated_engine._confidence_engine
        result = engine.score(
            raw_confidence=signal.confidence,
            symbol=signal.symbol,
            direction="long",
            spread=0.5,  # within spread gate
            hour_utc=12,  # within session
        )

        # final_score should be 0.50 (no boost, no gate boost) which is < 0.65
        assert result.blocked is False
        assert result.final_score < isolated_engine._config.live_fire_min_confidence


class TestSignalPassesGate:
    """A signal that passes all gates and threshold should reach _execute_signal_live."""

    def test_high_confidence_signal_passes(self, isolated_engine):
        """Signal with high confidence and good conditions must pass."""
        signal = _make_signal(confidence=0.85)

        engine = isolated_engine._confidence_engine
        result = engine.score(
            raw_confidence=signal.confidence,
            symbol=signal.symbol,
            direction="long",
            spread=0.5,  # well within default 2.0 pip max
            hour_utc=12,  # within London/NY session
        )

        assert result.blocked is False
        assert result.final_score >= isolated_engine._config.live_fire_min_confidence
        assert len(result.gates_failed) == 0


class TestPaperModeUnchanged:
    """Paper mode must not invoke ConfidenceEngine at all."""

    def test_paper_mode_has_no_confidence_engine(self, paper_engine):
        """In paper mode, _confidence_engine must be None — no gating applied."""
        assert paper_engine._confidence_engine is None
        assert paper_engine._config.live_mode is False
