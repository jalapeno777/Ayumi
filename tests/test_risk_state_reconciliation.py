"""Sprint 024 (card 591cbfe6) tests — risk_state_blend.json ↔ risk_guard_state.json reconciliation.

Both files exist for historical reasons and have drifted in production.
Sprint 024 adds a reconciliation helper that reports divergence so an
operator can decide which file to trust for a given run.

The reconciliation is READ-ONLY — it never overwrites either file.
"""

from __future__ import annotations

import json
import logging

from adapters.ctrader.risk_state_reconciliation import (
    DEFAULT_BLEND_PATH,
    DEFAULT_RISK_GUARD_PATH,
    reconcile_risk_state_dicts,
    reconcile_risk_states,
)

# ── Fixture data ─────────────────────────────────────────────────────────────


def _matched_blend() -> dict:
    """A BLEND-state dict that matches the RISK_GUARD-state below."""
    return {
        "account_balance": 10000.0,
        "peak_balance": 10400.0,
        "daily_risk_used": 0.5,
        "open_risk": 100.0,
        "circuit_breaker": {
            "halted": False,
            "halted_until": None,
            "halt_reason": "",
            "recent_trades": [],
            "daily_dd_pct": 0.0,
            "account_dd_pct": 0.0,
        },
    }


def _matched_risk_guard() -> dict:
    """A RISK_GUARD-state dict that matches the BLEND-state above."""
    return {
        "peak_balance": 10400.0,
        "current_balance": 10000.0,
        "daily_start_balance": 10000.0,
        "current_day": "2026-08-21",
        "daily_trade_count": 0,
        "total_trades": 0,
        "circuit_breaker_triggered": False,
        "blocked_until": None,
        "last_save_ts": "2026-08-21T23:00:00+00:00",
    }


# ── Happy path ───────────────────────────────────────────────────────────────


class TestMatchedStates:
    """When both states agree, reconciliation reports matched=True with no divergences."""

    def test_identical_states_match(self):
        result = reconcile_risk_state_dicts(_matched_blend(), _matched_risk_guard())
        assert result.matched is True
        assert result.divergences == []
        assert result.divergent is False  # inverse property

    def test_balances_and_peak_round_trip(self):
        result = reconcile_risk_state_dicts(_matched_blend(), _matched_risk_guard())
        assert result.blend_balance == 10000.0  # noqa: PLR2004
        assert result.risk_guard_balance == 10000.0  # noqa: PLR2004
        assert result.blend_peak_balance == 10400.0  # noqa: PLR2004
        assert result.risk_guard_peak_balance == 10400.0  # noqa: PLR2004

    def test_circuit_breaker_round_trip(self):
        result = reconcile_risk_state_dicts(_matched_blend(), _matched_risk_guard())
        assert result.blend_circuit_halted is False
        assert result.risk_guard_circuit_triggered is False


# ── Divergent fixtures (the AC's "with divergent fixtures" requirement) ─────


class TestDivergentFixtures:
    """Each test class exercises one divergent case — proving the
    reconciliation catches every class of drift."""

    def test_balance_drift_detected(self):
        """Account balance differs between files — surface in divergences."""
        blend = _matched_blend()
        risk_guard = _matched_risk_guard()
        # BLEND sees a balance update the RISK_GUARD hasn't picked up yet
        blend["account_balance"] = 10500.0

        result = reconcile_risk_state_dicts(blend, risk_guard)
        assert result.matched is False
        assert any("balance_drift" in d for d in result.divergences)
        # delta is +500.00 (blend is fresher)
        assert any("+500.00" in d for d in result.divergences)

    def test_peak_balance_drift_detected(self):
        """Peak balance differs — secondary signal of stale state."""
        blend = _matched_blend()
        risk_guard = _matched_risk_guard()
        risk_guard["peak_balance"] = 10300.0  # BLEND is fresher at 10400

        result = reconcile_risk_state_dicts(blend, risk_guard)
        assert result.matched is False
        assert any("peak_balance_drift" in d for d in result.divergences)

    def test_circuit_breaker_mismatch_detected(self):
        """CRITICAL: one file says halted, the other says not — safety issue."""
        blend = _matched_blend()
        risk_guard = _matched_risk_guard()
        blend["circuit_breaker"]["halted"] = True  # BLEND says HALT

        result = reconcile_risk_state_dicts(blend, risk_guard)
        assert result.matched is False
        assert any("circuit_breaker_mismatch" in d for d in result.divergences)
        # Divergence message must include both states
        msg = next(d for d in result.divergences if "circuit_breaker_mismatch" in d)
        assert "blend_halted=True" in msg
        assert "risk_guard_triggered=False" in msg

    def test_combined_divergences_reported(self):
        """Multiple drift sources are all reported, not just the first."""
        blend = _matched_blend()
        risk_guard = _matched_risk_guard()
        blend["account_balance"] = 9950.0  # balance drift
        blend["peak_balance"] = 10450.0  # peak drift
        blend["circuit_breaker"]["halted"] = True  # cb mismatch

        result = reconcile_risk_state_dicts(blend, risk_guard)
        assert result.matched is False
        assert len(result.divergences) == 3  # noqa: PLR2004

    def test_within_tolerance_balance_drift_ignored(self):
        """A 1-cent drift (below tolerance) is NOT reported."""
        blend = _matched_blend()
        risk_guard = _matched_risk_guard()
        blend["account_balance"] = 10000.005  # half a cent up

        result = reconcile_risk_state_dicts(blend, risk_guard)
        # 0.5 cents is within the 1-cent tolerance
        assert result.matched is True


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Defensive tests for missing fields, partial files, and corruption."""

    def test_empty_blend_uses_risk_guard(self):
        """BLEND file missing → trust_blend=False (prefer RISK_GUARD)."""
        result = reconcile_risk_state_dicts({}, _matched_risk_guard())
        # No divergences because there's no data to compare
        assert result.matched is True
        assert result.trust_blend is False

    def test_empty_risk_guard_with_blend(self):
        """RISK_GUARD file missing → trust_blend=True (only BLEND has data)."""
        result = reconcile_risk_state_dicts(_matched_blend(), {})
        assert result.matched is True
        assert result.trust_blend is True

    def test_both_empty(self):
        """Both files empty → matched=True, no divergences, trust_blend=False."""
        result = reconcile_risk_state_dicts({}, {})
        assert result.matched is True
        assert result.trust_blend is False
        assert result.divergences == []

    def test_missing_balance_field_does_not_crash(self):
        """Files with no balance field don't raise; comparison is skipped."""
        blend = {"circuit_breaker": {"halted": False}}
        risk_guard = {"circuit_breaker_triggered": False}
        result = reconcile_risk_state_dicts(blend, risk_guard)
        assert result.matched is True
        assert result.blend_balance is None
        assert result.risk_guard_balance is None

    def test_none_values_treated_as_missing(self):
        """Explicit None is treated the same as absent."""
        blend = {"account_balance": None, "peak_balance": None}
        risk_guard = {"current_balance": None, "peak_balance": None}
        result = reconcile_risk_state_dicts(blend, risk_guard)
        assert result.matched is True


