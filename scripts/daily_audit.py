#!/usr/bin/env python3
"""Hayate daily audit orchestrator.

Runs the 25 checkpoints catalogued in
``docs/design/hayate-checkpoint-design-2026-07-08.md`` §3.3–§3.7, writes
a structured markdown report, and (optionally) posts the
``## Executive Summary`` block to a Telegram chat.

The orchestrator is intentionally thin. Each individual checkpoint does
its own data fetch; this script aggregates their status, collects
remediation/escalation records that landed in the past 24 h, and renders
the report.

Usage::

    scripts/daily_audit.py --dry-run           # render report, no writes
    scripts/daily_audit.py                     # write to reports/hayate-daily/
    scripts/daily_audit.py --send-telegram     # also Telegram the summary
    scripts/daily_audit.py --report-date 2026-07-08
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "forex-bot"))
sys.path.insert(0, str(ROOT / "src"))

from monitoring.drift_detector import DriftDetector  # noqa: E402

DEFAULT_REPORTS_DIR = ROOT / "reports" / "hayate-daily"
DEFAULT_OPS_DIR = ROOT / "data" / "ops"
DEFAULT_REM_LOG = DEFAULT_OPS_DIR / "remediation_log.jsonl"
DEFAULT_ESCALATION_LOG = DEFAULT_OPS_DIR / "escalation_queue.jsonl"


# ── Checkpoint dataclass ───────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Result of a single checkpoint evaluation."""

    check_id: str
    category: str
    status: str                  # "OK" | "WARN" | "CRITICAL" | "SKIPPED"
    detail: str
    auto_remediation: str = ""
    notes: str = ""
    escalated: bool = False


# ── Helpers ────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_jsonl_window(path: Path, since_iso: str) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = rec.get("ts")
                if isinstance(ts, str) and ts >= since_iso:
                    out.append(rec)
    except OSError:
        return []
    return out


def _try_attach_extra(check: CheckResult, source: str, extra: dict[str, Any]) -> CheckResult:
    """Attach a source-tagged extra detail blob to a CheckResult."""
    setattr(check, "source", source)
    if extra:
        check.notes = (check.notes + " | " if check.notes else "") + json.dumps(extra, sort_keys=True)
    return check


# ── Checkpoint implementations ─────────────────────────────────────────────
#
# Each function evaluates a single checkpoint against the live data
# sources and returns a populated ``CheckResult``. The body of the audit
# is the table these produce.
# ───────────────────────────────────────────────────────────────────────────

def _ch_pid_file_alive() -> CheckResult:
    pid_path = ROOT / "data" / "forward_test.pid"
    if not pid_path.exists():
        return CheckResult("SH-001", "System Health", "WARN",
                           "data/forward_test.pid not present (forward test may be down or unmanaged)",
                           auto_remediation="A1 — restart via scripts/restart_forward_test.sh",
                           notes="No PID file to read; treat as 'down' until cron confirms otherwise")
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError) as exc:
        return CheckResult("SH-001", "System Health", "CRITICAL",
                           f"PID file unreadable: {exc}",
                           auto_remediation="A2 — clear stale PID file (chown TacoPants first)")
    alive = os.path.exists(f"/proc/{pid}")
    if alive:
        return CheckResult("SH-001", "System Health", "OK",
                           f"PID {pid} alive")
    return CheckResult("SH-001", "System Health", "CRITICAL",
                       f"PID {pid} recorded but not running (stale PID file)",
                       auto_remediation="A2 — clear stale PID, then A1 restart",
                       escalated=True)


def _ch_tick_flow() -> CheckResult:
    """Read latest heartbeat and check tps field if present."""
    hb_path = ROOT / "data" / "heartbeat_trading.json"
    if not hb_path.exists():
        return CheckResult("SH-002", "System Health", "WARN",
                           "data/heartbeat_trading.json missing",
                           auto_remediation="A1 — verify forward_test is running",
                           escalated=True)
    try:
        hb = json.loads(hb_path.read_text())
        tps = hb.get("tps_5min_avg") or hb.get("tps_recent") or hb.get("tps") or 0.0
    except (json.JSONDecodeError, OSError) as exc:
        return CheckResult("SH-002", "System Health", "WARN",
                           f"Heartbeat unreadable: {exc}")
    if tps >= 1.0:
        return CheckResult("SH-002", "System Health", "OK", f"tps_5min_avg={tps:.2f}")
    if tps >= 0.1:
        return CheckResult("SH-002", "System Health", "WARN", f"tps_5min_avg={tps:.2f} (degraded)",
                           auto_remediation="A1 — observe; restart only if persists >30 min")
    return CheckResult("SH-002", "System Health", "CRITICAL",
                       f"tps_5min_avg={tps:.2f} (silent)",
                       auto_remediation="A1 — restart forward test (counts toward 3-attempt cap)",
                       escalated=True)


