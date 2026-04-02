import unittest
from datetime import datetime, timedelta

from signal_validator import (
    Direction,
    Session,
    Signal,
    SignalValidator,
    Strength,
    ValidatorConfig,
)


def _make_signal(
    *,
    direction=Direction.LONG,
    strength=Strength.STRONG,
    entry_price=1.1000,
    stop_loss=1.0950,
    take_profit=1.1100,
    candle_age_seconds=60.0,
    confluence_count=3,
    has_liquidity_sweep=False,
    has_order_block=False,
    has_fvg=False,
    session=Session.LONDON,
    signal_time=None,
) -> Signal:
    return Signal(
        direction=direction,
        strength=strength,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        signal_time=signal_time or datetime.utcnow(),
        candle_age_seconds=candle_age_seconds,
        confluence_count=confluence_count,
        has_liquidity_sweep=has_liquidity_sweep,
        has_order_block=has_order_block,
        has_fvg=has_fvg,
        session=session,
    )


class TestAcceptancePaths(unittest.TestCase):

    def test_london_session_long_passes(self):
        v = SignalValidator()
        s = _make_signal(session=Session.LONDON, direction=Direction.LONG)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_ny_am_session_long_passes(self):
        v = SignalValidator()
        s = _make_signal(session=Session.NY_AM, direction=Direction.LONG)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_ny_pm_session_long_passes(self):
        v = SignalValidator()
        s = _make_signal(session=Session.NY_PM, direction=Direction.LONG)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_sell_direction_passes(self):
        v = SignalValidator()
        s = _make_signal(direction=Direction.SHORT, entry_price=1.1000,
                         stop_loss=1.1050, take_profit=1.0900)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)


class TestStrengthGate(unittest.TestCase):

    def test_weak_signal_rejected_when_min_moderate(self):
        v = SignalValidator()
        s = _make_signal(strength=Strength.WEAK)
        r = v.validate(s)
        self.assertFalse(r.passed)
        self.assertIn("Strength", r.reason)

    def test_moderate_signal_accepted_when_min_moderate(self):
        v = SignalValidator()
        s = _make_signal(strength=Strength.MODERATE)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_strong_signal_accepted_when_min_moderate(self):
        v = SignalValidator()
        s = _make_signal(strength=Strength.STRONG)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_very_strong_signal_accepted_when_min_moderate(self):
        v = SignalValidator()
        s = _make_signal(strength=Strength.VERY_STRONG)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)


class TestFreshnessGate(unittest.TestCase):

    def test_fresh_signal_passes(self):
        v = SignalValidator()
        s = _make_signal(candle_age_seconds=0)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_signal_at_exact_max_age_passes(self):
        v = SignalValidator()
        s = _make_signal(candle_age_seconds=300.0)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_stale_signal_rejected(self):
        v = SignalValidator()
        s = _make_signal(candle_age_seconds=301.0)
        r = v.validate(s)
        self.assertFalse(r.passed)
        self.assertIn("age", r.reason)


class TestConfluenceGate(unittest.TestCase):

    def test_confluence_at_min_passes(self):
        v = SignalValidator()
        s = _make_signal(confluence_count=2)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_confluence_below_min_rejected(self):
        v = SignalValidator()
        s = _make_signal(confluence_count=1)
        r = v.validate(s)
        self.assertFalse(r.passed)
        self.assertIn("Confluence", r.reason)

    def test_zero_confluence_rejected(self):
        v = SignalValidator()
        s = _make_signal(confluence_count=0)
        r = v.validate(s)
        self.assertFalse(r.passed)


class TestSessionGate(unittest.TestCase):

    def test_outside_session_rejected_when_killzone_required(self):
        v = SignalValidator()
        s = _make_signal(session=Session.OUTSIDE)
        r = v.validate(s)
        self.assertFalse(r.passed)
        self.assertIn("killzone", r.reason)

    def test_outside_session_passes_when_killzone_not_required(self):
        cfg = ValidatorConfig(require_killzone=False)
        v = SignalValidator(config=cfg)
        s = _make_signal(session=Session.OUTSIDE)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)


class TestRiskRewardGate(unittest.TestCase):

    def test_good_rr_passes(self):
        v = SignalValidator()
        s = _make_signal(stop_loss=1.0950, take_profit=1.1100)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_exact_max_sl_tp_ratio_passes(self):
        cfg = ValidatorConfig(max_sl_tp_ratio=0.5)
        v = SignalValidator(config=cfg)
        s = _make_signal(entry_price=1.1000, stop_loss=1.0950, take_profit=1.1100)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_sl_tp_ratio_exceeds_max_rejected(self):
        cfg = ValidatorConfig(max_sl_tp_ratio=0.4)
        v = SignalValidator(config=cfg)
        s = _make_signal(stop_loss=1.0945, take_profit=1.1100)
        r = v.validate(s)
        self.assertFalse(r.passed)
        self.assertIn("ratio", r.reason)

    def test_zero_sl_rejected(self):
        v = SignalValidator()
        s = _make_signal(stop_loss=1.1000, take_profit=1.1100)
        r = v.validate(s)
        self.assertFalse(r.passed)
        self.assertIn("zero risk", r.reason.lower())

    def test_zero_tp_rejected(self):
        v = SignalValidator()
        s = _make_signal(stop_loss=1.0950, take_profit=1.1000)
        r = v.validate(s)
        self.assertFalse(r.passed)
        self.assertIn("zero reward", r.reason.lower())


