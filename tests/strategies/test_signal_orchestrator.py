"""Tests for Signal Orchestrator + P1 gate fixes."""

from datetime import datetime, timezone

from confidence.engine import ConfidenceEngine
from confidence.gates import (
    GateConfig,
    NewsBlackoutGate,
    VolatilityGate,
)
from orchestrator.signal_orchestrator import (
    OrchestratorTradeSignal,
    SignalOrchestrator,
)
from risk.profile_router import Profile, ProfileRouter
from risk.sl_position_sizer import SLPositionSizer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    confidence: float = 0.8,
    symbol: str = "EURUSD",
    direction: str = "long",
    entry: float = 1.0800,
    sl: float = 1.0780,
    tp: float = 1.0860,
    spread: float = 1.0,
    atr: float = 0.0008,
    confluences=None,
    **meta_kwargs,
) -> OrchestratorTradeSignal:
    metadata = {"spread": spread, "atr": atr}
    if confluences:
        metadata["confluences"] = confluences
    metadata.update(meta_kwargs)
    return OrchestratorTradeSignal(
        strategy_id="test_strat",
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        metadata=metadata,
    )


def _make_orchestrator(
    balance: float = 10000.0,
    sniper_threshold: float = 0.70,
    swarm_threshold: float = 0.40,
    max_daily_risk_pct: float = 0.03,
) -> SignalOrchestrator:
    gate_config = GateConfig(
        default_max_spread=5.0,
        atr_lookback_default=0.0008,
        min_atr_multiplier=0.1,
        max_atr_multiplier=10.0,
    )
    engine = ConfidenceEngine(gate_config=gate_config)
    router = ProfileRouter(
        sniper_threshold=sniper_threshold,
        swarm_threshold=swarm_threshold,
        max_sniper=10,
        max_swarm=10,
    )
    sizer = SLPositionSizer(
        account_balance=balance,
        daily_risk_cap_pct=max_daily_risk_pct,
    )
    return SignalOrchestrator(engine, router, sizer, balance)


# ===================================================================
# Task 1 — P1 Gate Fixes
# ===================================================================


class TestDynamicATRVolatilityGate:
    """P1 Fix 1: Dynamic ATR for volatility gate."""

    def test_per_symbol_min_atr_rejects(self):
        cfg = GateConfig(
            volatility_min_atr={"EURUSD": 0.0010},
        )
        gate = VolatilityGate(cfg)
        result = gate.check({"symbol": "EURUSD", "atr": 0.0005})
        assert not result.passed
        assert "below minimum" in result.reason

    def test_per_symbol_max_atr_rejects(self):
        cfg = GateConfig(
            volatility_max_atr={"EURUSD": 0.0010},
        )
        gate = VolatilityGate(cfg)
        result = gate.check({"symbol": "EURUSD", "atr": 0.0020})
        assert not result.passed
        assert "above maximum" in result.reason

    def test_per_symbol_atr_passes(self):
        cfg = GateConfig(
            volatility_min_atr={"EURUSD": 0.0005},
            volatility_max_atr={"EURUSD": 0.0015},
        )
        gate = VolatilityGate(cfg)
        result = gate.check({"symbol": "EURUSD", "atr": 0.0010})
        assert result.passed

    def test_atr_provider_used_when_no_atr_in_ctx(self):
        cfg = GateConfig(
            volatility_min_atr={"GBPUSD": 0.0010},
        )
        gate = VolatilityGate(cfg, atr_provider=lambda sym: 0.0020)
        result = gate.check({"symbol": "GBPUSD"})
        assert result.passed

    def test_no_atr_skips_gate(self):
        cfg = GateConfig()
        gate = VolatilityGate(cfg)
        result = gate.check({"symbol": "EURUSD"})
        assert result.passed
        assert "skipped" in result.reason

    def test_fallback_multiplier_still_works(self):
        """When no per-symbol ATR configured, falls back to multiplier logic."""
        cfg = GateConfig(
            atr_lookback_default=1.0,
            min_atr_multiplier=0.5,
            max_atr_multiplier=2.0,
        )
        gate = VolatilityGate(cfg)
        # ATR ratio 3.0 > max 2.0 → rejected
        result = gate.check({"symbol": "EURUSD", "atr": 3.0})
        assert not result.passed


class TestNewsBlackoutGateStub:
    """P1 Fix 2: News blackout gate stub."""

    def test_always_passes(self):
        gate = NewsBlackoutGate(blackout_minutes=30)
        result = gate.check({"symbol": "EURUSD"})
        assert result.passed

    def test_gate_name(self):
        gate = NewsBlackoutGate()
        result = gate.check({})
        assert result.gate_name == "news_blackout"


# ===================================================================
# Task 2 & 3 — Signal Orchestrator Tests
# ===================================================================


