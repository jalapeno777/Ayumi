"""SRF Runner — wraps existing walk-forward engine, writes results to DuckDB."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .schema import SRFDatabase, compute_data_hash, generate_run_id
from .data_qa import validate_data
from .param_stability import perturbation_stability_score, PerturbationStabilityResult

logger = logging.getLogger(__name__)


class StrategyRunner:
    """Runs a strategy through walk-forward validation and records results in DuckDB."""

    def __init__(
        self,
        db_path: str = "data/research/research.duckdb",
        repo_path: str = ".",
    ):
        self.db = SRFDatabase(db_path)
        self.repo_path = Path(repo_path).resolve()

    # ── public API ───────────────────────────────────────────────────────

    def run(
        self,
        *,
        strategy_name: str,
        strategy_factory: Any,
        pair: str,
        timeframe: int,
        data_path: str,
        params: dict | None = None,
        n_windows: int = 5,
        initial_balance: float = 10_000,
        spread_pips: float | None = None,
        min_confidence: float = 0.30,
        register_if_missing: bool = True,
        perturbation_evaluate_fn: callable | None = None,
    ) -> dict:
        """Execute a single walk-forward run. Returns run metadata + results dict.

        If ``perturbation_evaluate_fn`` is provided, runs a post-selection
        perturbation stability check (overfit spike detection) after the
        walk-forward validation completes.  The function should accept a
        params dict and return a scalar performance metric.

        Raises RuntimeError if git tree is dirty or data QA fails.
        """
        start = time.monotonic()

        # ── 1. Git-clean guard ────────────────────────────────────────────
        git_commit = self._get_git_commit()
        if git_commit is None:
            raise RuntimeError(
                "Git tree is dirty — SRF requires a clean tree for reproducibility. "
                "Commit or stash changes before running."
            )

        # ── 1b. Hypothesis doc gate ────────────────────────────────────────
        # Prevents post-hoc rationalization: every strategy must have a
        # hypothesis doc written BEFORE the sweep, not reconstructed from
        # results after seeing profit factors.
        hypothesis_path = (
            self.repo_path / "docs" / "edges" / f"{strategy_name}-hypothesis.md"
        )
        if not hypothesis_path.exists():
            raise RuntimeError(
                f"Strategy '{strategy_name}' has no hypothesis doc at "
                f"{hypothesis_path}. Write the edge hypothesis BEFORE running "
                "a sweep — this prevents post-hoc rationalization of results."
            )

        # ── 2. Load + validate data ───────────────────────────────────────
        df = self._load_data(data_path)
        qa = validate_data(df, pair, timeframe)
        if not qa.passed:
            failures_str = "; ".join(
                f"{f.check_name}: {f.detail}" for f in qa.failures if f.severity == "hard"
            )
            raise RuntimeError(f"Data QA failed for {pair} {timeframe}m: {failures_str}")

        data_hash = compute_data_hash(data_path)

        # ── 3. Convert to Bar objects ─────────────────────────────────────
        bars = self._df_to_bars(df, pair)

        # ── 4. Ensure strategy registered in DB ───────────────────────────
        run_id = generate_run_id(strategy_name, pair, timeframe)

        with self.db as conn:
            self._ensure_strategy_registered(
                conn, strategy_name, strategy_factory, register_if_missing
            )

            # ── 5. Insert run record ──────────────────────────────────────
            conn.execute(
                """INSERT INTO runs
                   (run_id, strategy_name, pair, timeframe, params_json,
                    git_commit, data_hash, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'running', now())""",
                [
                    run_id, strategy_name, pair, timeframe,
                    json.dumps(params or {}), git_commit, data_hash,
                ],
            )

            try:
                # ── 6. Run walk-forward ───────────────────────────────────
                results = self._run_walk_forward(
                    bars=bars,
                    strategy_factory=strategy_factory,
                    pair=pair,
                    n_windows=n_windows,
                    initial_balance=initial_balance,
                    spread_pips=spread_pips,
                    min_confidence=min_confidence,
                )

                # ── 7. Write results to DB ────────────────────────────────
                self._write_results(conn, run_id, results)

                compute_seconds = time.monotonic() - start

                conn.execute(
                    """UPDATE runs SET status='completed', compute_seconds=?,
                       completed_at=now() WHERE run_id=?""",
                    [compute_seconds, run_id],
                )

                logger.info(
                    "SRF run %s completed in %.1fs — %d windows, go_nogo=%s",
                    run_id, compute_seconds,
                    len(results.per_window),
                    results.go_nogo,
                )

                result_dict = {
                    "run_id": run_id,
                    "strategy": strategy_name,
                    "pair": pair,
                    "timeframe": timeframe,
                    "go_nogo": results.go_nogo,
                    "windows": len(results.per_window),
                    "compute_seconds": compute_seconds,
                    "git_commit": git_commit,
                    "data_hash": data_hash,
                }

                # ── 8. Optional perturbation stability check ─────────────
                if perturbation_evaluate_fn is not None:
                    psr = perturbation_stability_score(
                        perturbation_evaluate_fn,
                        params or {},
                    )
                    result_dict["perturbation_stability"] = psr.summary()
                    result_dict["overfit_spike"] = psr.is_overfit_spike
                    logger.info(
                        "SRF run %s perturbation stability: score=%.3f, overfit_spike=%s",
                        run_id, psr.stability_score, psr.is_overfit_spike,
                    )

                return result_dict

            except Exception as exc:
                conn.execute(
                    "UPDATE runs SET status='failed', completed_at=now() WHERE run_id=?",
                    [run_id],
                )
                logger.error("SRF run %s failed: %s", run_id, exc)
                raise

    # ── internals ────────────────────────────────────────────────────────

    def _get_git_commit(self) -> str | None:
        """Return current git commit hash, or None if tree is dirty."""
        try:
            # Check if tree is clean
            diff = subprocess.check_output(
                ["git", "diff", "--stat"],
                cwd=str(self.repo_path),
                stderr=subprocess.DEVNULL,
            ).strip()
            if diff:
                return None
            # Get commit hash
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(self.repo_path),
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            return commit
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def _load_data(self, data_path: str) -> pd.DataFrame:
        """Load bar data from CSV. Normalizes column names to lowercase."""
        df = pd.read_csv(data_path)
        # Normalize column names (CSVs may use TitleCase)
        rename_map = {}
        for col in df.columns:
            lower = col.lower()
            if lower != col:
                rename_map[col] = lower
        if rename_map:
            df = df.rename(columns=rename_map)
        # Normalize timestamp column name variants
        if "date" in df.columns and "timestamp" not in df.columns:
            df = df.rename(columns={"date": "timestamp"})
        return df

    def _df_to_bars(self, df: pd.DataFrame, pair: str):
        """Convert DataFrame to list of Bar objects."""
        from backtest.engine import Bar

        bars = []
        for _, row in df.iterrows():
            ts = row["timestamp"]
            # Handle epoch ms or ISO string
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            else:
                dt = pd.to_datetime(ts)
                if dt.tz is None:
                    dt = dt.tz_localize("UTC")

            bars.append(
                Bar(
                    time=dt,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0)),
                )
            )
        return bars

    def _run_walk_forward(
        self,
        bars: list,
        strategy_factory: Any,
        pair: str,
        n_windows: int,
        initial_balance: float,
        spread_pips: float | None,
        min_confidence: float,
    ):
        """Call the existing walk-forward runner."""
        from backtest.walk_forward_runner import run_strategy_walk_forward

        return run_strategy_walk_forward(
            bars=bars,
            strategy_factory=strategy_factory,
            pair=pair,
            n_windows=n_windows,
            initial_balance=initial_balance,
            spread_pips=spread_pips,
            min_confidence=min_confidence,
        )

    def _ensure_strategy_registered(
        self, conn, name: str, strategy_factory: Any, register: bool
    ) -> None:
        """Ensure strategy exists in DB. Register if missing and allowed."""
        row = conn.execute(
            "SELECT name FROM strategies WHERE name=?", [name]
        ).fetchone()

        if row is None and register:
            # Try to get module path from the factory's class
            if isinstance(strategy_factory, type):
                cls = strategy_factory
            elif hasattr(strategy_factory, "__class__"):
                cls = strategy_factory.__class__
            else:
                cls = None
            module_path = ""
            if cls and hasattr(cls, "__module__"):
                module_path = f"{cls.__module__}.{cls.__name__}"

            conn.execute(
                """INSERT INTO strategies (name, version, module_path, status)
                   VALUES (?, '1.0', ?, 'production')""",
                [name, module_path],
            )
            logger.info("Auto-registered strategy '%s' in DB", name)

    def _write_results(self, conn, run_id: str, results) -> None:
        """Write walk-forward results to DuckDB tables.

        All three writes (windows, trades, metrics_summary) are wrapped in a
        single explicit transaction. If any insert fails the entire batch is
        rolled back so partial data never leaks into the reporting tables.

        Per-window schema columns populated:
            run_id, window_idx, win_rate, profit_factor, sharpe,
            max_drawdown, trade_count, total_pnl, passed_go_nogo.

        Per-trade columns populated from `results._trade_records` (attached by
        the walk-forward runner). Each trade record carries ``window_id``,
        ``direction`` and ``pnl``; entry/exit price/time are stored as NULL
        because the walk-forward summary does not retain them — the full
        trade tape lives in the backtest engine. ``exit_reason`` is NULL in
        the same spirit; rationale is dropped (it isn't a column on the
        trades table).
        """
        import statistics

        # ── Windows ───────────────────────────────────────────────────────
        window_rows: list[list] = []
        for w in results.per_window:
            window_rows.append([
                run_id, w.window_index,
                w.win_rate, w.profit_factor, w.sharpe_ratio,
                w.max_drawdown, w.trade_count, w.total_pnl,
                w.passed_go_nogo,
            ])

        # ── Trades ────────────────────────────────────────────────────────
        # Pull trade records off the results object; the walk-forward runner
        # attaches ``_trade_records`` as a sidecar (typed as Any on the
        # dataclass). Be defensive: missing attribute, wrong type, or empty
        # list all degrade gracefully to "no trades persisted".
        trade_rows: list[list] = []
        trade_records = getattr(results, "_trade_records", None)
        if trade_records:
            for t in trade_records:
                if not isinstance(t, dict):
                    continue
                pnl = t.get("pnl")
                # Skip degenerate rows that have no numeric PnL — they corrupt
                # downstream aggregations.
                if pnl is None:
                    continue
                trade_rows.append([
                    run_id,
                    t.get("window_id"),
                    t.get("direction"),
                    pnl,
                    t.get("exit_reason"),
                ])

        # ── Metrics summary ───────────────────────────────────────────────
        windows_passed = sum(1 for w in results.per_window if w.passed_go_nogo)
        windows_total = len(results.per_window)

        wrs = [w.win_rate for w in results.per_window if w.trade_count > 0]
        pfs = [w.profit_factor for w in results.per_window if w.trade_count > 0]
        shrs = [w.sharpe_ratio for w in results.per_window if w.trade_count > 0]
        dds = [w.max_drawdown for w in results.per_window if w.trade_count > 0]
        total_trades = sum(w.trade_count for w in results.per_window)

        go_nogo_str = "go" if results.go_nogo else "no-go"

        summary_row = [
            run_id,
            statistics.mean(wrs) if wrs else None,
            statistics.stdev(wrs) if len(wrs) > 1 else None,
            statistics.mean(pfs) if pfs else None,
            statistics.stdev(pfs) if len(pfs) > 1 else None,
            statistics.mean(shrs) if shrs else None,
            statistics.stdev(shrs) if len(shrs) > 1 else None,
            statistics.mean(dds) if dds else None,
            statistics.stdev(dds) if len(dds) > 1 else None,
            total_trades, windows_passed, windows_total, go_nogo_str,
        ]

        # ── Single explicit transaction ───────────────────────────────────
        # Without an explicit BEGIN/COMMIT, DuckDB's autocommit treats each
        # executemany as its own commit and a failure mid-batch would leave
        # partial state. Atomic transaction is required for the reporting
        # views (v_top_strategies joins on run_id).
        try:
            conn.execute("BEGIN")
            self._insert_windows(conn, window_rows)
            self._insert_trades(conn, trade_rows)
            self._insert_metrics_summary(conn, summary_row)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.exception(
                "SRF persistence failed for run %s "
                "(windows=%d, trades=%d): %s",
                run_id, len(window_rows), len(trade_rows), exc,
            )
            raise

        logger.info(
            "SRF run %s persisted: %d windows, %d trades, summary written",
            run_id, len(window_rows), len(trade_rows),
        )

    # ── per-table inserts (split out for testability + clarity) ─────────

    @staticmethod
    def _insert_windows(conn, rows: list[list]) -> None:
        """Bulk-insert window metrics. Empty ``rows`` is a no-op."""
        if not rows:
            return
        conn.executemany(
            """INSERT INTO windows
               (run_id, window_idx, win_rate, profit_factor, sharpe,
                max_drawdown, trade_count, total_pnl, passed_go_nogo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    @staticmethod
    def _insert_trades(conn, rows: list[list]) -> None:
        """Bulk-insert per-trade rows. Empty ``rows`` is a no-op."""
        if not rows:
            return
        conn.executemany(
            """INSERT INTO trades
               (run_id, window_idx, direction, pnl, exit_reason)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )

    @staticmethod
    def _insert_metrics_summary(conn, row: list) -> None:
        """Insert the per-run aggregate row. ``row`` must have 13 elements."""
        if row is None or len(row) != 13:
            raise ValueError(
                f"metrics_summary row must have 13 elements, got {len(row) if row else 0}"
            )
        conn.execute(
            """INSERT INTO metrics_summary
               (run_id, mean_win_rate, std_win_rate, mean_profit_factor,
                std_profit_factor, mean_sharpe, std_sharpe,
                mean_max_drawdown, std_max_drawdown, total_trades,
                windows_passed, windows_total, go_nogo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            row,
        )
