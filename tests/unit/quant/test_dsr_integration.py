"""Tests for quant.dsr_integration — DSR post-WF integration layer.

Covers:

- ``annotate_wf_results_with_dsr`` adds the required fields, doesn't mutate
  the input, handles non-viable entries safely.
- ``generate_tier_ranking`` groups entries by tier and produces the
  documented summary.
- Mock WF data with deterministic Sharpe → known DSR p-value via
  :func:`quant.oos_gate.deflated_sharpe_ratio`.
- ``run_dsr_gate_on_report`` reads JSONL correctly and handles invalid
  lines.
- Edge cases: empty results list, zero-trade streams, missing fields.
"""

from __future__ import annotations  # noqa: I001

import json
from pathlib import Path

import pytest

from quant.dsr_integration import (
    DEFAULT_N_INDEPENDENT_TRIALS,
    TIER_THRESHOLDS,
    _MIN_TRADES_FLOOR,
    annotate_wf_results_with_dsr,
    estimate_n_obs,
    generate_tier_ranking,
    load_wf_report,
    run_dsr_gate_on_report,
    write_combined_annotated_report,
)
from quant.oos_gate import (
    TIER_A_PRODUCTION,
    TIER_B_DEMO,
    TIER_C_PAPER,
    deflated_sharpe_ratio,
    expected_max_sharpe,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    pair: str = "GBPUSD",
    timeframe: str = "H1",
    mean_sharpe: float = 5.0,
    mean_trade_count: float = 50.0,
    windows_passed: int = 5,
    windows_total: int = 5,
    go_nogo: bool = True,
    mean_win_rate: float = 0.65,
    mean_profit_factor: float = 2.0,
) -> dict:
    """Build a minimal WF JSONL entry."""
    return {
        "pair": pair,
        "timeframe": timeframe,
        "data_path": f"data/forex/historical/{pair}_{timeframe}.csv",
        "timestamp": "2026-07-08T16:00:00+00:00",
        "status": "complete",
        "optuna_best_value": 100.0,
        "optuna_n_trials": 30,
        "best_params": {"ema_period": 21},
        "windows_passed": windows_passed,
        "windows_total": windows_total,
        "go_nogo": go_nogo,
        "mean_profit_factor": mean_profit_factor,
        "mean_win_rate": mean_win_rate,
        "mean_sharpe": mean_sharpe,
        "mean_max_drawdown": 0.02,
        "mean_trade_count": mean_trade_count,
        "mean_total_pnl": 1000.0,
    }


# ---------------------------------------------------------------------------
# Tier thresholds sanity
# ---------------------------------------------------------------------------


class TestTierThresholds:
    """The DSR-integration tier table must mirror ``oos_gate.TierConfig``."""

    def test_tier_thresholds_aligned_with_oos_gate(self):
        """Tier definitions must match oos_gate production/demo/paper tiers."""
        by_name = {t.tier: t for t in TIER_THRESHOLDS}
        assert by_name["A"].min_windows_passed == TIER_A_PRODUCTION.min_windows_passed
        assert by_name["A"].min_aggregate_sharpe == TIER_A_PRODUCTION.min_aggregate_sharpe
        assert by_name["A"].dsr_alpha == TIER_A_PRODUCTION.dsr_alpha
        assert by_name["B"].min_windows_passed == TIER_B_DEMO.min_windows_passed
        assert by_name["C"].min_windows_passed == TIER_C_PAPER.min_windows_passed

    def test_tier_definitions_are_strictest_first(self):
        """Tier A must be the most demanding (highest min_sharpe, etc.)."""
        a, b, c = TIER_THRESHOLDS
        assert a.min_aggregate_sharpe >= b.min_aggregate_sharpe
        assert b.min_aggregate_sharpe >= c.min_aggregate_sharpe
        assert a.min_windows_passed >= b.min_windows_passed
        assert b.min_windows_passed >= c.min_windows_passed

    def test_default_n_trials_is_160(self):
        """Default n_independent_trials must match the canonical GateConfig."""
        assert DEFAULT_N_INDEPENDENT_TRIALS == 160


