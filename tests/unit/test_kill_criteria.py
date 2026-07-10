"""Tests for policy/kill_criteria.py — KillCriteriaChecker.

Phase 1c of the Brain + Behavioral Policy Consolidation sprint
(2026-07-10). Covers the global-criteria floor (spread + macro stub),
the per-strategy overrides (min_confluence, adx_range, session_window),
the any_triggered helper, the evidence-string contract, and the
midnight wrap-around semantics for the session window.
"""

from __future__ import annotations

import pytest

from core.conviction import KillCriterion
from policy.kill_criteria import KillCriteriaChecker


# ---------------------------------------------------------------------------
# Spread criterion (global)
# ---------------------------------------------------------------------------


class TestSpreadCriterion:
    """Global spread cap: ``spread_bps > max_spread_bps`` → triggered."""

    def test_spread_pass(self):
        """spread 1.5 with default max 2.0 → not triggered."""
        checker = KillCriteriaChecker()
        results = checker.check({"symbol": "GBPUSD", "spread_bps": 1.5, "hour_utc": 10})

        spread = next(r for r in results if r.name == "spread")
        assert spread.triggered is False
        assert spread.value == pytest.approx(1.5)
        assert spread.threshold == pytest.approx(2.0)

    def test_spread_fail(self):
        """spread 3.0 with default max 2.0 → triggered."""
        checker = KillCriteriaChecker()
        results = checker.check({"symbol": "GBPUSD", "spread_bps": 3.0, "hour_utc": 10})

        spread = next(r for r in results if r.name == "spread")
        assert spread.triggered is True
        assert spread.value == pytest.approx(3.0)
        assert spread.threshold == pytest.approx(2.0)

    def test_spread_boundary_exact_max_passes(self):
        """spread == max_spread_bps is NOT triggered (strict >)."""
        checker = KillCriteriaChecker(global_config={"max_spread_bps": 2.0})
        results = checker.check({"symbol": "GBPUSD", "spread_bps": 2.0, "hour_utc": 10})

        spread = next(r for r in results if r.name == "spread")
        assert spread.triggered is False

    def test_spread_custom_max_from_global_config(self):
        """global_config override lowers the cap → small spread still triggers."""
        checker = KillCriteriaChecker(global_config={"max_spread_bps": 1.0})
        results = checker.check({"symbol": "GBPUSD", "spread_bps": 1.5, "hour_utc": 10})

        spread = next(r for r in results if r.name == "spread")
        assert spread.triggered is True
        assert spread.threshold == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Macro event buffer (stub)
# ---------------------------------------------------------------------------


class TestMacroEventBufferStub:
    """Macro-event buffer is a stub: always passes with the documented evidence."""

    def test_macro_buffer_stub_always_passes(self):
        """No context combination triggers the macro buffer stub."""
        checker = KillCriteriaChecker()
        # Try several context shapes — the stub should always pass.
        for ctx in (
            {"symbol": "GBPUSD", "spread_bps": 1.0, "hour_utc": 0},
            {"symbol": "USDJPY", "spread_bps": 5.0, "hour_utc": 23},
            {"symbol": "EURUSD", "spread_bps": 0.5, "hour_utc": 12},
        ):
            results = checker.check(ctx)
            macro = next(r for r in results if r.name == "macro_event_buffer")
            assert macro.triggered is False
            assert macro.evidence == "News feed not integrated"


# ---------------------------------------------------------------------------
# ADX range criterion (per-strategy)
# ---------------------------------------------------------------------------