class TestSignalOrchestrator:
    """10+ tests for the full orchestrator pipeline."""

    def test_happy_path_sniper(self):
        """High confidence → sniper profile → sized correctly."""
        orch = _make_orchestrator()
        sig = _make_signal(confidence=0.80, entry=1.0800, sl=1.0780)
        order = orch.process_signal(sig)
        assert not order.rejected
        assert order.profile == Profile.SNIPER
        assert order.lots > 0
        assert order.confidence_final >= 0.70

    def test_happy_path_swarm(self):
        """Medium confidence → swarm → half risk."""
        orch = _make_orchestrator()
        sig = _make_signal(confidence=0.50, entry=1.0800, sl=1.0780)
        order = orch.process_signal(sig)
        assert not order.rejected
        assert order.profile == Profile.SWARM
        assert order.lots > 0
        assert order.risk_amount > 0

    def test_confidence_gate_rejection(self):
        """Low confidence → rejected by router."""
        orch = _make_orchestrator()
        sig = _make_signal(confidence=0.20, entry=1.0800, sl=1.0780)
        order = orch.process_signal(sig)
        assert order.rejected
        assert "Below minimum confidence" in order.rejection_reason

    def test_profile_router_rejection_below_040(self):
        """Confidence 0.39 → rejected."""
        orch = _make_orchestrator(swarm_threshold=0.40)
        sig = _make_signal(confidence=0.39, entry=1.0800, sl=1.0780)
        order = orch.process_signal(sig)
        assert order.rejected

    def test_sizer_rejection_sl_too_close(self):
        """Valid confidence but SL too close → rejected by sizer."""
        orch = _make_orchestrator()
        sig = _make_signal(confidence=0.80, entry=1.0800, sl=1.0799)  # 1 pip
        order = orch.process_signal(sig)
        assert order.rejected
        assert "minimum" in order.rejection_reason.lower() or "below minimum" in order.rejection_reason.lower()

    def test_daily_cap_reached(self):
        """Multiple signals exhausting daily cap → final one rejected."""
        orch = _make_orchestrator(max_daily_risk_pct=0.03)
        # Each sniper trade risks $50 (0.5% of 10k). Daily cap = $300 = 6 trades.
        # Register 6 open positions at $50 risk each
        for _ in range(6):
            sig = _make_signal(confidence=0.80, entry=1.0800, sl=1.0780)
            order = orch.process_signal(sig)
            if not order.rejected:
                orch._sizer.register_open_position(order.risk_amount)

        # 7th should be blocked
        sig = _make_signal(confidence=0.80, entry=1.0800, sl=1.0780)
        order = orch.process_signal(sig)
        assert order.rejected
        assert "daily" in order.rejection_reason.lower() or "exceeds" in order.rejection_reason.lower()

    def test_circuit_breaker_active(self):
        """Breaker triggered → all signals rejected."""
        orch = _make_orchestrator()
        # Trigger circuit breaker via drawdown
        orch._sizer.breaker.halt("test breaker")
        sig = _make_signal(confidence=0.80, entry=1.0800, sl=1.0780)
        order = orch.process_signal(sig)
        assert order.rejected
        assert "halted" in order.rejection_reason.lower()

    def test_profile_enum_passthrough(self):
        """Profile enum flows cleanly through full chain."""
        orch = _make_orchestrator()
        sig = _make_signal(confidence=0.75, entry=1.0800, sl=1.0780)
        order = orch.process_signal(sig)
        assert isinstance(order.profile, Profile)
        assert order.profile.value in ("sniper", "swarm")

    def test_balance_update_propagates(self):
        """update_balance propagates to sizer."""
        orch = _make_orchestrator(balance=10000.0)
        orch.update_balance(20000.0)
        assert orch._sizer.account_balance == 20000.0
        # Higher balance should produce larger lots for same signal
        sig = _make_signal(confidence=0.80, entry=1.0800, sl=1.0780)
        order = orch.process_signal(sig)
        assert not order.rejected
        assert order.lots > 0

    def test_confluence_boost_integration(self):
        """Multiple strategies agreeing → higher confidence → sniper instead of swarm."""
        orch = _make_orchestrator()
        # Base confidence 0.55 → would normally be swarm
        # Add confluences to push it above 0.70
        confluences = [
            {"strategy": "ema_cross", "direction": "long", "timeframe": "H1"},
            {"strategy": "rsi_div", "direction": "long", "timeframe": "H4"},
            {"strategy": "support_bounce", "direction": "long", "timeframe": "D1"},
        ]
        sig = _make_signal(confidence=0.55, confluences=confluences)
        order = orch.process_signal(sig)
        # With 3 confluences (0.05 * 3 strategies + 0.025 * 3 TFs = 0.225 boost),
        # final = 0.55 + 0.15 (capped) = 0.70 → sniper
        assert not order.rejected
        assert order.confidence_final >= 0.70
        assert order.profile == Profile.SNIPER

    def test_gates_passed_populated(self):
        """gates_passed list is populated on successful order."""
        orch = _make_orchestrator()
        sig = _make_signal(confidence=0.80, entry=1.0800, sl=1.0780)
        order = orch.process_signal(sig)
        assert len(order.gates_passed) > 0
        assert "spread" in order.gates_passed

    def test_unknown_symbol_rejected(self):
        """Unknown symbol → sizer blocks."""
        orch = _make_orchestrator()
        sig = _make_signal(symbol="FAKEPAIR", confidence=0.80, entry=1.0, sl=0.99)
        order = orch.process_signal(sig)
        assert order.rejected
        assert "Unknown instrument" in order.rejection_reason