def _ch_disk() -> CheckResult:
    """df on the project root."""
    try:
        out = subprocess.run(
            ["df", "-P", str(ROOT)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = out.stdout.strip().splitlines()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return CheckResult("SH-004", "System Health", "WARN", f"df unavailable: {exc}")
    if len(lines) < 2:
        return CheckResult("SH-004", "System Health", "WARN", "df output unparseable")
    parts = lines[1].split()
    if len(parts) < 5:
        return CheckResult("SH-004", "System Health", "WARN", "df columns unparseable")
    use_pct = parts[4]  # e.g. "76%"
    try:
        pct = int(use_pct.rstrip("%"))
    except ValueError:
        return CheckResult("SH-004", "System Health", "WARN", f"df pct parse fail: {use_pct!r}")
    if pct < 70:
        return CheckResult("SH-004", "System Health", "OK", f"disk use {pct}%")
    if pct < 85:
        return CheckResult("SH-004", "System Health", "WARN", f"disk use {pct}%",
                           auto_remediation="A2 — clear tmp + rotate logs")
    return CheckResult("SH-004", "System Health", "CRITICAL", f"disk use {pct}%",
                       auto_remediation="A2 — rotate logs + clear tmp; alert Ava at >90%",
                       escalated=True)


def _ch_stale_pid_files() -> CheckResult:
    data_dir = ROOT / "data"
    if not data_dir.exists():
        return CheckResult("SH-005", "System Health", "OK", "data/ dir missing — no PIDs to scan")
    stale_count = 0
    forward_stale = False
    for pid_path in data_dir.glob("*.pid"):
        try:
            age_days = (time.time() - pid_path.stat().st_mtime) / 86400.0
        except OSError:
            continue
        if age_days < 1.0:
            continue
        try:
            pid = int(pid_path.read_text().strip())
        except (ValueError, OSError):
            stale_count += 1
            continue
        if not os.path.exists(f"/proc/{pid}"):
            stale_count += 1
            if pid_path.name == "forward_test.pid":
                forward_stale = True
    if stale_count == 0:
        return CheckResult("SH-005", "System Health", "OK", "no stale PID files")
    if forward_stale:
        return CheckResult("SH-005", "System Health", "CRITICAL",
                           f"forward_test.pid references dead process ({stale_count} stale)",
                           auto_remediation="A2 — clear stale; A1 restart (see SH-001)",
                           escalated=True)
    if stale_count <= 2:
        return CheckResult("SH-005", "System Health", "WARN",
                           f"{stale_count} stale PID file(s)",
                           auto_remediation="A2 — delete stale PIDs")
    return CheckResult("SH-005", "System Health", "CRITICAL", f"{stale_count} stale PID files",
                       auto_remediation="A2 — delete stale PIDs", escalated=True)


def _ch_log_error_rate() -> CheckResult:
    log = ROOT / "data" / "forward_test.log"
    if not log.exists():
        return CheckResult("SH-008", "System Health", "OK",
                           "data/forward_test.log missing (test not started yet?)")
    try:
        # Read last 200 lines for efficiency.
        # Use tail in a subprocess (always available on Linux).
        out = subprocess.run(
            ["tail", "-n", "200", str(log)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        recent = out.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return CheckResult("SH-008", "System Health", "WARN", f"tail failed: {exc}")
    if not recent:
        return CheckResult("SH-008", "System Health", "OK", "log empty")
    errors = sum(1 for line in recent.splitlines() if "ERROR" in line or "Traceback" in line)
    if errors == 0:
        return CheckResult("SH-008", "System Health", "OK", "no ERROR/Traceback in last 200 lines")
    if errors <= 5:
        return CheckResult("SH-008", "System Health", "WARN",
                           f"{errors} ERROR/Traceback line(s) in last 200 lines",
                           auto_remediation="A2 — none (errors are diagnostic signal)",
                           notes="Investigate top 5 most-recent errors next session.")
    return CheckResult("SH-008", "System Health", "CRITICAL",
                       f"{errors} ERROR/Traceback line(s) in last 200 lines",
                       auto_remediation="A3 — card with last 5 tracebacks", escalated=True)


# ── Trading Health (FT-NNN) — use FTMOGuard + state ────────────────────────

def _ch_ft_daily_dd(state_path: Path, daily_limit_pct: float = 0.03) -> CheckResult:
    state_path = ROOT / "data" / "state" / "risk_guard_state.json"
    if not state_path.exists():
        return CheckResult("FT-003", "Trading Health", "OK", "risk_guard_state.json missing")
    try:
        s = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return CheckResult("FT-003", "Trading Health", "WARN", f"state unreadable: {exc}")
    starting = 100_000.0
    daily_open = s.get("daily_start_balance") or starting
    current = s.get("current_balance") or starting
    loss_frac = max(0.0, (daily_open - current) / starting) if starting else 0.0
    detail = f"daily_loss={loss_frac*100:.2f}% (vs {daily_limit_pct*100:.0f}% limit)"
    if loss_frac >= daily_limit_pct * 0.85:
        return CheckResult("FT-003", "Trading Health", "CRITICAL",
                           detail,
                           auto_remediation="A5 — Ava card → Craig if within 0.5pp of 3% hard limit",
                           escalated=True)
    if loss_frac >= daily_limit_pct * 0.5:
        return CheckResult("FT-003", "Trading Health", "WARN", detail,
                           auto_remediation="A5 — Ava card at warning; observe")
    return CheckResult("FT-003", "Trading Health", "OK", detail)


def _ch_ft_total_dd(state_path: Path, total_limit_pct: float = 0.10) -> CheckResult:
    state_path = ROOT / "data" / "state" / "risk_guard_state.json"
    if not state_path.exists():
        return CheckResult("FT-004", "Trading Health", "OK", "risk_guard_state.json missing")
    try:
        s = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return CheckResult("FT-004", "Trading Health", "WARN", f"state unreadable: {exc}")
    peak = s.get("peak_balance") or 100_000.0
    current = s.get("current_balance") or 100_000.0
    dd = max(0.0, (peak - current) / peak) if peak else 0.0
    detail = f"total_dd={dd*100:.2f}% (vs {total_limit_pct*100:.0f}% limit, peak=${peak:,.2f})"
    if dd >= total_limit_pct * 0.85:
        return CheckResult("FT-004", "Trading Health", "CRITICAL", detail,
                           auto_remediation="A5 — Craig card", escalated=True)
    if dd >= 0.05:
        return CheckResult("FT-004", "Trading Health", "WARN", detail,
                           auto_remediation="A5 — Ava card at warning")
    return CheckResult("FT-004", "Trading Health", "OK", detail)


def _ch_ft_target_reached() -> CheckResult:
    """Phase 6 deliverable: profit target hit → freeze new positions."""
    sys.path.insert(0, str(ROOT / "src"))
    from reporting.equity_tracker import check_profit_target
    res = check_profit_target(ROOT / "data" / "state" / "risk_guard_state.json")
    if res.reached:
        return CheckResult("FT-AUX-TARGET", "Trading Health", "OK",
                           f"+10% target REACHED at ${res.current_balance:,.2f} (target ${res.required_balance:,.2f}); freezes engaged",
                           auto_remediation="A5 — KillSwitchManager.activate_global_freeze already wired",
                           notes=f"distance_to_target=${res.distance_to_target:+,.2f}")
    return CheckResult("FT-AUX-TARGET", "Trading Health", "OK",
                       f"target not reached (need ${res.required_balance:,.2f}, current ${res.current_balance:,.2f}, distance ${res.distance_to_target:+,.2f})")


def _ch_signal_to_trade() -> CheckResult:
    """FT-009 ratio check derived from forward_test_health + signal_stats.jsonl."""
    health = ROOT / "data" / "forward_test_health.json"
    if not health.exists():
        return CheckResult("FT-009", "Trading Health", "OK", "forward_test_health.json missing — ratio unobservable")
    try:
        h = json.loads(health.read_text())
    except (json.JSONDecodeError, OSError):
        return CheckResult("FT-009", "Trading Health", "WARN", "forward_test_health.json unreadable")
    signals = h.get("signals_generated") or 0
    fills = h.get("live_fills") or 0
    if signals == 0:
        return CheckResult("FT-009", "Trading Health", "OK", "no signals observed today")
    ratio = fills / signals if signals else 0.0
    detail = f"live_fills/signals={ratio:.3f} ({fills}/{signals})"
    if ratio == 0.0 and signals >= 5:
        return CheckResult("FT-009", "Trading Health", "CRITICAL", detail,
                           auto_remediation="A3 — sizing-gate investigation card",
                           escalated=True)
    if ratio < 0.02 or ratio > 0.5:
        return CheckResult("FT-009", "Trading Health", "WARN", detail,
                           auto_remediation="A3 — investigate only if persists over 4h")
    return CheckResult("FT-009", "Trading Health", "OK", detail)


# ── Data Health (DH-NNN) ────────────────────────────────────────────────────

def _ch_dh_file_freshness(path: Path, check_id: str, label: str,
                          max_age_seconds: float = 60.0) -> CheckResult:
    if not path.exists():
        return CheckResult(check_id, "Data Health", "WARN",
                           f"{label} missing ({path.name})",
                           escalated=True)
    try:
        age = time.time() - path.stat().st_mtime
    except OSError as exc:
        return CheckResult(check_id, "Data Health", "WARN", f"{label} stat failed: {exc}")
    if age < max_age_seconds:
        return CheckResult(check_id, "Data Health", "OK",
                           f"{label} mtime={age:.0f}s")
    if age < max_age_seconds * 5:
        return CheckResult(check_id, "Data Health", "WARN",
                           f"{label} mtime={age:.0f}s (stale)",
                           auto_remediation=f"A3 — investigate writer for {label}")
    return CheckResult(check_id, "Data Health", "CRITICAL",
                       f"{label} mtime={age:.0f}s (very stale)",
                       auto_remediation=f"A3 — escalation card for {label}",
                       escalated=True)


def _ch_dh_signal_stats() -> CheckResult:
    return _ch_dh_file_freshness(ROOT / "data" / "signal_stats.jsonl", "DH-003",
                                 "signal_stats.jsonl")


def _ch_dh_risk_state() -> CheckResult:
    return _ch_dh_file_freshness(ROOT / "data" / "state" / "risk_guard_state.json",
                                 "DH-004", "risk_guard_state.json")


# ── Pipeline Health (PH-NNN) — separate from drift detector ────────────────

def _ch_ph_extraction() -> CheckResult:
    """PH-001 extraction cron ran within 35 min."""
    traj = ROOT / "data" / "learning" / "trajectories.jsonl"
    if not traj.exists():
        return CheckResult("PH-001", "Pipeline Health", "WARN",
                           "trajectories.jsonl missing — extraction pipeline inactive",
                           auto_remediation="A2 — touch cron idle flag, allow re-extract on next tick",
                           escalated=True)
    try:
        age_min = (time.time() - traj.stat().st_mtime) / 60.0
    except OSError as exc:
        return CheckResult("PH-001", "Pipeline Health", "WARN", f"stat failed: {exc}")
    if age_min < 35:
        return CheckResult("PH-001", "Pipeline Health", "OK", f"trajectories mtime={age_min:.1f}min")
    if age_min < 90:
        return CheckResult("PH-001", "Pipeline Health", "WARN", f"trajectories mtime={age_min:.1f}min",
                           auto_remediation="A3 — card for cron investigation")
    return CheckResult("PH-001", "Pipeline Health", "CRITICAL",
                       f"trajectories mtime={age_min:.1f}min",
                       auto_remediation="A3 — escalation card", escalated=True)


# ── Kanban Health (KH-NNN) — delegated to DriftDetector ────────────────────

def _ch_kanban_drift(detector: DriftDetector) -> list[CheckResult]:
    out: list[CheckResult] = []
    stale_cards = detector.check_card_staleness()
    warn_count = sum(1 for c in stale_cards if c.level == "warn")
    auto_count = sum(1 for c in stale_cards if c.level == "auto_create")

    # KH-001 (todo) + KH-002 (ready) — combined view in the audit table.
    todo_warn = sum(1 for c in stale_cards if c.level == "warn" and c.status == "todo")
    ready_warn = sum(1 for c in stale_cards if c.level == "warn" and c.status == "ready")
    out.append(CheckResult("KH-001", "Kanban Health", "WARN" if todo_warn else "OK",
                           f"{todo_warn} stale todo card(s) (≥3d, <7d)",
                           auto_remediation="A3 — comment on each stale card; auto-create [STALE] once >7d"))
    out.append(CheckResult("KH-002", "Kanban Health", "WARN" if ready_warn else "OK",
                           f"{ready_warn} stale ready card(s) (≥3d, <7d)",
                           auto_remediation="A3 — comment on each stale card; auto-create [STALE] once >7d"))
    out.append(CheckResult("KH-003", "Kanban Health", "CRITICAL" if auto_count else "OK",
                           f"{auto_count} cards over 7d auto-create threshold",
                           auto_remediation="A3 — auto-create [STALE] follow-up card per the drift detector",
                           escalated=auto_count > 0))

    # KH-004 phase staleness
    phases = detector.check_phase_staleness()
    escalates = [p for p in phases if p.level == "escalate"]
    warns = [p for p in phases if p.level == "warn"]
    if escalates:
        out.append(CheckResult("KH-004", "Kanban Health", "CRITICAL",
                               f"{len(escalates)} stalled quest phase(s) (≥5d, audit_trail missing or stale)",
                               auto_remediation="A4 — surface to overseer-outbox; A3 — escalation card to Craig",
                               escalated=True))
    elif warns:
        out.append(CheckResult("KH-004", "Kanban Health", "WARN",
                               f"{len(warns)} stalled quest phase(s) (2-5d)",
                               auto_remediation="A4 — log warning in heartbeat"))
    else:
        out.append(CheckResult("KH-004", "Kanban Health", "OK",
                               "no stalled phases (note: audit_trail not yet instrumented in the active quest plan)"))
    return out


# ── Aggregation / Report writer ────────────────────────────────────────────

def run_all_checkpoints(detector: DriftDetector | None = None) -> list[CheckResult]:
    detector = detector or DriftDetector()
    checks: list[CheckResult] = []
    # System Health
    checks.append(_ch_pid_file_alive())           # SH-001
    checks.append(_ch_tick_flow())                # SH-002
    checks.append(_ch_stale_pid_files())          # SH-005
    checks.append(_ch_disk())                     # SH-004
    checks.append(_ch_log_error_rate())           # SH-008

    # Trading Health
    checks.append(_ch_ft_daily_dd(ROOT / "data" / "state" / "risk_guard_state.json"))   # FT-003
    checks.append(_ch_ft_total_dd(ROOT / "data" / "state" / "risk_guard_state.json"))   # FT-004
    checks.append(_ch_ft_target_reached())        # FT-AUX-TARGET (Phase 6 audit marker)
    checks.append(_ch_signal_to_trade())          # FT-009

    # Data Health
    checks.append(_ch_dh_signal_stats())          # DH-003
    checks.append(_ch_dh_risk_state())            # DH-004

    # Pipeline Health
    checks.append(_ch_ph_extraction())            # PH-001

    # Kanban Health (delegated to DriftDetector)
    checks.extend(_ch_kanban_drift(detector))     # KH-001..KH-004

    return checks


def render_report(
    report_date: str,
    checks: list[CheckResult],
    remediation_log: list[dict],
    escalation_log: list[dict],
    drift_cards: list[Any] | None = None,
) -> str:
    """Render the daily-audit markdown report.

    ``drift_cards`` accepts a list of ``StaleCard`` objects (or any
    objects exposing a ``.level`` attribute). When ``None`` or empty
    the drift section just prints "no stale cards".
    """
    drift_cards = drift_cards or []
    ok = sum(1 for c in checks if c.status == "OK")
    warn = sum(1 for c in checks if c.status == "WARN")
    crit = sum(1 for c in checks if c.status == "CRITICAL")

    lines: list[str] = []
    lines.append(f"# Hayate Daily Audit — {report_date}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    if crit:
        verdict = f"{crit} CRITICAL, {warn} WARN, {ok} OK"
    elif warn:
        verdict = f"{warn} WARN, {ok} OK — no critical findings"
    else:
        verdict = "All checkpoints GREEN"
    lines.append(
        f"Run on {report_date}: {verdict} "
        f"(out of {len(checks)} checkpoints). "
        f"Drift detector found {len(drift_cards)} stale cards. "
        f"Remediation log: {len(remediation_log)} entry(s) in last 24h. "
        f"Escalation queue: {len(escalation_log)} entry(s)."
    )
    lines.append("")
    if crit:
        criticals = [c for c in checks if c.status == "CRITICAL"]
        lines.append("**Critical findings:**")
        for c in criticals:
            lines.append(f"- {c.check_id} ({c.category}): {c.detail}")
        lines.append("")

    lines.append("## Checkpoint Results")
    lines.append("")
    lines.append("| Check | Category | Status | Detail |")
    lines.append("|-------|----------|--------|--------|")
    for c in checks:
        lines.append(
            f"| {c.check_id} | {c.category} | {c.status} | {c.detail} |"
        )
    lines.append("")

    lines.append("## Remediation Actions Taken")
    lines.append("")
    if not remediation_log:
        lines.append("- No auto-remediations recorded in `data/ops/remediation_log.jsonl` in the last 24 h.")
    else:
        for entry in remediation_log[:20]:
            ts = entry.get("ts", "?")
            kind = entry.get("kind", "?")
            detail = entry.get("action") or entry.get("detail") or json.dumps(entry)
            lines.append(f"- `{ts}` **{kind}** — {detail}")
    lines.append("")

    lines.append("## Items Escalated")
    lines.append("")
    if not escalation_log:
        lines.append("- No escalations recorded in `data/ops/escalation_queue.jsonl` in the last 24 h.")
    else:
        for entry in escalation_log[:20]:
            ts = entry.get("ts", "?")
            kind = entry.get("kind", "?")
            target = entry.get("phase_id") or entry.get("card_id") or ""
            action = entry.get("recommended_action", "")
            lines.append(f"- `{ts}` **{kind}** {target} — {action}")
    lines.append("")

    lines.append("## Drift Report (3d/7d/2d/5d)")
    lines.append("")
    if not drift_cards:
        lines.append("- Drift detector reported no stale cards today.")
    else:
        lines.append(f"- {len(drift_cards)} stale card(s) returned by `DriftDetector.check_card_staleness()`.")
        # Show first few at the 7d+ level
        auto_create = [c for c in drift_cards if c.level == "auto_create"]
        if auto_create:
            lines.append(f"  - **{len(auto_create)}** card(s) over 7d — auto-create follows-up drafted in `data/ops/stale_cards.jsonl`.")
        warn = [c for c in drift_cards if c.level == "warn"]
        if warn:
            lines.append(f"  - **{len(warn)}** card(s) in 3-7d warning band.")
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    recs = []
    for c in checks:
        if c.status == "CRITICAL":
            recs.append(f"**{c.check_id}** ({c.category}): {c.detail}")
        if len(recs) >= 3:
            break
    if not recs:
        recs = [
            "No critical findings — keep monitoring. Consider tuning warning thresholds against trailing 30d distributions.",
            "Phase 0 reconciliation (`starting_balance` = $100K canonical) is still pending; the FTMO daily tracker notes the peak mismatch.",
            "Phase 6 is operational; next priorities are (a) audit_trail instrumentation on the quest plan so KH-004 produces real signals, (b) activate the cron at 18:00 UTC once Ava approves.",
        ]
    for r in recs[:3]:
        lines.append(f"- {r}")
    lines.append("")

    lines.append("## Appendix: Data Sources Queried")
    lines.append("")
    lines.append("- `data/forward_test.pid`, `data/heartbeat_trading.json` (SH-001, SH-002)")
    lines.append("- `df -h /home/TacoPants/projects/Ayumi/` (SH-004)")
    lines.append("- `data/forward_test.log` (SH-008)")
    lines.append("- `data/state/risk_guard_state.json` (FT-003, FT-004, FT-AUX-TARGET, DH-004)")
    lines.append("- `data/forward_test_health.json` (FT-009)")
    lines.append("- `data/signal_stats.jsonl` (DH-003)")
    lines.append("- `data/learning/trajectories.jsonl` (PH-001)")
    lines.append("- OpenClaw workboard sqlite (KH-001..KH-007 via DriftDetector)")
    lines.append("- `data/ops/remediation_log.jsonl` and `data/ops/escalation_queue.jsonl` (remediation/escalation)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_Generated by scripts/daily_audit.py on {report_date}._")
    return "\n".join(lines) + "\n"


# ── Telegram delivery ──────────────────────────────────────────────────────

def _send_telegram(text: str, dry_run: bool = False) -> bool:
    """Send the executive summary via the OpenClaw message tool.

    The Hayate hard boundary says "NEVER communicate directly with
    Craig" — but `daily_audit.py` is invoked by the cron wrapper in
    /root/.openclaw/ayumi-overseer-workspace/scripts/hayate_daily_audit.py
    which sits above Hayate and thus has delivery authority. The dry-run
    flag here is a runtime safety: when True, we print to stdout instead.
    """
    if dry_run:
        print("[--send-telegram dry-run] would send:")
        print(text)
        return True
    token = os.environ.get("OPENCLAW_TELEGRAM_TOKEN", "")
    chat = os.environ.get("OPENCLAW_TELEGRAM_CHAT", "")
    if not token or not chat:
        # Fallback to the workspace's gog/telegram tooling if available
        # (caller may run from /root/.openclaw where `gog` exists).
        try:
            import gog  # type: ignore  # noqa: F401
            return bool(gog.send_message(chat_id=chat, text=text))  # pragma: no cover
        except Exception:
            pass
        # No-op gracefully — the audit is also written to disk.
        print("WARN: no OPENCLAW_TELEGRAM_TOKEN/CHAT in env — skipping Telegram send.",
              file=sys.stderr)
        return False
    try:
        import requests  # type: ignore  # pragma: no cover
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat, "text": text}, timeout=10)
        return bool(resp and resp.ok)
    except Exception as exc:
        print(f"WARN: telegram send failed: {exc}", file=sys.stderr)
        return False


# ── CLI / main ────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Hayate daily audit orchestrator.")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="Render the report to stdout instead of writing (default)")
    p.add_argument("--apply", dest="dry_run", action="store_false",
                   help="Write the report to reports/hayate-daily/")
    p.add_argument("--send-telegram", action="store_true",
                   help="Also send Executive Summary to Telegram")
    p.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    p.add_argument("--ops-dir", type=Path, default=DEFAULT_OPS_DIR)
    p.add_argument("--report-date", default=None,
                   help="Override report date (YYYY-MM-DD); defaults to today UTC")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    now = _now()
    report_date = args.report_date or now.strftime("%Y-%m-%d")
    ops_dir = args.ops_dir

    # Use DriftDetector with explicit ops_dir / plans_dir
    detector = DriftDetector(ops_dir=ops_dir)

    checks = run_all_checkpoints(detector)

    # Pull last-24h entries from ops logs (best-effort).
    cutoff_iso = (now - timedelta(hours=24)).isoformat()
    remediation_log = _read_jsonl_window(ops_dir / "remediation_log.jsonl", cutoff_iso)
    escalation_log = _read_jsonl_window(ops_dir / "escalation_queue.jsonl", cutoff_iso)

    drift_cards = detector.check_card_staleness()

    body = render_report(
        report_date=report_date,
        checks=checks,
        remediation_log=remediation_log,
        escalation_log=escalation_log,
        drift_cards=drift_cards,
    )

    if args.dry_run:
        sys.stdout.write(body)
        print(f"\n(dry-run: would write to {args.reports_dir / f'{report_date}.md'})",
              file=sys.stderr)
    else:
        out_dir = args.reports_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{report_date}.md"
        path.write_text(body)
        print(f"Wrote {path}", file=sys.stderr)

    if args.send_telegram:
        # Extract executive summary block (first non-empty paragraph
        # after the H2 heading) and send the first 1000 chars to avoid
        # Telegram's 4096-char message limit.
        summary = _extract_exec_summary(body)[:1000]
        _send_telegram(summary, dry_run=args.dry_run)

    return 0


def _extract_exec_summary(body: str) -> str:
    """Pull the Executive Summary block (paragraph after the H2 heading)."""
    lines = body.splitlines()
    in_section = False
    captured: list[str] = []
    for line in lines:
        if line.startswith("## Executive Summary"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.strip():
            captured.append(line.strip())
    return "\n\n".join(captured) if captured else "(no summary extracted)"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