# ---------------------------------------------------------------------------
# estimate_n_obs
# ---------------------------------------------------------------------------


class TestEstimateNObs:
    """estimate_n_obs applies the floor and multiplies trades × windows."""

    def test_basic(self):
        """50 trades × 4 windows → 200, above the floor of 30."""
        entry = _make_entry(mean_trade_count=50.0, windows_passed=4)
        assert estimate_n_obs(entry) == 200

    def test_floor_applied(self):
        """5 trades × 2 windows → 10, floored to 30."""
        entry = _make_entry(mean_trade_count=5.0, windows_passed=2)
        assert estimate_n_obs(entry) == _MIN_TRADES_FLOOR

    def test_zero_windows_returns_zero(self):
        """No windows passed → n_obs = 0 (signals non-viability)."""
        entry = _make_entry(mean_trade_count=50.0, windows_passed=0)
        assert estimate_n_obs(entry) == 0

    def test_zero_trades_returns_zero(self):
        """Mean_trade_count = 0 → n_obs = 0 (signals non-viability)."""
        entry = _make_entry(mean_trade_count=0.0, windows_passed=5)
        assert estimate_n_obs(entry) == 0

    def test_missing_fields_returns_zero(self):
        """Empty entry → n_obs = 0."""
        assert estimate_n_obs({}) == 0


# ---------------------------------------------------------------------------
# annotate_wf_results_with_dsr
# ---------------------------------------------------------------------------


class TestAnnotateWfResultsWithDsr:
    """annotate_wf_results_with_dsr must add the documented fields."""

    def test_adds_required_fields(self):
        """Each annotated entry must expose dsr_pvalue + tier + tier_reason."""
        entries = [_make_entry()]
        annotated = annotate_wf_results_with_dsr(entries)
        assert len(annotated) == 1
        e = annotated[0]
        for field in (
            "dsr_pvalue",
            "dsr_n_obs",
            "dsr_n_trials",
            "dsr_expected_max_sr",
            "tier",
            "tier_reason",
            "dsr_viable",
        ):
            assert field in e, f"missing field: {field}"

    def test_does_not_mutate_input(self):
        """The caller's dicts must not be modified in-place."""
        entries = [_make_entry(mean_sharpe=12.0, mean_trade_count=80.0, windows_passed=5)]
        snapshot = json.dumps(entries, sort_keys=True)
        _ = annotate_wf_results_with_dsr(entries)
        # Re-serialize; should match the pre-call snapshot.
        assert json.dumps(entries, sort_keys=True) == snapshot

    def test_preserves_order(self):
        """Output order must match input order."""
        entries = [
            _make_entry(pair="GBPUSD", windows_passed=5, mean_sharpe=10.0),
            _make_entry(pair="USDJPY", windows_passed=3, mean_sharpe=5.0),
            _make_entry(pair="XAUUSD", windows_passed=4, mean_sharpe=7.0),
        ]
        annotated = annotate_wf_results_with_dsr(entries)
        assert [e["pair"] for e in annotated] == ["GBPUSD", "USDJPY", "XAUUSD"]

    def test_high_sharpe_lands_in_tier_a(self):
        """A strong-shuffle, well-populated stream must reach Tier A."""
        entries = [_make_entry(mean_sharpe=10.0, mean_trade_count=80.0, windows_passed=5)]
        annotated = annotate_wf_results_with_dsr(entries)
        assert annotated[0]["tier"] == "A"

    def test_fewer_windows_lands_in_lower_tier(self):
        """4-window streams cannot pass Tier A (5+ required)."""
        entries = [_make_entry(mean_sharpe=10.0, mean_trade_count=80.0, windows_passed=4)]
        annotated = annotate_wf_results_with_dsr(entries)
        assert annotated[0]["tier"] == "B"

    def test_zero_windows_yields_reject(self):
        """A zero-windows entry must be REJECTed, not silently classified."""
        entries = [_make_entry(windows_passed=0, mean_trade_count=50.0, mean_sharpe=5.0)]
        annotated = annotate_wf_results_with_dsr(entries)
        assert annotated[0]["tier"] == "REJECT"
        assert annotated[0]["dsr_viable"] is False
        assert annotated[0]["dsr_pvalue"] == 1.0

    def test_zero_sharpe_yields_reject_without_dsr_call(self):
        """zero-sharpe streams must not crash and must be REJECTed."""
        entries = [_make_entry(mean_sharpe=0.0, mean_trade_count=50.0, windows_passed=5)]
        annotated = annotate_wf_results_with_dsr(entries)
        assert annotated[0]["tier"] == "REJECT"
        # The reason should mention the sharpe is below the top tier's floor.
        assert "sharpe" in annotated[0]["tier_reason"]

    def test_custom_n_trials_propagates(self):
        """Custom n_trials must surface in dsr_n_trials and expected_max_sr."""
        entries = [_make_entry(mean_sharpe=10.0)]
        annotated = annotate_wf_results_with_dsr(entries, n_trials=50)
        assert annotated[0]["dsr_n_trials"] == 50
        assert annotated[0]["dsr_expected_max_sr"] == pytest.approx(expected_max_sharpe(50), rel=1e-9)


