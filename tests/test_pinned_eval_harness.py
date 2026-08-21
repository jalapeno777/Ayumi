"""Self-tests for the pinned-eval harness (BQ-1380).

Coverage:
- T0–T4 tier threshold table integrity (labels, monotonic floors, bounds)
- PinnedTask dataclass: hash determinism, hash stability, hash recompute
- PinnedTask.from_dict: bad row handling, task_id required, tier enforced
- capability_score: verdict bands, headroom sign, penalty application
- decomposition_score: atomicity / clarity / dependency sub-scores,
  clamping to tier_max_subtasks, long-prompt coupling penalty
- aggregate: per-tier + overall summary math, empty-input safety
- evaluate: end-to-end composition of capability + decomposition
- load_tasks_jsonl: bad-row skipping, comment lines, missing file
- write_results_jsonl: append + reset semantics, parent dir creation
- CLI --demo: full demo run, exit code, output file populated
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure the script is importable as a module
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pinned_eval_harness  # noqa: E402, F401, I001

# Import the runtime pieces directly to keep tests fast and dependency-free.
from pinned_eval_harness import (  # noqa: E402
    SCHEMA_VERSION,
    TIER_ORDER,
    TIER_THRESHOLDS,
    PinnedEvalResult,
    PinnedTask,
    _demo_tasks,
    aggregate,
    capability_score,
    content_hash,
    decomposition_score,
    evaluate,
    load_tasks_jsonl,
    write_results_jsonl,
)

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def small_task() -> PinnedTask:
    return PinnedTask(
        task_id="t-small",
        prompt="Rename foo to bar.",
        acceptance_criteria="grep returns zero hits.",
        expected_outputs=["diff"],
        tier="T1",
        tags=["refactor"],
    )


@pytest.fixture
def long_task() -> PinnedTask:
    long_prompt = (
        "Refactor the risk sizer module so that the per-pair max-risk "
        "overrides are loaded from a YAML config file at startup. Then "
        "wire the YAML through the launch script and add a unit test that "
        "verifies the override beats the global default. Additionally "
        "ensure that the schema is documented in docs/forex/risk-sizing.md "
        "and that missing config falls back cleanly without raising. "
        "Afterwards, validate via CI that the change does not regress any "
        "existing backtests and that the documented schema matches the "
        "loader."
    )
    return PinnedTask(
        task_id="t-long",
        prompt=long_prompt,
        acceptance_criteria=(
            "YAML schema is documented; the per-pair override beats the "
            "global default; missing config falls back cleanly without "
            "raising; CI green."
        ),
        expected_outputs=["diff", "test_log", "config_schema_doc"],
        tier="T3",
        tags=["risk", "config", "shared-state"],
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tier threshold table
# ═══════════════════════════════════════════════════════════════════════════


class TestTierThresholds:
    def test_all_tiers_present(self):
        assert set(TIER_THRESHOLDS) == set(TIER_ORDER)

    def test_tier_labels_match_task_mapping(self):
        assert TIER_THRESHOLDS["T0"].label == "trivial"
        assert TIER_THRESHOLDS["T1"].label == "simple"
        assert TIER_THRESHOLDS["T2"].label == "moderate"
        assert TIER_THRESHOLDS["T3"].label == "complex"
        assert TIER_THRESHOLDS["T4"].label == "expert"

    def test_min_capability_strictly_increasing(self):
        caps = [TIER_THRESHOLDS[t].min_capability for t in TIER_ORDER]
        assert caps == sorted(caps)
        for a, b in zip(caps, caps[1:]):  # noqa: B905
            assert b > a, f"non-monotonic min_capability: {caps}"

    def test_min_capability_within_unit_interval(self):
        for t in TIER_ORDER:
            v = TIER_THRESHOLDS[t].min_capability
            assert 0.0 <= v <= 1.0

    def test_tolerance_within_unit_interval(self):
        for t in TIER_ORDER:
            v = TIER_THRESHOLDS[t].tolerance
            assert 0.0 <= v <= 1.0

    def test_max_atomic_subtasks_positive_and_increasing(self):
        ms = [TIER_THRESHOLDS[t].max_atomic_subtasks for t in TIER_ORDER]
        assert all(m >= 1 for m in ms)
        for a, b in zip(ms, ms[1:]):  # noqa: B905
            assert b > a, f"non-monotonic max_atomic_subtasks: {ms}"

    def test_as_dict_round_trip_shape(self):
        d = TIER_THRESHOLDS["T2"].as_dict()
        assert d["tier"] == "T2"
        assert d["label"] == "moderate"
        assert "description" in d and d["description"]
        for key in ("min_capability", "max_atomic_subtasks", "tolerance"):
            assert key in d

    def test_tier_threshold_is_frozen(self):
        with pytest.raises(Exception):  # noqa: B017
            TIER_THRESHOLDS["T1"].min_capability = 0.99  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# PinnedTask dataclass + content hashing
# ═══════════════════════════════════════════════════════════════════════════


class TestPinnedTask:
    def test_unknown_tier_rejected(self):
        with pytest.raises(ValueError, match="unknown tier"):
            PinnedTask(task_id="bad", prompt="x", tier="T9")

    def test_empty_task_id_rejected(self):
        with pytest.raises(ValueError, match="task_id"):
            PinnedTask(task_id="", prompt="x", tier="T0")

    def test_content_hash_is_64_hex(self, small_task: PinnedTask):
        h = small_task.content_hash
        assert len(h) == 64
        int(h, 16)  # raises if not hex

    def test_content_hash_deterministic(self):
        a = PinnedTask(
            task_id="x",
            prompt="p",
            acceptance_criteria="a",
            expected_outputs=["diff"],
            tier="T1",
        )
        b = PinnedTask(
            task_id="x",
            prompt="p",
            acceptance_criteria="a",
            expected_outputs=["diff"],
            tier="T1",
        )
        assert a.content_hash == b.content_hash

    def test_content_hash_changes_with_prompt(self):
        a = PinnedTask(task_id="x", prompt="p1", tier="T0")
        b = PinnedTask(task_id="x", prompt="p2", tier="T0")
        assert a.content_hash != b.content_hash

    def test_content_hash_changes_with_acceptance(self):
        a = PinnedTask(
            task_id="x",
            prompt="p",
            acceptance_criteria="aa",
            tier="T1",
        )
        b = PinnedTask(
            task_id="x",
            prompt="p",
            acceptance_criteria="bb",
            tier="T1",
        )
        assert a.content_hash != b.content_hash

    def test_content_hash_changes_with_expected_outputs(self):
        a = PinnedTask(
            task_id="x",
            prompt="p",
            expected_outputs=["diff"],
            tier="T1",
        )
        b = PinnedTask(
            task_id="x",
            prompt="p",
            expected_outputs=["test_log"],
            tier="T1",
        )
        assert a.content_hash != b.content_hash

    def test_content_hash_changes_with_tier(self):
        a = PinnedTask(task_id="x", prompt="p", tier="T1")
        b = PinnedTask(task_id="x", prompt="p", tier="T2")
        assert a.content_hash != b.content_hash

    def test_content_hash_independent_of_tags_and_profile(self):
        a = PinnedTask(
            task_id="x",
            prompt="p",
            tier="T1",
            tags=["a"],
            agent_profile={"success_rate": 0.5},
        )
        b = PinnedTask(
            task_id="x",
            prompt="p",
            tier="T1",
            tags=["b"],
            agent_profile={"success_rate": 0.9},
        )
        # Tags + profile are *operational*, not part of content identity.
        assert a.content_hash == b.content_hash

    def test_expected_outputs_must_be_list(self):
        with pytest.raises(TypeError):
            PinnedTask(
                task_id="x",
                prompt="p",
                expected_outputs="diff",  # type: ignore[arg-type]
                tier="T0",
            )

    def test_agent_profile_must_be_dict(self):
        with pytest.raises(TypeError):
            PinnedTask(
                task_id="x",
                prompt="p",
                agent_profile="not-a-dict",  # type: ignore[arg-type]
                tier="T0",
            )

    def test_verify_hash_passes_on_fresh(self, small_task: PinnedTask):
        assert small_task.verify_hash()

    def test_verify_hash_detects_tamper(self, small_task: PinnedTask):
        original = small_task.prompt
        small_task.prompt = original + " (tampered)"
        assert not small_task.verify_hash()

    def test_from_dict_drops_unknown_keys(self):
        raw = {
            "task_id": "x",
            "prompt": "p",
            "tier": "T0",
            "future_field_we_dont_know_about": "ignore me",
        }
        t = PinnedTask.from_dict(raw)
        assert t.task_id == "x"
        assert not hasattr(t, "future_field_we_dont_know_about")

    def test_from_dict_rejects_non_dict(self):
        with pytest.raises(TypeError):
            PinnedTask.from_dict("not a dict")  # type: ignore[arg-type]

    def test_from_dict_requires_task_id(self):
        with pytest.raises(ValueError, match="task_id"):
            PinnedTask.from_dict({"prompt": "p", "tier": "T0"})

    def test_content_hash_public_accessor_matches(self, small_task: PinnedTask):
        assert content_hash(small_task) == small_task.content_hash


# ═══════════════════════════════════════════════════════════════════════════
# capability_score
# ═══════════════════════════════════════════════════════════════════════════


class TestCapabilityScore:
    def test_strong_verdict_at_high_capability(self):
        t = PinnedTask(task_id="x", prompt="p", tier="T1")
        out = capability_score(t, 0.95)
        assert out["verdict"] in ("STRONG", "READY")
        assert out["final_score"] >= 0.65

    def test_fail_verdict_below_tolerance(self):
        t = PinnedTask(task_id="x", prompt="p", tier="T4")
        out = capability_score(t, 0.30)  # 0.30 << 0.90 - 0.10
        assert out["verdict"] == "FAIL"
        assert out["final_score"] <= 0.20

    def test_verdict_band_thresholds(self):
        # At min_capability for T2 (0.70) with no penalty, we expect READY
        t = PinnedTask(task_id="x", prompt="p", tier="T2")
        out = capability_score(t, 0.70)
        assert out["verdict"] in ("STRONG", "READY")
        assert 0.0 <= out["final_score"] <= 1.0

    def test_measured_capability_out_of_range_rejected(self):
        t = PinnedTask(task_id="x", prompt="p", tier="T0")
        with pytest.raises(ValueError):
            capability_score(t, 1.5)
        with pytest.raises(ValueError):
            capability_score(t, -0.1)

    def test_rework_penalty_reduces_score(self):
        t = PinnedTask(task_id="x", prompt="p", tier="T1")
        clean = capability_score(t, 0.95)
        dirty = capability_score(t, 0.95, rework_rate=0.5)
        assert dirty["final_score"] < clean["final_score"]
        assert dirty["rework_penalty"] > 0

    def test_rework_penalty_capped(self):
        t = PinnedTask(task_id="x", prompt="p", tier="T1")
        out = capability_score(t, 0.95, rework_rate=1.0)
        assert out["rework_penalty"] <= 0.25

    def test_rework_rate_out_of_range_rejected(self):
        t = PinnedTask(task_id="x", prompt="p", tier="T1")
        with pytest.raises(ValueError):
            capability_score(t, 0.5, rework_rate=-0.1)
        with pytest.raises(ValueError):
            capability_score(t, 0.5, rework_rate=1.5)

    def test_token_penalty_above_threshold(self):
        t = PinnedTask(task_id="x", prompt="p", tier="T1")
        out = capability_score(t, 0.95, avg_tokens=50000)
        assert out["token_penalty"] > 0
        assert out["token_penalty"] <= 0.15

    def test_token_penalty_capped(self):
        t = PinnedTask(task_id="x", prompt="p", tier="T1")
        out = capability_score(t, 0.95, avg_tokens=10_000_000)
        assert out["token_penalty"] <= 0.15

    def test_negative_tokens_rejected(self):
        t = PinnedTask(task_id="x", prompt="p", tier="T1")
        with pytest.raises(ValueError):
            capability_score(t, 0.5, avg_tokens=-1)

    def test_agent_profile_overrides_applied(self):
        t = PinnedTask(
            task_id="x",
            prompt="p",
            tier="T1",
            agent_profile={
                "success_rate": 0.0,
                "rework_rate": 0.4,
                "avg_tokens": 20000,
            },
        )
        # measured_capability=0.0 triggers profile-relative scoring;
        # rework penalty should come from profile.
        out = capability_score(t, 0.0)
        assert out["rework_penalty"] > 0
        assert out["token_penalty"] > 0

    def test_score_always_in_unit_interval(self):
        for tier in TIER_ORDER:
            t = PinnedTask(task_id="x", prompt="p", tier=tier)
            for m in (0.0, 0.3, 0.5, 0.7, 0.9, 1.0):
                out = capability_score(t, m, rework_rate=0.5, avg_tokens=30000)
                assert 0.0 <= out["final_score"] <= 1.0

    def test_higher_tier_harder_to_pass(self):
        # With the same measured capability, T4 should score lower than T1.
        low = capability_score(PinnedTask(task_id="a", prompt="p", tier="T1"), 0.85)
        high = capability_score(PinnedTask(task_id="b", prompt="p", tier="T4"), 0.85)
        assert high["final_score"] < low["final_score"]


# ═══════════════════════════════════════════════════════════════════════════
# decomposition_score
# ═══════════════════════════════════════════════════════════════════════════


class TestDecompositionScore:
    def test_short_crisp_task_scores_well(self, small_task: PinnedTask):
        out = decomposition_score(small_task)
        assert out["combined"] >= 0.7
        assert out["verdict"] in ("DECOMPOSE_OK", "DECOMPOSE_CAUTIOUS")

    def test_long_multistep_task_penalized(self, long_task: PinnedTask):
        out = decomposition_score(long_task)
        # The fixture is deliberately long and contains several " and / then /
        # additionally / afterwards " coupling tokens.
        assert out["atomicity"] < 1.0
        assert out["combined"] < 1.0

    def test_subtask_clamped_to_tier_max(self, long_task: PinnedTask):
        out = decomposition_score(long_task)
        assert out["clamped_subtasks"] <= out["tier_max_subtasks"]

    def test_subtasks_at_least_one(self):
        t = PinnedTask(task_id="x", prompt="", tier="T0")
        out = decomposition_score(t)
        assert out["estimated_subtasks"] >= 1
        assert out["clamped_subtasks"] >= 1

    def test_clarity_higher_with_acceptance_text(self):
        no_acc = PinnedTask(task_id="x", prompt="do the thing", tier="T1")
        rich_acc = PinnedTask(
            task_id="x",
            prompt="do the thing",
            tier="T1",
            acceptance_criteria=("must return exactly one entry; verifies via assert; given input X then result is Y"),
            expected_outputs=["diff", "test_log", "schema"],
        )
        assert decomposition_score(rich_acc)["clarity"] > decomposition_score(no_acc)["clarity"]

    def test_clarity_floor_when_no_acceptance_no_outputs(self):
        t = PinnedTask(task_id="x", prompt="do the thing", tier="T1")
        out = decomposition_score(t)
        assert out["clarity"] == pytest.approx(0.30, abs=1e-9)

    def test_coupling_tags_reduce_dependency(self):
        clean = PinnedTask(
            task_id="x",
            prompt="short task",
            tier="T2",
        )
        coupled = PinnedTask(
            task_id="x",
            prompt="short task",
            tier="T2",
            tags=["shared-state", "race", "migration"],
        )
        assert decomposition_score(clean)["dependency"] > decomposition_score(coupled)["dependency"]

    def test_long_prompt_increments_subtasks(self):
        # Build a single long sentence (no coupling flags) > 250 words.
        long_prompt = "word " * 300
        t = PinnedTask(task_id="x", prompt=long_prompt, tier="T4")
        out = decomposition_score(t)
        # 300 words > 250 → +2 to subtasks; ensure clamped below tier max
        assert out["clamped_subtasks"] >= 3
        assert out["clamped_subtasks"] <= out["tier_max_subtasks"]

    def test_all_subscores_in_unit_interval(self):
        t = PinnedTask(
            task_id="x",
            prompt="Refactor X and Y and Z then verify.",
            tier="T3",
            acceptance_criteria="must be green",
            tags=["shared-state"],
        )
        out = decomposition_score(t)
        for k in ("atomicity", "clarity", "dependency", "combined"):
            assert 0.0 <= out[k] <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# aggregate
# ═══════════════════════════════════════════════════════════════════════════


def _make_result(task_id: str, tier: str, cap: float, decomp: float) -> PinnedEvalResult:
    return PinnedEvalResult(
        task_id=task_id,
        content_hash="x" * 64,
        tier=tier,
        label=TIER_THRESHOLDS[tier].label,
        capability={
            "tier": tier,
            "label": TIER_THRESHOLDS[tier].label,
            "min_capability": TIER_THRESHOLDS[tier].min_capability,
            "tolerance": TIER_THRESHOLDS[tier].tolerance,
            "measured_capability": cap,
            "headroom": 0.0,
            "raw_score": cap,
            "rework_penalty": 0.0,
            "token_penalty": 0.0,
            "final_score": cap,
            "verdict": "STRONG"
            if cap >= 0.85
            else "READY"
            if cap >= 0.65
            else "MARGINAL"
            if cap >= 0.45
            else "WEAK"
            if cap >= 0.20
            else "FAIL",
        },
        decomposition={
            "atomicity": decomp,
            "clarity": decomp,
            "dependency": decomp,
            "combined": decomp,
            "estimated_subtasks": 1,
            "clamped_subtasks": 1,
            "tier_max_subtasks": TIER_THRESHOLDS[tier].max_atomic_subtasks,
            "verdict": "DECOMPOSE_OK",
        },
        measured_capability=cap,
        agent_profile={},
        tags=[],
        prompt_chars=0,
        acceptance_chars=0,
        expected_outputs=[],
        timestamp="2026-01-01T00:00:00Z",
        schema_version=SCHEMA_VERSION,
    )


class TestAggregate:
    def test_empty_input_returns_zero_counts(self):
        out = aggregate([])
        assert out["total_tasks"] == 0
        assert out["overall"]["count"] == 0
        for t in TIER_ORDER:
            assert out["by_tier"][t]["count"] == 0

    def test_per_tier_counts(self):
        results = [
            _make_result("a", "T0", 0.95, 0.9),
            _make_result("b", "T0", 0.95, 0.9),
            _make_result("c", "T2", 0.75, 0.8),
            _make_result("d", "T4", 0.30, 0.6),
        ]
        out = aggregate(results)
        assert out["total_tasks"] == 4
        assert out["by_tier"]["T0"]["count"] == 2
        assert out["by_tier"]["T1"]["count"] == 0
        assert out["by_tier"]["T2"]["count"] == 1
        assert out["by_tier"]["T4"]["count"] == 1
        assert out["overall"]["count"] == 4

    def test_means_match_arithmetic(self):
        results = [
            _make_result("a", "T1", 0.6, 0.5),
            _make_result("b", "T1", 0.8, 0.7),
        ]
        out = aggregate(results)
        assert out["by_tier"]["T1"]["capability_mean"] == pytest.approx(0.7)
        assert out["by_tier"]["T1"]["decomposition_mean"] == pytest.approx(0.6)

    def test_verdict_counts_present(self):
        results = [
            _make_result("a", "T0", 0.95, 0.9),  # STRONG
            _make_result("b", "T0", 0.5, 0.9),  # MARGINAL
        ]
        out = aggregate(results)
        assert out["by_tier"]["T0"]["verdict_counts"]["STRONG"] == 1
        assert out["by_tier"]["T0"]["verdict_counts"]["MARGINAL"] == 1

    def test_ready_share(self):
        results = [
            _make_result("a", "T1", 0.95, 0.9),  # STRONG → ready
            _make_result("b", "T1", 0.7, 0.9),  # READY → ready
            _make_result("c", "T1", 0.5, 0.9),  # MARGINAL → not ready
        ]
        out = aggregate(results)
        assert out["by_tier"]["T1"]["ready_share"] == pytest.approx(2 / 3)

    def test_schema_version_in_summary(self):
        out = aggregate([])
        assert out["schema_version"] == SCHEMA_VERSION


# ═══════════════════════════════════════════════════════════════════════════
# evaluate (composition)
# ═══════════════════════════════════════════════════════════════════════════


class TestEvaluate:
    def test_evaluate_returns_complete_row(self, small_task: PinnedTask):
        r = evaluate(small_task, 0.80)
        assert r.task_id == small_task.task_id
        assert r.tier == "T1"
        assert r.label == "simple"
        assert r.content_hash == small_task.content_hash
        assert r.schema_version == SCHEMA_VERSION
        assert "verdict" in r.capability
        assert "verdict" in r.decomposition
        assert r.timestamp  # non-empty

    def test_evaluate_accepts_overrides(self, small_task: PinnedTask):
        r = evaluate(
            small_task,
            0.80,
            rework_rate=0.3,
            avg_tokens=15000,
            timestamp="2026-01-01T00:00:00Z",
        )
        assert r.capability["rework_penalty"] > 0
        assert r.capability["token_penalty"] > 0
        assert r.timestamp == "2026-01-01T00:00:00Z"

    def test_evaluate_as_dict_json_serializable(self, small_task: PinnedTask):
        r = evaluate(small_task, 0.5)
        # Round-trip through json.dumps to ensure full serialisability.
        json.dumps(r.as_dict(), default=str)


# ═══════════════════════════════════════════════════════════════════════════
# I/O
# ═══════════════════════════════════════════════════════════════════════════


class TestIO:
    def test_load_tasks_jsonl_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_tasks_jsonl(tmp_path / "nope.jsonl")

    def test_load_tasks_jsonl_skips_bad_rows(self, tmp_path: Path):
        f = tmp_path / "tasks.jsonl"
        f.write_text(
            "\n".join(
                [
                    json.dumps({"task_id": "good", "prompt": "p", "tier": "T0"}),
                    "not json",
                    json.dumps({"prompt": "missing-id", "tier": "T0"}),
                    json.dumps({"task_id": "bad-tier", "prompt": "p", "tier": "T9"}),
                    json.dumps({"task_id": "good2", "prompt": "p2", "tier": "T1"}),
                    "# comment",
                    "",
                ]
            )
            + "\n"
        )
        tasks = load_tasks_jsonl(f)
        ids = [t.task_id for t in tasks]
        assert ids == ["good", "good2"]

    def test_write_results_appends(self, tmp_path: Path):
        out = tmp_path / "r.jsonl"
        n1 = write_results_jsonl(out, [_make_result("a", "T0", 0.9, 0.9)])
        n2 = write_results_jsonl(out, [_make_result("b", "T1", 0.7, 0.7)])
        assert n1 == 1 and n2 == 1
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["task_id"] == "a"
        assert json.loads(lines[1])["task_id"] == "b"

    def test_write_results_creates_parent_dirs(self, tmp_path: Path):
        out = tmp_path / "deep" / "nested" / "r.jsonl"
        n = write_results_jsonl(out, [_make_result("a", "T0", 0.9, 0.9)])
        assert n == 1
        assert out.exists()

    def test_demo_tasks_have_one_per_tier(self):
        tasks = _demo_tasks()
        tiers = sorted(t.task_id.split("-")[1] for t in tasks)
        assert tiers == ["T0", "T1", "T2", "T3", "T4"]


# ═══════════════════════════════════════════════════════════════════════════
# CLI (subprocess)
# ═══════════════════════════════════════════════════════════════════════════


class TestCLI:
    def _script_path(self) -> Path:
        return SCRIPTS_DIR / "pinned_eval_harness.py"

    def test_demo_run_exits_zero(self, tmp_path: Path):
        out = tmp_path / "demo.jsonl"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(self._script_path()),
                "--demo",
                "--reset",
                "--summary",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0, f"stderr={result.stderr!r}\nstdout={result.stdout!r}"
        assert out.exists()
        rows = [json.loads(line) for line in out.read_text().strip().split("\n")]
        assert len(rows) == 5
        for r in rows:
            assert r["schema_version"] == SCHEMA_VERSION
            assert r["content_hash"]
            assert r["capability"]["verdict"] in {
                "STRONG",
                "READY",
                "MARGINAL",
                "WEAK",
                "FAIL",
            }

    def test_demo_summary_contains_overall(self, tmp_path: Path):
        out = tmp_path / "demo.jsonl"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(self._script_path()),
                "--demo",
                "--reset",
                "--summary",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0
        # The summary JSON is appended to stdout after INFO logs; pull the
        # block that starts with '{' on its own line.
        json_blocks = [blk for blk in result.stdout.split("\n\n") if blk.strip().startswith("{")]
        assert json_blocks, "no summary JSON found"
        summary = json.loads(json_blocks[-1])
        assert summary["total_tasks"] == 5
        assert "by_tier" in summary
        assert "overall" in summary

    def test_no_args_exits_one(self):
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(self._script_path())],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 1

    def test_bad_capability_exits_one(self, tmp_path: Path):
        out = tmp_path / "demo.jsonl"
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(self._script_path()),
                "--demo",
                "--capability",
                "1.5",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 1
        assert "--capability" in result.stderr or "capability" in result.stderr

    def test_loads_user_tasks(self, tmp_path: Path):
        tasks_path = tmp_path / "tasks.jsonl"
        tasks_path.write_text(
            json.dumps(
                {
                    "task_id": "u-1",
                    "prompt": "do it",
                    "tier": "T1",
                    "acceptance_criteria": "must work",
                    "expected_outputs": ["diff"],
                }
            )
            + "\n"
        )
        out = tmp_path / "results.jsonl"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(self._script_path()),
                "--tasks",
                str(tasks_path),
                "--capability",
                "0.8",
                "--reset",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        rows = [json.loads(line) for line in out.read_text().strip().split("\n")]
        assert len(rows) == 1
        assert rows[0]["task_id"] == "u-1"


# ═══════════════════════════════════════════════════════════════════════════
# Determinism — running twice must produce identical hashes
# ═══════════════════════════════════════════════════════════════════════════


class TestDeterminism:
    def test_demo_runs_produce_identical_hashes(self, tmp_path: Path):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        out1 = tmp_path / "a.jsonl"
        out2 = tmp_path / "b.jsonl"
        for o in (out1, out2):
            subprocess.run(  # noqa: S603
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "pinned_eval_harness.py"),
                    "--demo",
                    "--reset",
                    "--output",
                    str(o),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
        hashes1 = [json.loads(line)["content_hash"] for line in out1.read_text().strip().split("\n")]
        hashes2 = [json.loads(line)["content_hash"] for line in out2.read_text().strip().split("\n")]
        assert hashes1 == hashes2

    def test_demo_runs_produce_identical_scores(self, tmp_path: Path):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        out1 = tmp_path / "a.jsonl"
        out2 = tmp_path / "b.jsonl"
        for o in (out1, out2):
            subprocess.run(  # noqa: S603
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "pinned_eval_harness.py"),
                    "--demo",
                    "--reset",
                    "--output",
                    str(o),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
        rows1 = [json.loads(line) for line in out1.read_text().strip().split("\n")]
        rows2 = [json.loads(line) for line in out2.read_text().strip().split("\n")]
        # Compare all numeric fields (timestamps will be identical because
        # we run them in the same second here, but content_hash is the main
        # tamper-evidence check).
        for r1, r2 in zip(rows1, rows2):  # noqa: B905
            assert r1["task_id"] == r2["task_id"]
            assert r1["content_hash"] == r2["content_hash"]
            assert r1["capability"]["final_score"] == r2["capability"]["final_score"]
            assert r1["decomposition"]["combined"] == r2["decomposition"]["combined"]
