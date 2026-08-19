from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monitoring import remediation_actions as remediation


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_stale_audit_log_recreates_missing_remediation_flag(tmp_path):
    audit_doc = tmp_path / remediation.REMEDIATION_AUDIT_DOC
    audit_doc.parent.mkdir(parents=True)
    audit_doc.write_text("validated remediation audit\n", encoding="utf-8")

    result = remediation.detect_and_remediate("stale_audit_log", project_root=tmp_path)

    assert result.applied is True
    assert result.action_taken == "touch data/ayumi/remediation_validated.flag"
    assert (tmp_path / remediation.REMEDIATION_VALIDATED_FLAG).exists()
    log_entries = _read_jsonl(tmp_path / remediation.REMEDIATION_LOG_PATH)
    assert log_entries[-1]["pattern_name"] == "stale_audit_log"
    assert log_entries[-1]["applied"] is True


def test_signal_stats_owner_remediation_chowns_runtime_file(tmp_path, monkeypatch):
    signal_stats = tmp_path / remediation.SIGNAL_STATS_PATH
    signal_stats.parent.mkdir(parents=True)
    signal_stats.write_text("{}\n", encoding="utf-8")

    actual = signal_stats.stat()
    expected_uid = actual.st_uid + 1 if actual.st_uid < 60000 else actual.st_uid - 1
    expected_gid = actual.st_gid + 1 if actual.st_gid < 60000 else actual.st_gid - 1
    monkeypatch.setattr(
        remediation,
        "_resolve_runtime_identity",
        lambda project_root: (expected_uid, expected_gid, "runtime", "runtime"),
    )
    calls = []

    def fake_chown(path, uid, gid):
        calls.append((Path(path), uid, gid))

    monkeypatch.setattr(remediation.os, "chown", fake_chown)

    result = remediation.detect_and_remediate(
        "signal_stats_root_owned", project_root=tmp_path
    )

    assert result.applied is True
    assert result.action_taken == "chown_to_runtime_user(data/signal_stats.jsonl)"
    assert calls == [(signal_stats, expected_uid, expected_gid)]
    assert "expected runtime:runtime" in result.evidence


def test_stale_pid_file_remediation_removes_dead_forward_test_pid(
    tmp_path, monkeypatch
):
    pid_file = tmp_path / remediation.FORWARD_TEST_PID_PATH
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("424242\n", encoding="utf-8")
    monkeypatch.setattr(remediation, "_pid_is_alive", lambda pid: False)

    result = remediation.detect_and_remediate("stale_pid_file", project_root=tmp_path)

    assert result.applied is True
    assert result.action_taken == "remove_pid_file(data/forward_test.pid)"
    assert not pid_file.exists()
    assert "dead pid 424242" in result.evidence


def test_balance_snapshot_stale_remediation_refreshes_last_save_ts(tmp_path):
    state_file = tmp_path / remediation.RISK_GUARD_STATE_PATH
    state_file.parent.mkdir(parents=True)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    state_file.write_text(
        json.dumps(
            {
                "peak_balance": 100000.0,
                "current_balance": 100000.0,
                "daily_start_balance": 100000.0,
                "last_save_ts": old_ts,
            }
        ),
        encoding="utf-8",
    )

    result = remediation.detect_and_remediate(
        "balance_snapshot_stale", project_root=tmp_path
    )

    assert result.applied is True
    assert result.action_taken == "force_risk_guard_save()"
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["current_balance"] == 100000.0
    assert datetime.fromisoformat(payload["last_save_ts"]) > datetime.fromisoformat(
        old_ts
    )
    assert "exceeds 60 minutes" in result.evidence
