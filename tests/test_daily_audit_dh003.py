"""Targeted tests for DH-003 signal_stats staleness re-key (card 16bb9977).

Covers the acceptance criteria:
- DH-003 no longer fires CRITICAL on event-driven staleness during
  zero-signal periods (weekend/no-signal weekday).
- True-failure detection preserved: stats_fails>0 or signals-without-writes
  still trips CRITICAL.
"""

from __future__ import annotations

import json
import os
import time

import daily_audit  # noqa: E402
import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Point daily_audit at a tmp workspace with a stale stats file."""
    (tmp_path / "data").mkdir()
    stats = tmp_path / "data" / "signal_stats.jsonl"
    stats.write_text('{"signal_id": "x"}\n')
    # Make it very stale (~53h like the weekend false positive).
    old = time.time() - 53 * 3600
    os.utime(stats, (old, old))
    monkeypatch.setattr(daily_audit, "ROOT", tmp_path)
    return tmp_path, stats, old


def _no_failure_evidence(monkeypatch):
    monkeypatch.setattr(daily_audit, "_recent_stats_fails", lambda *a, **k: 0)
    monkeypatch.setattr(daily_audit, "_signals_since_last_write", lambda m: False)


def test_weekend_zero_signals_stale_is_ok(env, monkeypatch):
    """Zero-signal weekend staleness (53h) must not be CRITICAL."""
    _no_failure_evidence(monkeypatch)
    monkeypatch.setattr(daily_audit, "_get_market_status", lambda now=None: "weekend")
    res = daily_audit._ch_dh_signal_stats()
    assert res.status == "OK"
    assert "no failure evidence" in res.detail


def test_open_market_zero_signals_stale_is_not_critical(env, monkeypatch):
    """Zero-signal weekday staleness must not be CRITICAL either."""
    _no_failure_evidence(monkeypatch)
    monkeypatch.setattr(daily_audit, "_get_market_status", lambda now=None: "open")
    res = daily_audit._ch_dh_signal_stats()
    assert res.status in ("OK", "WARN")
    assert res.status != "CRITICAL"


def test_stats_fails_positive_is_critical(env, monkeypatch):
    """stats_fails>0 in B5 health lines must trip CRITICAL."""
    monkeypatch.setattr(daily_audit, "_recent_stats_fails", lambda *a, **k: 3)
    res = daily_audit._ch_dh_signal_stats()
    assert res.status == "CRITICAL"
    assert "stats_fails=3" in res.detail


def test_signals_without_writes_is_critical(env, monkeypatch):
    """Signals generated in-engine since last write must trip CRITICAL."""
    _no_failure_evidence(monkeypatch)
    monkeypatch.setattr(daily_audit, "_get_market_status", lambda now=None: "open")
    monkeypatch.setattr(
        daily_audit, "_signals_since_last_write", lambda m: True
    )
    res = daily_audit._ch_dh_signal_stats()
    assert res.status == "CRITICAL"
    assert "signals-without-writes" in res.detail


def test_missing_file_is_ok_without_positive_evidence(env, monkeypatch):
    """Missing signal_stats.jsonl with no positive failure evidence is OK.

    Per DH-003 contract: alerts key on positive evidence (stats_fails>0,
    signals-without-writes), not mere absence. With no file yet, the
    event-driven writer has not had its first event — absence alone is
    OK/INFO, not WARN/escalated.
    """
    stats = env[1]
    stats.unlink()
    monkeypatch.setattr(daily_audit, "_get_market_status", lambda now=None: "open")
    monkeypatch.setattr(
        daily_audit, "_signals_since_last_write", lambda m: False
    )
    res = daily_audit._ch_dh_signal_stats()
    assert res.status == "OK"
    assert not getattr(res, "escalated", False)


def test_missing_file_with_signals_is_critical(env, monkeypatch):
    """Missing signal_stats.jsonl with signals>0 since restart is CRITICAL.

    Positive evidence of writer failure: engine reports signals since
    last restart but signal_stats.jsonl was never written — writer dead.
    """
    stats = env[1]
    stats.unlink()
    monkeypatch.setattr(daily_audit, "_get_market_status", lambda now=None: "open")
    monkeypatch.setattr(
        daily_audit, "_signals_since_last_write", lambda m: True
    )
    res = daily_audit._ch_dh_signal_stats()
    assert res.status == "CRITICAL"
    assert "signals-without-writes" in res.detail


def test_fresh_file_ok(env, monkeypatch):
    stats = env[1]
    now = time.time()
    os.utime(stats, (now, now))
    _no_failure_evidence(monkeypatch)
    monkeypatch.setattr(daily_audit, "_get_market_status", lambda now=None: "open")
    res = daily_audit._ch_dh_signal_stats()
    assert res.status == "OK"


def test_signals_since_last_write_detection(env, monkeypatch):
    """_signals_since_last_write: mtime older than restart + signals>0 → True."""
    tmp_path, stats, old_mtime = env
    hb = tmp_path / "data" / "forward_test_health.json"
    hb = tmp_path / "data" / "forward_test_health.json"
    hb.write_text(
        json.dumps(
            {
                "signals_generated": 2,
                "last_restart_at": "2026-09-17T02:00:00+00:00",
            }
        )
    )
    # Use real clock logic: craft restart_at to be newer than file mtime.
    from datetime import datetime, timezone

    restart_iso = datetime.fromtimestamp(old_mtime + 3600, tz=timezone.utc).isoformat()
    hb.write_text(
        json.dumps({"signals_generated": 2, "last_restart_at": restart_iso})
    )
    assert daily_audit._signals_since_last_write(old_mtime) is True
    # Zero signals → False
    hb.write_text(
        json.dumps({"signals_generated": 0, "last_restart_at": restart_iso})
    )
    assert daily_audit._signals_since_last_write(old_mtime) is False
    # Write newer than restart → False
    hb.write_text(
        json.dumps({"signals_generated": 5, "last_restart_at": restart_iso})
    )
    assert daily_audit._signals_since_last_write(old_mtime + 7200) is False


def test_recent_stats_fails_parses_log(tmp_path):
    log = tmp_path / "forward_test.log"
    log.write_text(
        "2026-09-18 04:46:23 | INFO | ayumi.blend_launcher | [B5 Health] "
        "ticks=42033 signals=0 stats_fails=0\n"
        "2026-09-18 04:47:23 | INFO | ayumi.blend_launcher | [B5 Health] "
        "ticks=42142 signals=0 stats_fails=2\n"
        "2026-09-18 04:48:23 | INFO | ayumi.blend_launcher | unrelated line\n"
    )
    assert daily_audit._recent_stats_fails(log_path=log) == 2
    empty = tmp_path / "empty.log"
    empty.write_text("")
    assert daily_audit._recent_stats_fails(log_path=empty) is None
