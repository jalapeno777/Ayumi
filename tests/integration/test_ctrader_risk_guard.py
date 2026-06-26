from datetime import date

import pytest
from adapters.ctrader.models import TradeDirection, TradeSignal
from adapters.ctrader.risk_guard import (
    FTMO_PROFILE_CHALLENGE,
    FTMOConfig,
    FTMOProfile,
    RiskGuard,
    RiskLimitResult,
    RiskLimitType,
)


class TestFTMOProfile:
    def test_default_challenge_profile(self):
        assert FTMO_PROFILE_CHALLENGE.risk_per_trade_pct == 0.005
        assert FTMO_PROFILE_CHALLENGE.daily_loss_limit_pct == 0.05
        assert FTMO_PROFILE_CHALLENGE.total_drawdown_limit_pct == 0.10
        assert FTMO_PROFILE_CHALLENGE.max_trades_per_day == 10
        assert FTMO_PROFILE_CHALLENGE.max_positions == 3
        assert FTMO_PROFILE_CHALLENGE.min_risk_reward == 1.5

    def test_valid_profile(self):
        profile = FTMOProfile(
            risk_per_trade_pct=0.005,
            daily_loss_limit_pct=0.05,
            max_trades_per_day=10,
        )
        assert profile.risk_per_trade_pct == 0.005

    def test_exact_boundary_passes(self):
        profile = FTMOProfile(
            risk_per_trade_pct=0.005,
            daily_loss_limit_pct=0.05,
            max_trades_per_day=10,
        )
        assert (
            profile.risk_per_trade_pct * profile.max_trades_per_day
            == profile.daily_loss_limit_pct
        )

    def test_exceeds_daily_limit_raises(self):
        with pytest.raises(ValueError, match="exceeds daily_loss_limit_pct"):
            FTMOProfile(
                risk_per_trade_pct=0.01,
                daily_loss_limit_pct=0.05,
                max_trades_per_day=10,
            )

    def test_zero_risk_per_trade_raises(self):
        with pytest.raises(ValueError, match="risk_per_trade_pct must be positive"):
            FTMOProfile(risk_per_trade_pct=0.0)

    def test_negative_risk_per_trade_raises(self):
        with pytest.raises(ValueError, match="risk_per_trade_pct must be positive"):
            FTMOProfile(risk_per_trade_pct=-0.01)

    def test_zero_daily_loss_limit_raises(self):
        with pytest.raises(ValueError, match="daily_loss_limit_pct must be positive"):
            FTMOProfile(daily_loss_limit_pct=0.0)

    def test_zero_max_trades_raises(self):
        with pytest.raises(ValueError, match="max_trades_per_day must be positive"):
            FTMOProfile(max_trades_per_day=0)

    def test_single_trade_within_limit(self):
        profile = FTMOProfile(
            risk_per_trade_pct=0.02,
            daily_loss_limit_pct=0.05,
            max_trades_per_day=2,
        )
        assert profile is not None

    def test_custom_conservative_profile(self):
        profile = FTMOProfile(
            risk_per_trade_pct=0.003,
            daily_loss_limit_pct=0.05,
            max_trades_per_day=10,
        )
        assert profile.risk_per_trade_pct == 0.003


class TestFTMOConfig:
    def test_default_config_uses_profile(self):
        config = FTMOConfig()
        assert (
            config.daily_loss_limit_pct == FTMO_PROFILE_CHALLENGE.daily_loss_limit_pct
        )
        assert config.max_position_size_pct == FTMO_PROFILE_CHALLENGE.risk_per_trade_pct
        assert config.max_trades_per_day == FTMO_PROFILE_CHALLENGE.max_trades_per_day

    def test_max_position_size_pct_is_risk_per_trade(self):
        config = FTMOConfig()
        assert config.max_position_size_pct == 0.005

    def test_custom_config_overrides_profile(self):
        config = FTMOConfig(
            daily_loss_limit_pct=0.02,
            max_trades_per_day=5,
        )
        assert config.daily_loss_limit_pct == 0.02
        assert config.max_trades_per_day == 5


