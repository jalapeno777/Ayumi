from datetime import datetime, timezone

from hybrid.risk_manager import (
    LondonSessionConfig,
    RiskAction,
    RiskDecision,
    RiskManager,
)
from hybrid.signal import HumanSignal, SignalType

_LONDON_TIME = datetime(2026, 4, 23, 9, 30, tzinfo=timezone.utc)
_OUTSIDE_LONDON_TIME = datetime(2026, 4, 23, 14, 0, tzinfo=timezone.utc)


def _buy_signal(
    entry: float = 1.1000,
    sl: float = 1.0950,
    tp: float = 1.1150,
    confidence: float = 0.8,
    pair: str = "EUR/USD",
    timestamp: datetime | None = None,
) -> HumanSignal:
    return HumanSignal(
        signal_type=SignalType.BUY,
        pair=pair,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        confidence=confidence,
        timestamp=timestamp or _OUTSIDE_LONDON_TIME,
    )


class TestRiskManagerInit:
    def test_default_params(self):
        rm = RiskManager()
        assert rm.current_balance == 100_000.0
        assert rm.daily_trade_count == 0
        assert rm.open_position_count == 0

    def test_custom_balance(self):
        rm = RiskManager(starting_balance=50_000.0)
        assert rm.current_balance == 50_000.0


