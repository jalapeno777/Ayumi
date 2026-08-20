"""Bar-close timing audit for signal engine signals.

Reads historical signals from data/signals/*.jsonl, categorizes each signal by
whether it was evaluated on a closed bar (VALID), a forming bar (FORMING), or
after the bar close plus tolerance (LATE), and writes results to
data/audit/bar_close_audit.jsonl.

Usage:
    python -m backtest.audit_bar_close [--signals-dir DIR] [--output PATH]
        [--summary] [--tolerance-ms N] [--trading-db PATH]

Integrates with the Ayumi signal pipeline.  Read-only on production data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger("audit_bar_close")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

DEFAULT_TOLERANCE_MS = 1000
DEFAULT_TIMEFRAME = "H1"

# Spread lookup (from backtest.types PAIR_SPREAD_PIPS)
PAIR_SPREAD_PIPS: dict[str, float] = {
    "EURUSD": 1.5,
    "GBPUSD": 1.5,
    "USDJPY": 1.5,
    "AUDUSD": 1.5,
    "NZDUSD": 1.5,
    "USDCAD": 1.5,
    "USDCHF": 1.5,
    "GBPJPY": 3.0,
    "EURJPY": 2.0,
    "AUDJPY": 2.0,
    "EURGBP": 1.5,
    "EURAUD": 2.0,
    "GBPAUD": 2.5,
    "GBPCAD": 2.5,
    "EURNZD": 2.5,
    "GBPNZD": 3.0,
    "XAUUSD": 2.5,
    "XAGUSD": 3.0,
}
DEFAULT_SPREAD_PIPS = 1.5


def _get_spread_for_pair(pair: str) -> float:
    return PAIR_SPREAD_PIPS.get(pair.upper(), DEFAULT_SPREAD_PIPS)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AuditRecord:
    """Single signal audit result."""

    signal_id: str
    timestamp: str
    instrument: str
    direction: str
    timeframe: str
    timing_status: str  # VALID | FORMING | LATE
    spread_at_entry: float
    # Extra context (not in required output schema but useful)
    strategy_id: str
    bar_close_time: str
    offset_ms: int


@dataclass
class AuditSummary:
    """Aggregate statistics."""

    total_signals: int
    valid: int
    forming: int
    late: int
    skipped: int
    pct_valid: float
    pct_forming: float
    pct_late: float
    by_strategy: dict[str, dict[str, int]]
    by_timeframe: dict[str, dict[str, int]]


# ---------------------------------------------------------------------------
# Signal loading
# ---------------------------------------------------------------------------


def _parse_timestamp(raw: Any) -> Optional[datetime]:
    """Parse an ISO-format timestamp into a timezone-aware UTC datetime.

    Handles:
    - ``2025-01-06T07:00:00`` (naive → assumed UTC)
    - ``2025-01-06T07:00:00Z``
    - ``2025-01-06T07:00:00+00:00``
    - Unix epoch numbers
    """
    if raw is None:
        return None

    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (ValueError, OSError):
            return None

    if not isinstance(raw, str):
        return None

    ts = raw.strip()
    if not ts:
        return None

    # Try ISO format
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        # Try common alternative formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                dt = datetime.strptime(ts, fmt)
                break
            except ValueError:
                continue
        else:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt


def _generate_signal_id(signal: dict, file_source: str, line_num: int) -> str:
    """Deterministic signal ID from signal content + source location."""
    raw = f"{file_source}:{line_num}:{signal.get('timestamp', '')}:{signal.get('symbol', '')}:{signal.get('direction', '')}"  # noqa: E501
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def iter_signals(signals_dir: Path) -> Iterator[tuple[dict, str, int]]:
    """Yield (signal_dict, source_file, line_num) from all JSONL files.

    Skips empty lines and malformed JSON with a warning.
    """
    if not signals_dir.exists():
        logger.warning("Signals directory %s does not exist", signals_dir)
        return

    for filepath in sorted(signals_dir.glob("*.jsonl")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        obj = json.loads(stripped)
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed JSON in %s:%d", filepath.name, line_num)
                        continue
                    if not isinstance(obj, dict):
                        logger.warning("Skipping non-object line in %s:%d", filepath.name, line_num)
                        continue
                    yield obj, filepath.name, line_num
        except OSError as exc:
            logger.warning("Cannot read %s: %s", filepath, exc)


# ---------------------------------------------------------------------------
# Bar-close computation
# ---------------------------------------------------------------------------


def compute_bar_close(signal_ts: datetime, timeframe: str) -> Optional[datetime]:
    """Compute the nearest bar-close time for *signal_ts* given *timeframe*.

    Finds the closest timeframe-aligned boundary to *signal_ts*.
    Returns ``None`` if the timeframe is unknown.
    """
    seconds = TIMEFRAME_SECONDS.get(timeframe.upper())
    if seconds is None:
        logger.warning("Unknown timeframe: %s", timeframe)
        return None

    epoch = signal_ts.timestamp()
    # Nearest boundary
    nearest_epoch = round(epoch / seconds) * seconds
    return datetime.fromtimestamp(nearest_epoch, tz=timezone.utc)


def categorize_timing(
    signal_ts: datetime,
    bar_close: datetime,
    tolerance_ms: int = DEFAULT_TOLERANCE_MS,
) -> tuple[str, int]:
    """Categorize signal timing relative to bar close.

    Returns (status, offset_ms) where status is VALID, FORMING, or LATE.
    """
    diff_seconds = (signal_ts - bar_close).total_seconds()
    offset_ms = int(round(diff_seconds * 1000))

    if offset_ms == 0:
        return "VALID", offset_ms
    if offset_ms < 0:
        # Signal before bar close → forming bar
        return "FORMING", offset_ms
    # offset_ms > 0
    if offset_ms <= tolerance_ms:
        return "VALID", offset_ms
    return "LATE", offset_ms


# ---------------------------------------------------------------------------
# Trading DB integration
# ---------------------------------------------------------------------------


def fetch_spread_from_db(db_path: Path, symbol: str, entry_time: str) -> Optional[float]:
    """Try to look up spread from trade data.

    Currently the trades table does not store spread directly, so this
    returns None and we fall back to the static lookup table.
    """
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        # Check if a spread column exists
        cursor = conn.execute("PRAGMA table_info(trades)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        if "spread_at_entry" in columns:
            # Future: query actual spread
            return None
    except sqlite3.Error:
        pass
    return None


# ---------------------------------------------------------------------------
# Audit runner
# ---------------------------------------------------------------------------


def run_audit(
    signals_dir: Path,
    output_path: Path,
    trading_db: Path,
    tolerance_ms: int = DEFAULT_TOLERANCE_MS,
    print_summary: bool = False,
) -> AuditSummary:
    """Run the bar-close audit on all signal files.

    Args:
        signals_dir: Directory containing *.jsonl signal files.
        output_path: Path for JSONL output.
        trading_db: Path to trading.db (read-only).
        tolerance_ms: Late signal threshold in milliseconds.
        print_summary: If True, print aggregate stats to stdout.

    Returns:
        AuditSummary with aggregate statistics.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[AuditRecord] = []
    skipped = 0
    strategy_counts: dict[str, dict[str, int]] = {}
    timeframe_counts: dict[str, dict[str, int]] = {}

    def _bump(counter: dict, key: str, status: str):
        sub = counter.setdefault(key, {"VALID": 0, "FORMING": 0, "LATE": 0})
        sub[status] += 1

    for signal, source, line_num in iter_signals(signals_dir):
        # Parse timestamp
        signal_ts = _parse_timestamp(signal.get("timestamp"))
        if signal_ts is None:
            logger.warning("Skipping signal with unparseable timestamp in %s:%d", source, line_num)
            skipped += 1
            continue

        # Determine timeframe (default H1 per Signal dataclass)
        timeframe = signal.get("timeframe", DEFAULT_TIMEFRAME)

        # Determine instrument
        instrument = signal.get("symbol", signal.get("instrument", "UNKNOWN"))

        # Compute bar close
        bar_close = compute_bar_close(signal_ts, timeframe)
        if bar_close is None:
            skipped += 1
            continue

        # Categorize
        status, offset_ms = categorize_timing(signal_ts, bar_close, tolerance_ms)

        # Spread lookup
        spread = fetch_spread_from_db(trading_db, instrument, signal_ts.isoformat())
        if spread is None:
            spread = _get_spread_for_pair(instrument)

        # Generate signal ID
        signal_id = signal.get("signal_id") or _generate_signal_id(signal, source, line_num)

        # Strategy
        strategy_id = signal.get("strategy_id", signal.get("strategy_name", "unknown"))

        record = AuditRecord(
            signal_id=signal_id,
            timestamp=signal_ts.isoformat(),
            instrument=instrument,
            direction=signal.get("direction", "UNKNOWN"),
            timeframe=timeframe,
            timing_status=status,
            spread_at_entry=spread,
            strategy_id=strategy_id,
            bar_close_time=bar_close.isoformat(),
            offset_ms=offset_ms,
        )
        records.append(record)

        _bump(strategy_counts, strategy_id, status)
        _bump(timeframe_counts, timeframe, status)

    # Write JSONL output
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in records:
            # Output schema matches acceptance criteria
            out = {
                "signal_id": rec.signal_id,
                "timestamp": rec.timestamp,
                "instrument": rec.instrument,
                "direction": rec.direction,
                "timeframe": rec.timeframe,
                "timing_status": rec.timing_status,
                "spread_at_entry": rec.spread_at_entry,
            }
            f.write(json.dumps(out, default=str) + "\n")

    total = len(records)
    valid = sum(1 for r in records if r.timing_status == "VALID")
    forming = sum(1 for r in records if r.timing_status == "FORMING")
    late = sum(1 for r in records if r.timing_status == "LATE")

    summary = AuditSummary(
        total_signals=total,
        valid=valid,
        forming=forming,
        late=late,
        skipped=skipped,
        pct_valid=(valid / total * 100) if total else 0.0,
        pct_forming=(forming / total * 100) if total else 0.0,
        pct_late=(late / total * 100) if total else 0.0,
        by_strategy=strategy_counts,
        by_timeframe=timeframe_counts,
    )

    if print_summary:
        _print_summary(summary)

    logger.info(
        "Audit complete: %d signals (%d valid, %d forming, %d late, %d skipped)",
        total,
        valid,
        forming,
        late,
        skipped,
    )

    return summary