class TestAdxRangeCriterion:
    """``adx_range = [lo, hi]`` from strategy_config; out of range → triggered."""

    def test_adx_in_range(self):
        """adx 30 within [20, 50] → not triggered."""
        checker = KillCriteriaChecker(
            strategy_config={"adx_range": [20.0, 50.0]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 30.0,
                "strategy_name": "srmr_plus",
            }
        )
        adx = next(r for r in results if r.name == "adx_range")
        assert adx.triggered is False
        assert adx.value == pytest.approx(30.0)
        assert adx.threshold == pytest.approx(20.0)

    def test_adx_below_range(self):
        """adx 15 below [20, 50] → triggered with "below" evidence."""
        checker = KillCriteriaChecker(
            strategy_config={"adx_range": [20.0, 50.0]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 15.0,
                "strategy_name": "srmr_plus",
            }
        )
        adx = next(r for r in results if r.name == "adx_range")
        assert adx.triggered is True
        assert adx.value == pytest.approx(15.0)
        assert adx.threshold == pytest.approx(20.0)
        assert "below range" in adx.evidence
        assert "[20.0, 50.0]" in adx.evidence
        assert "srmr_plus" in adx.evidence

    def test_adx_above_range(self):
        """adx 60 above [20, 50] → triggered with "above" evidence."""
        checker = KillCriteriaChecker(
            strategy_config={"adx_range": [20.0, 50.0]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 60.0,
                "strategy_name": "srmr_plus",
            }
        )
        adx = next(r for r in results if r.name == "adx_range")
        assert adx.triggered is True
        assert adx.value == pytest.approx(60.0)
        assert "above range" in adx.evidence
        assert "[20.0, 50.0]" in adx.evidence

    def test_adx_at_lower_boundary_passes(self):
        """adx exactly at lo (20.0) is in-range (closed interval)."""
        checker = KillCriteriaChecker(
            strategy_config={"adx_range": [20.0, 50.0]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 20.0,
                "strategy_name": "srmr_plus",
            }
        )
        adx = next(r for r in results if r.name == "adx_range")
        assert adx.triggered is False

    def test_adx_at_upper_boundary_passes(self):
        """adx exactly at hi (50.0) is in-range (closed interval)."""
        checker = KillCriteriaChecker(
            strategy_config={"adx_range": [20.0, 50.0]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 50.0,
                "strategy_name": "srmr_plus",
            }
        )
        adx = next(r for r in results if r.name == "adx_range")
        assert adx.triggered is False


# ---------------------------------------------------------------------------
# Confluence criterion (per-strategy)
# ---------------------------------------------------------------------------


class TestConfluenceCriterion:
    """``min_confluence`` from strategy_config; below the minimum → triggered."""

    def test_confluence_above_min(self):
        """score 0.8, min 0.6 → not triggered."""
        checker = KillCriteriaChecker(
            strategy_config={"min_confluence": 0.6}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "confluence_score": 0.8,
                "strategy_name": "srmr_plus",
            }
        )
        conf = next(r for r in results if r.name == "min_confluence")
        assert conf.triggered is False
        assert conf.value == pytest.approx(0.8)
        assert conf.threshold == pytest.approx(0.6)

    def test_confluence_below_min(self):
        """score 0.4, min 0.6 → triggered."""
        checker = KillCriteriaChecker(
            strategy_config={"min_confluence": 0.6}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "confluence_score": 0.4,
                "strategy_name": "srmr_plus",
            }
        )
        conf = next(r for r in results if r.name == "min_confluence")
        assert conf.triggered is True
        assert conf.value == pytest.approx(0.4)
        assert conf.threshold == pytest.approx(0.6)
        assert "below minimum" in conf.evidence
        assert "srmr_plus" in conf.evidence

    def test_confluence_exact_min_passes(self):
        """score == min_confluence is NOT triggered (strict <)."""
        checker = KillCriteriaChecker(
            strategy_config={"min_confluence": 0.6}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "confluence_score": 0.6,
                "strategy_name": "srmr_plus",
            }
        )
        conf = next(r for r in results if r.name == "min_confluence")
        assert conf.triggered is False


# ---------------------------------------------------------------------------
# Session window criterion (per-strategy)
# ---------------------------------------------------------------------------