class TestValidateSignal:
    def test_close_signal_always_allowed(self):
        rm = RiskManager()
        signal = HumanSignal(signal_type=SignalType.CLOSE, pair="EUR/USD")
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.ALLOW
        assert "Close" in decision.reason

    def test_valid_buy_signal_allowed(self):
        rm = RiskManager()
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.ALLOW
        assert decision.risk_reward is not None
        assert decision.risk_reward >= 1.5

    def test_signal_without_stop_loss_rejected(self):
        rm = RiskManager()
        signal = HumanSignal(
            signal_type=SignalType.BUY,
            pair="EUR/USD",
            entry_price=1.1,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.REJECT
        assert "stop loss" in decision.reason.lower()

    def test_poor_risk_reward_rejected(self):
        rm = RiskManager()
        signal = _buy_signal(sl=1.0990, tp=1.1010)
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.REJECT
        assert "Risk:Reward" in decision.reason

    def test_daily_trade_limit_rejection(self):
        rm = RiskManager(max_trades_per_day=1)
        rm.record_trade(pnl=0.0)
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.REJECT
        assert "Daily trade limit" in decision.reason

    def test_sell_signal_allowed(self):
        rm = RiskManager()
        signal = HumanSignal(
            signal_type=SignalType.SELL,
            pair="GBP/USD",
            entry_price=1.2600,
            stop_loss=1.2650,
            take_profit=1.2450,
            confidence=0.7,
            timestamp=_OUTSIDE_LONDON_TIME,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.ALLOW


class TestDailyDrawdownCheck:
    def test_signal_rejected_when_daily_drawdown_exceeded(self):
        rm = RiskManager(
            starting_balance=100_000.0,
            max_daily_loss_pct=5.0,
        )
        rm.record_trade(pnl=-6_000.0)
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.REJECT
        assert "Daily drawdown" in decision.reason

    def test_signal_allowed_when_daily_drawdown_within_limit(self):
        rm = RiskManager(
            starting_balance=100_000.0,
            max_daily_loss_pct=5.0,
        )
        rm.record_trade(pnl=-2_000.0)
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.ALLOW


class TestTotalDrawdownCheck:
    def test_signal_rejected_when_total_drawdown_exceeded(self):
        rm = RiskManager(
            starting_balance=100_000.0,
            max_total_drawdown_pct=10.0,
        )
        rm.record_trade(pnl=10_000.0)
        rm.reset_daily_tracking()
        rm.record_trade(pnl=-11_000.0)
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.REJECT
        assert "Total drawdown" in decision.reason


class TestDailyRiskBudget:
    def test_signal_rejected_when_daily_risk_budget_exhausted(self):
        rm = RiskManager(
            risk_per_trade_pct=0.5,
            max_daily_risk_pct=1.0,
        )
        rm.record_trade(pnl=0.0, risk_pct=0.5)
        rm.record_trade(pnl=0.0, risk_pct=0.5)
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.REJECT
        assert "risk budget" in decision.reason.lower()

    def test_signal_allowed_within_daily_risk_budget(self):
        rm = RiskManager(
            risk_per_trade_pct=0.5,
            max_daily_risk_pct=1.5,
        )
        rm.record_trade(pnl=0.0, risk_pct=0.5)
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.ALLOW


class TestMaxPositionsCheck:
    def test_signal_rejected_when_max_positions_reached(self):
        rm = RiskManager(max_positions=1)
        rm.open_position()
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.REJECT
        assert "Max positions" in decision.reason

    def test_signal_allowed_when_positions_available(self):
        rm = RiskManager(max_positions=2)
        rm.open_position()
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.ALLOW


class TestPositionCounting:
    def test_open_position_increments(self):
        rm = RiskManager()
        assert rm.open_position_count == 0
        rm.open_position()
        assert rm.open_position_count == 1
        rm.open_position()
        assert rm.open_position_count == 2

    def test_close_position_decrements(self):
        rm = RiskManager()
        rm.open_position()
        rm.open_position()
        rm.close_position()
        assert rm.open_position_count == 1

    def test_close_position_does_not_go_negative(self):
        rm = RiskManager()
        rm.close_position()
        assert rm.open_position_count == 0


class TestCalculatePositionSize:
    def test_basic_position_size(self):
        rm = RiskManager(starting_balance=100_000.0, risk_per_trade_pct=0.5)
        signal = _buy_signal(entry=1.1000, sl=1.0950)
        size = rm.calculate_position_size(signal)
        assert size > 0

    def test_close_signal_returns_zero(self):
        rm = RiskManager()
        signal = HumanSignal(signal_type=SignalType.CLOSE, pair="EUR/USD")
        assert rm.calculate_position_size(signal) == 0.0

    def test_no_stop_loss_returns_zero(self):
        rm = RiskManager()
        signal = HumanSignal(
            signal_type=SignalType.BUY, pair="EUR/USD", entry_price=1.1
        )
        assert rm.calculate_position_size(signal) == 0.0

    def test_custom_account_balance(self):
        rm = RiskManager(starting_balance=100_000.0)
        signal = _buy_signal()
        default_size = rm.calculate_position_size(signal)
        custom_size = rm.calculate_position_size(signal, account_balance=50_000.0)
        assert custom_size < default_size

    def test_risk_pct_override(self):
        rm = RiskManager(
            starting_balance=100_000.0, risk_per_trade_pct=0.5, max_lot_size=100.0
        )
        signal = _buy_signal(entry=1.1000, sl=1.0950)
        default_size = rm.calculate_position_size(signal)
        doubled_size = rm.calculate_position_size(signal, risk_pct_override=1.0)
        assert doubled_size > default_size

    def test_position_size_uses_fixed_fractional(self):
        rm = RiskManager(
            starting_balance=100_000.0, risk_per_trade_pct=1.0, max_lot_size=100.0
        )
        signal = _buy_signal(entry=1.1000, sl=1.0950)
        size = rm.calculate_position_size(signal)
        expected_risk = 100_000.0 * 0.01
        stop_distance = 0.005
        expected_size = expected_risk / (stop_distance * 100_000)
        assert abs(size - round(expected_size, 2)) < 0.01


class TestRecordTrade:
    def test_record_win_increments_balance(self):
        rm = RiskManager(starting_balance=100_000.0)
        rm.record_trade(pnl=500.0)
        assert rm.current_balance == 100_500.0
        assert rm.daily_trade_count == 1

    def test_record_loss_decrements_balance(self):
        rm = RiskManager(starting_balance=100_000.0)
        rm.record_trade(pnl=-300.0)
        assert rm.current_balance == 99_700.0
        assert rm.daily_trade_count == 1

    def test_multiple_trades_accumulate(self):
        rm = RiskManager()
        rm.record_trade(100.0)
        rm.record_trade(-50.0)
        rm.record_trade(200.0)
        assert rm.current_balance == 100_250.0
        assert rm.daily_trade_count == 3

    def test_record_trade_tracks_daily_risk(self):
        rm = RiskManager(risk_per_trade_pct=0.5, max_daily_risk_pct=1.5)
        rm.record_trade(pnl=0.0, risk_pct=0.5)
        assert rm.daily_trade_count == 1
        decision = rm.validate_signal(_buy_signal())
        assert decision.suggested_lot_size == 0.5


class TestResetDailyTracking:
    def test_reset_clears_trade_count(self):
        rm = RiskManager()
        rm.record_trade(100.0)
        rm.record_trade(200.0)
        assert rm.daily_trade_count == 2
        rm.reset_daily_tracking()
        assert rm.daily_trade_count == 0

    def test_reset_clears_daily_risk_budget(self):
        rm = RiskManager(risk_per_trade_pct=0.5, max_daily_risk_pct=1.0)
        rm.record_trade(pnl=0.0, risk_pct=0.5)
        rm.record_trade(pnl=0.0, risk_pct=0.5)
        assert rm.daily_trade_count == 2
        rm.reset_daily_tracking()
        assert rm.daily_trade_count == 0
        decision = rm.validate_signal(_buy_signal())
        assert decision.action == RiskAction.ALLOW


class TestRiskDecision:
    def test_decision_fields(self):
        d = RiskDecision(
            action=RiskAction.ALLOW,
            reason="OK",
            risk_reward=2.0,
            suggested_lot_size=0.1,
        )
        assert d.action == RiskAction.ALLOW
        assert d.reason == "OK"
        assert d.risk_reward == 2.0
        assert d.suggested_lot_size == 0.1


class TestMaxLotSize:
    def test_default_max_lot_size(self):
        rm = RiskManager()
        assert rm.max_lot_size == 1.0

    def test_custom_max_lot_size(self):
        rm = RiskManager(max_lot_size=5.0)
        assert rm.max_lot_size == 5.0

    def test_position_size_capped_at_max(self):
        rm = RiskManager(
            starting_balance=100_000.0, risk_per_trade_pct=1.0, max_lot_size=1.0
        )
        signal = _buy_signal(entry=1.1000, sl=1.0990)
        size = rm.calculate_position_size(signal)
        assert size == 1.0

    def test_position_size_not_capped_when_below_max(self):
        rm = RiskManager(
            starting_balance=100_000.0, risk_per_trade_pct=0.1, max_lot_size=5.0
        )
        signal = _buy_signal(entry=1.1000, sl=1.0950)
        size = rm.calculate_position_size(signal)
        assert size < 5.0

    def test_position_size_with_high_max_lot_size_uncapped(self):
        rm = RiskManager(
            starting_balance=100_000.0, risk_per_trade_pct=1.0, max_lot_size=100.0
        )
        signal = _buy_signal(entry=1.1000, sl=1.0950)
        size = rm.calculate_position_size(signal)
        expected_risk = 100_000.0 * 0.01
        stop_distance = 0.005
        expected_size = expected_risk / (stop_distance * 100_000)
        assert abs(size - round(expected_size, 2)) < 0.01

    def test_zero_max_lot_size_returns_zero(self):
        rm = RiskManager(
            starting_balance=100_000.0, risk_per_trade_pct=0.5, max_lot_size=0.0
        )
        signal = _buy_signal(entry=1.1000, sl=1.0950)
        size = rm.calculate_position_size(signal)
        assert size == 0.0


class TestLondonSessionConfig:
    def test_contains_during_london_hours(self):
        cfg = LondonSessionConfig()
        t = datetime(2026, 4, 23, 9, 0, tzinfo=timezone.utc)
        assert cfg.contains(t) is True

    def test_contains_at_london_start(self):
        cfg = LondonSessionConfig()
        t = datetime(2026, 4, 23, 8, 0, tzinfo=timezone.utc)
        assert cfg.contains(t) is True

    def test_contains_at_london_end_exclusive(self):
        cfg = LondonSessionConfig()
        t = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
        assert cfg.contains(t) is False

    def test_contains_outside_london(self):
        cfg = LondonSessionConfig()
        t = datetime(2026, 4, 23, 14, 0, tzinfo=timezone.utc)
        assert cfg.contains(t) is False

    def test_contains_before_london(self):
        cfg = LondonSessionConfig()
        t = datetime(2026, 4, 23, 7, 59, tzinfo=timezone.utc)
        assert cfg.contains(t) is False

    def test_is_blocked_pair_gbpusd(self):
        cfg = LondonSessionConfig()
        assert cfg.is_blocked_pair("GBP/USD") is True
        assert cfg.is_blocked_pair("gbpusd") is True

    def test_is_blocked_pair_gbpcad(self):
        cfg = LondonSessionConfig()
        assert cfg.is_blocked_pair("GBP/CAD") is True

    def test_is_blocked_pair_non_gbp(self):
        cfg = LondonSessionConfig()
        assert cfg.is_blocked_pair("EUR/USD") is False
        assert cfg.is_blocked_pair("USD/JPY") is False

    def test_custom_blocked_prefixes(self):
        cfg = LondonSessionConfig(blocked_pair_prefixes=("EUR",))
        assert cfg.is_blocked_pair("EUR/USD") is True
        assert cfg.is_blocked_pair("GBP/USD") is False


class TestLondonRROverride:
    def test_london_rr_2_0_rejects_1_5_rr(self):
        rm = RiskManager()
        signal = _buy_signal(
            sl=1.0950,
            tp=1.1025,
            timestamp=_LONDON_TIME,
        )
        rr = (1.1025 - 1.1000) / (1.1000 - 1.0950)
        assert rr < 2.0
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.REJECT
        assert "Risk:Reward" in decision.reason

    def test_london_rr_2_0_allows_2_0_rr(self):
        rm = RiskManager()
        signal = _buy_signal(
            sl=1.0950,
            tp=1.1150,
            timestamp=_LONDON_TIME,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.ALLOW

    def test_non_london_rr_1_5_still_allowed(self):
        rm = RiskManager()
        signal = _buy_signal(
            sl=1.0950,
            tp=1.1080,
            timestamp=_OUTSIDE_LONDON_TIME,
        )
        rr = (1.1080 - 1.1000) / (1.1000 - 1.0950)
        assert rr >= 1.5
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.ALLOW

    def test_london_uses_higher_of_global_and_session_rr(self):
        rm = RiskManager(min_risk_reward=2.5)
        signal = _buy_signal(
            sl=1.0950,
            tp=1.1110,
            timestamp=_LONDON_TIME,
        )
        rr = (1.1110 - 1.1000) / (1.1000 - 1.0950)
        assert rr >= 2.0
        assert rr < 2.5
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.REJECT


class TestLondonPairFilter:
    def test_gbp_pair_rejected_during_london(self):
        rm = RiskManager()
        signal = _buy_signal(
            pair="GBP/USD",
            sl=1.2550,
            tp=1.2750,
            timestamp=_LONDON_TIME,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.REJECT
        assert "blocked" in decision.reason.lower()
        assert "London" in decision.reason

    def test_gbp_pair_allowed_outside_london(self):
        rm = RiskManager()
        signal = _buy_signal(
            pair="GBP/USD",
            entry=1.2600,
            sl=1.2650,
            tp=1.2450,
            timestamp=_OUTSIDE_LONDON_TIME,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.ALLOW

    def test_eur_pair_allowed_during_london(self):
        rm = RiskManager()
        signal = _buy_signal(
            pair="EUR/USD",
            sl=1.0950,
            tp=1.1150,
            timestamp=_LONDON_TIME,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.ALLOW

    def test_gbpcad_rejected_during_london(self):
        rm = RiskManager()
        signal = _buy_signal(
            pair="GBP/CAD",
            entry=1.7100,
            sl=1.7050,
            tp=1.7300,
            timestamp=_LONDON_TIME,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.REJECT


class TestLondonSizeReduction:
    def test_position_size_halved_during_london(self):
        rm = RiskManager(
            starting_balance=100_000.0,
            risk_per_trade_pct=1.0,
            max_lot_size=100.0,
        )
        london_signal = _buy_signal(entry=1.1000, sl=1.0950, timestamp=_LONDON_TIME)
        outside_signal = _buy_signal(
            entry=1.1000, sl=1.0950, timestamp=_OUTSIDE_LONDON_TIME
        )
        london_size = rm.calculate_position_size(london_signal)
        outside_size = rm.calculate_position_size(outside_signal)
        assert london_size > 0
        assert london_size == outside_size * 0.5

    def test_position_size_not_reduced_outside_london(self):
        rm = RiskManager(
            starting_balance=100_000.0,
            risk_per_trade_pct=1.0,
            max_lot_size=100.0,
        )
        signal = _buy_signal(entry=1.1000, sl=1.0950, timestamp=_OUTSIDE_LONDON_TIME)
        size = rm.calculate_position_size(signal)
        expected_risk = 100_000.0 * 0.01
        stop_distance = 0.005
        expected_size = expected_risk / (stop_distance * 100_000)
        assert abs(size - round(expected_size, 2)) < 0.01

    def test_custom_size_multiplier(self):
        cfg = LondonSessionConfig(size_multiplier=0.3)
        rm = RiskManager(
            starting_balance=100_000.0,
            risk_per_trade_pct=1.0,
            max_lot_size=100.0,
            london_config=cfg,
        )
        london_signal = _buy_signal(entry=1.1000, sl=1.0950, timestamp=_LONDON_TIME)
        outside_signal = _buy_signal(
            entry=1.1000, sl=1.0950, timestamp=_OUTSIDE_LONDON_TIME
        )
        london_size = rm.calculate_position_size(london_signal)
        outside_size = rm.calculate_position_size(outside_signal)
        assert abs(london_size - outside_size * 0.3) < 0.01


class TestLondonTradeCounting:
    def test_london_trade_count_increments_on_allow(self):
        rm = RiskManager()
        signal = _buy_signal(
            sl=1.0950,
            tp=1.1150,
            timestamp=_LONDON_TIME,
        )
        assert rm.london_trade_count == 0
        rm.validate_signal(signal)
        assert rm.london_trade_count == 1

    def test_london_trade_count_not_incremented_outside_london(self):
        rm = RiskManager()
        signal = _buy_signal(timestamp=_OUTSIDE_LONDON_TIME)
        rm.validate_signal(signal)
        assert rm.london_trade_count == 0

    def test_london_trade_count_reset_daily(self):
        rm = RiskManager()
        signal = _buy_signal(
            sl=1.0950,
            tp=1.1150,
            timestamp=_LONDON_TIME,
        )
        rm.validate_signal(signal)
        assert rm.london_trade_count == 1
        rm.reset_daily_tracking()
        assert rm.london_trade_count == 0

    def test_rejected_london_signal_not_counted(self):
        rm = RiskManager()
        signal = _buy_signal(
            pair="GBP/USD",
            sl=1.2650,
            tp=1.2750,
            timestamp=_LONDON_TIME,
        )
        rm.validate_signal(signal)
        assert rm.london_trade_count == 0


class TestIsLondonSession:
    def test_returns_true_during_london(self):
        rm = RiskManager()
        assert rm.is_london_session(_LONDON_TIME) is True

    def test_returns_false_outside_london(self):
        rm = RiskManager()
        assert rm.is_london_session(_OUTSIDE_LONDON_TIME) is False

    def test_uses_provided_datetime(self):
        rm = RiskManager()
        t = datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc)
        assert rm.is_london_session(t) is True

    def test_custom_london_hours(self):
        cfg = LondonSessionConfig(start_hour=9, end_hour=13)
        rm = RiskManager(london_config=cfg)
        early = datetime(2026, 4, 23, 8, 30, tzinfo=timezone.utc)
        mid = datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc)
        late = datetime(2026, 4, 23, 14, 0, tzinfo=timezone.utc)
        assert rm.is_london_session(early) is False
        assert rm.is_london_session(mid) is True
        assert rm.is_london_session(late) is False


class TestDisabledLondonConfig:
    def test_no_restrictions_when_config_empty(self):
        cfg = LondonSessionConfig(
            blocked_pair_prefixes=(),
            min_risk_reward=1.5,
            size_multiplier=1.0,
        )
        rm = RiskManager(london_config=cfg)
        signal = _buy_signal(
            pair="GBP/USD",
            entry=1.2600,
            sl=1.2650,
            tp=1.2450,
            timestamp=_LONDON_TIME,
        )
        decision = rm.validate_signal(signal)
        assert decision.action == RiskAction.ALLOW

        london_size = rm.calculate_position_size(
            _buy_signal(entry=1.1000, sl=1.0950, timestamp=_LONDON_TIME)
        )
        outside_size = rm.calculate_position_size(
            _buy_signal(entry=1.1000, sl=1.0950, timestamp=_OUTSIDE_LONDON_TIME)
        )
        assert london_size == outside_size