class TestRiskGuard:
    def test_initial_state(self):
        guard = RiskGuard(starting_balance=100000.0)
        assert guard.daily_trade_count == 0
        assert guard.total_trades == 0
        assert not guard.is_blocked
        assert guard.current_drawdown_pct == 0.0

    def test_signal_with_good_risk_reward(self):
        guard = RiskGuard(starting_balance=100000.0)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            take_profit_2=1.1200,
            take_profit_3=1.1300,
            volume=0.1,
            confidence=0.85,
            rationale="Test signal",
        )
        result = guard.check_signal(signal)
        assert result.allowed is True

    def test_signal_with_poor_risk_reward(self):
        guard = RiskGuard(starting_balance=100000.0)
        signal = TradeSignal(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0990,
            take_profit_1=1.1005,
            take_profit_2=1.1010,
            take_profit_3=1.1015,
            volume=0.1,
            confidence=0.85,
            rationale="Poor R:R signal",
        )
        result = guard.check_signal(signal)
        assert result.allowed is False
        assert result.limit_type == RiskLimitType.MIN_RISK_REWARD

    def test_trade_allowed_position_size_within_limits(self):
        config = FTMOConfig(max_position_size_pct=0.20)
        guard = RiskGuard(ftmo_config=config, starting_balance=100000.0)
        result = guard.check_trade_allowed(
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        assert result.allowed is True

    def test_trade_allowed_position_size_exceeds_limit(self):
        # 10.6 lot trade with 20-pip SL risks ~$2,120 (2.12%) on $100k — should be rejected.
        # Note: epsilon=0.0001 tolerance means threshold is 2.1%, so 2.12% exceeds it.
        config = FTMOConfig(max_position_size_pct=0.02)
        guard = RiskGuard(ftmo_config=config, starting_balance=100000.0)
        result = guard.check_trade_allowed(
            direction=TradeDirection.LONG,
            volume=10.6,
            entry_price=1.1000,
            stop_loss=1.0980,
            take_profit=1.1100,
        )
        assert result.allowed is False
        assert result.limit_type == RiskLimitType.POSITION_SIZE

    def test_record_trade_updates_counters(self):
        guard = RiskGuard(starting_balance=100000.0)
        guard._current_day = date.today()
        guard.record_trade(pnl=100.0, is_win=True, trade_count_increment=1)
        assert guard.daily_trade_count == 1
        assert guard.total_trades == 1

    def test_record_trade_updates_balance(self):
        guard = RiskGuard(starting_balance=100000.0)
        guard._current_day = date.today()
        initial_balance = guard._current_balance
        guard.record_trade(pnl=500.0, is_win=True, trade_count_increment=1)
        assert guard._current_balance == initial_balance + 500.0

    def test_record_trade_updates_peak_balance(self):
        guard = RiskGuard(starting_balance=100000.0)
        guard._current_day = date.today()
        guard.record_trade(pnl=1000.0, is_win=True, trade_count_increment=1)
        assert guard._peak_balance == 101000.0

    def test_circuit_breaker_triggered_on_daily_loss(self):
        config = FTMOConfig(daily_loss_limit_pct=0.05)
        guard = RiskGuard(ftmo_config=config, starting_balance=100000.0)

        guard._current_day = date.today()
        guard._daily_start_balance = 100000.0
        guard._current_balance = 94000.0
        guard._daily_trade_count = 1  # A trade occurred → daily loss check is active

        result = guard.check_trade_allowed(
            direction=TradeDirection.LONG,
            volume=0.01,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        assert result.allowed is False
        assert result.limit_type == RiskLimitType.DAILY_LOSS

    def test_reset_circuit_breaker(self):
        config = FTMOConfig(daily_loss_limit_pct=0.05)
        guard = RiskGuard(ftmo_config=config, starting_balance=100000.0)

        guard._current_day = date.today()
        guard._daily_start_balance = 100000.0
        guard._current_balance = 94000.0
        guard._daily_trade_count = 1  # A trade occurred → daily loss check is active

        guard.check_trade_allowed(
            direction=TradeDirection.LONG,
            volume=0.01,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        assert guard.is_blocked is True

        guard.reset_circuit_breaker()
        assert guard.is_blocked is False

    def test_get_stats(self):
        guard = RiskGuard(starting_balance=100000.0)
        stats = guard.get_stats()
        assert "total_trades" in stats
        assert "daily_trades" in stats
        assert "current_balance" in stats
        assert "is_blocked" in stats


class TestDailyLossNoTradesGuard:
    """B1 fix: daily loss limit must NOT trigger when no trades occurred today."""

    def test_no_trades_balance_drop_does_not_trigger(self):
        """Even if balance drops (e.g. broker sync), 0 trades → no daily loss check."""
        config = FTMOConfig(daily_loss_limit_pct=0.05)
        guard = RiskGuard(ftmo_config=config, starting_balance=100000.0)
        guard._current_day = date.today()
        guard._daily_start_balance = 100000.0
        # Simulate balance sync that shows a 7% drop — but no trades happened
        guard._current_balance = 93000.0
        assert guard.daily_trade_count == 0

        result = guard.check_trade_allowed(
            direction=TradeDirection.LONG,
            volume=0.01,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        assert result.allowed is True, (
            f"Daily loss should be skipped with 0 trades, got: {result.message}"
        )
        assert not guard.is_blocked

    def test_daily_loss_still_triggers_after_trades(self):
        """When trades HAVE occurred, daily loss limit must still work."""
        config = FTMOConfig(daily_loss_limit_pct=0.05)
        guard = RiskGuard(ftmo_config=config, starting_balance=100000.0)
        guard._current_day = date.today()
        guard._daily_start_balance = 100000.0
        # Record one trade with a loss
        guard.record_trade(pnl=-6000.0, is_win=False, trade_count_increment=1)
        assert guard.daily_trade_count == 1
        assert guard._current_balance == 94000.0  # 6% loss > 5% limit

        result = guard.check_trade_allowed(
            direction=TradeDirection.LONG,
            volume=0.01,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        assert result.allowed is False
        assert result.limit_type == RiskLimitType.DAILY_LOSS

    def test_daily_loss_within_limit_with_trades(self):
        """Trades occurred but loss is within limit — should be allowed."""
        config = FTMOConfig(daily_loss_limit_pct=0.05)
        guard = RiskGuard(ftmo_config=config, starting_balance=100000.0)
        guard._current_day = date.today()
        guard._daily_start_balance = 100000.0
        # Small loss, within 5% limit
        guard.record_trade(pnl=-1000.0, is_win=False, trade_count_increment=1)

        result = guard.check_trade_allowed(
            direction=TradeDirection.LONG,
            volume=0.01,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        # 1% loss < 5% limit — should pass daily loss check
        assert result.limit_type != RiskLimitType.DAILY_LOSS


class TestRiskLimitResult:
    def test_result_allowed(self):
        result = RiskLimitResult(
            allowed=True,
            limit_type=RiskLimitType.POSITION_SIZE,
            message="Trade allowed",
        )
        assert result.allowed is True

    def test_result_rejected(self):
        result = RiskLimitResult(
            allowed=False,
            limit_type=RiskLimitType.DAILY_LOSS,
            message="Daily loss limit exceeded",
            current_value=0.035,
            limit_value=0.03,
        )
        assert result.allowed is False
        assert result.current_value == 0.035
