"""Tests for card 080094ef r2 — in-process exit record + recorded-exit classification.

Rin HIGH finding (comment b27b6a40, card 080094ef-f260-4a5e-b34f-41a39d5f4919):
the restart-reason classification in ``_classify_restart_reason`` reads the
live systemd unit's ``Result=``/``ExecMainStatus``. After a crash followed by
successful ``Restart=always`` reactivation, the live values are
``Result=success, ExecMainStatus=0`` — those values describe the CURRENT
activation, not the prior crash that triggered the restart, so the classifier
returns ``clean_24h_rotation`` for what was actually a fault.

Fix: write our own exit record at known exit sites
(``_record_last_exit`` → ``data/forward_test_last_exit.json``), then have
``_read_systemd_restart_status`` prefer that record over the live unit
properties, and have ``_classify_restart_reason`` dispatch on
``exit_source == "recorded"`` before falling back to the live path.

These tests guard against regression of:

  * ``_record_last_exit`` writes a well-formed JSON file atomically and
    never raises on filesystem errors.
  * ``_read_last_exit_record`` returns ``None`` for missing/corrupt files
    and never raises.
  * ``_signal_name_for`` maps well-known signals to their canonical names
    and falls back to ``SIG_<n>`` for unknown.
  * **Crash → successful restart is not masked as ``clean_24h_rotation``**:
    when a recorded exit has ``triggered_by="signal"`` and a non-zero exit
    code, ``_classify_restart_reason`` returns ``external_signal_termination``
    even when the live unit reports ``success``/0.
  * Other recorded scenarios map to the correct labels:
      - signal + exit_code=0 → ``clean_24h_rotation`` (handler ran cleanly)
      - sys_exit(0) → ``clean_24h_rotation``
      - sys_exit(1) → ``pid_guard_or_launch_failure``
      - sys_exit(2) → ``foreign_uid_signal_stats``
      - exception → ``uncaught_exception_exit_<n>``
  * Live fallback path still works when no recorded file exists.

All subprocess calls (systemctl) are mocked — these tests never touch the
real systemd unit.
"""

from __future__ import annotations

import json
import os
import signal as sig
from pathlib import Path
from unittest.mock import patch

import pytest

# Importing the launcher module executes its top-level load_dotenv() call,
# which is harmless if .env is absent. pythonpath in pytest.ini includes
# ``scripts`` so this resolves cleanly.
import launch_blend_forward_test as launcher  # noqa: E402


# ── 1. _signal_name_for: canonical mapping + fallback ──────────────────────


@pytest.mark.parametrize(
    ("signum", "expected"),
    [
        (sig.SIGTERM, "SIGTERM"),
        (sig.SIGINT, "SIGINT"),
        (sig.SIGHUP, "SIGHUP"),
        (sig.SIGKILL, "SIGKILL"),
        (sig.SIGABRT, "SIGABRT"),
    ],
)
def test_signal_name_for_known_signals(signum: int, expected: str) -> None:
    assert launcher._signal_name_for(signum) == expected


def test_signal_name_for_unknown_falls_back() -> None:
    """Non-existent signal number (e.g. 999) returns ``SIG_999``."""
    assert launcher._signal_name_for(999) == "SIG_999"


# ── 2. _record_last_exit + _read_last_exit_record round-trip ───────────────


def test_record_and_read_round_trip(tmp_path: Path, monkeypatch) -> None:
    """Recorded exit survives a subsequent read with the expected shape."""
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", tmp_path / "last_exit.json")
    launcher._record_last_exit(
        exit_code=0,
        triggered_by="signal",
        signal_name="SIGTERM",
        detail="signum=15",
    )
    rec = launcher._read_last_exit_record()
    assert rec is not None
    assert rec["exit_code"] == 0
    assert rec["triggered_by"] == "signal"
    assert rec["signal_name"] == "SIGTERM"
    assert rec["detail"] == "signum=15"
    assert "exit_at" in rec
    assert rec["pid"] == os.getpid()


def test_record_atomic_write_does_not_leave_tmp(tmp_path: Path, monkeypatch) -> None:
    """The .tmp sidecar is replaced (not left behind) after a successful write."""
    target = tmp_path / "last_exit.json"
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", target)
    launcher._record_last_exit(0, "atexit", detail="cleanup")
    assert target.exists()
    # No .tmp sidecar should remain after os.replace().
    assert not (tmp_path / "last_exit.json.tmp").exists()