# ---------------------------------------------------------------------------
# generate_tier_ranking
# ---------------------------------------------------------------------------


class TestGenerateTierRanking:
    """generate_tier_ranking groups entries by tier and emits a summary."""

    def test_groups_by_tier(self):
        """The 4 buckets must contain the right entries.

        NOTE: DSR is significant only when mean_sharpe >
        ``expected_max_sharpe(n_trials)`` (~2.69 for n_trials=160). So
        every test entry must use sharpe well above that floor.
        """
        entries = [
            _make_entry(pair="A1", windows_passed=5, mean_sharpe=10.0, mean_trade_count=80.0),
            _make_entry(pair="B1", windows_passed=4, mean_sharpe=3.0, mean_trade_count=80.0),
            _make_entry(pair="C1", windows_passed=3, mean_sharpe=3.0, mean_trade_count=80.0),
            _make_entry(pair="X1", windows_passed=0, mean_sharpe=0.0, mean_trade_count=0.0),
        ]
        annotated = annotate_wf_results_with_dsr(entries)
        ranking = generate_tier_ranking(annotated)
        assert [e["pair"] for e in ranking["tier_a"]] == ["A1"]
        assert [e["pair"] for e in ranking["tier_b"]] == ["B1"]
        assert [e["pair"] for e in ranking["tier_c"]] == ["C1"]
        assert [e["pair"] for e in ranking["rejected"]] == ["X1"]

    def test_summary_counts(self):
        """summary counts must equal bucket lengths and total."""
        entries = [
            _make_entry(pair="A1", windows_passed=5, mean_sharpe=10.0, mean_trade_count=80.0),
            _make_entry(pair="A2", windows_passed=5, mean_sharpe=12.0, mean_trade_count=80.0),
            _make_entry(pair="B1", windows_passed=4, mean_sharpe=3.0, mean_trade_count=80.0),
            _make_entry(pair="R1", windows_passed=0, mean_sharpe=0.0, mean_trade_count=0.0),
        ]
        annotated = annotate_wf_results_with_dsr(entries)
        ranking = generate_tier_ranking(annotated)
        s = ranking["summary"]
        assert s["total"] == 4
        assert s["tier_a_count"] == 2
        assert s["tier_b_count"] == 1
        assert s["tier_c_count"] == 0
        assert s["rejected_count"] == 1
        assert s["viable_count"] == 3  # only R1 is non-viable

    def test_empty_input(self):
        """Empty input → all-zero buckets, summary 0/0/0/0."""
        ranking = generate_tier_ranking([])
        assert ranking["tier_a"] == []
        assert ranking["tier_b"] == []
        assert ranking["tier_c"] == []
        assert ranking["rejected"] == []
        assert ranking["summary"] == {
            "total": 0,
            "tier_a_count": 0,
            "tier_b_count": 0,
            "tier_c_count": 0,
            "rejected_count": 0,
            "viable_count": 0,
        }

    def test_unknown_tier_value_becomes_rejected(self):
        """A garbage tier string must be coerced to REJECT (no key error)."""
        annotated = [{"tier": "Z", "dsr_viable": True}]
        ranking = generate_tier_ranking(annotated)
        assert len(ranking["rejected"]) == 1
        assert len(ranking["tier_a"]) == 0


