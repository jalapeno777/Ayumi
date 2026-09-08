"""Tests for card 758273a7-c3f1-41fa-95dc-7384c260acd7 — harness isolation.

ruff: noqa: S608 — ruff flags ``f"Found pattern at offsets: {[m.start() for m in
matches]}"`` as a SQL-injection vector. This is a false positive: ``.start()``
returns a regex match offset (``int``), not SQL. The test exercises regex
source matching, not database queries.

Card 758273a7 (URGENT, 2026-09-08): the blend harness previously wrote
to LIVE forward-test state paths, contaminating ``data/kill_switches/
global.state`` and ``data/risk_state_blend.json`` when invoked as root.
Root-run re-run #3 poisoned live engine startup state during the Phase 1
restart 16:30 UTC incident.

These tests guard against regression of:

  * Default isolated per-run state dir (never LIVE paths).
  * Startup guard refuses on live PID file presence (kill -0 probe).
  * Startup guard refuses on foreign-ownership of live state files.
  * ``--allow-foreign-ownership`` bypass (operator-only flag).
  * ``--keep-state-dir`` preserves the isolated dir for post-mortem.
  * Isolated ``KillSwitchManager`` writes ONLY to its own state_dir, never
    to ``data/kill_switches/`` even when activations fire.

The tests monkeypatch ``LIVE_*`` paths inside the harness module so the
suite runs without touching real production state. The integration
check (mtime + sha256 before/after) is performed at proof time, not in
unit tests.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Ensure src/forex-bot and scripts/ are importable for
# adapters.ctrader.kill_switch and backtest_blend_harness.
_REPO_ROOT = Path(__file__).resolve().parents[3]
for sub in ("src/forex-bot", "scripts"):
    p = str(_REPO_ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest

import scripts.backtest_blend_harness as harness  # noqa: E402

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_fake_live_files(monkeypatch, tmp_path: Path):
    """Create fake LIVE state files under tmp_path and monkeypatch the
    harness's ``LIVE_*`` constants to point at them. Returns the live root.
    """
    live_root = tmp_path / "fake_live"
    live_root.mkdir()
    kill_switch_dir = live_root / "data" / "kill_switches"
    kill_switch_dir.mkdir(parents=True)
    live_state = kill_switch_dir / "global.state"
    live_state.write_text(json.dumps({"active": False, "version": 1}) + "\n")
    live_risk = live_root / "data" / "risk_state_blend.json"
    live_risk.write_text(json.dumps({"starting_balance": 10000.0}) + "\n")
    pid_file = live_root / "data" / "forward_test.pid"

    monkeypatch.setattr(harness, "LIVE_FORWARD_TEST_PID", pid_file)
    monkeypatch.setattr(harness, "LIVE_KILL_SWITCH_GLOBAL_STATE", live_state)
    monkeypatch.setattr(harness, "LIVE_RISK_STATE_BLEND", live_risk)
    return live_root


def _harness_source_path() -> Path:
    return _REPO_ROOT / "scripts" / "backtest_blend_harness.py"


# ── AC1: default state dir is isolated (tempfile, never LIVE) ──────────────


def test_default_state_dir_is_isolated_temp_dir():
    """``_resolve_state_dir`` returns a tempdir under tempfile.gettempdir()
    by default — never ``data/kill_switches`` or ``data/risk_state_blend.json``.
    Card 758273a7: harness must not touch LIVE paths by default.
    """
    args = argparse.Namespace(state_dir=None, allow_foreign_ownership=False, keep_state_dir=False)
    resolved = harness._resolve_state_dir(args)
    try:
        assert resolved.exists(), f"Isolated state dir must exist: {resolved}"
        assert str(resolved).startswith(tempfile.gettempdir()), (
            f"Default state dir must be under tempfile.gettempdir() for auto-cleanup; got {resolved}"
        )
        assert "data/kill_switches" not in str(resolved)
        assert "data/risk_state_blend" not in str(resolved)
    finally:
        import shutil

        shutil.rmtree(resolved, ignore_errors=True)


def test_explicit_state_dir_respected(tmp_path):
    """``--state-dir PATH`` overrides the default tempdir."""
    explicit = tmp_path / "my_harness_state"
    args = argparse.Namespace(state_dir=str(explicit), allow_foreign_ownership=False, keep_state_dir=False)
    resolved = harness._resolve_state_dir(args)
    assert resolved == explicit.resolve()
    assert resolved.exists()


# ── AC2: startup guard refuses when PID file present and live ──────────────


def test_guard_refuses_when_pid_file_present(monkeypatch, tmp_path):
    """Live forward_test.pid with live PID → harness refuses."""
    _make_fake_live_files(monkeypatch, tmp_path)
    pid_file = harness.LIVE_FORWARD_TEST_PID
    pid_file.write_text(str(os.getpid()))

    args = argparse.Namespace(allow_foreign_ownership=False, keep_state_dir=False)
    state_dir = tmp_path / "harness_state"
    state_dir.mkdir()
    with pytest.raises(harness.RefuseToRun) as excinfo:
        harness._verify_isolation_or_refuse(args, state_dir)
    assert "LIVE forward_test engine is running" in str(excinfo.value)
    assert str(os.getpid()) in str(excinfo.value)


def test_guard_allows_stale_pid_file(monkeypatch, tmp_path, caplog):
    """Stale PID file (PID no longer alive) is logged and ignored."""
    import logging

    _make_fake_live_files(monkeypatch, tmp_path)
    harness.LIVE_FORWARD_TEST_PID.write_text("99999999")

    args = argparse.Namespace(allow_foreign_ownership=False, keep_state_dir=False)
    state_dir = tmp_path / "harness_state"
    state_dir.mkdir()
    with caplog.at_level(logging.WARNING, logger="ayumi.backtest_harness"):
        # Must not raise
        harness._verify_isolation_or_refuse(args, state_dir)
    assert any("Stale PID file" in rec.message for rec in caplog.records), (
        f"Expected a 'Stale PID file' warning; got: {[r.message for r in caplog.records]}"
    )


# ── AC3: startup guard refuses on foreign-ownership ─────────────────────────


def test_guard_refuses_on_foreign_ownership(monkeypatch, tmp_path):
    """Live state file owned by a different uid → harness refuses."""
    _make_fake_live_files(monkeypatch, tmp_path)
    real_getuid = os.getuid

    def fake_getuid():
        return 0 if real_getuid() != 0 else 1

    monkeypatch.setattr(os, "getuid", fake_getuid)
    # And ensure pwd.getpwuid works for our fake uid 0
    import pwd

    def fake_getpwuid(uid):
        if uid == 0:
            return pwd.struct_passwd(("root", "", 0, 0, "", "/root", "/bin/bash"))
        raise KeyError(uid)

    monkeypatch.setattr(pwd, "getpwuid", fake_getpwuid)

    args = argparse.Namespace(allow_foreign_ownership=False, keep_state_dir=False)
    state_dir = tmp_path / "harness_state"
    state_dir.mkdir()
    with pytest.raises(harness.RefuseToRun) as excinfo:
        harness._verify_isolation_or_refuse(args, state_dir)
    assert "LIVE state file" in str(excinfo.value)
    assert "758273a7" in str(excinfo.value)


def test_guard_allows_with_allow_foreign_ownership(monkeypatch, tmp_path):
    """``--allow-foreign-ownership`` bypasses the ownership check."""
    _make_fake_live_files(monkeypatch, tmp_path)
    real_getuid = os.getuid

    def fake_getuid():
        return 0 if real_getuid() != 0 else 1

    monkeypatch.setattr(os, "getuid", fake_getuid)

    args = argparse.Namespace(allow_foreign_ownership=True, keep_state_dir=False)
    state_dir = tmp_path / "harness_state"
    state_dir.mkdir()
    # Must not raise
    harness._verify_isolation_or_refuse(args, state_dir)


def test_guard_passes_clean_state(monkeypatch, tmp_path):
    """No PID file, no live state files → guard passes silently."""
    live_root = tmp_path / "fake_live"
    live_root.mkdir()
    (live_root / "data").mkdir()
    monkeypatch.setattr(harness, "LIVE_FORWARD_TEST_PID", live_root / "data" / "forward_test.pid")
    monkeypatch.setattr(
        harness,
        "LIVE_KILL_SWITCH_GLOBAL_STATE",
        live_root / "data" / "kill_switches" / "global.state",
    )
    monkeypatch.setattr(
        harness,
        "LIVE_RISK_STATE_BLEND",
        live_root / "data" / "risk_state_blend.json",
    )

    args = argparse.Namespace(allow_foreign_ownership=False, keep_state_dir=False)
    state_dir = tmp_path / "harness_state"
    state_dir.mkdir()
    # Must not raise
    harness._verify_isolation_or_refuse(args, state_dir)


# ── AC4: isolated KillSwitchManager writes only to its own state_dir ───────


def test_isolated_killswitch_writes_only_to_isolated_dir(tmp_path):
    """Activating kill on an isolated KillSwitchManager writes ONLY to its
    state_dir — never to ``LIVE_KILL_SWITCH_GLOBAL_STATE`` (which the test
    points at a sentinel under tmp_path).
    """
    from adapters.ctrader.kill_switch import KillSwitchManager

    # Sentinel "LIVE" state file
    sentinel_live = tmp_path / "live_kill_switches" / "global.state"
    sentinel_live.parent.mkdir(parents=True)
    sentinel_content_before = json.dumps({"active": False, "version": 1}) + "\n"
    sentinel_live.write_text(sentinel_content_before)
    sentinel_mtime_before = sentinel_live.stat().st_mtime

    # Isolated KillSwitchManager bound to a different state_dir
    isolated_dir = tmp_path / "isolated_state" / "kill_switches"
    isolated_ks = KillSwitchManager(state_dir=str(isolated_dir), disabled=False)
    isolated_ks.activate_global_kill(reason="test", triggered_by="unit_test")

    # 1. Isolated dir got the kill state file
    isolated_state_file = isolated_dir / "global.state"
    assert isolated_state_file.exists(), (
        f"Isolated KillSwitchManager must write its state file to {isolated_state_file}"
    )
    state = json.loads(isolated_state_file.read_text())
    assert state["active"] is True
    assert state["reason"] == "test"

    # 2. Sentinel LIVE state file was NOT modified
    assert sentinel_live.read_text() == sentinel_content_before, (
        "Sentinel LIVE kill-switch state must be unchanged after isolated KS activation"
    )
    assert sentinel_live.stat().st_mtime == sentinel_mtime_before, (
        "Sentinel LIVE kill-switch state mtime must be unchanged after isolated KS activation"
    )


# ── AC5: source-level invariants ───────────────────────────────────────────


def test_harness_exposes_state_dir_arg():
    """``--state-dir`` must be a documented CLI option (card 758273a7)."""
    src = _harness_source_path().read_text(encoding="utf-8")
    assert '"--state-dir"' in src, "harness must expose --state-dir CLI arg"


def test_harness_exposes_allow_foreign_ownership_arg():
    """``--allow-foreign-ownership`` must be a documented CLI option (card 758273a7)."""
    src = _harness_source_path().read_text(encoding="utf-8")
    assert '"--allow-foreign-ownership"' in src


def test_harness_exposes_keep_state_dir_arg():
    """``--keep-state-dir`` must be a documented CLI option (card 758273a7)."""
    src = _harness_source_path().read_text(encoding="utf-8")
    assert '"--keep-state-dir"' in src


def test_harness_does_not_unlink_live_risk_state():
    """The harness must NOT contain an unconditional unlink() of the live
    risk state path. Card 758273a7: pre-fix harness line 313-316 poisoned
    ``data/risk_state_blend.json`` on every run.

    The LIVE path IS referenced (as the ``LIVE_RISK_STATE_BLEND`` constant
    that the ownership guard checks); what we forbid is the combination
    of that live path with ``.unlink()`` (the poisoning action).
    """
    src = _harness_source_path().read_text(encoding="utf-8")
    # Look for `...risk_state_blend.json").unlink()` (the poisoning pattern)
    forbidden_pattern = re.compile(
        r"risk_state_blend\.json[^)]*\)\s*\.\s*unlink\s*\(",
        re.MULTILINE,
    )
    # The LIVE constant declaration (LIVE_RISK_STATE_BLEND = ...) is fine
    # and must NOT match — only the live risk state being unlinked is bad.
    matches = list(forbidden_pattern.finditer(src))
    assert not matches, (
        f"Harness must NOT unlink the live risk_state_blend.json; "
        f"delete from the isolated state_dir instead. "
        f"Found pattern at offsets: {[m.start() for m in matches]}"
    )


def test_harness_rewires_engine_kill_switch_before_build_components():
    """The harness must replace ``engine._kill_switch`` with the isolated
    instance BEFORE ``engine._build_components()`` so every consumer sees
    the isolated state_dir. Card 758273a7.
    """
    src = _harness_source_path().read_text(encoding="utf-8")
    # Find a code-level (indented) call, not a comment/docstring occurrence.
    code_call_re = re.compile(r"^\s+engine\._build_components\(\)", re.MULTILINE)
    code_assign_re = re.compile(r"^\s+engine\._kill_switch = isolated_ks", re.MULTILINE)
    build_match = code_call_re.search(src)
    assign_match = code_assign_re.search(src)
    assert build_match, "Harness must call engine._build_components()"
    assert assign_match, "Harness must assign engine._kill_switch = isolated_ks (indented code)"
    assert assign_match.start() < build_match.start(), (
        f"Harness must assign engine._kill_switch = isolated_ks BEFORE "
        f"engine._build_components() — every consumer (PositionMonitor, "
        f"PaperTrader._risk_guard, ExecutionPermissionPolicy, market_feed) "
        f"is wired via self._kill_switch in _build_components(). "
        f"got assign@{assign_match.start()} build@{build_match.start()}"
    )
    iso_decl = src.find("isolated_ks = _build_isolated_kill_switch(")
    assert iso_decl > 0, "Harness must construct isolated_ks via _build_isolated_kill_switch(state_dir)"


def test_harness_calls_verify_isolation_at_run_backtest_top():
    """``run_backtest`` must call ``_verify_isolation_or_refuse`` near its top.
    Card 758273a7: guard must run before any state-writing work.
    """
    src = _harness_source_path().read_text(encoding="utf-8")
    fn_start = src.index("def run_backtest(")
    fn_end = src.index("\ndef ", fn_start + 1)
    fn_body = src[fn_start:fn_end]
    guard_call_pos = fn_body.index("_verify_isolation_or_refuse(args, state_dir)")
    assert guard_call_pos < 4000, "Guard must run at the top of run_backtest, before any state-writing work"


def test_harness_uses_isolated_risk_state_path_in_run_backtest():
    """``run_backtest`` must delete/use the isolated risk state path, not LIVE.
    Card 758273a7.
    """
    src = _harness_source_path().read_text(encoding="utf-8")
    fn_start = src.index("def run_backtest(")
    fn_end = src.index("\ndef ", fn_start + 1)
    fn_body = src[fn_start:fn_end]
    assert 'state_path = state_dir / "risk_state_blend.json"' in fn_body, (
        "Harness must derive risk_state path from state_dir (isolated), "
        "not from PROJECT_ROOT / 'data' / 'risk_state_blend.json'"
    )


def test_harness_redirects_blend_runner_persistence_path():
    """The harness must redirect ``blend_runner._persistence._path`` to the
    isolated state dir. Card 758273a7: ``build_blend_runner()`` (defined in
    launch_blend_forward_test.py:1285+) defaults to ``data/risk_state_blend.json``,
    and the runner's ``stop()`` writes there — which would be the LIVE path
    unless redirected.
    """
    src = _harness_source_path().read_text(encoding="utf-8")
    fn_start = src.index("def run_backtest(")
    fn_end = src.index("\ndef ", fn_start + 1)
    fn_body = src[fn_start:fn_end]
    assert "blend_runner._persistence._path =" in fn_body, (
        "Harness must redirect blend_runner._persistence._path to the "
        "isolated state dir; otherwise blend_runner.stop() writes to the "
        "LIVE data/risk_state_blend.json (card 758273a7 second poisoning "
        "channel)."
    )
    # Must come AFTER blend_runner = build_blend_runner()
    build_pos = fn_body.index("blend_runner = build_blend_runner()")
    redirect_pos = fn_body.index("blend_runner._persistence._path =")
    assert build_pos < redirect_pos, (
        "Persistence redirect must come AFTER blend_runner construction"
    )


def test_harness_patches_engine_kill_switch_manager_reference():
    """The harness must patch ``forward_test_engine.KillSwitchManager``
    before constructing the engine so the engine's __init__-time
    ``self._kill_switch = KillSwitchManager()`` (line 535) uses the
    isolated state dir, not ``data/kill_switches/``.

    Card 758273a7 second poisoning channel: the engine's __init__ creates
    a default KillSwitchManager pointing at the LIVE path BEFORE the
    harness can replace ``engine._kill_switch``. That default instance's
    ``_load_state()`` fails on a corrupt sentinel and triggers the
    fail-safe ``_save_state()`` (active=True, reason='corrupt_state_file'),
    corrupting the live ``data/kill_switches/global.state``. The harness
    must swap the engine's class reference so the __init__-time instance
    is itself isolated.
    """
    src = _harness_source_path().read_text(encoding="utf-8")
    # Check that the harness patches the kill_switch module's
    # KillSwitchManager reference (broader patch than just forward_test_engine).
    assert "_ks_module.KillSwitchManager =" in src, (
        "Harness must swap adapters.ctrader.kill_switch.KillSwitchManager "
        "to a subclass that defaults state_dir to the isolated dir (card "
        "758273a7 — every KillSwitchManager() call in the engine pipeline "
        "must target the isolated dir)."
    )
    # And restores the kill_switch module's reference
    assert "_ks_module.KillSwitchManager = _saved_ks_cls" in src, (
        "Harness must restore the kill_switch module's original "
        "KillSwitchManager reference after engine construction "
        "(card 758273a7)"
    )
    # And also patches the forward_test_engine / paper_trader references
    assert "_fte_module.KillSwitchManager =" in src, (
        "Harness must also patch forward_test_engine.KillSwitchManager "
        "(defensive: catches pre-existing bindings from other importers)"
    )


# ── AC6: keep-state-dir flag preserves dir for post-mortem ────────────────


def test_keep_state_dir_preserves_directory(tmp_path):
    """``--keep-state-dir`` must prevent auto-cleanup of the isolated dir."""
    state_dir = tmp_path / "harness_state"
    state_dir.mkdir()
    (state_dir / "kill_switches").mkdir()

    harness._cleanup_state_dir(state_dir, keep=True)
    assert state_dir.exists(), "--keep-state-dir must preserve the state dir"


# ── AC7 (Rin rework 4f384bfc MEDIUM): failure-path tests ────────────────


def test_isolation_patch_restores_module_bindings_on_exception(tmp_path, monkeypatch):
    """``_isolation_patch`` must restore ALL module-level KillSwitchManager
    bindings on the exception path. Card 758273a7 REWORK (Rin verdict
    4f384bfc HIGH #1) — pre-rework restoration was success-only, leaking
    _HarnessIsolatedKS into subsequent in-process constructions.
    """
    import adapters.ctrader.forward_test_engine as fte_mod
    import adapters.ctrader.kill_switch as ks_mod
    from adapters.ctrader import paper_trader as pt_mod

    # Capture originals for the assertion at the end.
    orig_ks = ks_mod.KillSwitchManager
    orig_fte = fte_mod.KillSwitchManager
    orig_pt = getattr(pt_mod, "KillSwitchManager", None)

    # Build an isolated_ks to feed into the context manager.
    isolated_ks_dir = tmp_path / "isolated_ks"
    isolated_ks_dir.mkdir()
    isolated_ks = harness._build_isolated_kill_switch(isolated_ks_dir)

    # Inject an exception inside the with-block.
    sentinel = RuntimeError("simulated mid-run failure")
    with pytest.raises(RuntimeError) as excinfo:
        with harness._isolation_patch(isolated_ks):
            # Verify patches are applied inside the with-block.
            assert ks_mod.KillSwitchManager is not orig_ks, (
                "ks_module.KillSwitchManager must be patched inside the with-block"
            )
            assert fte_mod.KillSwitchManager is not orig_fte
            raise sentinel
    assert excinfo.value is sentinel

    # After the with-block exits (via exception), originals MUST be restored.
    assert ks_mod.KillSwitchManager is orig_ks, (
        "ks_module.KillSwitchManager must be restored after exception"
    )
    assert fte_mod.KillSwitchManager is orig_fte, (
        "fte_module.KillSwitchManager must be restored after exception"
    )
    if orig_pt is not None:
        assert getattr(pt_mod, "KillSwitchManager", None) is orig_pt, (
            "pt_module.KillSwitchManager must be restored after exception"
        )


def test_isolation_patch_restores_disabled_flag_on_exception(tmp_path):
    """``_isolation_patch`` must restore ``KillSwitchManager._disabled``
    on the exception path. Card 758273a7 REWORK (Rin verdict 4f384bfc
    HIGH #2) — pre-rework flipped ``_disabled = False`` and never
    restored, leaking enabled state into subsequent in-process runs.
    """
    from adapters.ctrader.kill_switch import KillSwitchManager

    # Capture the original class-level value.
    orig_disabled = KillSwitchManager._disabled

    # Pre-condition: verify we are starting from a known state. If the
    # harness left _disabled=False from a previous failed test, this
    # assertion catches it.
    isolated_ks_dir = tmp_path / "isolated_ks"
    isolated_ks_dir.mkdir()
    isolated_ks = harness._build_isolated_kill_switch(isolated_ks_dir)

    with pytest.raises(RuntimeError, match="simulated"):
        with harness._isolation_patch(isolated_ks):
            # Inside the with-block, _disabled must be False (patched).
            assert KillSwitchManager._disabled is False, (
                "_disabled must be False inside the with-block (harness-enabled)"
            )
            raise RuntimeError("simulated")

    # After the with-block, _disabled must be restored to the captured value.
    assert KillSwitchManager._disabled is orig_disabled, (
        f"_disabled must be restored to original ({orig_disabled}) after "
        f"exception; got {KillSwitchManager._disabled}"
    )


def test_isolation_patch_restores_on_normal_return(tmp_path):
    """``_isolation_patch`` must restore on the normal-return path too
    (Rin HIGH #1 + #2 — both paths must restore). Two sequential in-process
    runs must not leak state into each other.
    """
    import adapters.ctrader.kill_switch as ks_mod
    from adapters.ctrader.kill_switch import KillSwitchManager

    orig_ks = ks_mod.KillSwitchManager
    orig_disabled = KillSwitchManager._disabled

    isolated_ks_dir = tmp_path / "isolated_ks"
    isolated_ks_dir.mkdir()
    isolated_ks = harness._build_isolated_kill_switch(isolated_ks_dir)

    # First run — normal completion.
    with harness._isolation_patch(isolated_ks):
        assert KillSwitchManager._disabled is False
        assert ks_mod.KillSwitchManager is not orig_ks

    # After first run: originals restored.
    assert KillSwitchManager._disabled is orig_disabled
    assert ks_mod.KillSwitchManager is orig_ks

    # Second run — must also restore cleanly (proving no leakage).
    with harness._isolation_patch(isolated_ks):
        assert KillSwitchManager._disabled is False
        assert ks_mod.KillSwitchManager is not orig_ks

    assert KillSwitchManager._disabled is orig_disabled, (
        "_disabled must be restored after second in-process run too"
    )
    assert ks_mod.KillSwitchManager is orig_ks


def test_guard_refuses_on_unreadable_pid_file_via_permission_error(
    monkeypatch, tmp_path, caplog
):
    """PID file that raises PermissionError on read_text() must REFUSE,
    not proceed. Card 758273a7 REWORK (Rin verdict 4f384bfc HIGH #3).
    Pre-rework guard treated PermissionError as STALE (fail-open), which
    let an unreadable / foreign-owned PID file slip past the guard.
    """
    import logging

    _make_fake_live_files(monkeypatch, tmp_path)
    pid_file = harness.LIVE_FORWARD_TEST_PID
    pid_file.write_text("99999")  # content exists, but read will be denied

    # Monkeypatch read_text to raise PermissionError (simulates a file
    # locked or owned by a foreign user).
    def fake_read_text(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied", str(pid_file))

    monkeypatch.setattr(type(pid_file), "read_text", fake_read_text)

    args = argparse.Namespace(allow_foreign_ownership=False, keep_state_dir=False)
    state_dir = tmp_path / "harness_state"
    state_dir.mkdir()

    with caplog.at_level(logging.WARNING, logger="ayumi.backtest_harness"):
        with pytest.raises(harness.RefuseToRun) as excinfo:
            harness._verify_isolation_or_refuse(args, state_dir)

    # The error message must mention fail-closed / unreadable.
    err = str(excinfo.value)
    assert "unreadable" in err.lower(), (
        f"RefuseToRun message must explain unreadable PID file; got: {err}"
    )
    assert "failing closed" in err.lower() or "FAIL CLOSED" in err or "refuses" in err.lower(), (
        f"RefuseToRun message must indicate fail-closed semantics; got: {err}"
    )
    assert "4f384bfc" in err, (
        f"RefuseToRun message must cite Rin verdict 4f384bfc; got: {err}"
    )