def test_record_overwrites_previous(tmp_path: Path, monkeypatch) -> None:
    """A second record replaces the first (the most-recent exit is canonical)."""
    target = tmp_path / "last_exit.json"
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", target)
    launcher._record_last_exit(0, "sys_exit", detail="first")
    launcher._record_last_exit(134, "signal", signal_name="SIGABRT", detail="second")
    rec = launcher._read_last_exit_record()
    assert rec is not None
    assert rec["triggered_by"] == "signal"
    assert rec["exit_code"] == 134
    assert rec["detail"] == "second"


def test_read_returns_none_when_missing(tmp_path: Path, monkeypatch) -> None:
    """No file → returns None without raising."""
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", tmp_path / "nope.json")
    assert launcher._read_last_exit_record() is None


def test_read_returns_none_when_corrupt(tmp_path: Path, monkeypatch) -> None:
    """A non-JSON file → returns None without raising."""
    target = tmp_path / "last_exit.json"
    target.write_text("not valid json {{")
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", target)
    assert launcher._read_last_exit_record() is None


def test_read_returns_none_when_wrong_shape(tmp_path: Path, monkeypatch) -> None:
    """A JSON value that is not a dict → returns None."""
    target = tmp_path / "last_exit.json"
    target.write_text(json.dumps(["not", "a", "dict"]))
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", target)
    assert launcher._read_last_exit_record() is None


def test_record_never_raises_on_permission_error(tmp_path: Path, monkeypatch) -> None:
    """A permission failure during write must NOT propagate (defensive posture)."""
    # Make the parent dir read-only so the .tmp write fails.
    target = tmp_path / "readonly" / "last_exit.json"
    target.parent.mkdir()
    target.parent.chmod(0o500)  # r-x, no write
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", target)
    try:
        launcher._record_last_exit(0, "sys_exit")  # must not raise
    finally:
        target.parent.chmod(0o700)


# ── 3. _classify_restart_reason: regression test for Rin HIGH finding ────


def _make_sd_status(
    *,
    exit_source: str = "live",
    last_result: str = "unknown",
    last_exit_code: int | None = None,
    triggered_by: str | None = None,
    signal_name: str | None = None,
    exit_at: str = "2026-09-15T21:26:47Z",
    detail: str | None = None,
) -> dict:
    return {
        "n_restarts": 12,
        "last_restart_at": "2026-09-15T21:27:17Z",
        "last_result": last_result,
        "last_exit_code": last_exit_code,
        "exit_source": exit_source,
        "last_exit_triggered_by": triggered_by,
        "last_exit_signal_name": signal_name,
        "last_exit_detail": detail,
        "last_exit_at": exit_at,
    }


def test_recorded_crash_after_reactivation_is_not_clean_24h_rotation() -> None:
    """Rin HIGH finding regression: a SIGABRT crash followed by successful
    Restart=always reactivation must be classified as ``external_signal_termination``
    even though the live unit reports ``Result=success, ExecMainStatus=0``.

    Simulates the scenario where:
      1. The process exited with SIGABRT (exit_code=134) and was either:
         (a) caught by a future SIGABRT trap that records via _record_last_exit,
         (b) recorded via os._exit(134), or
         (c) discovered via the journal path (covered separately in the
             journal-path tests below).
      2. Restart=always re-launched the process. The current activation is
         ``Result=success, ExecMainStatus=0`` — which masks the crash.

    The classifier must look at the recorded exit (source of truth for the
    prior activation) and emit ``external_signal_termination``.
    """
    sd = _make_sd_status(
        exit_source="recorded",
        # Live values are success/0 because the CURRENT activation is healthy:
        last_result="success",
        # Recorded exit_code=134 (SIGABRT convention; Python reports
        # negative-signal exits as 128+|signum|=134 for SIGABRT=6).
        last_exit_code=134,
        # Recorded values describe the PRIOR activation that crashed:
        triggered_by="signal",
        signal_name="SIGABRT",
        exit_at="2026-09-15T21:26:47Z",
        detail="signum=6",
    )
    reason = launcher._classify_restart_reason(sd)
    assert reason == "external_signal_termination", (
        f"recorded signal crash must classify as external_signal_termination, "
        f"not {reason!r} (Rin HIGH regression)"
    )
    # Belt-and-braces: it MUST NOT silently downgrade to clean_24h_rotation.
    assert reason != "clean_24h_rotation"