# ---------------------------------------------------------------------------
# Mock WF data → known DSR
# ---------------------------------------------------------------------------


class TestDsrFormulaMath:
    """The DSR p-value we emit must match the production deflated_sharpe_ratio."""

    def test_known_sharpe_to_known_pvalue(self):
        """For a fixed Sharpe/n_obs/n_trials we must match oos_gate exactly."""
        sr = 4.0
        n_obs = 200
        n_trials = 160
        expected = deflated_sharpe_ratio(
            observed_sr=sr,
            n_trials=n_trials,
            n_obs=n_obs,
            skewness=0.0,
            kurtosis_regular=3.0,
        )
        entries = [_make_entry(mean_sharpe=sr, mean_trade_count=40.0, windows_passed=5)]
        annotated = annotate_wf_results_with_dsr(entries, n_trials=n_trials)
        # n_obs = round(40 * 5) = 200 (no floor needed, already > 30).
        assert annotated[0]["dsr_n_obs"] == n_obs
        assert annotated[0]["dsr_pvalue"] == pytest.approx(expected, rel=1e-12)

    def test_high_sharpe_collapses_pvalue_to_near_zero(self):
        """Huge Sharpe with sane n_obs → p-value ~ 0."""
        entries = [_make_entry(mean_sharpe=20.0, mean_trade_count=80.0, windows_passed=5)]
        annotated = annotate_wf_results_with_dsr(entries)
        assert annotated[0]["dsr_pvalue"] < 1e-6
        assert annotated[0]["tier"] == "A"

    def test_marginal_sharpe_likely_fails_dsr(self):
        """A Sharpe barely above the floor but below E[max SR|null] should fail."""
        # E[max SR | null] for n_trials=160 is ~2.69, so SR=2.7 with n_obs=30
        # puts us right at the edge — DSR should fail the alpha=0.05 test.
        entries = [_make_entry(mean_sharpe=2.7, mean_trade_count=10.0, windows_passed=3)]
        annotated = annotate_wf_results_with_dsr(entries)
        # 3 windows passed = Tier C min. Sharpe 2.7 > 0.50 (Tier C floor).
        # DSR depends on p-value: with mean_sharpe 2.7 vs E_max 2.69 and n_obs=30,
        # the z-score is tiny and p ~ 0.5 → fails DSR check (p < 0.10 false).
        # So tier should be REJECT (not Tier C).
        assert annotated[0]["tier"] == "REJECT"
        assert annotated[0]["dsr_pvalue"] > 0.10


# ---------------------------------------------------------------------------
# run_dsr_gate_on_report / load_wf_report
# ---------------------------------------------------------------------------


class TestRunDsrGateOnReport:
    """run_dsr_gate_on_report reads JSONL and produces the documented shape."""

    def test_load_wf_report_parses_jsonl(self, tmp_path: Path):
        """load_wf_report must parse each non-empty line as JSON."""
        report = tmp_path / "wf.jsonl"
        report.write_text(
            "\n".join(json.dumps(_make_entry(pair=p)) for p in ("GBPUSD", "USDJPY"))
            + "\n\n"  # trailing blank line must be ignored
        )
        entries = load_wf_report(report)
        assert len(entries) == 2
        assert [e["pair"] for e in entries] == ["GBPUSD", "USDJPY"]

    def test_load_wf_report_invalid_line_raises(self, tmp_path: Path):
        """Invalid JSON must raise ValueError with line number context."""
        report = tmp_path / "bad.jsonl"
        report.write_text("{not json}\n")
        with pytest.raises(ValueError, match="line 1"):
            load_wf_report(report)

    def test_run_dsr_gate_on_report_shape(self, tmp_path: Path):
        """run_dsr_gate_on_report must return the documented wrapper dict."""
        report = tmp_path / "wf.jsonl"
        lines = [json.dumps(_make_entry(pair=p)) for p in ("GBPUSD", "USDJPY")]
        report.write_text("\n".join(lines) + "\n")

        result = run_dsr_gate_on_report(report)
        assert result["source_path"] == str(report)
        assert result["n_trials"] == DEFAULT_N_INDEPENDENT_TRIALS
        assert "entries" in result
        assert "tier_ranking" in result
        assert result["tier_ranking"]["summary"]["total"] == 2

    def test_run_dsr_gate_on_report_custom_n_trials(self, tmp_path: Path):
        """Custom n_trials must propagate through the wrapper."""
        report = tmp_path / "wf.jsonl"
        report.write_text(json.dumps(_make_entry()) + "\n")
        result = run_dsr_gate_on_report(report, n_trials=50)
        assert result["n_trials"] == 50
        assert result["entries"][0]["dsr_n_trials"] == 50