class TestConfluenceScoring(unittest.TestCase):

    def test_freshness_penalty_applied(self):
        v = SignalValidator()
        s = _make_signal(candle_age_seconds=400, confluence_count=3)
        score = v.confluence_score(s, freshness_penalty=0.5)
        self.assertLess(score, 3.0)

    def test_killzone_bonus_applied(self):
        v = SignalValidator()
        s = _make_signal(session=Session.LONDON, confluence_count=3)
        score = v.confluence_score(s, killzone_bonus=1.0)
        self.assertGreater(score, 3.0)

    def test_combined_penalty_and_bonus(self):
        v = SignalValidator()
        s = _make_signal(candle_age_seconds=400, session=Session.NY_AM, confluence_count=3)
        score = v.confluence_score(s, freshness_penalty=0.5, killzone_bonus=1.0)
        self.assertAlmostEqual(score, 3.5, places=2)

    def test_score_floor_at_zero(self):
        v = SignalValidator()
        s = _make_signal(candle_age_seconds=400, confluence_count=0)
        score = v.confluence_score(s, freshness_penalty=10.0)
        self.assertGreaterEqual(score, 0.0)


class TestBatchValidation(unittest.TestCase):

    def test_batch_returns_all_results(self):
        v = SignalValidator()
        good = _make_signal()
        bad = _make_signal(strength=Strength.WEAK)
        results = v.validate_batch([good, bad])
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].passed)
        self.assertFalse(results[1].passed)


class TestFiltering(unittest.TestCase):

    def test_filter_keeps_only_passing_signals(self):
        v = SignalValidator()
        signals = [
            _make_signal(),
            _make_signal(strength=Strength.WEAK),
            _make_signal(),
        ]
        filtered = v.filter(signals)
        self.assertEqual(len(filtered), 2)


class TestCustomConfig(unittest.TestCase):

    def test_custom_min_strength(self):
        cfg = ValidatorConfig(min_strength=Strength.STRONG)
        v = SignalValidator(config=cfg)
        s = _make_signal(strength=Strength.MODERATE)
        r = v.validate(s)
        self.assertFalse(r.passed)

    def test_custom_max_candle_age(self):
        cfg = ValidatorConfig(max_candle_age_seconds=10.0)
        v = SignalValidator(config=cfg)
        s = _make_signal(candle_age_seconds=15.0)
        r = v.validate(s)
        self.assertFalse(r.passed)

    def test_custom_min_confluence(self):
        cfg = ValidatorConfig(min_confluence=5)
        v = SignalValidator(config=cfg)
        s = _make_signal(confluence_count=3)
        r = v.validate(s)
        self.assertFalse(r.passed)


class TestConfluenceCounting(unittest.TestCase):

    def test_count_with_boolean_flags(self):
        v = SignalValidator()
        s = _make_signal(confluence_count=1, has_liquidity_sweep=True,
                         has_order_block=True, has_fvg=True)
        count = v.count_confluences(s)
        self.assertEqual(count, 4)

    def test_count_without_boolean_flags(self):
        v = SignalValidator()
        s = _make_signal(confluence_count=2)
        count = v.count_confluences(s)
        self.assertEqual(count, 2)

    def test_count_with_partial_flags(self):
        v = SignalValidator()
        s = _make_signal(confluence_count=2, has_order_block=True)
        count = v.count_confluences(s)
        self.assertEqual(count, 3)


class TestEdgeCases(unittest.TestCase):

    def test_just_over_max_candle_age_rejected(self):
        v = SignalValidator()
        s = _make_signal(candle_age_seconds=300.001)
        r = v.validate(s)
        self.assertFalse(r.passed)
        self.assertIn("age", r.reason)

    def test_short_direction_risk_reward(self):
        v = SignalValidator()
        s = _make_signal(direction=Direction.SHORT, entry_price=1.1000,
                         stop_loss=1.1050, take_profit=1.0800)
        r = v.validate(s)
        self.assertTrue(r.passed, r.reason)

    def test_default_config_values(self):
        cfg = ValidatorConfig()
        self.assertEqual(cfg.min_strength, Strength.MODERATE)
        self.assertEqual(cfg.max_candle_age_seconds, 300.0)
        self.assertEqual(cfg.min_confluence, 2)
        self.assertTrue(cfg.require_killzone)
        self.assertEqual(cfg.max_sl_tp_ratio, 0.5)

    def test_empty_batch_returns_empty(self):
        v = SignalValidator()
        results = v.validate_batch([])
        self.assertEqual(len(results), 0)

    def test_validation_result_contains_signal(self):
        v = SignalValidator()
        s = _make_signal()
        r = v.validate(s)
        self.assertIs(r.signal, s)

    def test_confluence_score_no_penalty_no_bonus(self):
        v = SignalValidator()
        s = _make_signal(candle_age_seconds=10, session=Session.OUTSIDE, confluence_count=5)
        score = v.confluence_score(s, freshness_penalty=0.1, killzone_bonus=0.2)
        self.assertEqual(score, 5.0)

    def test_first_failing_gate_short_circuits(self):
        v = SignalValidator()
        s = _make_signal(strength=Strength.WEAK, candle_age_seconds=9999, confluence_count=0,
                         session=Session.OUTSIDE)
        r = v.validate(s)
        self.assertFalse(r.passed)
        self.assertIn("Strength", r.reason)


if __name__ == "__main__":
    unittest.main()