def test_recorded_signal_handler_clean_exit_is_clean_24h_rotation() -> None:
    """Our SIGTERM/SIGINT handler ran cleanly → exit_code=0 → clean_24h_rotation.

    This is the proactive-24h rotation path (card 7d3b535d). When our
    shutdown handler catches the signal and exits 0 via ``sys.exit(0)``,
    the recorded exit has ``triggered_by="signal"`` and ``exit_code=0`` —
    the classifier must keep emitting ``clean_24h_rotation`` so the daily
    rotation cadence stays self-documenting.
    """
    sd = _make_sd_status(
        exit_source="recorded",
        triggered_by="signal",
        signal_name="SIGTERM",
        last_exit_code=0,  # our handler records 0 after sys.exit(0)
        exit_at="2026-09-15T21:26:47Z",
    )
    assert launcher._classify_restart_reason(sd) == "clean_24h_rotation"


def test_recorded_sys_exit_zero_is_clean_24h_rotation() -> None:
    """Explicit ``sys.exit(0)`` → ``clean_24h_rotation`` (intentional stop)."""
    sd = _make_sd_status(
        exit_source="recorded",
        triggered_by="sys_exit",
        last_exit_code=0,
        exit_at="2026-09-15T21:26:47Z",
        detail="intentional_stop",
    )
    assert launcher._classify_restart_reason(sd) == "clean_24h_rotation"


def test_recorded_sys_exit_one_is_pid_guard_or_launch_failure() -> None:
    """``sys.exit(1)`` (paper-on-live OR engine-start failure) → fault label."""
    sd = _make_sd_status(
        exit_source="recorded",
        triggered_by="sys_exit",
        # exit_code=1 (default from the int conversion in _record_last_exit)
        exit_at="2026-09-15T21:26:47Z",
        detail="paper_on_live_endpoint",
    )
    sd["last_exit_code"] = 1
    assert (
        launcher._classify_restart_reason(sd)
        == "pid_guard_or_launch_failure"
    )


def test_recorded_sys_exit_two_is_foreign_uid_signal_stats() -> None:
    """``sys.exit(2)`` (foreign-UID signal_stats rejection) → Sep 11 anomaly label."""
    sd = _make_sd_status(
        exit_source="recorded",
        triggered_by="sys_exit",
        exit_at="2026-09-15T21:26:47Z",
        detail="foreign_uid_signal_stats_rejection",
    )
    sd["last_exit_code"] = 2
    assert launcher._classify_restart_reason(sd) == "foreign_uid_signal_stats"


def test_recorded_sys_exit_unknown_code_is_unknown() -> None:
    """``sys.exit(7)`` (no matching branch) → ``unknown_exit_7`` for visibility."""
    sd = _make_sd_status(
        exit_source="recorded",
        triggered_by="sys_exit",
        exit_at="2026-09-15T21:26:47Z",
    )
    sd["last_exit_code"] = 7
    assert launcher._classify_restart_reason(sd) == "unknown_exit_7"


def test_recorded_exception_exit_labels_uncaught() -> None:
    """An uncaught exception in ``main()`` → ``uncaught_exception_exit_<n>``.

    Without the exception-recording wiring (card r2), an uncaught exception
    would propagate out of ``main()`` and Python would exit with code 1 but
    leave NO recorded file. The next restart would then see only the live
    unit's success state and mis-classify as ``clean_24h_rotation``.
    """
    sd = _make_sd_status(
        exit_source="recorded",
        triggered_by="exception",
        exit_at="2026-09-15T21:26:47Z",
        detail="RuntimeError: broker connection lost",
    )
    sd["last_exit_code"] = 1
    assert launcher._classify_restart_reason(sd) == "uncaught_exception_exit_1"


