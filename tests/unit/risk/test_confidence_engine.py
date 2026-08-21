"""Tests for Confidence Engine, Gates, and integration with ProfileRouter + Sizer."""

import pytest
from confidence.engine import ConfidenceEngine
from confidence.gates import GateConfig
from risk.profile_router import Profile, ProfileRouter
from risk.sl_position_sizer import SLPositionSizer


@pytest.fixture
def engine():
    return ConfidenceEngine()


@pytest.fixture
def sizer():
    return SLPositionSizer(account_balance=10000.0)


@pytest.fixture
def router():
    return ProfileRouter()


class TestBasicScoring:
    def test_raw_passthrough(self, engine):
        result = engine.score(0.75, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert not result.blocked
        assert result.final_score == pytest.approx(0.75)

    def test_clamp_high(self, engine):
        result = engine.score(1.5, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert result.final_score == pytest.approx(1.0)

    def test_clamp_low(self, engine):
        result = engine.score(-0.2, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert result.final_score == pytest.approx(0.0)

    def test_zero_confidence(self, engine):
        result = engine.score(0.0, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert result.final_score == pytest.approx(0.0)


class TestConfluenceBoost:
    def test_single_confluence(self, engine):
        confluences = [{"strategy": "ema_cross", "direction": "long", "timeframe": "H1"}]
        result = engine.score(0.60, symbol="EURUSD", spread=1.0, hour_utc=10, confluences=confluences)
        assert result.final_score > 0.60
        assert result.confluence_boost > 0

    def test_multiple_confluences(self, engine):
        confluences = [
            {"strategy": "ema_cross", "direction": "long", "timeframe": "H1"},
            {"strategy": "rsi_div", "direction": "long", "timeframe": "H4"},
        ]
        result = engine.score(0.60, symbol="EURUSD", spread=1.0, hour_utc=10, confluences=confluences)
        assert result.final_score > 0.60
        # Two agreeing strategies + two timeframes = bigger boost
        base = engine.score(0.60, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert result.final_score > base.final_score

    def test_confluence_capped_at_1(self, engine):
        confluences = [
            {"strategy": "s1", "direction": "long", "timeframe": "M15"},
            {"strategy": "s2", "direction": "long", "timeframe": "H1"},
            {"strategy": "s3", "direction": "long", "timeframe": "H4"},
        ]
        result = engine.score(0.95, symbol="EURUSD", spread=1.0, hour_utc=10, confluences=confluences)
        assert result.final_score <= 1.0

    def test_opposite_direction_no_boost(self, engine):
        confluences = [{"strategy": "ema_cross", "direction": "short", "timeframe": "H1"}]
        result = engine.score(
            0.60,
            symbol="EURUSD",
            spread=1.0,
            hour_utc=10,
            direction="long",
            confluences=confluences,
        )
        assert result.confluence_boost == pytest.approx(0.0)

    def test_no_confluences(self, engine):
        result = engine.score(0.60, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert result.confluence_boost == pytest.approx(0.0)


class TestGateRejection:
    def test_spread_gate_reject(self, engine):
        result = engine.score(0.80, symbol="EURUSD", spread=5.0, hour_utc=10)
        assert result.blocked
        assert "spread" in result.block_reason.lower()

    def test_spread_gate_custom_symbol(self):
        config = GateConfig(symbol_max_spreads={"XAUUSD": 5.0})
        engine = ConfidenceEngine(config)
        result = engine.score(0.80, symbol="XAUUSD", spread=3.0, hour_utc=10)
        assert not result.blocked

    def test_session_gate_reject(self, engine):
        # Hour 3 UTC = outside all sessions (NY closed at 22, London opens at 8, Asia 0-8... 3 is in Asia)
        # Let's use hour 23 which is outside all
        result = engine.score(0.80, symbol="EURUSD", spread=1.0, hour_utc=23)
        assert result.blocked
        assert "session" in result.block_reason.lower()

    def test_session_gate_pass(self, engine):
        result = engine.score(0.80, symbol="EURUSD", spread=1.0, hour_utc=14)
        assert not result.blocked
        assert "session" in result.gates_passed

    def test_volatility_gate_reject(self, engine):
        result = engine.score(0.80, symbol="EURUSD", spread=1.0, hour_utc=10, atr=5.0)
        assert result.blocked
        assert "volatility" in result.gates_failed

    def test_volatility_gate_pass(self, engine):
        result = engine.score(0.80, symbol="EURUSD", spread=1.0, hour_utc=10, atr=0.8)
        assert not result.blocked
        assert "volatility" in result.gates_passed

    def test_no_atr_passes(self, engine):
        """No ATR data should pass (stub behavior)."""
        result = engine.score(0.80, symbol="EURUSD", spread=1.0, hour_utc=10, atr=0.0)
        assert not result.blocked


class TestProfileRouterIntegration:
    def test_high_confidence_routes_sniper(self, router, engine):
        result = engine.score(0.85, symbol="EURUSD", spread=1.0, hour_utc=10)
        profile = router.route(result.final_score)
        assert profile == Profile.SNIPER

    def test_medium_confidence_routes_swarm(self, router, engine):
        result = engine.score(0.50, symbol="EURUSD", spread=1.0, hour_utc=10)
        profile = router.route(result.final_score)
        assert profile == Profile.SWARM

    def test_low_confidence_rejected(self, router, engine):
        result = engine.score(0.20, symbol="EURUSD", spread=1.0, hour_utc=10)
        profile = router.route(result.final_score)
        assert profile is None


class TestFullPipelineIntegration:
    """Integration test: confidence → router → sizer → lots."""

    def test_sniper_pipeline(self, engine, router, sizer):
        result = engine.score(0.85, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert not result.blocked

        profile = router.route(result.final_score)
        assert profile == Profile.SNIPER

        size = sizer.calculate("EURUSD", 1.0850, 1.0820, profile=profile)
        assert not size.blocked
        assert size.lots > 0

    def test_swarm_pipeline(self, engine, router, sizer):
        result = engine.score(0.50, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert not result.blocked

        profile = router.route(result.final_score)
        assert profile == Profile.SWARM

        size = sizer.calculate("EURUSD", 1.0850, 1.0820, profile=profile)
        assert not size.blocked
        assert size.lots > 0
        # Swarm should be smaller than sniper
        sniper_profile = router.route(0.85)
        sniper_size = sizer.calculate("EURUSD", 1.0850, 1.0820, profile=sniper_profile)
        assert size.lots < sniper_size.lots

    def test_blocked_by_gate_no_lots(self, engine, router, sizer):
        result = engine.score(0.85, symbol="EURUSD", spread=10.0, hour_utc=10)
        assert result.blocked
        # Should not reach router/sizer — blocked at gate
        assert result.block_reason != ""

    def test_rejected_confidence_no_lots(self, engine, router, sizer):
        result = engine.score(0.10, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert not result.blocked

        profile = router.route(result.final_score)
        assert profile is None  # Below threshold

    def test_profile_enum_to_sizer(self, engine, router, sizer):
        """Verify Profile enum flows cleanly into sizer (P1 fix validation)."""
        result = engine.score(0.85, symbol="EURUSD", spread=1.0, hour_utc=10)
        profile = router.route(result.final_score)
        assert profile == Profile.SNIPER

        # Pass the Profile enum directly — should not raise
        size = sizer.calculate("EURUSD", 1.0850, 1.0820, profile=profile)
        assert not size.blocked
        assert size.lots > 0


class TestCustomGate:
    def test_add_custom_gate(self):
        from confidence.gates import GateCheck

        class StubGate:
            def check(self, ctx):
                return GateCheck(gate_name="stub", passed=True)

        engine = ConfidenceEngine()
        engine.add_gate(StubGate())
        result = engine.score(0.80, symbol="EURUSD", spread=1.0, hour_utc=10)
        assert not result.blocked
        assert "stub" in result.gates_passed