# ---------------------------------------------------------------------------
# write_combined_annotated_report
# ---------------------------------------------------------------------------


class TestWriteCombinedAnnotatedReport:
    """The combined-JSON writer covers the multi-report batch path."""

    def test_writes_combined_json(self, tmp_path: Path):
        """write_combined_annotated_report emits the documented schema."""
        report_a = tmp_path / "a.jsonl"
        report_b = tmp_path / "b.jsonl"
        report_a.write_text(json.dumps(_make_entry(pair="GBPUSD")) + "\n")
        report_b.write_text(json.dumps(_make_entry(pair="USDJPY")) + "\n")

        out = tmp_path / "combined.json"
        written = write_combined_annotated_report([report_a, report_b], out)

        assert written == out
        assert out.exists()

        doc = json.loads(out.read_text())
        assert doc["phase"] == "10b"
        assert doc["n_independent_trials"] == DEFAULT_N_INDEPENDENT_TRIALS
        assert set(doc.keys()) == {
            "generated_at",
            "phase",
            "n_independent_trials",
            "source_reports",
            "per_report",
            "combined",
            "tier_definitions",
        }
        assert doc["combined"]["summary"]["total"] == 2
        # Tier definitions match oos_gate constants.
        tiers = {d["tier"]: d for d in doc["tier_definitions"]}
        assert tiers["A"]["min_aggregate_sharpe"] == TIER_A_PRODUCTION.min_aggregate_sharpe

    def test_creates_parent_directories(self, tmp_path: Path):
        """Missing parent dirs must be created automatically."""
        out = tmp_path / "nested" / "subdir" / "combined.json"
        report = tmp_path / "wf.jsonl"
        report.write_text(json.dumps(_make_entry()) + "\n")
        written = write_combined_annotated_report([report], out)
        assert written.exists()


# ---------------------------------------------------------------------------
# End-to-end smoke (the actual JSONL files in reports/)
# ---------------------------------------------------------------------------


class TestEndToEndOnRealReports:
    """Smoke test against the SRMR+ pipeline JSONL on disk.

    Marked ``skipif`` so the test still passes in CI without the report
    files; specifically exercises the full pipeline (load → annotate →
    write) against the July 8 SRMR+ report set.
    """

    REPORTS_DIR = Path("reports/srmr-plus-pipeline-2026-07-08")

    @pytest.mark.skipif(
        not Path("reports/srmr-plus-pipeline-2026-07-08/XAUUSD_focused_results.jsonl").exists(),
        reason="SRMR+ pipeline reports not available",
    )
    def test_full_pipeline_against_real_reports(self):
        """Real JSONL → annotated JSON must round-trip without errors."""
        paths = sorted(self.REPORTS_DIR.glob("*_focused_results.jsonl"))
        assert paths, "no focused_results.jsonl files found"

        results = [run_dsr_gate_on_report(p) for p in paths]
        all_entries = [e for r in results for e in r["entries"]]
        ranking = generate_tier_ranking(all_entries)

        # Sanity invariants: counts add up.
        s = ranking["summary"]
        expected_total = sum(sum(1 for line in p.read_text().splitlines() if line.strip()) for p in paths)
        assert s["total"] == expected_total
        assert s["viable_count"] >= 0
        # At least some streams must reach Tier A/B in the SRMR+ set,
        # otherwise our integration is wrong.
        assert s["tier_a_count"] + s["tier_b_count"] + s["tier_c_count"] > 0