def test_recorded_atexit_clean_is_clean_24h_rotation() -> None:
    """atexit hook (implicit clean stop) → ``clean_24h_rotation``."""
    sd = _make_sd_status(
        exit_source="recorded",
        triggered_by="atexit",
        last_exit_code=0,
        exit_at="2026-09-15T21:26:47Z",
    )
    assert launcher._classify_restart_reason(sd) == "clean_24h_rotation"


# ── 4. Live fallback path (no recorded file) ──────────────────────────────


def test_live_fallback_watchdog() -> None:
    """``Result=watchdog`` → ``watchdog_timeout`` (live path, no record)."""
    sd = _make_sd_status(exit_source="live", last_result="watchdog", last_exit_code=None)
    assert launcher._classify_restart_reason(sd) == "watchdog_timeout"


def test_live_fallback_signal() -> None:
    """``Result=signal`` → ``external_signal_termination`` (live path)."""
    sd = _make_sd_status(exit_source="live", last_result="signal", last_exit_code=None)
    assert launcher._classify_restart_reason(sd) == "external_signal_termination"


def test_live_fallback_core_dump() -> None:
    """``Result=core-dump`` → ``core_dump`` (live path)."""
    sd = _make_sd_status(exit_source="live", last_result="core-dump", last_exit_code=None)
    assert launcher._classify_restart_reason(sd) == "core_dump"


def test_live_fallback_success_is_clean_24h_rotation() -> None:
    """Live Result=success, ExecMainStatus=0 → ``clean_24h_rotation`` (r1 contract).

    This test documents the r1 behaviour for the FALLBACK path only. The
    r2 fix does NOT change this — when no recorded file exists (e.g. first
    ever start, or a crash that bypassed our recording), the live path is
    the only signal available and we keep its r1 priority order.
    """
    sd = _make_sd_status(exit_source="live", last_result="success", last_exit_code=0)
    assert launcher._classify_restart_reason(sd) == "clean_24h_rotation"


def test_live_fallback_pre_startup_when_no_status() -> None:
    """``ExecMainStatus`` empty → ``pre_startup`` (service has never run)."""
    sd = _make_sd_status(exit_source="live", last_result="unknown", last_exit_code=None)
    assert launcher._classify_restart_reason(sd) == "pre_startup"


# ── 5. _read_systemd_restart_status: prefers recorded over live ────────────


