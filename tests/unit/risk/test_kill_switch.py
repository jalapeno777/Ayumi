"""Unit tests for Kill Switch Manager (Phase 1E.1).

Tests cover:
  - Activate/deactivate global kill
  - Activate/deactivate global freeze
  - State persistence to file (write + reload)
  - Corrupt file → defaults to KILL (fail-safe)
  - Atomic write (no partial reads)
  - History audit log
  - is_globally_killed() performance (< 1ms)
  - CLI tool integration
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

from _project_root import PROJECT_ROOT

from adapters.ctrader.kill_switch import (
    GlobalKillState,
    KillSwitchManager,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _enable_kill_switch_for_tests():
    """Enable kill switch in-process for testing.

    Production has _disabled=True (Craig directive Jun 27). Tests need it
    enabled to verify activation/persistence logic. Restored after each test.
    """
    original = KillSwitchManager._disabled
    KillSwitchManager._disabled = False
    yield
    KillSwitchManager._disabled = original


@pytest.fixture
def tmp_state_dir(tmp_path):
    """Provide a temporary state directory."""
    d = tmp_path / "kill_switches"
    d.mkdir()
    return str(d)


@pytest.fixture
def ksm(tmp_state_dir):
    """Fresh KillSwitchManager with temp state dir."""
    return KillSwitchManager(state_dir=tmp_state_dir)


# ── Activate/Deactivate Global Kill ──────────────────────────────────────────


class TestGlobalKill:
    def test_inactive_on_fresh_start(self, ksm):
        assert not ksm.is_globally_killed()
        assert not ksm.is_globally_frozen()
        assert not ksm.is_active()

    def test_activate_global_kill(self, ksm):
        ksm.activate_global_kill(
            reason="test_kill",
            triggered_by="test_suite",
        )
        assert ksm.is_globally_killed()
        assert not ksm.is_globally_frozen()
        assert ksm.is_active()

    def test_deactivate_global_kill(self, ksm):
        ksm.activate_global_kill(reason="test", triggered_by="test")
        assert ksm.is_globally_killed()

        ksm.deactivate(reason="test_recovery")
        assert not ksm.is_globally_killed()
        assert not ksm.is_active()

    def test_kill_status_dict(self, ksm):
        ksm.activate_global_kill(
            reason="manual",
            triggered_by="operator",
            close_positions=True,
        )
        status = ksm.get_status()
        assert status["active"] is True
        assert status["mode"] == "kill"
        assert status["reason"] == "manual"
        assert status["triggered_by"] == "operator"
        assert status["level"] == "global"
        assert status["positions_closed"] is False  # not yet closed

    def test_reactivate_kill_updates_reason(self, ksm):
        ksm.activate_global_kill(reason="first", triggered_by="test")
        ksm.activate_global_kill(reason="second", triggered_by="test")
        status = ksm.get_status()
        assert status["reason"] == "second"
        assert ksm.is_globally_killed()


# ── Activate/Deactivate Global Freeze ────────────────────────────────────────


class TestGlobalFreeze:
    def test_activate_global_freeze(self, ksm):
        ksm.activate_global_freeze(
            reason="spread_widening",
            triggered_by="monitor",
        )
        assert ksm.is_globally_frozen()
        assert not ksm.is_globally_killed()
        assert ksm.is_active()

    def test_deactivate_global_freeze(self, ksm):
        ksm.activate_global_freeze(reason="test", triggered_by="test")
        assert ksm.is_globally_frozen()

        ksm.deactivate(reason="recovery")
        assert not ksm.is_globally_frozen()
        assert not ksm.is_active()

    def test_freeze_to_kill_escalation(self, ksm):
        ksm.activate_global_freeze(reason="freeze_first", triggered_by="test")
        assert ksm.is_globally_frozen()
        assert not ksm.is_globally_killed()

        ksm.activate_global_kill(reason="escalate", triggered_by="test")
        assert ksm.is_globally_killed()
        assert not ksm.is_globally_frozen()

    def test_freeze_status_dict(self, ksm):
        ksm.activate_global_freeze(reason="monitoring", triggered_by="auto")
        status = ksm.get_status()
        assert status["active"] is True
        assert status["mode"] == "freeze"
        assert status["reason"] == "monitoring"


# ── State Persistence ─────────────────────────────────────────────────────────


class TestStatePersistence:
    def test_state_persists_to_file(self, tmp_state_dir):
        ksm1 = KillSwitchManager(state_dir=tmp_state_dir)
        ksm1.activate_global_kill(reason="persist_test", triggered_by="test")

        # State file should exist
        state_file = Path(tmp_state_dir) / "global.state"
        assert state_file.exists()

        # Verify file contents
        data = json.loads(state_file.read_text())
        assert data["active"] is True
        assert data["mode"] == "kill"
        assert data["reason"] == "persist_test"

    def test_state_reload_on_new_instance(self, tmp_state_dir):
        ksm1 = KillSwitchManager(state_dir=tmp_state_dir)
        ksm1.activate_global_kill(reason="reload_test", triggered_by="test")

        # Create a new instance pointing to same state dir
        ksm2 = KillSwitchManager(state_dir=tmp_state_dir)
        assert ksm2.is_globally_killed()
        assert ksm2.get_status()["reason"] == "reload_test"

    def test_inactive_state_persists(self, tmp_state_dir):
        ksm1 = KillSwitchManager(state_dir=tmp_state_dir)
        ksm1.activate_global_kill(reason="temp", triggered_by="test")
        ksm1.deactivate(reason="manual")

        ksm2 = KillSwitchManager(state_dir=tmp_state_dir)
        assert not ksm2.is_globally_killed()
        assert not ksm2.is_active()

    def test_freeze_state_persists_across_reload(self, tmp_state_dir):
        ksm1 = KillSwitchManager(state_dir=tmp_state_dir)
        ksm1.activate_global_freeze(reason="freeze_persist", triggered_by="test")

        ksm2 = KillSwitchManager(state_dir=tmp_state_dir)
        assert ksm2.is_globally_frozen()
        assert not ksm2.is_globally_killed()


# ── Corrupt File Handling ────────────────────────────────────────────────────


class TestCorruptFile:
    def test_corrupt_file_defaults_to_kill(self, tmp_state_dir):
        # Write corrupt state file
        state_file = Path(tmp_state_dir) / "global.state"
        state_file.write_text("{ broken json {{{")

        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        # Fail-safe: should default to KILL
        assert ksm.is_globally_killed()

    def test_corrupt_file_logs_critical(self, tmp_state_dir, caplog):
        import logging

        state_file = Path(tmp_state_dir) / "global.state"
        state_file.write_text("not json at all")

        with caplog.at_level(logging.CRITICAL):
            _ksm = KillSwitchManager(state_dir=tmp_state_dir)

        assert any("CORRUPT" in record.message for record in caplog.records)

    def test_corrupt_file_writes_valid_state(self, tmp_state_dir):
        state_file = Path(tmp_state_dir) / "global.state"
        state_file.write_text("garbage")

        _ksm = KillSwitchManager(state_dir=tmp_state_dir)
        # After fail-safe activation, state file should be valid
        data = json.loads(state_file.read_text())
        assert data["active"] is True
        assert data["mode"] == "kill"

    def test_missing_state_file_starts_inactive(self, tmp_state_dir):
        # Don't create the file — should start fresh
        ksm = KillSwitchManager(state_dir=tmp_state_dir)
        assert not ksm.is_active()


# ── Atomic Write ──────────────────────────────────────────────────────────────


class TestAtomicWrite:
    def test_no_temp_files_left_after_write(self, ksm, tmp_state_dir):
        ksm.activate_global_kill(reason="atomic_test", triggered_by="test")

        # Check no .tmp files left in state dir
        state_dir = Path(tmp_state_dir)
        tmp_files = list(state_dir.glob(".global.state.*.tmp"))
        assert len(tmp_files) == 0, f"Temp files left behind: {tmp_files}"

    def test_state_file_is_valid_json(self, ksm, tmp_state_dir):
        ksm.activate_global_kill(reason="json_test", triggered_by="test")

        state_file = Path(tmp_state_dir) / "global.state"
        # Should be parseable as JSON
        data = json.loads(state_file.read_text())
        assert isinstance(data, dict)
        assert "active" in data
        assert "mode" in data

    def test_multiple_rapid_writes(self, ksm, tmp_state_dir):
        """Rapidly toggle kill switch to stress-test atomic writes."""
        for i in range(20):
            ksm.activate_global_kill(reason=f"rapid_{i}", triggered_by="stress")
            ksm.deactivate(reason=f"recover_{i}")

        # Final state should be valid
        state_file = Path(tmp_state_dir) / "global.state"
        data = json.loads(state_file.read_text())
        assert data["active"] is False


# ── History Audit Log ────────────────────────────────────────────────────────


class TestHistoryLog:
    def test_history_logged_on_activate(self, ksm, tmp_state_dir):
        ksm.activate_global_kill(reason="audit_test", triggered_by="auditor")

        history_file = Path(tmp_state_dir) / "history.jsonl"
        assert history_file.exists()

        lines = history_file.read_text().strip().split("\n")
        assert len(lines) >= 1

        event = json.loads(lines[-1])
        assert event["event"] == "activated"
        assert event["mode"] == "kill"
        assert event["reason"] == "audit_test"
        assert event["triggered_by"] == "auditor"

    def test_history_logged_on_deactivate(self, ksm, tmp_state_dir):
        ksm.activate_global_kill(reason="test", triggered_by="test")
        ksm.deactivate(reason="audit_recovery")

        history_file = Path(tmp_state_dir) / "history.jsonl"
        lines = history_file.read_text().strip().split("\n")
        events = [json.loads(l) for l in lines]

        deactivate_events = [e for e in events if e["event"] == "deactivated"]
        assert len(deactivate_events) >= 1
        assert deactivate_events[-1]["reason"] == "audit_recovery"

    def test_history_is_append_only(self, ksm, tmp_state_dir):
        ksm.activate_global_kill(reason="first", triggered_by="test")
        ksm.deactivate(reason="mid")
        ksm.activate_global_freeze(reason="third", triggered_by="test")

        history_file = Path(tmp_state_dir) / "history.jsonl"
        lines = history_file.read_text().strip().split("\n")
        events = [json.loads(l) for l in lines]

        # Should have: activated, deactivated, activated (3 events)
        assert len(events) == 3
        assert events[0]["event"] == "activated"
        assert events[0]["mode"] == "kill"
        assert events[1]["event"] == "deactivated"
        assert events[2]["event"] == "activated"
        assert events[2]["mode"] == "freeze"

    def test_positions_closed_logged(self, ksm, tmp_state_dir):
        ksm.activate_global_kill(reason="close_test", triggered_by="test")
        ksm.record_positions_closed(count=3)

        history_file = Path(tmp_state_dir) / "history.jsonl"
        lines = history_file.read_text().strip().split("\n")
        events = [json.loads(l) for l in lines]

        close_events = [e for e in events if e["event"] == "positions_closed"]
        assert len(close_events) == 1
        assert close_events[0]["count"] == 3


# ── Performance ───────────────────────────────────────────────────────────────


class TestPerformance:
    def test_is_globally_killed_under_1ms(self, ksm):
        ksm.activate_global_kill(reason="perf_test", triggered_by="test")

        # Warm up
        for _ in range(100):
            ksm.is_globally_killed()

        # Measure
        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            ksm.is_globally_killed()
        elapsed = time.perf_counter() - start
        per_call_us = (elapsed / iterations) * 1_000_000

        # Must be well under 1ms (1000μs). Target is < 0.01ms (10μs).
        assert per_call_us < 1000, (
            f"is_globally_killed() took {per_call_us:.2f}μs per call (target: < 1000μs)"
        )

    def test_is_globally_frozen_under_1ms(self, ksm):
        ksm.activate_global_freeze(reason="perf_test", triggered_by="test")

        # Warm up
        for _ in range(100):
            ksm.is_globally_frozen()

        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            ksm.is_globally_frozen()
        elapsed = time.perf_counter() - start
        per_call_us = (elapsed / iterations) * 1_000_000

        assert per_call_us < 1000, (
            f"is_globally_frozen() took {per_call_us:.2f}μs per call (target: < 1000μs)"
        )

    def test_inactive_check_under_1ms(self, ksm):
        # Test fast path when NOT killed (most common case)
        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            ksm.is_globally_killed()
        elapsed = time.perf_counter() - start
        per_call_us = (elapsed / iterations) * 1_000_000

        assert per_call_us < 1000


# ── CLI Tool Integration ─────────────────────────────────────────────────────


@pytest.mark.skipif(
    KillSwitchManager._disabled,
    reason="CLI tests require kill switch enabled, but production has _disabled=True (Craig directive)",
)
class TestCLI:
    @pytest.fixture
    def cli_env(self, tmp_state_dir):
        """Environment for CLI tests."""
        return {
            "state_dir": tmp_state_dir,
            "script": str(PROJECT_ROOT / "scripts" / "kill_switch.py"),
            "python": str(PROJECT_ROOT / ".venv" / "bin" / "python"),
        }

    def test_cli_status_inactive(self, cli_env):
        result = subprocess.run(
            [
                cli_env["python"],
                cli_env["script"],
                "--state-dir",
                cli_env["state_dir"],
                "status",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "INACTIVE" in result.stdout

    def test_cli_kill(self, cli_env):
        # Activate kill
        result = subprocess.run(
            [
                cli_env["python"],
                cli_env["script"],
                "--state-dir",
                cli_env["state_dir"],
                "kill",
                "--reason",
                "cli_test",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "KILL" in result.stdout

        # Verify via status
        result = subprocess.run(
            [
                cli_env["python"],
                cli_env["script"],
                "--state-dir",
                cli_env["state_dir"],
                "status",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "ACTIVE" in result.stdout
        assert "KILL" in result.stdout
        assert "cli_test" in result.stdout

    def test_cli_freeze(self, cli_env):
        result = subprocess.run(
            [
                cli_env["python"],
                cli_env["script"],
                "--state-dir",
                cli_env["state_dir"],
                "freeze",
                "--reason",
                "freeze_cli",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "FREEZE" in result.stdout

        result = subprocess.run(
            [
                cli_env["python"],
                cli_env["script"],
                "--state-dir",
                cli_env["state_dir"],
                "status",
            ],
            capture_output=True,
            text=True,
        )
        assert "FREEZE" in result.stdout

    def test_cli_recover(self, cli_env):
        # Kill first
        subprocess.run(
            [
                cli_env["python"],
                cli_env["script"],
                "--state-dir",
                cli_env["state_dir"],
                "kill",
                "--reason",
                "temp",
            ],
            capture_output=True,
            text=True,
        )

        # Recover
        result = subprocess.run(
            [
                cli_env["python"],
                cli_env["script"],
                "--state-dir",
                cli_env["state_dir"],
                "recover",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "DEACTIVATED" in result.stdout

        # Verify inactive
        result = subprocess.run(
            [
                cli_env["python"],
                cli_env["script"],
                "--state-dir",
                cli_env["state_dir"],
                "status",
            ],
            capture_output=True,
            text=True,
        )
        assert "INACTIVE" in result.stdout


# ── GlobalKillState Dataclass ────────────────────────────────────────────────


class TestGlobalKillState:
    def test_default_state(self):
        state = GlobalKillState()
        assert state.active is False
        assert state.mode == "kill"
        assert state.version == 1

    def test_round_trip_serialization(self):
        original = GlobalKillState(
            active=True,
            mode="freeze",
            reason="test_round",
            triggered_by="unit_test",
            triggered_at="2026-06-05T14:00:00Z",
        )
        d = original.to_dict()
        restored = GlobalKillState.from_dict(d)

        assert restored.active == original.active
        assert restored.mode == original.mode
        assert restored.reason == original.reason
        assert restored.triggered_by == original.triggered_by
        assert restored.triggered_at == original.triggered_at
