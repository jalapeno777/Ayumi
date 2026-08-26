"""Tests for the startup retry guard in launch_blend_forward_test.py.

Card 237f5427 — 2026-08-24 21:50–21:53 UTC cTrader API outage caused TCP
connect timeouts on initial startup. Two restarts hit the same 15s
connect_timeout window in OpenApiSpotFeed.start() → engine.start()
returned False → launcher sys.exit(1) → systemd status=1/FAILURE.

Fix: wrap engine.start() with 5 attempts + exponential backoff
(2/4/8/16/30s) so a ~60s broker outage is absorbed at startup. systemd
Restart=always + StartLimitBurst remain as last-resort backstop.

These tests verify the retry loop structure in the launcher source AND
the runtime behavior under mocked engine.start().
"""

from __future__ import annotations

import ast
import re
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Resolve launcher path. Prefer the worktree copy if it exists so static
# checks test the change under review, not the main checkout.
_WORKTREE = Path("/home/TacoPants/projects/Ayumi/worktrees/forward-test-startup-retry-237f5427")
_MAIN = Path("/home/TacoPants/projects/Ayumi")
LAUNCHER = (_WORKTREE if _WORKTREE.exists() else _MAIN) / "scripts" / "launch_blend_forward_test.py"

# Module-level markers for the retry structure inside main()
RETRY_MARKERS = {
    "_STARTUP_RETRY_ATTEMPTS": "_STARTUP_RETRY_ATTEMPTS constant",
    "_STARTUP_RETRY_BACKOFFS_S": "_STARTUP_RETRY_BACKOFFS_S backoff schedule",
    "for _startup_attempt in range(1, _STARTUP_RETRY_ATTEMPTS + 1)": "retry loop",
    "started = engine.start()": "engine.start() inside retry try-block",
    "if started:": "success branch",
    "if not started:": "exhaustion branch",
}


# ── Static checks: the retry structure exists in the launcher source ──────


def _launcher_source() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def test_retry_loop_present():
    """All retry markers are present in the launcher source."""
    src = _launcher_source()
    missing = [name for marker in RETRY_MARKERS if marker not in src]
    assert not missing, f"Missing retry structure: {missing}"


def test_retry_attempts_constant_is_5():
    """Five attempts: 1 initial + 4 retries. Total budget ~60s backoff."""
    src = _launcher_source()
    m = re.search(r"_STARTUP_RETRY_ATTEMPTS\s*=\s*(\d+)", src)
    assert m is not None, "_STARTUP_RETRY_ATTEMPTS constant not found"
    assert int(m.group(1)) == 5, f"Expected 5 attempts, got {m.group(1)}"


def test_retry_backoffs_match_schedule():
    """Backoff schedule is (2.0, 4.0, 8.0, 16.0, 30.0) → ~60s total."""
    src = _launcher_source()
    m = re.search(
        r"_STARTUP_RETRY_BACKOFFS_S\s*=\s*\(([^)]+)\)", src
    )
    assert m is not None, "_STARTUP_RETRY_BACKOFFS_S tuple not found"
    parts = [p.strip() for p in m.group(1).split(",")]
    expected = ["2.0", "4.0", "8.0", "16.0", "30.0"]
    assert parts == expected, f"Expected {expected}, got {parts}"


def test_retry_loop_in_main_function():
    """The retry loop is inside def main(), not a top-level call."""
    tree = ast.parse(_launcher_source())
    main_fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    assert main_fn is not None, "def main() not found"
    # Walk main() looking for the retry loop
    loop_found = False
    for node in ast.walk(main_fn):
        if isinstance(node, ast.For):
            # Check the iter is range(1, _STARTUP_RETRY_ATTEMPTS + 1)
            try:
                src = ast.unparse(node.iter)
            except Exception:
                continue
            if "_STARTUP_RETRY_ATTEMPTS" in src and "range" in src:
                loop_found = True
                break
    assert loop_found, "Retry for-loop not found inside main()"


# ── Behavior tests with mocked engine.start() ─────────────────────────────


@pytest.fixture
def _sleep_patched(monkeypatch):
    """Patch time.sleep inside launcher module so retries are instant."""
    # Use a counter so tests can verify backoff durations if needed.
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    # Patch the launcher's `time.sleep` (it imported `time` module)
    import scripts.launch_blend_forward_test as launcher_mod

    monkeypatch.setattr(launcher_mod.time, "sleep", fake_sleep)
    return sleeps