class TestSessionWindowCriterion:
    """``session_window = [start, end]`` UTC; outside → triggered.

    Wrap-around (start > end) is allowed: e.g. ``[22, 6]`` covers the
    Asia-London overlap. Half-open interval — the end hour is OUT.
    """

    def test_session_in_window(self):
        """hour 10 within [8, 17] → not triggered."""
        checker = KillCriteriaChecker(
            strategy_config={"session_window": [8, 17]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "strategy_name": "srmr_plus",
            }
        )
        sess = next(r for r in results if r.name == "session_window")
        assert sess.triggered is False
        assert sess.value == pytest.approx(10.0)
        assert sess.threshold == pytest.approx(8.0)

    def test_session_outside_window(self):
        """hour 23 outside [8, 17] → triggered."""
        checker = KillCriteriaChecker(
            strategy_config={"session_window": [8, 17]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 23,
                "strategy_name": "srmr_plus",
            }
        )
        sess = next(r for r in results if r.name == "session_window")
        assert sess.triggered is True
        assert sess.value == pytest.approx(23.0)
        assert sess.threshold == pytest.approx(8.0)
        assert "outside window" in sess.evidence
        assert "[8, 17]" in sess.evidence
        assert "srmr_plus" in sess.evidence

    def test_session_wrap_midnight(self):
        """hour 2 within [22, 6] (wrap) → not triggered."""
        checker = KillCriteriaChecker(
            strategy_config={"session_window": [22, 6]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 2,
                "strategy_name": "srmr_plus",
            }
        )
        sess = next(r for r in results if r.name == "session_window")
        assert sess.triggered is False

    def test_session_wrap_midnight_outside_before_start(self):
        """hour 21 outside [22, 6] (before the wrap window opens) → triggered."""
        checker = KillCriteriaChecker(
            strategy_config={"session_window": [22, 6]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 21,
                "strategy_name": "srmr_plus",
            }
        )
        sess = next(r for r in results if r.name == "session_window")
        assert sess.triggered is True

    def test_session_wrap_midnight_at_start_passes(self):
        """hour 22 exactly at the start of [22, 6] → in (inclusive)."""
        checker = KillCriteriaChecker(
            strategy_config={"session_window": [22, 6]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 22,
                "strategy_name": "srmr_plus",
            }
        )
        sess = next(r for r in results if r.name == "session_window")
        assert sess.triggered is False

    def test_session_at_end_hour_is_outside(self):
        """hour 17 with window [8, 17] is OUT (half-open interval)."""
        checker = KillCriteriaChecker(
            strategy_config={"session_window": [8, 17]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 17,
                "strategy_name": "srmr_plus",
            }
        )
        sess = next(r for r in results if r.name == "session_window")
        assert sess.triggered is True


# ---------------------------------------------------------------------------
# Strategy config selection
# ---------------------------------------------------------------------------


class TestStrategyConfigSelection:
    """Per-strategy criteria only run when the corresponding key is present."""

    def test_no_strategy_config_only_global(self):
        """strategy_config=None → only spread + macro_buffer are checked."""
        checker = KillCriteriaChecker()
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 30.0,
                "confluence_score": 0.8,
            }
        )
        names = {r.name for r in results}
        assert names == {"spread", "macro_event_buffer"}

    def test_empty_strategy_config_only_global(self):
        """strategy_config={} (empty dict) is treated like None."""
        checker = KillCriteriaChecker(strategy_config={})
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 30.0,
                "confluence_score": 0.8,
            }
        )
        names = {r.name for r in results}
        assert names == {"spread", "macro_event_buffer"}

    def test_partial_strategy_config_runs_only_configured(self):
        """Only ``adx_range`` set → confluence + session are skipped."""
        checker = KillCriteriaChecker(
            strategy_config={"adx_range": [20.0, 50.0]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 23,
                "adx": 30.0,
                "confluence_score": 0.4,
                "strategy_name": "srmr_plus",
            }
        )
        names = {r.name for r in results}
        # Note: confluence_score=0.4 is below typical min; with no
        # min_confluence configured the confluence criterion is
        # omitted, so it must not appear in results at all.
        assert names == {"spread", "macro_event_buffer", "adx_range"}

    def test_full_strategy_config_runs_all_per_strategy(self):
        """All three per-strategy keys → all three per-strategy criteria."""
        checker = KillCriteriaChecker(
            strategy_config={
                "min_confluence": 0.6,
                "adx_range": [20.0, 50.0],
                "session_window": [8, 17],
            }
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 30.0,
                "confluence_score": 0.8,
                "strategy_name": "srmr_plus",
            }
        )
        names = {r.name for r in results}
        assert names == {
            "spread",
            "macro_event_buffer",
            "min_confluence",
            "adx_range",
            "session_window",
        }


