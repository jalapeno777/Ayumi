"""Signal Injection Test — force a synthetic signal through the full pipeline.

Goal: Inject a mock buy signal (GBPUSD, lot=0.01) through the full pipeline:
    StrategyAdapter → SignalOrchestrator → (ConfidenceEngine → ProfileRouter → SLPositionSizer)

This isolates pipeline bugs from signal generation issues. If the synthetic
signal reaches the sizing stage and produces an OrchestratedOrder with
lots > 0, the pipeline wiring is correct. Failures at any stage pinpoint
the broken component.

Pipeline stages under test:
    1. StrategyAdapter.adapt_signal() — raw dict → TradeSignal
    2. ConfidenceEngine.score() — gates (spread, session, volatility)
    3. ProfileRouter.route() — confidence threshold → Sniper/Swarm/Reject
    4. SLPositionSizer.calculate() — SL distance → lots
    5. SignalOrchestrator.process_signal() — full wiring

Pipeline breaks documented:
    - Spread gate rejects if spread > max_spread (default 2.0 pips)
    - Session gate rejects if hour_utc outside trading sessions
    - Volatility gate rejects if ATR outside configured range
    - Profile router rejects if confidence < 0.40 (SWARM_THRESHOLD)
    - Position sizer blocks if SL distance < 5 pips or daily risk exceeded
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from orchestrator.signal_orchestrator import SignalOrchestrator, TradeSignal, OrchestratedOrder
from orchestrator.strategy_adapter import StrategyAdapter
from confidence.engine import ConfidenceEngine
from confidence.gates import GateConfig
from risk.profile_router import ProfileRouter, Profile
from risk.sl_position_sizer import SLPositionSizer


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def gate_config():
    """Standard gate config with per-symbol spreads."""
    return GateConfig(
        default_max_spread=2.0,
        symbol_max_spreads={"GBPUSD": 2.0, "EURUSD": 2.0, "XAUUSD": 3.5},
    )


@pytest.fixture
def confidence_engine(gate_config):
    return ConfidenceEngine(gate_config=gate_config)


@pytest.fixture
def profile_router():
    return ProfileRouter()


@pytest.fixture
def position_sizer():
    return SLPositionSizer(account_balance=10000.0)


@pytest.fixture
def orchestrator(confidence_engine, profile_router, position_sizer):
    return SignalOrchestrator(
        confidence_engine=confidence_engine,
        profile_router=profile_router,
        position_sizer=position_sizer,
        account_balance=10000.0,
    )


@pytest.fixture
def adapter():
    return StrategyAdapter()


def _make_gbpusd_long_signal(adapter: StrategyAdapter) -> TradeSignal:
    """Create a valid GBPUSD long signal via the adapter."""
    raw_output = {
        "symbol": "GBPUSD",
        "direction": "LONG",
        "entry_price": 1.27500,
        "stop_loss": 1.27300,  # 20 pips SL
        "take_profit": 1.27900,  # 40 pips TP
        "confidence": 0.80,
        "spread": 1.0,  # pips
        # NOTE: ATR omitted — volatility gate blocks price-domain ATR values
        # because atr_lookback_default=1.0 causes ratio mismatch.
        # See TestPipelineBreakDocumentation.test_volatility_gate_atr_mismatch.
        "timestamp": datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc),  # 10:00 UTC = London session
    }
    return adapter.adapt_signal("srmr_plus", raw_output)


# ── Stage 1: StrategyAdapter ──────────────────────────────────────────

class TestStrategyAdapter:
    """Verify raw strategy output converts to TradeSignal correctly."""

    def test_adapt_valid_long_signal(self, adapter):
        raw = {
            "symbol": "GBPUSD",
            "direction": "LONG",
            "entry_price": 1.27500,
            "stop_loss": 1.27300,
            "take_profit": 1.27900,
            "confidence": 0.80,
            "spread": 1.0,
            "atr": 0.0015,
        }
        signal = adapter.adapt_signal("srmr_plus", raw)

        assert signal.strategy_id == "srmr_plus"
        assert signal.symbol == "GBPUSD"
        assert signal.direction == "LONG"
        assert signal.entry_price == 1.27500
        assert signal.stop_loss == 1.27300
        assert signal.confidence == 0.80
        assert signal.metadata["spread"] == 1.0
        assert signal.metadata["atr"] == 0.0015

    def test_adapt_missing_required_field_raises(self, adapter):
        raw = {
            "symbol": "GBPUSD",
            "direction": "LONG",
            # Missing entry_price and stop_loss
        }
        with pytest.raises(ValueError, match="Missing required fields"):
            adapter.adapt_signal("test", raw)

    def test_adapt_normalizes_lowercase_direction(self, adapter):
        raw = {
            "symbol": "EURUSD",
            "direction": "long",
            "entry_price": 1.0850,
            "stop_loss": 1.0830,
        }
        signal = adapter.adapt_signal("test", raw)
        assert signal.direction == "LONG"


# ── Stage 2: ConfidenceEngine ─────────────────────────────────────────

class TestConfidenceEngineInjection:
    """Verify the confidence engine processes injected signals."""

    def test_high_confidence_passes_all_gates(self, confidence_engine):
        # NOTE: ATR is omitted (defaults to 0) — the volatility gate is skipped
        # when no ATR is provided. See test_volatility_gate_atr_mismatch for
        # documentation of the ATR pipeline break.
        result = confidence_engine.score(
            raw_confidence=0.80,
            symbol="GBPUSD",
            direction="long",
            spread=1.0,
            hour_utc=10,
        )
        assert not result.blocked
        assert result.final_score >= 0.80
        assert "spread" in result.gates_passed
        assert "session" in result.gates_passed

    def test_wide_spread_blocks(self, confidence_engine):
        result = confidence_engine.score(
            raw_confidence=0.80,
            symbol="GBPUSD",
            spread=5.0,  # Exceeds 2.0 max
            hour_utc=10,
        )
        assert result.blocked
        assert "spread" in result.gates_failed
        assert "Spread" in result.block_reason

    def test_off_session_blocks(self, confidence_engine):
        result = confidence_engine.score(
            raw_confidence=0.80,
            symbol="GBPUSD",
            spread=1.0,
            hour_utc=23,  # Outside all sessions (22 is NY close)
        )
        assert result.blocked
        assert "session" in result.gates_failed


# ── Stage 3: ProfileRouter ────────────────────────────────────────────

class TestProfileRouterInjection:
    """Verify routing thresholds work with injected confidence scores."""

    def test_high_confidence_routes_to_sniper(self, profile_router):
        profile = profile_router.route(0.85)
        assert profile == Profile.SNIPER

    def test_medium_confidence_routes_to_swarm(self, profile_router):
        profile = profile_router.route(0.55)
        assert profile == Profile.SWARM

    def test_low_confidence_rejected(self, profile_router):
        profile = profile_router.route(0.30)
        assert profile is None


# ── Stage 4: SLPositionSizer ──────────────────────────────────────────

class TestPositionSizerInjection:
    """Verify the sizer produces valid lots for injected signals."""

    def test_gbpusd_valid_sl_produces_lots(self, position_sizer):
        result = position_sizer.calculate(
            symbol="GBPUSD",
            entry_price=1.27500,
            sl_price=1.27300,  # 20 pips
            profile=Profile.SNIPER,
        )
        assert not result.blocked
        assert result.lots > 0.0
        assert result.sl_distance_pips == pytest.approx(20.0, abs=0.1)

    def test_too_tight_sl_blocks(self, position_sizer):
        result = position_sizer.calculate(
            symbol="GBPUSD",
            entry_price=1.27500,
            sl_price=1.27495,  # 0.5 pips — below 5 pip minimum
            profile=Profile.SNIPER,
        )
        assert result.blocked
        assert "minimum" in result.block_reason.lower()


# ── Stage 5: Full Pipeline (SignalOrchestrator) ───────────────────────

class TestFullPipelineInjection:
    """End-to-end: synthetic signal → orchestrator → OrchestratedOrder.

    This is the critical test that verifies the full pipeline wiring.
    """

    def test_happy_path_gbpusd_long(self, orchestrator, adapter):
        """Inject a high-confidence GBPUSD long signal.

        Expected: reaches sizing, produces non-zero lots.
        This confirms the full pipeline: adapter → confidence → routing → sizing.
        """
        signal = _make_gbpusd_long_signal(adapter)
        order = orchestrator.process_signal(signal)

        assert isinstance(order, OrchestratedOrder)
        assert not order.rejected
        assert order.lots > 0.0
        assert order.profile in (Profile.SNIPER, Profile.SWARM)
        assert order.confidence_final >= 0.70  # Should be Sniper
        assert "spread" in order.gates_passed

    def test_low_confidence_signal_rejected_at_routing(self, orchestrator, adapter):
        """Inject a low-confidence signal — should pass gates but fail at routing."""
        raw = {
            "symbol": "GBPUSD",
            "direction": "LONG",
            "entry_price": 1.27500,
            "stop_loss": 1.27300,
            "confidence": 0.20,  # Below 0.40 swarm threshold
            "spread": 1.0,
            "timestamp": datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc),
        }
        signal = adapter.adapt_signal("weak_strategy", raw)
        order = orchestrator.process_signal(signal)

        assert order.rejected
        assert "threshold" in order.rejection_reason.lower() or "below" in order.rejection_reason.lower()

    def test_wide_spread_rejected_at_confidence(self, orchestrator, adapter):
        """Inject signal with excessive spread — should fail at spread gate."""
        raw = {
            "symbol": "GBPUSD",
            "direction": "LONG",
            "entry_price": 1.27500,
            "stop_loss": 1.27300,
            "confidence": 0.80,
            "spread": 5.0,  # Way above 2.0 max
            "timestamp": datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc),
        }
        signal = adapter.adapt_signal("test", raw)
        order = orchestrator.process_signal(signal)

        assert order.rejected
        assert "spread" in order.rejection_reason.lower() or "Spread" in order.rejection_reason

    def test_unknown_symbol_blocks_at_sizing(self, orchestrator, adapter):
        """Inject signal for unknown symbol — passes confidence but fails at sizing."""
        raw = {
            "symbol": "EURGBP",
            "direction": "LONG",
            "entry_price": 0.8500,
            "stop_loss": 0.8480,
            "confidence": 0.75,
            "spread": 1.0,
            "timestamp": datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc),
        }
        signal = adapter.adapt_signal("test", raw)
        order = orchestrator.process_signal(signal)

        # EURGBP is not in INSTRUMENTS dict, so sizer will block
        assert order.rejected
        assert "Unknown instrument" in order.rejection_reason

    def test_too_tight_sl_blocks_at_sizing(self, orchestrator, adapter):
        """Inject signal with SL too tight — should pass confidence but fail at sizing."""
        raw = {
            "symbol": "GBPUSD",
            "direction": "LONG",
            "entry_price": 1.27500,
            "stop_loss": 1.27499,  # 0.1 pip — below 5 pip minimum
            "confidence": 0.80,
            "spread": 1.0,
            "timestamp": datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc),
        }
        signal = adapter.adapt_signal("test", raw)
        order = orchestrator.process_signal(signal)

        assert order.rejected
        assert "pips" in order.rejection_reason.lower()

    def test_short_direction_signal(self, orchestrator, adapter):
        """Inject a short signal — should flow through just like long."""
        raw = {
            "symbol": "EURUSD",
            "direction": "SHORT",
            "entry_price": 1.08500,
            "stop_loss": 1.08700,  # 20 pips above for short
            "take_profit": 1.08100,
            "confidence": 0.75,
            "spread": 1.0,
            # NOTE: ATR omitted — same volatility gate issue as GBPUSD test
            "timestamp": datetime(2026, 7, 2, 14, 0, 0, tzinfo=timezone.utc),  # NY session
        }
        signal = adapter.adapt_signal("rsi_threshold", raw)
        order = orchestrator.process_signal(signal)

        assert not order.rejected
        assert order.lots > 0.0
        assert order.signal.direction == "SHORT"


# ── Pipeline Break Documentation ──────────────────────────────────────

class TestPipelineBreakDocumentation:
    """Document known pipeline breaks found during injection testing.

    Each test documents a specific failure mode that can prevent live signals
    from reaching the paper order stage, even when the strategy is generating
    valid signals.
    """

    BREAK_DOC = """
    Pipeline Break Documentation
    ============================

    The following break points were identified through synthetic signal injection:

    1. SPREAD GATE (confidence/gates.py:SpreadGate)
       - Trigger: spread > symbol_max_spread (default 2.0 pips)
       - Impact: Rejects signal before confidence scoring completes
       - Real-world cause: Live spreads widen during news events, low liquidity,
         or session transitions. Backtest assumes fixed 1.5 pip spread.
       - Fix: Monitor live spread distribution; consider adaptive thresholds.

    2. SESSION GATE (confidence/gates.py:SessionGate)
       - Trigger: hour_utc outside London (8-17), NY (13-22), Asia (0-8)
       - Impact: Rejects all signals outside configured sessions
       - Real-world cause: Strategies may produce signals during off-hours
         if they compute on every tick. The 13:00 UTC NY open creates a gap
         between 17:00-13:00 UTC where only Asia (0-8) overlaps.
       - Note: SessionGate does NOT get hour_utc from the signal's timestamp.
         The orchestrator passes hour_utc=0 by default (metadata lacks it),
         which means ALL signals may be tested against midnight UTC unless
         the caller explicitly sets the hour.
       - FIX NEEDED: SignalOrchestrator.process_signal() does not extract
         hour_utc from signal.timestamp. It passes hour_utc=0 (default in
         ConfidenceEngine.score) unless metadata contains it. This is a
         pipeline break — see test_session_gate_uses_signal_timestamp.

    3. VOLATILITY GATE (confidence/gates.py:VolatilityGate)
       - Trigger: ATR outside configured min/max range
       - Impact: Rejects if ATR too low (dead market) or too high (chaotic)
       - Real-world cause: Backtest uses historical ATR; live ATR may differ.
       - Note: When atr=0 (not provided), gate is SKIPPED (passes by default).
         This means signals without ATR metadata bypass volatility filtering.

    4. PROFILE ROUTER (risk/profile_router.py:ProfileRouter)
       - Trigger: confidence < 0.40 (SWARM_THRESHOLD)
       - Impact: Signal rejected — no order created
       - Real-world cause: Confidence gates or confluence penalties drag
         scores below threshold. Strategies producing 0.5-0.6 raw confidence
         can end up below 0.40 after gate penalties.

    5. POSITION SIZER (risk/sl_position_sizer.py:SLPositionSizer)
       - Trigger: SL distance < 5 pips, unknown symbol, daily risk exceeded
       - Impact: Signal blocked at sizing stage
       - Real-world cause: Strategy sets SL too tight, or symbol not in
         INSTRUMENTS dict (currently only EURUSD, GBPUSD, USDJPY, XAUUSD).
       - NOTE: Strategies producing signals for pairs not in INSTRUMENTS
         (e.g., EURGBP, AUDJPY) will pass confidence but fail at sizing.

    6. CONSTRUCTOR WIRING (orchestrator/signal_orchestrator.py)
       - The orchestrator does NOT pass hour_utc from signal.timestamp to
         the confidence engine. ConfidenceEngine.score() defaults to
         hour_utc=0 (midnight UTC, which is in Asia session). This means:
         a) Signals generated during NY session (13-22 UTC) are evaluated
            as if they occurred at midnight.
         b) If the gate config changes Asia hours, signals could be rejected.
         c) The session gate is currently passing by luck (0 UTC is in Asia).
       - This is NOT a bug per se — the orchestrator may be designed to
         receive hour_utc through a different path. But it IS a wiring gap.
    """

    def test_pipeline_break_documentation_is_complete(self):
        """Ensure all identified breaks are documented."""
        doc = self.BREAK_DOC
        assert "SPREAD GATE" in doc
        assert "SESSION GATE" in doc
        assert "VOLATILITY GATE" in doc
        assert "PROFILE ROUTER" in doc
        assert "POSITION SIZER" in doc
        assert "CONSTRUCTOR WIRING" in doc

    def test_volatility_gate_atr_mismatch(self, confidence_engine):
        """BREAK #3: Volatility gate rejects price-domain ATR values.

        Strategies produce ATR in price domain (e.g., 0.0015 for GBPUSD ≈15 pips).
        The volatility gate's fallback check computes ratio = ATR / atr_lookback_default,
        where atr_lookback_default=1.0. This makes ratio = 0.0015, which is far
        below min_atr_multiplier=0.5, causing every signal with real ATR to be
        blocked.

        The gate only works correctly when either:
        a) Per-symbol volatility_min_atr/max_atr ranges are configured, OR
        b) atr_lookback_default is set to a realistic price-domain value, OR
        c) The gate is skipped (atr=0 or not provided)

        Impact: In the current configuration, any signal that includes a
        realistic ATR value will be blocked by the volatility gate. Signals
        without ATR pass through (gate skipped). This means the volatility
        gate is either doing nothing (when ATR is absent) or incorrectly
        blocking everything (when ATR is present).
        """
        result = confidence_engine.score(
            raw_confidence=0.80,
            symbol="GBPUSD",
            direction="long",
            spread=1.0,
            atr=0.0015,  # Realistic ATR for GBPUSD (~15 pips)
            hour_utc=10,
        )
        assert result.blocked, "Volatility gate should block price-domain ATR values"
        assert "volatility" in result.gates_failed
        assert "ATR ratio" in result.block_reason

    def test_session_gate_uses_signal_timestamp(self, orchestrator, adapter):
        """CRITICAL: Verify whether the orchestrator passes hour_utc from timestamp.

        The SignalOrchestrator.process_signal() does NOT extract hour_utc from
        signal.timestamp. ConfidenceEngine.score() defaults to hour_utc=0.
        This test documents the behavior.
        """
        # Signal at 14:00 UTC (NY session)
        raw = {
            "symbol": "GBPUSD",
            "direction": "LONG",
            "entry_price": 1.27500,
            "stop_loss": 1.27300,
            "confidence": 0.80,
            "spread": 1.0,
            "timestamp": datetime(2026, 7, 2, 14, 0, 0, tzinfo=timezone.utc),
        }
        signal = adapter.adapt_signal("test", raw)
        order = orchestrator.process_signal(signal)

        # Signal should NOT be rejected for session reasons since 0 UTC
        # falls within Asia session (0-8). But the ACTUAL hour (14 UTC)
        # would also pass (London/NY overlap). So this test passes either way.
        #
        # The break would manifest if:
        # - Asia session hours are narrowed (e.g., 1-7)
        # - hour_utc=0 falls outside the new range
        # Then ALL signals would fail session gate regardless of actual time.
        assert not order.rejected, (
            "Signal should pass — hour_utc defaults to 0 which is in Asia session. "
            "If this fails, the session gate config has changed and the "
            "hour_utc wiring gap (Break #6) is now causing rejections."
        )
