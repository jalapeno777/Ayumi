from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monitoring.cycle_detector import CycleDetector


def _append(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def _entry(pattern_name: str, *, applied: bool = True, days_ago: int = 0) -> dict:
    return {
        "pattern_name": pattern_name,
        "applied": applied,
        "action_taken": "test",
        "evidence": "test",
        "timestamp": (
            datetime.now(timezone.utc) - timedelta(days=days_ago)
        ).isoformat(),
    }


def test_check_recent_cycles_returns_false_at_threshold(tmp_path):
    log_path = tmp_path / "data/ops/remediation_log.jsonl"
    queue_path = tmp_path / "data/ops/escalation_queue.jsonl"
    for _ in range(3):
        _append(log_path, _entry("stale_pid_file"))

    detector = CycleDetector(log_path, queue_path)

    assert detector.check_recent_cycles("stale_pid_file", days=7, threshold=3) is False
    assert not queue_path.exists()


def test_check_recent_cycles_escalates_code_fix_candidate_over_threshold(tmp_path):
    log_path = tmp_path / "data/ops/remediation_log.jsonl"
    queue_path = tmp_path / "data/ops/escalation_queue.jsonl"
    for _ in range(4):
        _append(log_path, _entry("stale_pid_file"))
    _append(log_path, _entry("stale_pid_file", days_ago=9))
    _append(log_path, _entry("stale_pid_file", applied=False))
    _append(log_path, _entry("signal_stats_root_owned"))

    detector = CycleDetector(log_path, queue_path)

    assert detector.check_recent_cycles("stale_pid_file", days=7, threshold=3) is True
    queue_entries = [
        json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()
    ]
    assert queue_entries[-1]["pattern_name"] == "stale_pid_file"
    assert queue_entries[-1]["classification"] == "code-fix candidate"
    assert "4 times" in queue_entries[-1]["reason"]