# ---------------------------------------------------------------------------
# any_triggered helper
# ---------------------------------------------------------------------------


class TestAnyTriggeredHelper:
    """Static helper that returns True iff any criterion has triggered=True."""

    def test_any_triggered_helper(self):
        """Mix of pass/fail → True (at least one triggered)."""
        results = [
            KillCriterion(name="spread", triggered=False, value=1.0, threshold=2.0, evidence="ok"),
            KillCriterion(name="adx_range", triggered=True, value=15.0, threshold=20.0, evidence="low"),
            KillCriterion(name="session_window", triggered=False, value=10.0, threshold=8.0, evidence="ok"),
        ]
        assert KillCriteriaChecker.any_triggered(results) is True

    def test_any_triggered_all_pass_returns_false(self):
        """All criteria pass → False."""
        results = [
            KillCriterion(name="spread", triggered=False, value=1.0, threshold=2.0, evidence="ok"),
            KillCriterion(name="macro_event_buffer", triggered=False, value=0.0, threshold=0.0, evidence="ok"),
            KillCriterion(name="adx_range", triggered=False, value=30.0, threshold=20.0, evidence="ok"),
        ]
        assert KillCriteriaChecker.any_triggered(results) is False

    def test_any_triggered_empty_list_returns_false(self):
        """Empty results → False (vacuously)."""
        assert KillCriteriaChecker.any_triggered([]) is False

    def test_any_triggered_single_triggered(self):
        """Single triggered criterion in a list of one → True."""
        results = [
            KillCriterion(name="spread", triggered=True, value=5.0, threshold=2.0, evidence="wide"),
        ]
        assert KillCriteriaChecker.any_triggered(results) is True


# ---------------------------------------------------------------------------
# "All pass" full evaluation
# ---------------------------------------------------------------------------


class TestAllPassFullEvaluation:
    """A clean context produces a result list with no triggered=True anywhere."""

    def test_all_pass_returns_empty_triggered(self):
        """No KillCriterion in the returned list has triggered=True."""
        checker = KillCriteriaChecker(
            strategy_config={
                "min_confluence": 0.6,
                "adx_range": [20.0, 50.0],
                "session_window": [8, 17],
            }
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 30.0,
                "confluence_score": 0.8,
                "strategy_name": "srmr_plus",
            }
        )

        assert len(results) == 5
        triggered_names = [r.name for r in results if r.triggered]
        assert triggered_names == []
        assert KillCriteriaChecker.any_triggered(results) is False

    def test_check_returns_list_of_kill_criterion(self):
        """Every entry in the returned list is a KillCriterion instance."""
        checker = KillCriteriaChecker()
        results = checker.check({"symbol": "GBPUSD", "spread_bps": 1.0, "hour_utc": 10})
        assert len(results) >= 1
        for r in results:
            assert isinstance(r, KillCriterion)
            assert isinstance(r.name, str)
            assert isinstance(r.triggered, bool)


# ---------------------------------------------------------------------------
# Evidence string contract
# ---------------------------------------------------------------------------


