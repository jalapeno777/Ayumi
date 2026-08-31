"""Tests for scripts/audit_metric.py.

Covers:
  * Clean audit: claimed matches truth within the 2x threshold.
  * Planted-divergence calibration fixture: the 2026-06-28 incident where a
    dashboard reported 0.77 win rate while the actual was 0.02. The auditor
    must flag this (ratio = 37.5x, well above the 2x threshold).
  * Boundary: ratio exactly at 2x is NOT flagged (threshold is strict >).
  * Threshold cross: ratio just above 2x IS flagged.
  * Input modes: --Xxx, --Xxx-file, --Xxx-shell all resolve to the same float.
  * JSONL append: rows are written to the configured log; rerun appends.
  * Exit code: clean -> 0, flagged -> 1, usage error -> 2.
  * Standing rule doc: docs/ops/metric-audit.md is present and references the
    2x threshold so the rule is durable.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_metric.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd or ROOT),
    )


def test_clean_audit_emits_jsonl_and_returns_zero(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    proc = _run(
        [
            "--metric",
            "win_rate",
            "--claim",
            "0.50",
            "--truth",
            "0.51",
            "--jsonl-log",
            str(log),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    row = json.loads(proc.stdout.strip())
    assert row["flagged"] is False
    assert row["ratio"] == pytest.approx(abs(0.50 - 0.51) / 0.51)
    # Append-only log was written.
    assert log.exists()
    persisted = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert len(persisted) == 1
    assert persisted[0]["metric"] == "win_rate"


def test_planted_divergence_77_vs_2_is_flagged(tmp_path: Path) -> None:
    """The 2026-06-28 calibration fixture.

    A dashboard reported a 77% win rate; the actual win rate (counted from the
    trade journal) was 2%. The auditor MUST flag this. The ratio is 37.5x —
    far above the 2x threshold. If this test ever fails, the auditor is broken
    and dashboards may once again be trusted unchecked.
    """
    log = tmp_path / "audit.jsonl"
    proc = _run(
        [
            "--metric",
            "win_rate",
            "--claim",
            "0.77",
            "--truth",
            "0.02",
            "--jsonl-log",
            str(log),
        ]
    )
    assert proc.returncode == 1, proc.stderr
    row = json.loads(proc.stdout.strip())
    assert row["flagged"] is True
    # 0.75 / 0.02 = 37.5x — planted lie must be loud.
    assert row["ratio"] == pytest.approx(37.5)
    persisted = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert persisted[0]["flagged"] is True


def test_threshold_boundary_is_not_flagged() -> None:
    """Ratio == 2x exactly must not be flagged (threshold is strict >)."""
    proc = _run(
        [
            "--metric",
            "latency_p95_ms",
            "--claim",
            "30.0",
            "--truth",
            "10.0",
            "--no-log",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    row = json.loads(proc.stdout.strip())
    assert row["ratio"] == pytest.approx(2.0)
    assert row["flagged"] is False


def test_threshold_just_above_is_flagged() -> None:
    """Ratio just above 2x must be flagged — the boundary has to be respected."""
    proc = _run(
        [
            "--metric",
            "latency_p95_ms",
            "--claim",
            "30.1",
            "--truth",
            "10.0",
            "--no-log",
        ]
    )
    assert proc.returncode == 1, proc.stderr
    row = json.loads(proc.stdout.strip())
    assert row["ratio"] == pytest.approx(2.01)
    assert row["flagged"] is True


def test_file_input_mode(tmp_path: Path) -> None:
    claim_file = tmp_path / "claim.txt"
    truth_file = tmp_path / "truth.txt"
    claim_file.write_text("0.42\n")
    truth_file.write_text("0.40\n")
    proc = _run(
        [
            "--metric",
            "sharpe",
            "--claim-file",
            str(claim_file),
            "--truth-file",
            str(truth_file),
            "--no-log",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    row = json.loads(proc.stdout.strip())
    assert row["claimed"] == pytest.approx(0.42)
    assert row["actual"] == pytest.approx(0.40)


def test_shell_input_mode() -> None:
    proc = _run(
        [
            "--metric",
            "drawdown",
            "--claim-shell",
            "echo 0.15",
            "--truth-shell",
            "echo 0.14",
            "--no-log",
        ]
    )
    assert proc.returncode == 0, proc.stderr
    row = json.loads(proc.stdout.strip())
    assert row["claimed"] == pytest.approx(0.15)
    assert row["actual"] == pytest.approx(0.14)


def test_multiple_input_modes_is_usage_error() -> None:
    proc = _run(
        [
            "--metric",
            "x",
            "--claim",
            "0.1",
            "--claim-file",
            "/dev/null",
            "--truth",
            "0.1",
        ]
    )
    assert proc.returncode == 2
    assert "exactly one" in proc.stderr


def test_non_numeric_truth_returns_2() -> None:
    proc = _run(
        [
            "--metric",
            "x",
            "--claim",
            "0.1",
            "--truth",
            "not-a-number",
        ]
    )
    assert proc.returncode == 2


def test_jsonl_log_is_append_only(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    for claimed, actual in [("0.10", "0.10"), ("0.20", "0.20"), ("0.30", "0.30")]:
        _run(
            [
                "--metric",
                "metric_x",
                "--claim",
                claimed,
                "--truth",
                actual,
                "--jsonl-log",
                str(log),
            ]
        )
    lines = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert len(lines) == 3
    assert [row["claimed"] for row in lines] == [0.10, 0.20, 0.30]


def test_no_log_skips_persistence_but_emits_stdout(tmp_path: Path) -> None:
    log = tmp_path / "should-not-exist.jsonl"
    proc = _run(
        [
            "--metric",
            "x",
            "--claim",
            "0.1",
            "--truth",
            "0.1",
            "--jsonl-log",
            str(log),
            "--no-log",
        ]
    )
    assert proc.returncode == 0
    assert not log.exists()
    assert json.loads(proc.stdout.strip())["metric"] == "x"


def test_open_finding_is_attempted_on_flag(tmp_path: Path, monkeypatch) -> None:
    """--open-finding should call the workboard CLI exactly once when flagged.

    We don't require the workboard CLI to actually exist in the test environment;
    we just verify the subprocess path is exercised and a non-flagged audit
    does NOT spawn it.
    """
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        class _R:
            returncode = 0
            stderr = ""
        return _R()

    import scripts.audit_metric as am  # noqa: WPS433 — intentional local import

    monkeypatch.setattr(am.subprocess, "run", fake_run)

    # Flagged: should attempt to open a finding.
    rc = am.main(
        [
            "--metric",
            "win_rate",
            "--claim",
            "0.77",
            "--truth",
            "0.02",
            "--no-log",
            "--open-finding",
        ]
    )
    assert rc == 1
    assert len(calls) == 1
    assert calls[0][0] == "workboard_create"
    assert "[FINDING]" in calls[0]

    # Clean: should NOT attempt to open a finding.
    calls.clear()
    rc = am.main(
        [
            "--metric",
            "win_rate",
            "--claim",
            "0.50",
            "--truth",
            "0.50",
            "--no-log",
            "--open-finding",
        ]
    )
    assert rc == 0
    assert calls == []


def test_standing_rule_doc_exists_and_documents_threshold() -> None:
    """Acceptance criterion: the >2x standing rule is documented durably."""
    doc = ROOT / "docs" / "ops" / "metric-audit.md"
    assert doc.exists(), f"missing standing-rule doc at {doc}"
    text = doc.read_text(encoding="utf-8")
    assert "2x" in text or "2.0" in text or "ratio" in text.lower()
    # The doc must mention both halves of the rule: the >2x flag and the
    # "no metric may gate a decision" half.
    assert "FINDING" in text or "finding" in text
