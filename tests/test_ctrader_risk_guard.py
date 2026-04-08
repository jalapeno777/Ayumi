from datetime import date
import pytest

from adapters.ctrader.models import TradeSignal, TradeDirection
from adapters.ctrader.risk_guard import (
    RiskGuard,
    FTMOConfig,
    FTMOProfile,
    FTMO_PROFILE_CHALLENGE,
    RiskLimitType,
    RiskLimitResult,
)


class TestFTMOConfig:
    def test_default_config(self):
        config = FTMOConfig()
        assert config.daily_loss_limit_pct == 0.05
        assert config.total_drawdown_limit_pct == 0.10
        assert config.max_trades_per_day == 10
        assert config.max_positions == 3
        assert config.min_risk_reward == 1.5

    def test_custom_config(self):
        config = FTMOConfig(
            daily_loss_limit_pct=0.02,
            max_trades_per_day=5,
        )
        assert config.daily_loss_limit_pct == 0.02
        assert config.max_trades_per_day == 5


class TestFTMOProfile:
    def test_default_profile(self):
        profile = FTMOProfile()
        assert profile.risk_per_trade_pct == 0.005
        assert profile.daily_loss_limit_pct == 0.05
        assert profile.max_trades_per_day == 10

    def test_challenge_profile(self):
        assert FTMO_PROFILE_CHALLENGE.risk_per_trade_pct == 0.005
        assert FTMO_PROFILE_CHALLENGE.daily_loss_limit_pct == 0.05
        assert FTMO_PROFILE_CHALLENGE.max_trades_per_day == 10

    def test_valid_profile(self):
        profile = FTMOProfile(
            risk_per_trade_pct=0.01,
            daily_loss_limit_pct=0.05,
            max_trades_per_day=5,
        )
        assert profile.risk_per_trade_pct == 0.01

    def test_invalid_profile_raises_error(self):
        with pytest.raises(ValueError, match="Invalid FTMO profile"):
            FTMOProfile(
                risk_per_trade_pct=0.02,
                daily_loss_limit_pct=0.05,
                max_trades_per_day=10,
            )

    def test_invalid_profile_edge_case(self):
        with pytest.raises(ValueError, match="Invalid FTMO profile"):
            FTMOProfile(
                risk_per_trade_pct=0.005,
                daily_loss_limit_pct=0.04,
                max_trades_per_day=10,
            )

    def test_valid_profile_exact_boundary(self):
        profile = FTMOProfile(
            risk_per_trade_pct=0.005,
            daily_loss_limit_pct=0.05,
            max_trades_per_day=10,
        )
        assert profile.risk_per_trade_pct * profile.max_trades_per_day == profile.daily_loss_limit_pct


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
        config = FTMOConfig(max_position_size_pct=0.02)
        guard = RiskGuard(ftmo_config=config, starting_balance=100000.0)
        result = guard.check_trade_allowed(
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
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