def _print_summary(summary: AuditSummary) -> None:
    """Print human-readable aggregate stats."""
    print("\n" + "=" * 60)
    print("       BAR-CLOSE TIMING AUDIT SUMMARY")
    print("=" * 60)
    print(f"\n  Total signals:   {summary.total_signals}")
    print(f"  Skipped:         {summary.skipped}")
    print()
    print(f"  VALID:           {summary.valid:>6d}  ({summary.pct_valid:.1f}%)")
    print(f"  FORMING:         {summary.forming:>6d}  ({summary.pct_forming:.1f}%)")
    print(f"  LATE:            {summary.late:>6d}  ({summary.pct_late:.1f}%)")

    if summary.by_strategy:
        print("\n  By Strategy:")
        for strat, counts in sorted(summary.by_strategy.items()):
            s_total = sum(counts.values())
            s_valid = counts.get("VALID", 0)
            s_forming = counts.get("FORMING", 0)
            s_late = counts.get("LATE", 0)
            pct_v = (s_valid / s_total * 100) if s_total else 0
            pct_f = (s_forming / s_total * 100) if s_total else 0
            pct_l = (s_late / s_total * 100) if s_total else 0
            print(f"    {strat:<30s} V:{pct_v:5.1f}%  F:{pct_f:5.1f}%  L:{pct_l:5.1f}%")

    if summary.by_timeframe and len(summary.by_timeframe) > 1:
        print("\n  By Timeframe:")
        for tf, counts in sorted(summary.by_timeframe.items()):
            t_total = sum(counts.values())
            t_valid = counts.get("VALID", 0)
            t_forming = counts.get("FORMING", 0)
            t_late = counts.get("LATE", 0)
            pct_v = (t_valid / t_total * 100) if t_total else 0
            pct_f = (t_forming / t_total * 100) if t_total else 0
            pct_l = (t_late / t_total * 100) if t_total else 0
            print(f"    {tf:<10s}              V:{pct_v:5.1f}%  F:{pct_f:5.1f}%  L:{pct_l:5.1f}%")

    print("\n" + "=" * 60 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit signal timing relative to bar close times.")
    parser.add_argument(
        "--signals-dir",
        type=Path,
        default=Path("data/signals"),
        help="Directory containing signal JSONL files (default: data/signals)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/audit/bar_close_audit.jsonl"),
        help="Output JSONL path (default: data/audit/bar_close_audit.jsonl)",
    )
    parser.add_argument(
        "--trading-db",
        type=Path,
        default=Path("data/trading.db"),
        help="Path to trading.db (default: data/trading.db)",
    )
    parser.add_argument(
        "--tolerance-ms",
        type=int,
        default=DEFAULT_TOLERANCE_MS,
        help=f"Late signal threshold in ms (default: {DEFAULT_TOLERANCE_MS})",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print aggregate stats to stdout",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    summary = run_audit(
        signals_dir=args.signals_dir,
        output_path=args.output,
        trading_db=args.trading_db,
        tolerance_ms=args.tolerance_ms,
        print_summary=args.summary,
    )

    # Exit code: 0 if any signals processed, 1 if none
    return 0 if summary.total_signals > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
