#!/usr/bin/env python3
"""FTMO Challenge Simulation Engine.

Replays trade-level results from walk-forward backtests through FTMO
challenge rules to determine pass/fail.

FTMO Challenge Rules (default):
    - $10 000 starting account
    - 5 % maximum daily loss (from starting equity of the day)
    - 10 % maximum total drawdown (from peak equity)
    - 10 % profit target

Usage (programmatic)::

    from backtest.ftmo_simulation import FTMOSimulation, FTMOConfig

    sim = FTMOSimulation(FTMOConfig())
    result = sim.run(trades)
    print(result.passed, result.violations)

CLI::

    python -m forex_bot.backtest.run_ftmo_sim --input data/forex/historical/wf_results.csv
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

logger = logging.getLogger("ayumi.ftmo_simulation")

# ── Constants ──────────────────────────────────────────────────────────

DEFAULT_ACCOUNT_SIZE = 10_000.0
DEFAULT_DAILY_LOSS_LIMIT_PCT = 0.05  # 5 % of day-start equity
DEFAULT_MAX_DRAWDOWN_PCT = 0.10  # 10 % from peak equity
DEFAULT_PROFIT_TARGET_PCT = 0.10  # 10 % from starting balance

# CSV column names expected in the walk-forward results file
CSV_COLUMNS = [
    "timestamp",
    "pair",
    "direction",
    "entry_price",
    "exit_price",
    "size",
    "pnl",
    "strategy",
]


# ── Data classes ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class FTMOConfig:
    """Configuration for the FTMO simulation."""

    account_size: float = DEFAULT_ACCOUNT_SIZE
    daily_loss_limit_pct: float = DEFAULT_DAILY_LOSS_LIMIT_PCT
    max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT
    profit_target_pct: float = DEFAULT_PROFIT_TARGET_PCT

    @property
    def daily_loss_limit(self) -> float:
        """Absolute daily loss limit in account currency."""
        return self.account_size * self.daily_loss_limit_pct

    @property
    def max_drawdown(self) -> float:
        """Absolute max drawdown in account currency."""
        return self.account_size * self.max_drawdown_pct

    @property
    def profit_target(self) -> float:
        """Absolute profit target in account currency."""
        return self.account_size * self.profit_target_pct


@dataclass(frozen=True)
class Trade:
    """A single trade record from walk-forward results."""

    timestamp: datetime
    pair: str
    direction: str  # "long" or "short"
    entry_price: float
    exit_price: float
    size: float  # lot size
    pnl: float  # realised P&L in account currency
    strategy: str = "unknown"


@dataclass
class FTMOViolation:
    """An FTMO rule violation."""

    rule: str
    timestamp: datetime
    details: str
    value: float


@dataclass
class FTMOResult:
    """Result of an FTMO simulation run."""

    passed: bool
    final_equity: float
    max_drawdown_abs: float
    max_drawdown_pct: float
    profit_pct: float
    daily_pnl: dict[str, float] = field(default_factory=dict)
    equity_curve: list[dict] = field(default_factory=list)
    trade_log: list[dict] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    strategy: str = "all"

    def to_dict(self) -> dict:
        """Serialise to a JSON-friendly dict."""
        return {
            "passed": self.passed,
            "strategy": self.strategy,
            "final_equity": round(self.final_equity, 2),
            "max_drawdown_abs": round(self.max_drawdown_abs, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct * 100, 2),
            "profit_pct": round(self.profit_pct * 100, 2),
            "daily_pnl": {k: round(v, 2) for k, v in self.daily_pnl.items()},
            "equity_curve": self.equity_curve,
            "trade_log": self.trade_log,
            "violations": self.violations,
        }


# ── Simulation engine ─────────────────────────────────────────────────


class FTMOSimulation:
    """Replay trades through FTMO challenge rules.

    The simulation processes trades chronologically, tracking:

    * **Daily P&L** — reset at the start of each trading day.  If the
      cumulative daily loss exceeds the limit, a ``daily_loss`` violation
      is recorded and the simulation optionally stops trading for that
      day.
    * **Peak equity** — the highest equity seen so far.  If equity falls
      below ``peak × (1 - max_drawdown_pct)`` a ``max_drawdown`` violation
      is recorded.
    * **Profit target** — if equity exceeds
      ``account_size × (1 + profit_target_pct)`` the challenge is passed.
    """

    def __init__(self, config: FTMOConfig | None = None) -> None:
        self.config = config or FTMOConfig()

    # ── Public API ────────────────────────────────────────────────────

    def run(
        self,
        trades: Sequence[Trade],
        strategy_filter: str | None = None,
        stop_on_violation: bool = True,
    ) -> FTMOResult:
        """Run the FTMO simulation over a list of trades.

        Args:
            trades: Chronologically ordered trade records.
            strategy_filter: If set, only trades matching this strategy
                are simulated.
            stop_on_violation: If ``True`` (default) the simulation stops
                processing further trades after the first hard violation
                (daily loss or max drawdown).  If ``False``, violations
                are recorded but all trades are processed.

        Returns:
            :class:`FTMOResult` with full simulation details.
        """
        cfg = self.config

        # Filter by strategy if requested
        if strategy_filter:
            trades = [t for t in trades if t.strategy == strategy_filter]

        equity = cfg.account_size
        peak_equity = cfg.account_size
        max_dd_abs = 0.0
        current_day: date | None = None
        day_start_equity = cfg.account_size
        daily_pnl: dict[str, float] = {}
        equity_curve: list[dict] = []
        trade_log: list[dict] = []
        violations: list[dict] = []
        passed = False
        stopped = False

        for trade in trades:
            if stopped:
                break

            trade_day = trade.timestamp.date()
            day_key = trade_day.isoformat()

            # New trading day — reset daily tracking
            if current_day is None or trade_day != current_day:
                current_day = trade_day
                day_start_equity = equity
                daily_pnl.setdefault(day_key, 0.0)

            # Apply trade P&L
            equity += trade.pnl
            daily_pnl[day_key] += trade.pnl

            # Track peak equity
            if equity > peak_equity:
                peak_equity = equity

            # Compute drawdown from peak
            dd_abs = peak_equity - equity
            if dd_abs > max_dd_abs:
                max_dd_abs = dd_abs

            dd_pct = dd_abs / peak_equity if peak_equity > 0 else 0.0

            # Record equity curve point
            equity_curve.append(
                {
                    "timestamp": trade.timestamp.isoformat(),
                    "equity": round(equity, 2),
                    "daily_pnl": round(daily_pnl[day_key], 2),
                    "peak": round(peak_equity, 2),
                }
            )

            # Record trade
            trade_log.append(
                {
                    "timestamp": trade.timestamp.isoformat(),
                    "pair": trade.pair,
                    "direction": trade.direction,
                    "pnl": round(trade.pnl, 2),
                    "equity_after": round(equity, 2),
                    "strategy": trade.strategy,
                }
            )

            # ── Rule checks ───────────────────────────────────────────

            # 1. Daily loss limit
            daily_loss = day_start_equity - equity
            daily_loss_limit_abs = day_start_equity * cfg.daily_loss_limit_pct
            if daily_loss >= daily_loss_limit_abs:
                violations.append(
                    {
                        "rule": "daily_loss",
                        "timestamp": trade.timestamp.isoformat(),
                        "details": (
                            f"Daily loss {daily_loss:.2f} exceeds limit "
                            f"{daily_loss_limit_abs:.2f} (5% of "
                            f"{day_start_equity:.2f})"
                        ),
                        "value": round(daily_loss, 2),
                    }
                )
                if stop_on_violation:
                    stopped = True

            # 2. Max total drawdown
            if dd_abs >= cfg.max_drawdown:
                violations.append(
                    {
                        "rule": "max_drawdown",
                        "timestamp": trade.timestamp.isoformat(),
                        "details": (
                            f"Drawdown {dd_abs:.2f} ({dd_pct:.1%}) exceeds "
                            f"max {cfg.max_drawdown:.2f} "
                            f"({cfg.max_drawdown_pct:.0%}) from peak "
                            f"{peak_equity:.2f}"
                        ),
                        "value": round(dd_abs, 2),
                    }
                )
                if stop_on_violation:
                    stopped = True

            # 3. Profit target reached
            if equity >= cfg.account_size + cfg.profit_target:
                passed = True
                # Don't stop — let remaining trades run for full picture

        # If no explicit pass, check final equity
        if not passed:
            passed = equity >= cfg.account_size + cfg.profit_target and not violations

        # Compute final metrics
        profit_abs = equity - cfg.account_size
        profit_pct = profit_abs / cfg.account_size if cfg.account_size > 0 else 0.0
        final_max_dd_pct = max_dd_abs / peak_equity if peak_equity > 0 else 0.0

        # Profit target overrides violations only if no hard violations
        # occurred
        has_hard_violation = any(v["rule"] in ("daily_loss", "max_drawdown") for v in violations)
        if has_hard_violation:
            passed = False

        strat_label = strategy_filter or "all"
        return FTMOResult(
            passed=passed,
            final_equity=round(equity, 2),
            max_drawdown_abs=round(max_dd_abs, 2),
            max_drawdown_pct=final_max_dd_pct,
            profit_pct=profit_pct,
            daily_pnl=daily_pnl,
            equity_curve=equity_curve,
            trade_log=trade_log,
            violations=violations,
            strategy=strat_label,
        )

    def run_per_strategy(
        self,
        trades: Sequence[Trade],
        stop_on_violation: bool = True,
    ) -> dict[str, FTMOResult]:
        """Run simulation for each strategy individually + a blended result.

        Returns:
            Dict keyed by strategy name, plus ``"blended"`` for the
            portfolio blend of all strategies.
        """
        results: dict[str, FTMOResult] = {}
        strategies = sorted({t.strategy for t in trades})

        for strat in strategies:
            results[strat] = self.run(
                trades,
                strategy_filter=strat,
                stop_on_violation=stop_on_violation,
            )

        # Blended (all strategies together)
        results["blended"] = self.run(
            trades,
            strategy_filter=None,
            stop_on_violation=stop_on_violation,
        )

        return results

    # ── CSV loading ───────────────────────────────────────────────────

    @staticmethod
    def load_trades(csv_path: str | Path) -> list[Trade]:
        """Load trades from a walk-forward results CSV file.

        Expected columns::

            timestamp,pair,direction,entry_price,exit_price,size,pnl,strategy

        The ``timestamp`` column should be ISO-8601 formatted
        (``YYYY-MM-DD HH:MM:SS`` or ``YYYY-MM-DDTHH:MM:SS``).

        Args:
            csv_path: Path to the CSV file.

        Returns:
            List of :class:`Trade` objects sorted chronologically.

        Raises:
            FileNotFoundError: If the CSV file does not exist.
            ValueError: If the CSV is missing required columns.
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"Walk-forward results CSV not found: {csv_path}")

        trades: list[Trade] = []
        with open(csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError("CSV file is empty or has no header")

            missing = set(CSV_COLUMNS) - set(reader.fieldnames)
            if missing:
                raise ValueError(f"CSV missing required columns: {missing}")

            for row_num, row in enumerate(reader, start=2):
                try:
                    ts_str = row["timestamp"].strip()
                    # Handle both space and T separators
                    ts_str_normalised = ts_str.replace("T", " ")
                    timestamp = datetime.fromisoformat(ts_str_normalised)

                    trades.append(
                        Trade(
                            timestamp=timestamp,
                            pair=row["pair"].strip(),
                            direction=row["direction"].strip().lower(),
                            entry_price=float(row["entry_price"]),
                            exit_price=float(row["exit_price"]),
                            size=float(row["size"]),
                            pnl=float(row["pnl"]),
                            strategy=row["strategy"].strip() if row.get("strategy") else "unknown",
                        )
                    )
                except (ValueError, KeyError) as exc:
                    logger.warning("Skipping malformed CSV row %d: %s", row_num, exc)

        trades.sort(key=lambda t: t.timestamp)
        logger.info("Loaded %d trades from %s", len(trades), csv_path)
        return trades