# ── Disk-based API ───────────────────────────────────────────────────────────


class TestDiskReconciliation:
    """Test the file-path-based API used by operator tooling."""

    def test_reconcile_from_disk(self, tmp_path):
        """Load both files from disk and reconcile them."""
        blend_path = tmp_path / "risk_state_blend.json"
        guard_path = tmp_path / "risk_guard_state.json"
        blend_path.write_text(json.dumps(_matched_blend()))
        guard_path.write_text(json.dumps(_matched_risk_guard()))

        result = reconcile_risk_states(blend_path, guard_path)
        assert result.matched is True

    def test_missing_blend_file_treated_as_empty(self, tmp_path):
        """A missing BLEND file is treated as empty (no error)."""
        guard_path = tmp_path / "risk_guard_state.json"
        guard_path.write_text(json.dumps(_matched_risk_guard()))
        blend_path = tmp_path / "does_not_exist.json"

        result = reconcile_risk_states(blend_path, guard_path)
        assert result.matched is True
        assert result.trust_blend is False

    def test_corrupt_blend_file_logs_warning(self, tmp_path, caplog):
        """A corrupt BLEND file logs a warning and is treated as empty."""
        guard_path = tmp_path / "risk_guard_state.json"
        guard_path.write_text(json.dumps(_matched_risk_guard()))
        blend_path = tmp_path / "risk_state_blend.json"
        blend_path.write_text("NOT VALID JSON {{{{")

        with caplog.at_level(logging.WARNING, logger="ayumi.risk_state_reconciliation"):
            result = reconcile_risk_states(blend_path, guard_path)
        assert any("unreadable" in rec.message.lower() for rec in caplog.records)
        assert result.matched is True

    def test_default_paths_point_to_known_locations(self):
        """Default paths match the production deployment locations."""
        # The constants are pure strings — verify they reference the
        # known sub-paths so an operator can grep for them.
        assert "risk_state_blend.json" in DEFAULT_BLEND_PATH
        assert "risk_guard_state.json" in DEFAULT_RISK_GUARD_PATH
        # Guard state lives under data/state/, blend under data/
        assert DEFAULT_RISK_GUARD_PATH.startswith("data/state/")
        assert DEFAULT_BLEND_PATH.startswith("data/")


# ── Dataclass shape ──────────────────────────────────────────────────────────


class TestResultDataclass:
    """RiskStateReconciliation serialises cleanly for audit logs."""

    def test_to_dict_includes_all_fields(self):
        result = reconcile_risk_state_dicts(_matched_blend(), _matched_risk_guard())
        as_dict = result.to_dict()
        for key in (
            "matched",
            "divergences",
            "blend_balance",
            "risk_guard_balance",
            "blend_peak_balance",
            "risk_guard_peak_balance",
            "blend_circuit_halted",
            "risk_guard_circuit_triggered",
            "trust_blend",
            "generated_at",
        ):
            assert key in as_dict

    def test_generated_at_is_iso_utc(self):
        """generated_at is a parseable ISO-8601 UTC timestamp."""
        from datetime import datetime

        result = reconcile_risk_state_dicts({}, {})
        ts = datetime.fromisoformat(result.generated_at)
        assert ts.tzinfo is not None  # timezone-aware