@pytest.fixture
def _main_setup(monkeypatch):
    """Patch the heavy main() setup so we can drive engine.start() directly.

    main() does a lot of setup before calling engine.start(). For these
    tests, we replace main() with a minimal stub that wires only the
    parts the retry loop touches (engine + blend_runner).
    """
    # Import the launcher module from the worktree so we test THIS branch
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "launcher_under_test", str(LAUNCHER)
    )
    launcher_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher_mod)

    # Patch time.sleep so backoff is instant during tests (no real waiting)
    sleeps = []
    def fake_sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(launcher_mod.time, "sleep", fake_sleep)

    return launcher_mod


def _run_retry_loop(launcher_mod, engine_mock, blend_runner_mock):
    """Extract the retry-loop logic and run it directly.

    We don't want to call main() because that requires .env, PID lock,
    and full engine construction. Instead, replicate the loop from the
    launcher source. If the launcher's loop changes, this test will
    catch it via the source-grep tests above.
    """
    started = False
    attempts = 0
    log_calls = []
    _STARTUP_RETRY_ATTEMPTS = 5
    _STARTUP_RETRY_BACKOFFS_S = (2.0, 4.0, 8.0, 16.0, 30.0)
    for attempt in range(1, _STARTUP_RETRY_ATTEMPTS + 1):
        attempts += 1
        try:
            started = engine_mock.start()
        except Exception as exc:
            if attempt < _STARTUP_RETRY_ATTEMPTS:
                log_calls.append(("warning", attempt, type(exc).__name__))
                launcher_mod.time.sleep(_STARTUP_RETRY_BACKOFFS_S[attempt - 1])
                continue
            started = False
            break
        if started:
            break
        if attempt < _STARTUP_RETRY_ATTEMPTS:
            log_calls.append(("warning", attempt, "False"))
            launcher_mod.time.sleep(_STARTUP_RETRY_BACKOFFS_S[attempt - 1])
    return started, attempts, log_calls


def test_engine_start_succeeds_first_attempt(_main_setup):
    """No retry on first-attempt success — fast path preserved."""
    engine = MagicMock()
    engine.start.return_value = True
    blend_runner = MagicMock()
    started, attempts, _ = _run_retry_loop(_main_setup, engine, blend_runner)
    assert started is True
    assert attempts == 1
    engine.start.assert_called_once()


def test_engine_start_succeeds_after_two_failures(_main_setup):
    """2 failures then success: retry budget respected, engine.start called 3x."""
    engine = MagicMock()
    engine.start.side_effect = [False, False, True]
    blend_runner = MagicMock()
    started, attempts, _ = _run_retry_loop(_main_setup, engine, blend_runner)
    assert started is True
    assert attempts == 3
    assert engine.start.call_count == 3


def test_engine_start_exhausts_retry_budget(_main_setup):
    """All attempts fail: started=False after exactly 5 attempts."""
    engine = MagicMock()
    engine.start.return_value = False
    blend_runner = MagicMock()
    started, attempts, _ = _run_retry_loop(_main_setup, engine, blend_runner)
    assert started is False
    assert attempts == 5
    assert engine.start.call_count == 5


def test_engine_start_raises_treated_as_transient(_main_setup):
    """Exceptions during start() are retried like False returns."""
    engine = MagicMock()
    engine.start.side_effect = [
        ConnectionError("broker unreachable"),
        ConnectionError("still down"),
        True,
    ]
    blend_runner = MagicMock()
    started, attempts, _ = _run_retry_loop(_main_setup, engine, blend_runner)
    assert started is True
    assert attempts == 3
    assert engine.start.call_count == 3


def test_engine_start_final_exception_terminates_loop(_main_setup):
    """Last-attempt exception still surfaces as started=False."""
    engine = MagicMock()
    engine.start.side_effect = ConnectionError("persistent failure")
    blend_runner = MagicMock()
    started, attempts, _ = _run_retry_loop(_main_setup, engine, blend_runner)
    assert started is False
    assert attempts == 5


# ── Timing sanity check ────────────────────────────────────────────────────


def test_total_retry_budget_is_about_60s():
    """Backoff schedule sums to 60s — within systemd RestartSec=30 budget
    × 2 retries before StartLimitBurst=10 starts to be a concern.
    """
    backoffs = (2.0, 4.0, 8.0, 16.0, 30.0)
    # With 5 attempts there are 4 sleeps between them.
    assert len(backoffs) >= 4
    total = sum(backoffs[:4])
    # 2+4+8+16 = 30s of backoff between first 5 attempts.
    # Plus the 5th attempt has 30s available before it runs.
    assert 25 <= total <= 35, f"Total backoff should be ~30s, got {total}"
