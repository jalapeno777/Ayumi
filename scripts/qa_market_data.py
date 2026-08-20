#!/usr/bin/env python3
"""QA checks on M1 (and other timeframe) bar CSV data.

This script inspects every CSV in ``data/forex/historical/`` (and
``data/forex/dukascopy/`` if present) and produces a Markdown QA report at
``reports/qa-report-{YYYY-MM-DD}.md``.

Checks performed per file:

1. **Gap detection** — Identify missing bars at the file's native cadence.
   Weekend gaps (FX market closed Sat / Sun) are expected and *not* counted;
   only weekday gaps are flagged. A "weekend gap" is defined as one whose
   preceding bar is Friday >= 21:00 UTC *or* Saturday, and whose following
   bar is Sunday >= 21:00 UTC *or* Monday. Everything else with a delta
   larger than the expected bar period is a real gap.

2. **Timestamp integrity** — Monotonically increasing (no backward steps),
   no duplicate timestamps.

3. **Price sanity** — Reject negative values; flag any bar-to-bar close move
   larger than 5% as anomalous (likely data error, fat finger, or genuine
   flash event — surfaced for human review).

4. **Regime-shift flags** — Mark periods of bar data falling inside the
   following windows (UTC):

       CHF unpeg          2015-01-15
       COVID onset        2020-03-01 .. 2020-06-30
       Rate-hike cycle    2022-06-01 .. 2023-12-31

   These windows often exhibit atypical price behaviour, statistical
   non-stationarity, or structural breaks that downstream ML / backtests
   should be aware of.

5. **Output** — ``reports/qa-report-{YYYY-MM-DD}.md`` summarising:
   - Pair-level gap density (gaps per 1000 bars, weekend-gaps separately)
   - Top anomalies (timestamp / price)
   - Regime-shift bar counts per pair

Usage::

    python scripts/qa_market_data.py                       # default
    python scripts/qa_market_data.py --pairs XAUUSD EURUSD # subset
    python scripts/qa_market_data.py --historical-dir ...  # custom dir
    python scripts/qa_market_data.py --print-summary       # stdout summary
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

# Default search paths for input CSVs (in priority order).
DEFAULT_INPUT_DIRS = (
    Path("data/forex/historical"),
    Path("data/forex/dukascopy"),
)

# Default report directory.
DEFAULT_REPORT_DIR = Path("reports")

# Bar periods we know how to interpret. Anything not in this map will still be
# scanned but gap analysis will fall back to "median delta × 1.5" as the
# expected period.
KNOWN_PERIODS_MIN: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M10": 10,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

# Regime-shift windows (inclusive). All UTC.
REGIME_WINDOWS: list[tuple[str, datetime, datetime]] = [
    (
        "CHF unpeg (2015-01-15)",
        datetime(2015, 1, 14, 22, 0, tzinfo=timezone.utc),
        datetime(2015, 1, 16, 0, 0, tzinfo=timezone.utc),
    ),
    (
        "COVID onset (2020-03-01 .. 2020-06-30)",
        datetime(2020, 3, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2020, 6, 30, 23, 59, tzinfo=timezone.utc),
    ),
    (
        "Rate-hike cycle (2022-06-01 .. 2023-12-31)",
        datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2023, 12, 31, 23, 59, tzinfo=timezone.utc),
    ),
]

# Daily close hour for FX markets (UTC). Friday close ~ 22:00 UTC.
FRIDAY_CLOSE_HOUR_UTC = 21  # treat a Friday bar at >=21:00 UTC as "near close"

# Price jump threshold (5%) for the "anomalous bar" check.
PRICE_JUMP_THRESHOLD = 0.05

# Cap on rows sampled per file when reporting detailed anomalies.
ANOMALY_DETAIL_CAP = 20


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------


@dataclass
class FileReport:
    """QA findings for a single CSV file."""

    pair: str
    timeframe: str
    path: str
    rows: int
    first_ts: str
    last_ts: str
    csv_header: list[str] = field(default_factory=list)
    timestamp_ok: bool = True
    timestamp_issues: list[str] = field(default_factory=list)
    duplicate_count: int = 0
    negative_price_count: int = 0
    big_jump_count: int = 0
    big_jump_samples: list[dict] = field(default_factory=list)
    gap_count: int = 0
    weekend_gap_count: int = 0
    gap_density: float = 0.0  # gaps per 1000 bars
    weekend_gap_density: float = 0.0
    regime_counts: dict[str, int] = field(default_factory=dict)
    inferred_period_min: float | None = None
    skipped: bool = False
    skip_reason: str = ""


# -----------------------------------------------------------------------------
# CSV parsing — tolerant to two existing on-disk dialects
# -----------------------------------------------------------------------------


@dataclass
class ParsedBars:
    """Parsed OHLCV rows + the timestamp column name used."""

    df: pd.DataFrame  # columns: timestamp (datetime64[ns, UTC]), open, high, low, close, volume
    ts_col: str


def _detect_timestamp_col(header: list[str]) -> str | None:
    """Pick the timestamp column from a CSV header.

    Recognises ``timestamp``, ``Timestamp``, ``Date``, ``date``, ``Datetime``,
    and ``datetime``. We don't accept any other column as a timestamp proxy.
    """
    norm = {h.strip().lower(): h for h in header}
    for cand in ("timestamp", "date", "datetime", "time"):
        if cand in norm:
            return norm[cand]
    return None


def _looks_like_market_data(header: list[str]) -> bool:
    """True when the CSV header clearly contains OHLC columns we can use."""
    norm = {h.strip().lower() for h in header}
    return {"open", "high", "low", "close"}.issubset(norm)


def _load_csv(path: Path) -> ParsedBars | None:
    """Load a CSV and return a normalised ``ParsedBars`` or ``None`` on failure."""
    try:
        with open(path, "r", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
    except (OSError, StopIteration) as e:
        print(f"  [skip] {path}: cannot read header ({e})", file=sys.stderr)
        return None

    # Bail out early on CSVs that aren't market data (feature CSVs, walk-
    # forward results, etc.) — they don't have the OHLC quartet and the
    # QA checks below wouldn't be meaningful.
    if not _looks_like_market_data(header):
        return None

    ts_col = _detect_timestamp_col(header)
    if ts_col is None:
        print(f"  [skip] {path}: no timestamp column (header={header})", file=sys.stderr)
        return None

    # Read the rest with pandas using only the columns we want.
    wanted = [ts_col, "Open", "High", "Low", "Close", "Volume"]
    # Some files don't have all OHLCV columns (e.g. feature CSVs); defer to pandas
    # dtype detection if our hand-picked list fails.
    try:
        df = pd.read_csv(path, usecols=wanted)
    except (ValueError, KeyError):
        df = pd.read_csv(path)

    # Normalise column names to lowercase.
    df = df.rename(
        columns={
            ts_col: "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    if "timestamp" not in df.columns:
        # Last-ditch: take the first column as timestamp.
        df = df.rename(columns={df.columns[0]: "timestamp"})

    # Parse timestamps.
    try:
        ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    except (TypeError, ValueError) as e:
        print(f"  [skip] {path}: timestamp parse failed ({e})", file=sys.stderr)
        return None

    bad_ts = int(ts.isna().sum())
    if bad_ts == len(ts):
        print(f"  [skip] {path}: all timestamps unparseable", file=sys.stderr)
        return None
    if bad_ts > 0:
        print(
            f"  [warn] {path}: dropped {bad_ts} rows with unparseable timestamps",
            file=sys.stderr,
        )
        df = df.loc[ts.notna()].copy()
        ts = ts.loc[ts.notna()]

    df["timestamp"] = ts
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = float("nan")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    else:
        df["volume"] = 0

    df = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    return ParsedBars(df=df, ts_col=ts_col)


# -----------------------------------------------------------------------------
# Per-file QA checks
# -----------------------------------------------------------------------------


_FILENAME_RE = re.compile(r"^(?P<pair>[A-Z]{6})_(?P<tf>M\d+|H\d+|D\d+)(?:_.*)?$")


def _pair_timeframe_from_filename(path: Path) -> tuple[str, str]:
    """Infer (pair, timeframe) from the filename stem. Defaults to UNK."""
    stem = path.stem.upper()
    # Try first with the strict pattern.
    m = _FILENAME_RE.match(stem)
    if m:
        return m.group("pair"), m.group("tf")
    # Fallback: split on first underscore.
    parts = stem.split("_", 1)
    if len(parts) == 2 and len(parts[0]) in (6, 7):
        return parts[0], parts[1]
    return "UNK", "UNK"


def _expected_period_min(timeframe: str, deltas_min: pd.Series) -> float:
    """Best estimate of the bar period in minutes (median used as fallback)."""
    if timeframe in KNOWN_PERIODS_MIN:
        return float(KNOWN_PERIODS_MIN[timeframe])
    if deltas_min.empty:
        return 1.0
    med = float(deltas_min.median())
    return med if med > 0 else 1.0


def _is_weekend_gap(prev_ts: pd.Timestamp, next_ts: pd.Timestamp) -> bool:
    """True if the gap spans the FX weekend (Fri 22:00 UTC .. Sun 22:00 UTC)."""
    # Convert to UTC pandas Timestamp.
    p = pd.Timestamp(prev_ts)
    n = pd.Timestamp(next_ts)
    if p.tzinfo is None:
        p = p.tz_localize(timezone.utc)
    if n.tzinfo is None:
        n = n.tz_localize(timezone.utc)

    p_wd = p.weekday()
    n_wd = n.weekday()
    p_hour = p.hour

    # Case 1: prev is Friday (4) at/after 21:00 UTC, next is Sunday (6) or later.
    if p_wd == 4 and p_hour >= FRIDAY_CLOSE_HOUR_UTC:
        return n_wd in (6, 0) and (n_wd > 4 or (n.day != p.day))
    # Case 2: prev is Saturday (5) -- still FX weekend in progress.
    if p_wd == 5:
        return n_wd in (6, 0)
    # Case 3: prev is Sunday (6) early, before Sunday open.
    if p_wd == 6:
        return n_wd in (6, 0) and n > p
    return False


def _check_timestamp_integrity(df: pd.DataFrame, rep: FileReport) -> None:
    """Cheap O(N) pass — flags unordered or duplicate timestamps."""
    ts = df["timestamp"].to_numpy()
    rep.timestamp_ok = True
    if len(ts) < 2:
        return

    # Vectorised duplicate detection via diff==0.
    diffs = ts[1:] - ts[:-1]
    dup_idx = (diffs == pd.Timedelta(0)).nonzero()[0]
    if len(dup_idx):
        rep.timestamp_ok = False
        rep.duplicate_count = int(len(dup_idx))
        for i in dup_idx[:ANOMALY_DETAIL_CAP]:
            rep.timestamp_issues.append(f"duplicate timestamp at row {int(i) + 1}: {pd.Timestamp(ts[i]).isoformat()}")

    # Negative delta = backward step.
    neg_idx = (diffs < pd.Timedelta(0)).nonzero()[0]
    if len(neg_idx):
        rep.timestamp_ok = False
        for i in neg_idx[:ANOMALY_DETAIL_CAP]:
            rep.timestamp_issues.append(
                f"non-monotonic at row {int(i) + 1}: "
                f"{pd.Timestamp(ts[i]).isoformat()} -> {pd.Timestamp(ts[i + 1]).isoformat()}"
            )


def _check_price_sanity(df: pd.DataFrame, rep: FileReport) -> None:
    """Negative prices = bug; >5% bar-to-bar close moves = anomalous."""
    prices = df[["open", "high", "low", "close"]].to_numpy()
    neg_mask = (prices < 0).any(axis=1)
    if neg_mask.any():
        rep.negative_price_count = int(neg_mask.sum())
        rep.timestamp_issues.append(f"{rep.negative_price_count} rows with negative OHLC values")

    close = df["close"].to_numpy()
    ts = df["timestamp"].to_numpy()
    if len(close) < 2:
        return
    # Vectorised percent-change check. We divide only when the prior close
    # is non-zero (a zero close is itself a data error we'll surface elsewhere
    # via the negative-price or big-jump checks; here we just skip the ratio).
    prev = close[:-1]
    curr = close[1:]
    safe = np_where_nonzero(prev)
    ratio = (curr - prev) / safe
    big = (np_abs(ratio) > PRICE_JUMP_THRESHOLD).nonzero()[0]
    if len(big):
        rep.big_jump_count = int(len(big))
        for i in big[:ANOMALY_DETAIL_CAP]:
            ts0 = pd.Timestamp(ts[i]).isoformat()
            ts1 = pd.Timestamp(ts[i + 1]).isoformat()
            rep.big_jump_samples.append(
                {
                    "t0": ts0,
                    "t1": ts1,
                    "close0": float(prev[i]),
                    "close1": float(curr[i]),
                    "delta_pct": round(100.0 * (curr[i] - prev[i]) / prev[i], 3),
                }
            )


def _check_gaps(df: pd.DataFrame, rep: FileReport) -> None:
    """Classify gaps in the bar stream into weekday vs weekend."""
    ts = df["timestamp"]
    if len(ts) < 2:
        return
    deltas = ts.diff().dropna()
    if deltas.empty:
        return

    expected_min = _expected_period_min(rep.timeframe, deltas.dt.total_seconds() / 60.0)
    rep.inferred_period_min = expected_min

    threshold = pd.Timedelta(minutes=expected_min * 1.5)
    big = deltas[deltas > threshold]
    if big.empty:
        return

    weekend = 0
    weekday = 0
    rows = df.itertuples(index=False)
    last = next(rows)
    for cur in rows:
        delta = cur.timestamp - last.timestamp
        if delta > threshold:
            if _is_weekend_gap(last.timestamp, cur.timestamp):
                weekend += 1
            else:
                weekday += 1
        last = cur

    rep.gap_count = int(weekday)
    rep.weekend_gap_count = int(weekend)
    nrows = max(1, rep.rows)
    rep.gap_density = round(1000.0 * weekday / nrows, 4)
    rep.weekend_gap_density = round(1000.0 * weekend / nrows, 4)


def _check_regime_windows(df: pd.DataFrame, rep: FileReport) -> None:
    """Count rows in each known regime-shift window."""
    ts = df["timestamp"]
    out: dict[str, int] = {}
    for name, start, end in REGIME_WINDOWS:
        in_win = (ts >= pd.Timestamp(start)) & (ts <= pd.Timestamp(end))
        out[name] = int(in_win.sum())
    rep.regime_counts = out


def _qa_file(path: Path) -> FileReport:
    """Run all checks on one CSV file."""
    parsed = _load_csv(path)
    pair, tf = _pair_timeframe_from_filename(path)
    rep = FileReport(
        pair=pair,
        timeframe=tf,
        path=str(path),
        rows=0,
        first_ts="",
        last_ts="",
        csv_header=[],
    )

    if parsed is None:
        rep.skipped = True
        rep.skip_reason = "load_failed"
        return rep

    df = parsed.df
    if df.empty:
        rep.skipped = True
        rep.skip_reason = "empty_file"
        return rep

    rep.rows = len(df)
    rep.first_ts = df["timestamp"].iloc[0].isoformat()
    rep.last_ts = df["timestamp"].iloc[-1].isoformat()

    try:
        _check_timestamp_integrity(df, rep)
    except Exception as e:
        rep.timestamp_issues.append(f"timestamp_integrity check errored: {e}")
    try:
        _check_price_sanity(df, rep)
    except Exception as e:
        rep.timestamp_issues.append(f"price_sanity check errored: {e}")
    try:
        _check_gaps(df, rep)
    except Exception as e:
        rep.timestamp_issues.append(f"gap check errored: {e}")
    try:
        _check_regime_windows(df, rep)
    except Exception as e:
        rep.timestamp_issues.append(f"regime check errored: {e}")

    return rep


# -----------------------------------------------------------------------------
# Tiny numpy helpers (avoid pulling numpy if we can; but pandas already
# brings it — using it for clarity over re-implementing diff/sign/where).
# -----------------------------------------------------------------------------

# We import numpy lazily because some environments may not have it.
np_abs = None
np_where_nonzero = None


def _ensure_numpy() -> None:
    global np_abs, np_where_nonzero
    if np_abs is None:
        import numpy as _np

        def _np_where_nonzero(a):
            """Return ``a`` with zeros replaced by 1 (avoid div-by-zero)."""
            return _np.where(a != 0, a, 1.0)

        np_abs = _np.abs
        np_where_nonzero = _np_where_nonzero


# -----------------------------------------------------------------------------
# Report rendering
# -----------------------------------------------------------------------------


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a GitHub-flavoured-Markdown pipe table."""
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def render_markdown(reports: list[FileReport], generated_at: datetime) -> str:
    """Render the QA report as a single Markdown document."""
    lines: list[str] = []
    lines.append("# Market Data QA Report")
    lines.append("")
    lines.append(f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")

    scanned = [r for r in reports if not r.skipped]
    skipped = [r for r in reports if r.skipped]
    lines.append(f"Files scanned: {len(scanned)} ({len(skipped)} skipped)")
    lines.append("")

    # ---- Gap density per pair (only pairs with non-zero gaps) ----
    gap_rows: list[list[str]] = []
    for rep in sorted(reports, key=lambda r: (r.pair, r.timeframe)):
        if rep.skipped:
            continue
        gap_rows.append(
            [
                rep.pair,
                rep.timeframe,
                str(rep.rows),
                str(rep.gap_count),
                str(rep.weekend_gap_count),
                f"{rep.gap_density:.4f}",
                f"{rep.weekend_gap_density:.4f}",
                f"{rep.inferred_period_min:.2f}" if rep.inferred_period_min is not None else "n/a",
            ]
        )
    lines.append("## Gap density per pair")
    lines.append("")
    lines.append("Gap density = gaps per 1000 bars. Weekend gaps (Sat / Sun UTC) are expected and reported separately.")
    lines.append("")
    lines.append(
        _format_table(
            [
                "Pair",
                "TF",
                "Rows",
                "Gaps",
                "Weekend gaps",
                "Gap/1k",
                "Wknd/1k",
                "Δ (min)",
            ],
            gap_rows,
        )
    )
    lines.append("")

    # ---- Anomalies ----
    lines.append("## Anomalies")
    lines.append("")
    any_anom = False
    for rep in sorted(reports, key=lambda r: (r.pair, r.timeframe)):
        if rep.skipped:
            continue
        bits: list[str] = []
        if rep.duplicate_count:
            bits.append(f"{rep.duplicate_count} duplicate timestamps")
        if rep.negative_price_count:
            bits.append(f"{rep.negative_price_count} negative-price rows")
        if rep.big_jump_count:
            bits.append(f"{rep.big_jump_count} >{int(PRICE_JUMP_THRESHOLD * 100)}% close jumps")
        if bits:
            any_anom = True
            lines.append(f"- **{rep.pair} {rep.timeframe}** — {', '.join(bits)}  ")
            lines.append(f"  - path: `{rep.path}`")
            for issue in rep.timestamp_issues[:ANOMALY_DETAIL_CAP]:
                lines.append(f"  - {issue}")
            for s in rep.big_jump_samples[:ANOMALY_DETAIL_CAP]:
                lines.append(
                    f"  - jump: `{s['t0']}` close={s['close0']} → "
                    f"`{s['t1']}` close={s['close1']} (Δ {s['delta_pct']:+.3f}%)"
                )
    if not any_anom:
        lines.append("_No anomalies detected._")
    lines.append("")

    # ---- Regime-shift bar counts ----
    lines.append("## Regime-shift bar counts")
    lines.append("")
    regime_headers = ["Pair", "TF"] + [name for name, _, _ in REGIME_WINDOWS]
    regime_rows: list[list[str]] = []
    for rep in sorted(reports, key=lambda r: (r.pair, r.timeframe)):
        if rep.skipped:
            continue
        row = [rep.pair, rep.timeframe]
        for name, _, _ in REGIME_WINDOWS:
            row.append(str(rep.regime_counts.get(name, 0)))
        regime_rows.append(row)
    lines.append(_format_table(regime_headers, regime_rows))
    lines.append("")

    # ---- Skipped files (if any) ----
    if skipped:
        lines.append("## Skipped files")
        lines.append("")
        for rep in skipped:
            lines.append(f"- `{rep.path}` — {rep.skip_reason}")
        lines.append("")

    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------


def discover_csvs(roots: Iterable[Path]) -> list[Path]:
    """Find CSV files under each root, sorted for deterministic output."""
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        out.extend(sorted(p for p in root.glob("*.csv") if p.is_file()))
    # De-dup while preserving order (overlap between historical and dukascopy).
    seen: set[Path] = set()
    deduped: list[Path] = []
    for p in out:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        deduped.append(p)
    return deduped


def filter_by_pair(paths: Iterable[Path], pairs: list[str]) -> list[Path]:
    """Restrict to a set of pairs (uppercase)."""
    if not pairs:
        return list(paths)
    wanted = {p.upper() for p in pairs}
    out = []
    for p in paths:
        pair, _ = _pair_timeframe_from_filename(p)
        if pair in wanted:
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    _ensure_numpy()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--pairs",
        nargs="*",
        default=[],
        help="Restrict to these pairs (e.g. EURUSD XAUUSD). Default: all pairs.",
    )
    parser.add_argument(
        "--historical-dir",
        default=str(DEFAULT_INPUT_DIRS[0]),
        help="Primary historical CSV dir (default: %(default)s)",
    )
    parser.add_argument(
        "--dukascopy-dir",
        default=str(DEFAULT_INPUT_DIRS[1]),
        help="Secondary dukascopy CSV dir (default: %(default)s)",
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
        help="Where to write the QA report (default: %(default)s)",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Echo a short summary to stdout after writing the report.",
    )
    args = parser.parse_args(argv)

    roots = [Path(args.historical_dir), Path(args.dukascopy_dir)]
    paths = discover_csvs(roots)
    paths = filter_by_pair(paths, args.pairs)
    if not paths:
        print("No CSV files found to scan.", file=sys.stderr)
        return 1

    print(f"Scanning {len(paths)} CSV file(s)...", file=sys.stderr)

    reports: list[FileReport] = []
    for p in paths:
        try:
            rep = _qa_file(p)
        except Exception as e:
            pair, tf = _pair_timeframe_from_filename(p)
            rep = FileReport(
                pair=pair,
                timeframe=tf,
                path=str(p),
                rows=0,
                first_ts="",
                last_ts="",
                csv_header=[],
                timestamp_ok=False,
            )
            rep.skipped = True
            rep.skip_reason = f"unhandled exception: {type(e).__name__}: {e}"
        reports.append(rep)
        tag = "skipped" if rep.skipped else f"rows={rep.rows} gaps={rep.gap_count}+{rep.weekend_gap_count}w"
        print(f"  {p}  [{tag}]", file=sys.stderr)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / f"qa-report-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"

    md = render_markdown(reports, datetime.now(timezone.utc))
    out_path.write_text(md)
    print(f"Report written to: {out_path}", file=sys.stderr)

    if args.print_summary:
        # Echo a short summary to stdout for piping.
        scan = [r for r in reports if not r.skipped]
        total = sum(r.gap_count for r in scan)
        wknd = sum(r.weekend_gap_count for r in scan)
        anom = sum(1 for r in scan if r.duplicate_count or r.negative_price_count or r.big_jump_count)
        print(
            json.dumps(
                {
                    "files": len(scan),
                    "skipped": len(reports) - len(scan),
                    "weekday_gaps": total,
                    "weekend_gaps": wknd,
                    "files_with_anomalies": anom,
                    "report": str(out_path),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
