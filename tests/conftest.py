"""Tests conftest — standard fixtures and path setup.

Backtest stub isolation is now centralized here instead of duplicated in
individual test files. The previous per-file cleanup fixtures from
BQ-37e1f69e have been superseded by the autouse ``_isolate_backtest_stub``
fixture and the ``pytest_pycollect_makemodule`` hook below.
"""

import sys
from pathlib import Path

import pytest


# Autouse safety net (card 84df1bcc): fail any test that writes under
# <repo>/data/. Snapshots mtime/size of every file under data/ before the
# test body and compares after yield. Any modified, created, or deleted
# file under data/ causes ``pytest.fail`` so unisolated test writes never
# reach production state. Tests that legitimately need to write under
# data/ must use ``tmp_path`` (the path is captured per-test by pytest
# and is not under the repo tree).
_REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# External writer exemption (card 22fb282b, followup4)
# ---------------------------------------------------------------------------
# The live forward-test engine (scripts/launch_blend_forward_test.py) writes
# FIVE repo data/ files from a SEPARATE PROCESS outside any pytest run:
#
#   1. data/heartbeat_trading.json          (~5s heartbeat)
#   2. data/edge_telemetry_state.json       (telemetry state)
#   3. data/forex/equity_snapshots.jsonl    (equity snapshots, basename match)
#   4. data/forward_test_health.json        (health probe)
#   5. data/overseer_state.json             (overseer state)
#
# When the engine is running, the snapshot-vs-current diff in
# ``_guard_repo_data_writes`` would otherwise flag every one of these
# externally-written files as test pollution, producing intermittent
# teardown ERROR across the entire test suite (the per-file whack-a-mole
# is over — this is a conftest-level defect). The five basenames are
# basenames (not full paths) so coverage is automatic for ``forex/``.
#
# The exemption is CONDITIONAL on the engine actually running: if the
# engine is down (e.g. CI, dev box, post-shutdown), these files revert
# to strict guard behaviour so a genuine test write to one of them will
# still fail. Engine detection uses /proc scanning (Linux-native,
# deterministic, no subprocess flakiness) for ``launch_blend_forward_test``.
_EXTERNAL_WRITER_FILES: frozenset[str] = frozenset({
    "heartbeat_trading.json",
    "edge_telemetry_state.json",
    "equity_snapshots.jsonl",
    "forward_test_health.json",
    "overseer_state.json",
})


