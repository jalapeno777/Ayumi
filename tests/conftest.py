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

    Performance: ``data_dir.rglob('*')`` is O(N) on the file count; with
    a few hundred state files this adds <5ms per test, which is well
    within the per-test overhead budget. The fixture short-circuits when
    ``<repo>/data/`` does not exist.
    """
    data_dir = _REPO_ROOT / "data"
    if not data_dir.is_dir():
        yield
        return

    snapshot: dict[str, tuple[int, int, int]] = {}
    for path in data_dir.rglob("*"):
        if path.is_file():
            st = path.stat()
            snapshot[str(path.resolve())] = (st.st_mtime_ns, st.st_size, st.st_ino)

    yield

    violations: list[str] = []
    current_files: set[str] = set()
    if data_dir.is_dir():
        for path in data_dir.rglob("*"):
            if path.is_file():
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
    don't pick up production state or pollute each other."""
    fake_state = str(tmp_path / "risk_guard_state.json")
    # Patch the default parameter value so any RiskGuard() created
    # without an explicit state_path uses the temp path.
    monkeypatch.setattr(
        "adapters.ctrader.risk_guard.RiskGuard.__init__.__defaults__",
        (None, 100000.0, fake_state),
    )
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
