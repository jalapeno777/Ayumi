"""Daily performance report generation from trade history."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass
class DailyPerformance:
    date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    sniper_trades: int
    swarm_trades: int
    sniper_win_rate: float
    swarm_win_rate: float
    confidence_distribution: dict[str, int]  # "low"/"med"/"high" -> count
    gate_rejections: dict[str, int]  # gate_name -> count
    circuit_breaker_triggers: int
    daily_risk_used_pct: float
    per_strategy: dict[str, dict]


class DailyAnalytics:
    """Generates daily performance reports from trade history."""

    def __init__(self, trade_log_path: str = "logs/trades.jsonl", starting_balance: float = 10000.0, config: dict | None = None) -> None:
        self._trade_log = trade_log_path
        self._starting_balance = starting_balance
        self._config = config or {}
        self._tz = ZoneInfo("America/Toronto")

    def _load_trades(self, date: str | None = None) -> list[dict]:
        """Load trades from JSONL log, optionally filtered by date."""
        if not os.path.exists(self._trade_log):
            return []

        trades = []
        with open(self._trade_log) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    t = __import__("json").loads(line)
                except __import__("json").JSONDecodeError:
                    continue
                if date:
                    ts = t.get("timestamp", "")
                    if not ts.startswith(date):
                        continue
                trades.append(t)
        return trades

    def generate_report(self, date: str | None = None) -> DailyPerformance:
        """Generate daily report. Default: today."""
        if date is None:
            date = datetime.now(self._tz).strftime("%Y-%m-%d")

        trades = self._load_trades(date)
        return self._build_report(date, trades)

    def generate_summary(self, days: int = 7) -> list[DailyPerformance]:
        """Generate reports for last N days."""
        reports = []
        today = datetime.now(self._tz)
        for i in range(days):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            reports.append(self.generate_report(d))
        return reports

    def format_report(self, report: DailyPerformance) -> str:
        """Format report as human-readable text."""
        lines = [
            f"📊 Daily Performance — {report.date}",
            f"{'─' * 40}",
            f"Trades: {report.total_trades} (W: {report.winning_trades} / L: {report.losing_trades})",
            f"Win Rate: {report.win_rate:.1%}",
            f"PnL: ${report.total_pnl:+.2f}",
            f"Max Drawdown: ${report.max_drawdown:.2f}",
            f"",
            f"Sniper: {report.sniper_trades} trades ({report.sniper_win_rate:.1%} WR)",
            f"Swarm: {report.swarm_trades} trades ({report.swarm_win_rate:.1%} WR)",
            f"",
            f"Confidence: low={report.confidence_distribution.get('low', 0)} | "
            f"med={report.confidence_distribution.get('med', 0)} | "
            f"high={report.confidence_distribution.get('high', 0)}",
            f"Gate Rejections: {report.gate_rejections or 'none'}",
            f"Circuit Breakers: {report.circuit_breaker_triggers}",
            f"Risk Used: {report.daily_risk_used_pct:.1%}",
        ]
        if report.per_strategy:
            lines.append("")
            lines.append("Per Strategy:")
            for sid, stats in report.per_strategy.items():
                lines.append(f"  {sid}: {stats.get('trades', 0)} trades, "
                             f"${stats.get('pnl', 0):+.2f}")
        return "\n".join(lines)

    def _build_report(self, date: str, trades: list[dict]) -> DailyPerformance:
        if not trades:
            return DailyPerformance(
                date=date, total_trades=0, winning_trades=0, losing_trades=0,
                win_rate=0.0, total_pnl=0.0, max_drawdown=0.0,
                sniper_trades=0, swarm_trades=0, sniper_win_rate=0.0,
                swarm_win_rate=0.0, confidence_distribution={"low": 0, "med": 0, "high": 0},
                gate_rejections={}, circuit_breaker_triggers=0, daily_risk_used_pct=0.0,
                per_strategy={},
            )

        winning = [t for t in trades if t.get("pnl", 0) > 0]
        losing = [t for t in trades if t.get("pnl", 0) <= 0]
        win_rate = len(winning) / len(trades) if trades else 0.0
        total_pnl = sum(t.get("pnl", 0) for t in trades)

        # Max drawdown from running equity
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            equity += t.get("pnl", 0)
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)

        # Profile stats
        sniper = [t for t in trades if t.get("profile") == "sniper"]
        swarm = [t for t in trades if t.get("profile") == "swarm"]
        sniper_wins = [t for t in sniper if t.get("pnl", 0) > 0]
        swarm_wins = [t for t in swarm if t.get("pnl", 0) > 0]

        # Confidence buckets
        conf_dist = {"low": 0, "med": 0, "high": 0}
        for t in trades:
            c = t.get("confidence", 0.5)
            if c < 0.6:
                conf_dist["low"] += 1
            elif c < 0.8:
                conf_dist["med"] += 1
            else:
                conf_dist["high"] += 1

        # Gate rejections
        gate_rej: dict[str, int] = {}
        for t in trades:
            for gate in t.get("gate_rejections", []):
                gate_rej[gate] = gate_rej.get(gate, 0) + 1

        # Per-strategy
        per_strat: dict[str, dict] = {}
        for t in trades:
            sid = t.get("strategy_id", "unknown")
            if sid not in per_strat:
                per_strat[sid] = {"trades": 0, "pnl": 0.0}
            per_strat[sid]["trades"] += 1
            per_strat[sid]["pnl"] += t.get("pnl", 0)

        total_risk = sum(t.get("risk_amount", 0) for t in trades)
        daily_risk_pct = total_risk / self._starting_balance if total_risk else 0.0

        return DailyPerformance(
            date=date,
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=win_rate,
            total_pnl=round(total_pnl, 2),
            max_drawdown=round(max_dd, 2),
            sniper_trades=len(sniper),
            swarm_trades=len(swarm),
            sniper_win_rate=len(sniper_wins) / len(sniper) if sniper else 0.0,
            swarm_win_rate=len(swarm_wins) / len(swarm) if swarm else 0.0,
            confidence_distribution=conf_dist,
            gate_rejections=gate_rej,
            circuit_breaker_triggers=sum(1 for t in trades if t.get("circuit_breaker")),
            daily_risk_used_pct=round(daily_risk_pct, 4),
            per_strategy={k: {"trades": v["trades"], "pnl": round(v["pnl"], 2)} for k, v in per_strat.items()},
        )