def _is_engine_running() -> bool:
    """Return True iff ``launch_blend_forward_test`` is running on this host.

    Implementation: scan ``/proc/<pid>/cmdline`` for any process whose
    command line contains the engine script name. /proc is Linux-only;
    the engine itself is Linux-only (it relies on Linux process control
    and POSIX signals), so the platform assumption is consistent. This
    avoids subprocess flakiness (PATH issues, pgrep exit-code variability,
    race between check and fixture yield).
    """
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
        return False
    for pid_dir in proc_dir.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            cmdline_bytes = (pid_dir / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        try:
            cmdline = cmdline_bytes.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - defensive
            continue
        if "launch_blend_forward_test" in cmdline:
            return True
    return False


@pytest.fixture(autouse=True)
def _guard_repo_data_writes():
    """Fail any test that writes under ``<repo>/data/``.

    Snapshots ``(mtime_ns, size, inode)`` for every file under
    ``<repo>/data/`` before yielding, then re-scans after the test body
    returns. Any modified, created, or deleted file is reported as a hard
    test failure with ``pytest.fail``.

    The fixture is a pure observer: it does not patch or redirect any
    code path, so it works alongside the per-test ``tmp_path`` fixtures
    that isolate signal-stats and risk-guard writes. Tests that already
    use ``tmp_path`` (or any non-``data/`` location) are unaffected.

    External-writer exemption (card 22fb282b, followup4): when the live
    forward-test engine ``launch_blend_forward_test`` is running, the
    five externally-written files listed in ``_EXTERNAL_WRITER_FILES``
    are exempted from the snapshot/comparison (matched by basename).
    When the engine is NOT running, those files revert to strict guard
    behaviour so any genuine test pollution to them still fails. This
    is the structural fix that supersedes per-file whack-a-mole module
    shadow fixtures (e.g. tests/integration/test_ctrader_risk_guard.py's
    prior ``_guard_repo_data_writes`` override is removed in followup4;
    the companion ``_isolate_risk_guard_and_dependencies`` path-isolation
    fixture is kept as genuine defense-in-depth).

    Performance: ``data_dir.rglob('*')`` is O(N) on the file count; with
    a few hundred state files this adds <5ms per test, which is well
    within the per-test overhead budget. The fixture short-circuits when
    ``<repo>/data/`` does not exist.
    """
    data_dir = _REPO_ROOT / "data"
    if not data_dir.is_dir():
        yield
        return

    engine_running = _is_engine_running()
    excluded_names = _EXTERNAL_WRITER_FILES if engine_running else frozenset()

    snapshot: dict[str, tuple[int, int, int]] = {}
    for path in data_dir.rglob("*"):
        if path.is_file() and path.name not in excluded_names:
            st = path.stat()
            snapshot[str(path.resolve())] = (st.st_mtime_ns, st.st_size, st.st_ino)

    yield

    violations: list[str] = []
    current_files: set[str] = set()
    if data_dir.is_dir():
        for path in data_dir.rglob("*"):
            if path.is_file() and path.name not in excluded_names:
                key = str(path.resolve())
                current_files.add(key)
                if key in snapshot:
                    pre_mtime, pre_size, pre_ino = snapshot[key]
                    st = path.stat()
                    if (
                        st.st_mtime_ns != pre_mtime
                        or st.st_size != pre_size
                        or st.st_ino != pre_ino
                    ):
                        try:
                            rel = path.relative_to(_REPO_ROOT)
                        except ValueError:
                            rel = path
                        violations.append(f"modified: {rel}")
                else:
                    try:
                        rel = path.relative_to(_REPO_ROOT)
                    except ValueError:
                        rel = path
                    violations.append(f"created: {rel}")

    deleted = set(snapshot.keys()) - current_files
    for key in sorted(deleted):
        try:
            rel = Path(key).relative_to(_REPO_ROOT)
        except ValueError:
            rel = Path(key)
        violations.append(f"deleted: {rel}")

    if violations:
        pytest.fail(
            "Test wrote under <repo>/data/ — use tmp_path-based fixtures "
            "instead. Violations: " + "; ".join(violations[:5])
        )


# Autouse: ensure RiskGuard default state file doesn't leak between tests.
@pytest.fixture(autouse=True)
def _isolate_risk_guard_state(monkeypatch, tmp_path):
    """Redirect RiskGuard's default state_path to a temp dir so tests
    don't pick up production state or pollute each other.

    Two layers: (a) patch ``RiskGuard.__init__.__defaults__`` so direct
    ``RiskGuard()`` calls without args resolve to the tmp_path, and
    (b) wrap ``RiskGuard.__init__`` so any caller that explicitly passes
    the production literal path ``data/state/risk_guard_state.json``
    (e.g. PaperTrader, which always passes ``state_path=state_path or
    "data/state/risk_guard_state.json"``) is redirected to the tmp_path.
    """
    from adapters.ctrader.risk_guard import RiskGuard as _RG

    fake_state = str(tmp_path / "risk_guard_state.json")
    monkeypatch.setattr(
        "adapters.ctrader.risk_guard.RiskGuard.__init__.__defaults__",
        (None, 100000.0, fake_state),
    )

    _PROD_RG_PATH = "data/state/risk_guard_state.json"

    original_init = _RG.__init__

    def _init_wrapper(self, *args, **kwargs):
        # If state_path was not provided as kwarg AND positional args
        # don't carry an explicit state_path (3rd positional), don't
        # touch anything — defaults already patched.
        # If state_path was provided AND it equals the production
        # literal, swap to tmp_path.
        if "state_path" in kwargs and kwargs["state_path"] == _PROD_RG_PATH:
            kwargs["state_path"] = fake_state
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(_RG, "__init__", _init_wrapper)
    yield


@pytest.fixture(autouse=True)
def _isolate_signal_stats(monkeypatch, tmp_path):
    """Redirect SignalStatsRecorder's default log path to a temp dir so
    tests don't pollute the production signal_stats.jsonl file."""
    fake_log = str(tmp_path / "signal_stats.jsonl")
    # Patch the SignalStatsRecorder default path
    monkeypatch.setattr(
        "signal_engine.signal_stats.SignalStatsRecorder.__init__.__defaults__",
        (fake_log,),
    )
    # Also patch PaperTrader's default stats_log_path
    monkeypatch.setattr(
        "adapters.ctrader.paper_trader.PaperTrader.__init__.__defaults__",
        (None, None, 100000.0, None, None, fake_log),
    )
    yield


@pytest.fixture(autouse=True)
def _isolate_edge_telemetry(monkeypatch, tmp_path):
    """Redirect EdgeTelemetryTracker's default persist path to a temp
    dir so tests don't pollute the production data/edge_telemetry.jsonl
    file. Pair with cluster A teardown-isolation guard.
    """
    fake_path = str(tmp_path / "edge_telemetry.jsonl")
    monkeypatch.setattr(
        "risk.edge_telemetry.EdgeTelemetryTracker.__init__.__defaults__",
        (fake_path,),
    )
    yield


@pytest.fixture(autouse=True)
def _isolate_heartbeat(monkeypatch, tmp_path):
    """Redirect ForwardTestEngine's ``_HEARTBEAT_FILE`` module constant
    so tests don't pollute the production data/heartbeat_trading.json
    file. Pair with cluster A teardown-isolation guard.
    """
    fake_path = str(tmp_path / "heartbeat_trading.json")
    monkeypatch.setattr(
        "adapters.ctrader.forward_test_engine._HEARTBEAT_FILE",
        fake_path,
    )
    yield


# ---------------------------------------------------------------------------
# Backtest stub isolation
# ---------------------------------------------------------------------------
# Some unit tests (e.g. ``test_forward_test_flag_persistence.py``) install fake
# ``backtest.*`` stubs at import time to avoid heavy transitive dependencies.
# If those stubs leak into other test modules during collection, imports of
# real backtest symbols fail and the full suite breaks.
#
# The hook runs before pytest imports each test module, and the autouse fixture
# runs around every test, so stub-dependent tests get their stubs restored and
# real-backtest tests get a clean import environment.


def _remove_backtest_stubs():
    """Pop all ``backtest.*`` stub modules from ``sys.modules``.

    Returns a dict of the popped modules so they can be restored later. A
    module is treated as a stub if it (or its parent ``backtest`` package)
    carries the marker ``_tsukasa_stub = True``.
    """
    saved = {}
    bt_pkg = sys.modules.get("backtest")
    pkg_is_stub = bt_pkg is not None and getattr(bt_pkg, "_tsukasa_stub", False)

    for key in list(sys.modules.keys()):
        if key.startswith("backtest"):
            mod = sys.modules.get(key)
            if mod is None:
                continue
            if getattr(mod, "_tsukasa_stub", False) or pkg_is_stub:
                saved[key] = sys.modules.pop(key)
    return saved


# Collection-time isolation: run before each test module is collected so every
# module imports the real backtest package.
def pytest_pycollect_makemodule(module_path, parent):
    _remove_backtest_stubs()


# Per-test isolation: run before/after every test so stub-dependent tests have
# their stubs restored and real-backtest tests get a clean import environment.
@pytest.fixture(autouse=True)
def _isolate_backtest_stub():
    saved = _remove_backtest_stubs()
    yield
    for key, mod in saved.items():
        if key not in sys.modules:
            sys.modules[key] = mod


@pytest.fixture
def tmp_state_dir(tmp_path):
    d = tmp_path / "kill_switches"
    d.mkdir()
    return str(d)


@pytest.fixture
def mock_kill_switch(tmp_state_dir):
    from adapters.ctrader.kill_switch import KillSwitchManager

    mgr = KillSwitchManager(state_dir=tmp_state_dir)
    return mgr