def test_read_systemd_prefers_recorded_over_live_success(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: a recorded crash + a live success state → recorded wins.

    Mocks ``subprocess.run`` to return the live ``Result=success,
    ExecMainStatus=0`` (the masked state after Restart=always reactivation).
    Writes a recorded exit file with a SIGABRT crash. Verifies the returned
    ``sd_status`` has ``exit_source == "recorded"`` and the recorded exit
    code, NOT the live 0.
    """
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", tmp_path / "last_exit.json")
    recorded = {
        "exit_code": 134,
        "triggered_by": "signal",
        "signal_name": "SIGABRT",
        "detail": "signum=6",
        "exit_at": "2026-09-15T21:26:47Z",
        "pid": 2017001,
    }
    tmp_path.joinpath("last_exit.json").write_text(json.dumps(recorded, indent=2))

    # Mock the systemctl call to return the live success state.
    systemctl_output = "\n".join([
        "NRestarts=12",
        "ActiveEnterTimestamp=Tue 2026-09-15 21:27:17 UTC",
        "Result=success",
        "ExecMainStatus=0/SUCCESS",
        "",
    ])

    class _FakeProc:
        returncode = 0
        stdout = systemctl_output

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _FakeProc(),
    )

    sd = launcher._read_systemd_restart_status()
    assert sd["exit_source"] == "recorded"
    assert sd["last_exit_code"] == 134
    assert sd["last_exit_triggered_by"] == "signal"
    assert sd["last_exit_signal_name"] == "SIGABRT"
    # The synthesized last_result reflects the recorded signal path:
    assert sd["last_result"] == "recorded-signal"
    # And the classifier emits the fault label, NOT clean_24h_rotation.
    assert launcher._classify_restart_reason(sd) == "external_signal_termination"


def test_read_systemd_falls_back_to_live_when_no_record(tmp_path: Path, monkeypatch) -> None:
    """No recorded file → uses the live path (r1 behaviour)."""
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", tmp_path / "nope.json")

    systemctl_output = "\n".join([
        "NRestarts=12",
        "ActiveEnterTimestamp=Tue 2026-09-15 21:27:17 UTC",
        "Result=watchdog",
        "ExecMainStatus=0/SUCCESS",
        "",
    ])

    class _FakeProc:
        returncode = 0
        stdout = systemctl_output

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _FakeProc(),
    )

    sd = launcher._read_systemd_restart_status()
    assert sd["exit_source"] == "live"
    assert sd["last_result"] == "watchdog"
    assert launcher._classify_restart_reason(sd) == "watchdog_timeout"


def test_read_systemd_returns_none_when_neither_available(tmp_path: Path, monkeypatch) -> None:
    """No record AND systemctl fails → ``exit_source == "none"``."""
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", tmp_path / "nope.json")

    class _FakeProc:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _FakeProc(),
    )

    sd = launcher._read_systemd_restart_status()
    assert sd["exit_source"] == "none"
    assert sd["n_restarts"] == 0
    # Classifier falls through to ``pre_startup`` when no signal is available.
    assert launcher._classify_restart_reason(sd) == "pre_startup"


# ── 5b. Journal path: covers untrapped signals (SIGKILL, SIGABRT, SIGSEGV) ─


def test_journal_signal_abrt_classifies_as_external_signal_termination(tmp_path: Path, monkeypatch) -> None:
    """Rin HIGH finding (full coverage): SIGABRT crash followed by successful
    Restart=always reactivation must classify as ``external_signal_termination``.

    Scenario: the process crashed with SIGABRT (untrapped, so no recorded
    file). The journal records ``Main process exited, code=killed,
    status=6/ABRT`` from the prior PID. Restart=always re-launched the
    process; the current activation reports Result=success, ExecMainStatus=0.

    Without the journal path, the classifier would fall through to the live
    path and mis-classify as ``clean_24h_rotation``. The journal path
    closes this gap.
    """
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", tmp_path / "nope.json")

    # Mock systemctl: returns MainPID for the CURRENT activation plus masked
    # live state (Result=success, ExecMainStatus=0) for the reactivated run.
    systemctl_output = "\n".join([
        "NRestarts=12",
        "MainPID=2017001",
        "ActiveEnterTimestamp=Tue 2026-09-15 21:27:17 UTC",
        "Result=success",
        "ExecMainStatus=0/SUCCESS",
        "",
    ])

    # Mock journalctl: returns a PRIOR activation's SIGABRT exit (pid 1357880,
    # NOT 2017001 which is the current MainPID).
    journal_lines = [
        json.dumps({
            "_PID": "1357880",
            "__REALTIME_TIMESTAMP": "2026-09-15T21:26:48Z",
            "MESSAGE": "Main process exited, code=killed, status=6/ABRT",
        }),
        # A current-activation entry that MUST be excluded by MainPID filter.
        json.dumps({
            "_PID": "2017001",
            "__REALTIME_TIMESTAMP": "2026-09-15T21:27:17Z",
            "MESSAGE": "Main process exited, code=exited, status=0/SUCCESS",
        }),
        "",
    ]
    journal_output = "\n".join(journal_lines)

    def _fake_run(argv, **kw):
        cmd = argv[0] if argv else ""
        proc = type("_FakeProc", (), {})()
        if cmd == "/usr/bin/systemctl":
            proc.returncode = 0
            proc.stdout = systemctl_output
        elif cmd == "/usr/bin/journalctl":
            proc.returncode = 0
            proc.stdout = journal_output
        else:
            proc.returncode = 1
            proc.stdout = ""
        return proc

    monkeypatch.setattr("subprocess.run", _fake_run)

    sd = launcher._read_systemd_restart_status()
    assert sd["exit_source"] == "journal", (
        f"expected journal source when no recorded file and journal has prior exit; "
        f"got exit_source={sd['exit_source']!r}"
    )
    assert sd["last_exit_triggered_by"] == "signal"
    assert sd["last_exit_signal_name"] == "ABRT"
    assert sd["last_exit_code"] == 6
    # CRITICAL: the prior activation was a SIGABRT crash, not a clean rotation.
    assert launcher._classify_restart_reason(sd) == "external_signal_termination"


def test_journal_excludes_current_main_pid(tmp_path: Path, monkeypatch) -> None:
    """The journal query MUST exclude entries from the current MainPID.

    Without this exclusion, the CURRENT activation's success log entry
    would be returned and the classifier would emit ``clean_24h_rotation``
    — the exact mask Rin flagged.
    """
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", tmp_path / "nope.json")

    systemctl_output = "\n".join([
        "NRestarts=12",
        "MainPID=9999",
        "ActiveEnterTimestamp=Tue 2026-09-15 21:27:17 UTC",
        "Result=success",
        "ExecMainStatus=0/SUCCESS",
        "",
    ])
    # Only the CURRENT activation's entries are present (no prior activation).
    journal_lines = [
        json.dumps({
            "_PID": "9999",  # current MainPID — must be excluded
            "__REALTIME_TIMESTAMP": "2026-09-15T21:27:17Z",
            "MESSAGE": "Main process exited, code=exited, status=0/SUCCESS",
        }),
        "",
    ]
    journal_output = "\n".join(journal_lines)

    def _fake_run(argv, **kw):
        cmd = argv[0] if argv else ""
        proc = type("_FakeProc", (), {})()
        if cmd == "/usr/bin/systemctl":
            proc.returncode = 0
            proc.stdout = systemctl_output
        elif cmd == "/usr/bin/journalctl":
            proc.returncode = 0
            proc.stdout = journal_output
        else:
            proc.returncode = 1
            proc.stdout = ""
        return proc

    monkeypatch.setattr("subprocess.run", _fake_run)

    sd = launcher._read_systemd_restart_status()
    # The current MainPID was the only PID in the journal → no prior
    # activation distinguishable → fall back to live path.
    assert sd["exit_source"] == "live"


def test_journal_unavailable_falls_back_to_live(tmp_path: Path, monkeypatch) -> None:
    """When journalctl fails AND no recorded file exists, fall back to live."""
    monkeypatch.setattr(launcher, "_LAST_EXIT_RECORD_PATH", tmp_path / "nope.json")

    systemctl_output = "\n".join([
        "NRestarts=12",
        "MainPID=9999",
        "Result=watchdog",
        "ExecMainStatus=0/SUCCESS",
        "",
    ])

    def _fake_run(argv, **kw):
        cmd = argv[0] if argv else ""
        proc = type("_FakeProc", (), {})()
        if cmd == "/usr/bin/systemctl":
            proc.returncode = 0
            proc.stdout = systemctl_output
        elif cmd == "/usr/bin/journalctl":
            # Simulate journalctl unavailable (permission denied).
            proc.returncode = 1
            proc.stdout = ""
        else:
            proc.returncode = 1
            proc.stdout = ""
        return proc

    monkeypatch.setattr("subprocess.run", _fake_run)

    sd = launcher._read_systemd_restart_status()
    assert sd["exit_source"] == "live"
    assert launcher._classify_restart_reason(sd) == "watchdog_timeout"


# ── 6. End-to-end smoke: launcher imports cleanly with the r2 wiring ──────


def test_launcher_module_imports_with_recorded_exit_path() -> None:
    """Smoke test: the launcher module exposes the r2 surface area.

    Verifies the constants and helpers added in r2 are importable and have
    the expected names. If we got here, import succeeded; this just
    confirms the surface contract.
    """
    assert hasattr(launcher, "_LAST_EXIT_RECORD_PATH")
    assert hasattr(launcher, "_record_last_exit")
    assert hasattr(launcher, "_read_last_exit_record")
    assert hasattr(launcher, "_signal_name_for")
    assert hasattr(launcher, "_read_journal_last_exit")
    # Classifier signature changed to take the full sd_status dict.
    # Under ``from __future__ import annotations`` annotations are strings,
    # so accept either form.
    import inspect
    sig_obj = inspect.signature(launcher._classify_restart_reason)
    params = list(sig_obj.parameters.values())
    assert len(params) == 1, (
        f"_classify_restart_reason should take exactly one positional "
        f"arg (sd_status dict); got {len(params)}"
    )
    ann = params[0].annotation
    assert ann is dict or ann == "dict" or ann == dict, (
        f"_classify_restart_reason param must be typed as dict; got {ann!r}"
    )