class TestEvidenceStrings:
    """Evidence strings include the actual measured value and symbol/strategy."""

    def test_evidence_strings_include_values(self):
        """Each evidence string contains the measured value and identifying name."""
        checker = KillCriteriaChecker(
            strategy_config={
                "min_confluence": 0.6,
                "adx_range": [20.0, 50.0],
                "session_window": [8, 17],
            }
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 3.2,
                "hour_utc": 23,
                "adx": 18.5,
                "confluence_score": 0.4,
                "strategy_name": "srmr_plus",
            }
        )

        by_name = {r.name: r for r in results}

        # Spec example: "Spread 3.2 bps exceeds max 2.0 bps for GBPUSD"
        spread_evidence = by_name["spread"].evidence
        assert "3.2" in spread_evidence
        assert "2.0" in spread_evidence
        assert "GBPUSD" in spread_evidence

        # Spec example: "ADX 18.5 below range [20.0, 50.0] for strategy srmr_plus"
        adx_evidence = by_name["adx_range"].evidence
        assert "18.5" in adx_evidence
        assert "20.0" in adx_evidence
        assert "50.0" in adx_evidence
        assert "srmr_plus" in adx_evidence

        # Spec example: "Hour 23 UTC outside window [8, 17] for strategy srmr_plus"
        sess_evidence = by_name["session_window"].evidence
        assert "23" in sess_evidence
        assert "8, 17" in sess_evidence
        assert "srmr_plus" in sess_evidence

        # Confluence evidence must include the score and strategy.
        conf_evidence = by_name["min_confluence"].evidence
        assert "0.4" in conf_evidence
        assert "srmr_plus" in conf_evidence

    def test_evidence_unknown_strategy_falls_back_to_unknown(self):
        """When strategy_name is absent, evidence says 'unknown'."""
        checker = KillCriteriaChecker(
            strategy_config={"adx_range": [20.0, 50.0]}
        )
        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 15.0,
                # no strategy_name
            }
        )
        adx = next(r for r in results if r.name == "adx_range")
        assert adx.triggered is True
        assert "unknown" in adx.evidence


# ---------------------------------------------------------------------------
# Defaults + configuration
# ---------------------------------------------------------------------------


class TestDefaultsAndConfig:
    """Defaults are applied when the constructor configs are absent/partial."""

    def test_default_max_spread_is_two_bps(self):
        """Constructor without global_config uses max_spread_bps = 2.0."""
        checker = KillCriteriaChecker()
        assert checker.max_spread_bps == pytest.approx(2.0)

    def test_default_macro_buffer_is_thirty_minutes(self):
        """Constructor without global_config uses macro_event_buffer_minutes = 30."""
        checker = KillCriteriaChecker()
        assert checker.macro_event_buffer_minutes == 30

    def test_global_config_partial_override(self):
        """Only the keys present in global_config are overridden; others keep defaults."""
        checker = KillCriteriaChecker(global_config={"max_spread_bps": 1.5})
        assert checker.max_spread_bps == pytest.approx(1.5)
        # macro_event_buffer_minutes keeps its default of 30
        assert checker.macro_event_buffer_minutes == 30

    def test_strategy_config_isolated_from_caller(self):
        """Mutating the caller's strategy_config dict afterwards does not
        affect the checker's behavior."""
        original = {"adx_range": [20.0, 50.0]}
        checker = KillCriteriaChecker(strategy_config=original)
        # Caller mutates their dict afterwards.
        original["adx_range"] = [10.0, 12.0]
        original["min_confluence"] = 0.99  # adds a new key too

        results = checker.check(
            {
                "symbol": "GBPUSD",
                "spread_bps": 1.0,
                "hour_utc": 10,
                "adx": 30.0,
                "confluence_score": 0.8,
                "strategy_name": "srmr_plus",
            }
        )
        names = {r.name for r in results}
        # The checker should still see only adx_range — its copy was
        # taken at construction time and the caller's later mutations
        # must not leak through.
        assert "min_confluence" not in names
        adx = next(r for r in results if r.name == "adx_range")
        # The threshold captured at construction was 20.0, not 10.0.
        assert adx.threshold == pytest.approx(20.0)