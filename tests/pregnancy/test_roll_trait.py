"""Tests for the Pregnancy Protocol trait-roll script.

Covers:
- happy-path roll + ledger append
- hash chain continuity (prev_hash linkage + per-record self-hash)
- duplicate-category refusal
- --verify correctness (including single-record)
- --verify detects tampering (self-hash mismatch)
- --verify detects within-record origin inconsistency
- --dry-run writes nothing
- deterministic --seed reproduces same outcome
- --self-test exits 0
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pregnancy" / "roll_trait.py"
POOL = ROOT / "memory" / "pregnancy" / "trait_pool_harem_v1.json"


def _run(args, tmp_path, cwd=None):
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd or tmp_path,
    )


def _fresh_paths(tmp_path, name="session_a"):
    state = tmp_path / f"state_{name}.json"
    ledger = tmp_path / f"ledger_{name}.jsonl"
    return state, ledger


def _canonical(record_without_hash: dict) -> bytes:
    return json.dumps(record_without_hash, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _expected_hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def test_script_and_pool_exist():
    assert SCRIPT.exists(), f"missing roll script: {SCRIPT}"
    assert POOL.exists(), f"missing trait pool: {POOL}"


def test_pool_structure():
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    for cat in ("voice_tone", "personality_axis", "speech_pattern", "quirk", "warmth_affinity", "aesthetic"):
        assert cat in pool, f"missing category: {cat}"
        opts = pool[cat]
        assert isinstance(opts, list) and 4 <= len(opts) <= 6, f"bad option count in {cat}: {len(opts)}"
        for opt in opts:
            assert "id" in opt and "label" in opt and "origin" in opt
            assert opt["origin"] in ("ava", "craig"), f"bad origin in {cat}: {opt['origin']}"
    all_opts = [o for cat in pool if cat != "_meta" for o in pool[cat]]
    ava = sum(1 for o in all_opts if o["origin"] == "ava")
    craig = sum(1 for o in all_opts if o["origin"] == "craig")
    assert ava + craig == len(all_opts)
    # ~50/50: allow up to ±2 skew across the 34 options (i.e., between 15/19 and 19/15)
    assert abs(ava - craig) <= 2, f"origin imbalance: ava={ava}, craig={craig}"


def test_roll_appends_and_updates_state(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    proc = _run(["--category", "voice_tone", "--seed", "42", "--state", str(state), "--ledger", str(ledger)], tmp_path)
    assert proc.returncode == 0, proc.stderr
    rec = json.loads(proc.stdout.strip())
    assert rec["category"] == "voice_tone"
    assert rec["index"] == 0
    assert rec["prev_hash"] == "0" * 64
    assert rec["seed"] == 42
    assert rec["hash"] == _expected_hash(rec), "self-hash mismatch"
    assert rec["origin"] == rec["outcome"]["origin"]
    assert ledger.exists() and ledger.read_text().strip() == proc.stdout.strip()
    state = json.loads(state.read_text())
    assert state["chain_root"] == rec["hash"]
    assert "voice_tone" in state["trait_locks"]
    assert state["next_index"] == 1


def test_chain_continuity(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    p1 = _run(["--category", "voice_tone", "--seed", "1", "--state", str(state), "--ledger", str(ledger)], tmp_path)
    p2 = _run(["--category", "aesthetic", "--seed", "2", "--state", str(state), "--ledger", str(ledger)], tmp_path)
    assert p1.returncode == 0 and p2.returncode == 0, (p1.stderr, p2.stderr)
    r1 = json.loads(p1.stdout.strip())
    r2 = json.loads(p2.stdout.strip())
    assert r2["prev_hash"] == r1["hash"], "chain continuity broken: r2.prev_hash != r1.hash"
    state = json.loads(state.read_text())
    assert state["chain_root"] == r2["hash"]


def test_duplicate_category_refused(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    p1 = _run(["--category", "quirk", "--seed", "5", "--state", str(state), "--ledger", str(ledger)], tmp_path)
    assert p1.returncode == 0
    p2 = _run(["--category", "quirk", "--seed", "6", "--state", str(state), "--ledger", str(ledger)], tmp_path)
    assert p2.returncode == 2
    assert "already locked" in p2.stderr


def test_unknown_category_refused(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    proc = _run(
        [
            "--category", "not_a_real_category", "--seed", "1",
            "--state", str(state), "--ledger", str(ledger),
        ],
        tmp_path,
    )
    assert proc.returncode != 0
    assert "unknown category" in proc.stderr


def test_verify_after_two_rolls(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    assert _run(["--category", "voice_tone", "--seed", "1", "--state", str(state), "--ledger", str(ledger)], tmp_path).returncode == 0  # noqa: E501
    assert _run(["--category", "aesthetic", "--seed", "2", "--state", str(state), "--ledger", str(ledger)], tmp_path).returncode == 0  # noqa: E501
    proc = _run(["--verify", "--ledger", str(ledger)], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "chain verified" in proc.stdout


def test_verify_single_record(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    assert _run(["--category", "voice_tone", "--seed", "1", "--state", str(state), "--ledger", str(ledger)], tmp_path).returncode == 0  # noqa: E501
    proc = _run(["--verify", "--ledger", str(ledger)], tmp_path)
    assert proc.returncode == 0, proc.stderr


def test_verify_detects_self_hash_tamper(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    assert _run(["--category", "voice_tone", "--seed", "1", "--state", str(state), "--ledger", str(ledger)], tmp_path).returncode == 0  # noqa: E501
    # Tamper: replace the stored self-hash with a dummy. Verifier must detect.
    lines = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rec = json.loads(lines[0])
    rec["hash"] = "f" * 64
    lines[0] = json.dumps(rec, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = _run(["--verify", "--ledger", str(ledger)], tmp_path)
    assert proc.returncode != 0, "self-hash tamper went undetected"
    assert "self-hash mismatch" in proc.stdout


def test_verify_detects_within_record_origin_drift(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    assert _run(["--category", "voice_tone", "--seed", "1", "--state", str(state), "--ledger", str(ledger)], tmp_path).returncode == 0  # noqa: E501
    lines = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rec = json.loads(lines[0])
    rec["origin"] = "craig" if rec["origin"] == "ava" else "ava"  # flip top-level only
    lines[0] = json.dumps(rec, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = _run(["--verify", "--ledger", str(ledger)], tmp_path)
    assert proc.returncode != 0, "origin drift went undetected"


def test_verify_detects_prev_hash_break(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    assert _run(["--category", "voice_tone", "--seed", "1", "--state", str(state), "--ledger", str(ledger)], tmp_path).returncode == 0  # noqa: E501
    assert _run(["--category", "aesthetic", "--seed", "2", "--state", str(state), "--ledger", str(ledger)], tmp_path).returncode == 0  # noqa: E501
    lines = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # Corrupt record 1'state outcome (this breaks its self-hash AND record 2'state prev_hash linkage)
    r1 = json.loads(lines[0])
    r1["outcome"]["id"] = "vt_tampered"
    lines[0] = json.dumps(r1, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = _run(["--verify", "--ledger", str(ledger)], tmp_path)
    assert proc.returncode != 0


def test_dry_run_writes_nothing(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    proc = _run(["--category", "voice_tone", "--seed", "9", "--dry-run", "--state", str(state), "--ledger", str(ledger)], tmp_path)  # noqa: E501
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload.get("dry_run") is True
    assert not state.exists()
    assert not ledger.exists()


def test_deterministic_seed_reproduces_outcome(tmp_path):
    s1, l1 = _fresh_paths(tmp_path, "a")
    s2, l2 = _fresh_paths(tmp_path, "b")
    p1 = _run(["--category", "voice_tone", "--seed", "12345", "--state", str(s1), "--ledger", str(l1)], tmp_path)
    p2 = _run(["--category", "voice_tone", "--seed", "12345", "--state", str(s2), "--ledger", str(l2)], tmp_path)
    assert p1.returncode == 0 and p2.returncode == 0
    r1 = json.loads(p1.stdout.strip())
    r2 = json.loads(p2.stdout.strip())
    assert r1["outcome"]["id"] == r2["outcome"]["id"]
    assert r1 == r2


def test_self_test_exits_zero(tmp_path):
    proc = _run(["--self-test"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_state_chain_root_matches_record_hash(tmp_path):
    state, ledger = _fresh_paths(tmp_path)
    assert _run(["--category", "quirk", "--seed", "11", "--state", str(state), "--ledger", str(ledger)], tmp_path).returncode == 0  # noqa: E501
    state = json.loads(state.read_text())
    last = json.loads([ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()][-1])
    assert state["chain_root"] == last["hash"]
