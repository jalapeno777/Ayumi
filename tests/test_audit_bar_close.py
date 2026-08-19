"""Comprehensive tests for the bar-close timing audit script.

Tests cover:
- Timestamp parsing (ISO, Z suffix, naive, epoch, malformed)
- Bar-close computation for each timeframe
- Timing categorization (VALID, FORMING, LATE)
- Tolerance boundary handling
- Signal loading from JSONL (including empty/malformed files)
- Full audit run with summary
- CLI argument handling
- Spread lookup
- Output file format
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure the backtest module is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src" / "forex-bot"))

from backtest.audit_bar_close import (
    _generate_signal_id,
    _get_spread_for_pair,
    _parse_timestamp,
    categorize_timing,
    compute_bar_close,
    fetch_spread_from_db,
    iter_signals,
    main,
    run_audit,
)


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_iso_naive(self):
        """Naive ISO timestamp assumed UTC."""
        dt = _parse_timestamp("2025-01-06T07:00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.hour == 7

    def test_iso_z_suffix(self):
        dt = _parse_timestamp("2025-01-06T07:00:00Z")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_iso_with_offset(self):
        dt = _parse_timestamp("2025-01-06T12:00:00+05:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.hour == 7  # 12:00 +05:00 = 07:00 UTC

    def test_epoch_number(self):
        dt = _parse_timestamp(1736146800)  # 2025-01-06T07:00:00Z
        assert dt is not None
        assert dt.year == 2025
        assert dt.hour == 7

    def test_epoch_float(self):
        dt = _parse_timestamp(1736146800.5)
        assert dt is not None
        assert dt.microsecond == 500000

    def test_none(self):
        assert _parse_timestamp(None) is None

    def test_empty_string(self):
        assert _parse_timestamp("") is None

    def test_whitespace(self):
        assert _parse_timestamp("   ") is None

    def test_garbage(self):
        assert _parse_timestamp("not-a-timestamp") is None

    def test_alt_format(self):
        dt = _parse_timestamp("2025-01-06 07:00:00")
        assert dt is not None
        assert dt.hour == 7

    def test_slash_format(self):
        dt = _parse_timestamp("2025/01/06 07:00:00")
        assert dt is not None
        assert dt.hour == 7

    def test_non_string_non_number(self):
        assert _parse_timestamp([1, 2, 3]) is None


# ---------------------------------------------------------------------------
# Bar-close computation
# ---------------------------------------------------------------------------


class TestComputeBarClose:
    def test_h1_exact(self):
        """Signal at exact hour boundary → bar close at same time."""
        ts = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "H1")
        assert bc == datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)

    def test_h1_mid_bar(self):
        """Signal at 07:20 → nearest H1 close is 07:00 (20 min closer than 08:00)."""
        ts = datetime(2025, 1, 6, 7, 20, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "H1")
        assert bc == datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)

    def test_h1_exact_midpoint(self):
        """Signal at exactly 07:30 is equidistant — rounds to nearest even boundary."""
        ts = datetime(2025, 1, 6, 7, 30, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "H1")
        # At exact midpoint, Python rounds to nearest even boundary
        assert bc in (
            datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 6, 8, 0, 0, tzinfo=timezone.utc),
        )

    def test_h1_near_next(self):
        """Signal at 07:45 → nearest is 08:00."""
        ts = datetime(2025, 1, 6, 7, 45, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "H1")
        assert bc == datetime(2025, 1, 6, 8, 0, 0, tzinfo=timezone.utc)

    def test_m15_exact(self):
        ts = datetime(2025, 1, 6, 7, 15, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "M15")
        assert bc == datetime(2025, 1, 6, 7, 15, 0, tzinfo=timezone.utc)

    def test_m15_mid(self):
        ts = datetime(2025, 1, 6, 7, 7, 30, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "M15")
        assert bc == datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)

    def test_m5_exact(self):
        ts = datetime(2025, 1, 6, 7, 5, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "M5")
        assert bc == datetime(2025, 1, 6, 7, 5, 0, tzinfo=timezone.utc)

    def test_h4_boundary(self):
        ts = datetime(2025, 1, 6, 8, 0, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "H4")
        assert bc == datetime(2025, 1, 6, 8, 0, 0, tzinfo=timezone.utc)

    def test_d1_boundary(self):
        ts = datetime(2025, 1, 6, 0, 0, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "D1")
        assert bc == datetime(2025, 1, 6, 0, 0, 0, tzinfo=timezone.utc)

    def test_unknown_timeframe(self):
        ts = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "INVALID")
        assert bc is None

    def test_lowercase_timeframe(self):
        ts = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        bc = compute_bar_close(ts, "h1")
        assert bc is not None
        assert bc.hour == 7


# ---------------------------------------------------------------------------
# Timing categorization
# ---------------------------------------------------------------------------


class TestCategorizeTiming:
    def test_exact_match_valid(self):
        ts = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        bc = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        status, offset = categorize_timing(ts, bc, tolerance_ms=1000)
        assert status == "VALID"
        assert offset == 0

    def test_within_tolerance_valid(self):
        """500ms after close is within 1000ms tolerance → VALID."""
        ts = datetime(2025, 1, 6, 7, 0, 0, 500000, tzinfo=timezone.utc)
        bc = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        status, offset = categorize_timing(ts, bc, tolerance_ms=1000)
        assert status == "VALID"
        assert offset == 500

    def test_forming(self):
        """Signal 1 second before bar close → FORMING."""
        ts = datetime(2025, 1, 6, 6, 59, 59, tzinfo=timezone.utc)
        bc = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        status, offset = categorize_timing(ts, bc, tolerance_ms=1000)
        assert status == "FORMING"
        assert offset == -1000

    def test_late(self):
        """Signal 2 seconds after bar close → LATE (> 1000ms)."""
        ts = datetime(2025, 1, 6, 7, 0, 2, tzinfo=timezone.utc)
        bc = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        status, offset = categorize_timing(ts, bc, tolerance_ms=1000)
        assert status == "LATE"
        assert offset == 2000

    def test_late_custom_tolerance(self):
        """With 5000ms tolerance, 2s late is still VALID."""
        ts = datetime(2025, 1, 6, 7, 0, 2, tzinfo=timezone.utc)
        bc = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        status, offset = categorize_timing(ts, bc, tolerance_ms=5000)
        assert status == "VALID"
        assert offset == 2000

    def test_boundary_exact_tolerance(self):
        """Exactly at tolerance boundary → VALID (<=)."""
        ts = datetime(2025, 1, 6, 7, 0, 1, tzinfo=timezone.utc)
        bc = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        status, _ = categorize_timing(ts, bc, tolerance_ms=1000)
        assert status == "VALID"

    def test_one_ms_over_tolerance(self):
        """1ms over tolerance → LATE."""
        ts = datetime(2025, 1, 6, 7, 0, 1, 100000, tzinfo=timezone.utc)
        bc = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        status, offset = categorize_timing(ts, bc, tolerance_ms=1000)
        assert status == "LATE"
        assert offset == 1100

    def test_far_past(self):
        """Signal well before bar close."""
        ts = datetime(2025, 1, 6, 6, 30, 0, tzinfo=timezone.utc)
        bc = datetime(2025, 1, 6, 7, 0, 0, tzinfo=timezone.utc)
        status, offset = categorize_timing(ts, bc)
        assert status == "FORMING"
        assert offset == -1800000  # -30 min in ms


# ---------------------------------------------------------------------------
# Signal ID generation
# ---------------------------------------------------------------------------


class TestSignalIdGeneration:
    def test_deterministic(self):
        signal = {
            "timestamp": "2025-01-06T07:00:00",
            "symbol": "EURUSD",
            "direction": "LONG",
        }
        id1 = _generate_signal_id(signal, "test.jsonl", 1)
        id2 = _generate_signal_id(signal, "test.jsonl", 1)
        assert id1 == id2

    def test_different_line_different_id(self):
        signal = {
            "timestamp": "2025-01-06T07:00:00",
            "symbol": "EURUSD",
            "direction": "LONG",
        }
        id1 = _generate_signal_id(signal, "test.jsonl", 1)
        id2 = _generate_signal_id(signal, "test.jsonl", 2)
        assert id1 != id2

    def test_different_file_different_id(self):
        signal = {
            "timestamp": "2025-01-06T07:00:00",
            "symbol": "EURUSD",
            "direction": "LONG",
        }
        id1 = _generate_signal_id(signal, "a.jsonl", 1)
        id2 = _generate_signal_id(signal, "b.jsonl", 1)
        assert id1 != id2

    def test_hex_length(self):
        signal = {}
        sid = _generate_signal_id(signal, "f", 1)
        assert len(sid) == 16
        int(sid, 16)  # valid hex


# ---------------------------------------------------------------------------
# Spread lookup
# ---------------------------------------------------------------------------


class TestSpreadLookup:
    def test_known_pair(self):
        assert _get_spread_for_pair("EURUSD") == 1.5

    def test_known_pair_jpy(self):
        assert _get_spread_for_pair("GBPJPY") == 3.0

    def test_case_insensitive(self):
        assert _get_spread_for_pair("eurusd") == 1.5

    def test_unknown_pair(self):
        assert (
            _get_spread_for_pair("UNKNOWN") == DEFAULT_SPREAD_PIPS
            if (DEFAULT_SPREAD_PIPS := 1.5)
            else None
        )

    def test_gold(self):
        assert _get_spread_for_pair("XAUUSD") == 2.5


# ---------------------------------------------------------------------------
# Signal iteration
# ---------------------------------------------------------------------------


class TestIterSignals:
    def test_normal_file(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"strategy_id": "test", "symbol": "EURUSD", "direction": "LONG", '
            '"timestamp": "2025-01-06T07:00:00"}\n'
            '{"strategy_id": "test", "symbol": "EURUSD", "direction": "SHORT", '
            '"timestamp": "2025-01-06T09:00:00"}\n'
        )
        signals = list(iter_signals(tmp_path))
        assert len(signals) == 2
        assert signals[0][0]["direction"] == "LONG"
        assert signals[1][0]["direction"] == "SHORT"

    def test_empty_lines_skipped(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '\n{"strategy_id": "test", "timestamp": "2025-01-06T07:00:00"}\n\n   \n'
        )
        signals = list(iter_signals(tmp_path))
        assert len(signals) == 1

    def test_malformed_json_skipped(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"valid": true}\n{bad json}\n{"also_valid": true}\n')
        signals = list(iter_signals(tmp_path))
        assert len(signals) == 2  # malformed line skipped

    def test_non_object_skipped(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('[1, 2, 3]\n{"valid": true}\n"just a string"\n')
        signals = list(iter_signals(tmp_path))
        assert len(signals) == 1

    def test_nonexistent_dir(self, tmp_path):
        signals = list(iter_signals(tmp_path / "nonexistent"))
        assert len(signals) == 0

    def test_empty_dir(self, tmp_path):
        signals = list(iter_signals(tmp_path))
        assert len(signals) == 0

    def test_multiple_files(self, tmp_path):
        (tmp_path / "a.jsonl").write_text('{"id": 1}\n')
        (tmp_path / "b.jsonl").write_text('{"id": 2}\n')
        (tmp_path / "c.jsonl").write_text('{"id": 3}\n')
        signals = list(iter_signals(tmp_path))
        assert len(signals) == 3

    def test_non_jsonl_ignored(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not json")
        (tmp_path / "data.json").write_text('{"id": 1}')
        (tmp_path / "signals.jsonl").write_text('{"id": 2}\n')
        signals = list(iter_signals(tmp_path))
        assert len(signals) == 1


# ---------------------------------------------------------------------------
# DB spread lookup
# ---------------------------------------------------------------------------


class TestFetchSpreadFromDB:
    def test_nonexistent_db(self, tmp_path):
        result = fetch_spread_from_db(
            tmp_path / "nope.db", "EURUSD", "2025-01-06T07:00:00"
        )
        assert result is None

    def test_db_without_spread_column(self, tmp_path):
        """Standard trades table has no spread_at_entry column → None."""
        db = tmp_path / "trading.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE trades (
                trade_id TEXT, symbol TEXT, direction TEXT,
                entry_price REAL, entry_time TEXT
            )
        """)
        conn.commit()
        conn.close()
        result = fetch_spread_from_db(db, "EURUSD", "2025-01-06T07:00:00")
        assert result is None


# ---------------------------------------------------------------------------
# Full audit run
# ---------------------------------------------------------------------------


class TestRunAudit:
    @pytest.fixture
    def signals_dir(self, tmp_path):
        d = tmp_path / "signals"
        d.mkdir()
        (d / "strategy_a.jsonl").write_text(
            '{"strategy_id": "strategy_a", "symbol": "EURUSD", "direction": "LONG", '
            '"timestamp": "2025-01-06T07:00:00", "confidence": 0.8}\n'
            '{"strategy_id": "strategy_a", "symbol": "EURUSD", "direction": "SHORT", '
            '"timestamp": "2025-01-06T09:00:00", "confidence": 0.6}\n'
        )
        (d / "strategy_b.jsonl").write_text(
            '{"strategy_id": "strategy_b", "symbol": "GBPUSD", "direction": "LONG", '
            '"timestamp": "2025-01-06T07:00:30", "confidence": 0.7}\n'
            '{"strategy_id": "strategy_b", "symbol": "GBPUSD", "direction": "SHORT", '
            '"timestamp": "2025-01-06T06:59:00", "confidence": 0.5}\n'
        )
        return d

    @pytest.fixture
    def trading_db(self, tmp_path):
        db = tmp_path / "trading.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE trades (
                trade_id TEXT, symbol TEXT, direction TEXT,
                entry_price REAL, entry_time TEXT
            )
        """)
        conn.commit()
        conn.close()
        return db

    def test_audit_creates_output(self, signals_dir, trading_db, tmp_path):
        output = tmp_path / "audit" / "output.jsonl"
        summary = run_audit(signals_dir, output, trading_db)
        assert output.exists()
        lines = output.read_text().strip().split("\n")
        assert len(lines) == 4  # 4 signals

    def test_output_format(self, signals_dir, trading_db, tmp_path):
        output = tmp_path / "audit.jsonl"
        run_audit(signals_dir, output, trading_db)
        first = json.loads(output.read_text().strip().split("\n")[0])
        required_fields = {
            "signal_id",
            "timestamp",
            "instrument",
            "direction",
            "timeframe",
            "timing_status",
            "spread_at_entry",
        }
        assert required_fields.issubset(first.keys())

    def test_valid_signals(self, signals_dir, trading_db, tmp_path):
        """Signals at exact hour boundaries with H1 should be VALID."""
        output = tmp_path / "audit.jsonl"
        summary = run_audit(signals_dir, output, trading_db)
        # strategy_a signals are at 07:00:00 and 09:00:00 → exact H1 boundaries → VALID
        assert summary.valid >= 2

    def test_forming_signal(self, signals_dir, trading_db, tmp_path):
        """Signal at 06:59:00 → FORMING."""
        output = tmp_path / "audit.jsonl"
        summary = run_audit(signals_dir, output, trading_db)
        # strategy_b has a signal at 06:59:00 → FORMING
        assert summary.forming >= 1

    def test_late_signal(self, signals_dir, trading_db, tmp_path):
        """Signal at 07:00:30 is 30s late → LATE."""
        output = tmp_path / "audit.jsonl"
        summary = run_audit(signals_dir, output, trading_db, tolerance_ms=1000)
        # strategy_b has a signal at 07:00:30 → 30s after 07:00 → LATE
        assert summary.late >= 1

    def test_tolerance_affects_late(self, signals_dir, trading_db, tmp_path):
        """With 60000ms tolerance, 30s late is VALID."""
        output = tmp_path / "audit.jsonl"
        summary = run_audit(signals_dir, output, trading_db, tolerance_ms=60000)
        # All signals should be VALID (30s < 60s tolerance)
        assert summary.late == 0

    def test_summary_counts(self, signals_dir, trading_db, tmp_path):
        output = tmp_path / "audit.jsonl"
        summary = run_audit(signals_dir, output, trading_db, tolerance_ms=1000)
        assert summary.total_signals == 4
        assert summary.valid + summary.forming + summary.late == 4

    def test_summary_percentages(self, signals_dir, trading_db, tmp_path):
        output = tmp_path / "audit.jsonl"
        summary = run_audit(signals_dir, output, trading_db, tolerance_ms=1000)
        total_pct = summary.pct_valid + summary.pct_forming + summary.pct_late
        assert abs(total_pct - 100.0) < 0.01

    def test_by_strategy(self, signals_dir, trading_db, tmp_path):
        output = tmp_path / "audit.jsonl"
        summary = run_audit(signals_dir, output, trading_db)
        assert "strategy_a" in summary.by_strategy
        assert "strategy_b" in summary.by_strategy
        assert sum(summary.by_strategy["strategy_a"].values()) == 2

    def test_empty_signals_dir(self, tmp_path, trading_db):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        output = tmp_path / "audit.jsonl"
        summary = run_audit(empty_dir, output, trading_db)
        assert summary.total_signals == 0
        assert summary.valid == 0
        assert summary.pct_valid == 0.0

    def test_all_malformed(self, tmp_path, trading_db):
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir()
        (bad_dir / "bad.jsonl").write_text("{broken\n{also broken\n")
        output = tmp_path / "audit.jsonl"
        summary = run_audit(bad_dir, output, trading_db)
        assert summary.total_signals == 0
        assert summary.skipped == 0  # malformed JSON skipped during iteration

    def test_spread_in_output(self, signals_dir, trading_db, tmp_path):
        output = tmp_path / "audit.jsonl"
        run_audit(signals_dir, output, trading_db)
        for line in output.read_text().strip().split("\n"):
            rec = json.loads(line)
            assert rec["spread_at_entry"] > 0
            assert rec["spread_at_entry"] in (1.5, 3.0, 2.5)

    def test_mixed_timeframes(self, tmp_path, trading_db):
        """Signals with explicit timeframe field."""
        d = tmp_path / "signals"
        d.mkdir()
        (d / "mixed.jsonl").write_text(
            '{"symbol": "EURUSD", "direction": "LONG", "timestamp": "2025-01-06T07:05:00", "timeframe": "M5"}\n'
            '{"symbol": "EURUSD", "direction": "LONG", "timestamp": "2025-01-06T07:05:00", "timeframe": "H1"}\n'
        )
        output = tmp_path / "audit.jsonl"
        summary = run_audit(d, output, trading_db)
        # M5 signal at 07:05:00 → VALID (M5 boundary)
        # H1 signal at 07:05:00 → nearest H1 is 07:00:00 → 5min late → LATE
        assert summary.valid >= 1
        assert summary.late >= 1


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_cli_runs_successfully(self, tmp_path):
        d = tmp_path / "signals"
        d.mkdir()
        (d / "test.jsonl").write_text(
            '{"symbol": "EURUSD", "direction": "LONG", "timestamp": "2025-01-06T07:00:00"}\n'
        )
        output = tmp_path / "out.jsonl"
        db = tmp_path / "trading.db"
        # Create empty db
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE trades (trade_id TEXT)")
        conn.commit()
        conn.close()

        code = main(
            [
                "--signals-dir",
                str(d),
                "--output",
                str(output),
                "--trading-db",
                str(db),
                "--summary",
            ]
        )
        assert code == 0
        assert output.exists()

    def test_cli_no_signals(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        output = tmp_path / "out.jsonl"
        db = tmp_path / "trading.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE trades (trade_id TEXT)")
        conn.commit()
        conn.close()

        code = main(
            [
                "--signals-dir",
                str(empty),
                "--output",
                str(output),
                "--trading-db",
                str(db),
            ]
        )
        assert code == 1  # no signals → exit 1

    def test_cli_custom_tolerance(self, tmp_path):
        d = tmp_path / "signals"
        d.mkdir()
        # Signal 500ms after H1 close
        (d / "test.jsonl").write_text(
            '{"symbol": "EURUSD", "direction": "LONG", "timestamp": "2025-01-06T07:00:00.500000"}\n'
        )
        output = tmp_path / "out.jsonl"
        db = tmp_path / "trading.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE trades (trade_id TEXT)")
        conn.commit()
        conn.close()

        # With tolerance 100, 500ms is LATE
        main(
            [
                "--signals-dir",
                str(d),
                "--output",
                str(output),
                "--trading-db",
                str(db),
                "--tolerance-ms",
                "100",
            ]
        )
        lines = output.read_text().strip().split("\n")
        rec = json.loads(lines[0])
        assert rec["timing_status"] == "LATE"

    def test_cli_default_tolerance_valid(self, tmp_path):
        d = tmp_path / "signals"
        d.mkdir()
        (d / "test.jsonl").write_text(
            '{"symbol": "EURUSD", "direction": "LONG", "timestamp": "2025-01-06T07:00:00.500000"}\n'
        )
        output = tmp_path / "out.jsonl"
        db = tmp_path / "trading.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE trades (trade_id TEXT)")
        conn.commit()
        conn.close()

        # Default tolerance 1000ms, 500ms is VALID
        main(
            [
                "--signals-dir",
                str(d),
                "--output",
                str(output),
                "--trading-db",
                str(db),
            ]
        )
        lines = output.read_text().strip().split("\n")
        rec = json.loads(lines[0])
        assert rec["timing_status"] == "VALID"


# ---------------------------------------------------------------------------
# Realistic input tests (mandatory)
# ---------------------------------------------------------------------------


class TestRealisticInputs:
    """Test with realistic signal data matching actual data/signals/*.jsonl format."""

    @pytest.fixture
    def realistic_signals(self, tmp_path):
        d = tmp_path / "signals"
        d.mkdir()
        (d / "killzone_momentum_EURUSD.jsonl").write_text(
            '{"strategy_id": "killzone_momentum", "symbol": "EURUSD", "direction": "SHORT", '
            '"entry_price": 1.09502, "stop_loss": 1.09667, "take_profit": 1.0932, '
            '"confidence": 0.657, "timestamp": "2025-01-06T07:00:00", "outcome_pnl": -1.65}\n'
            '{"strategy_id": "killzone_momentum", "symbol": "EURUSD", "direction": "LONG", '
            '"entry_price": 1.10086, "stop_loss": 1.09605, "take_profit": 1.10996, '
            '"confidence": 0.444, "timestamp": "2025-01-06T09:00:00", "outcome_pnl": 9.1}\n'
            '{"strategy_id": "killzone_momentum", "symbol": "EURUSD", "direction": "SHORT", '
            '"entry_price": 1.09863, "stop_loss": 1.10395, "take_profit": 1.08858, '
            '"confidence": 0.749, "timestamp": "2025-01-06T11:00:00", "outcome_pnl": -5.33}\n'
        )
        (d / "solo_EURUSD.jsonl").write_text(
            '{"strategy_id": "solo", "symbol": "EURUSD", "direction": "SHORT", '
            '"entry_price": 1.10263, "stop_loss": 1.11032, "take_profit": 1.09199, '
            '"confidence": 0.859, "timestamp": "2025-01-06T07:00:00", "outcome_pnl": 10.63}\n'
            '{"strategy_id": "solo", "symbol": "EURUSD", "direction": "SHORT", '
            '"entry_price": 1.1004, "stop_loss": 1.10307, "take_profit": 1.09424, '
            '"confidence": 0.7, "timestamp": "2025-01-06T09:00:00", "outcome_pnl": 6.17}\n'
        )
        return d

    @pytest.fixture
    def empty_db(self, tmp_path):
        db = tmp_path / "trading.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE trades (
                trade_id TEXT, strategy_name TEXT, symbol TEXT,
                direction TEXT, entry_price REAL, entry_time TEXT
            )
        """)
        conn.commit()
        conn.close()
        return db

    def test_all_valid_on_real_data(self, realistic_signals, empty_db, tmp_path):
        """Real signals at exact hour boundaries → all VALID."""
        output = tmp_path / "audit.jsonl"
        summary = run_audit(realistic_signals, output, empty_db)
        assert summary.total_signals == 5
        assert summary.valid == 5
        assert summary.forming == 0
        assert summary.late == 0

    def test_output_matches_schema(self, realistic_signals, empty_db, tmp_path):
        """Output records match required schema exactly."""
        output = tmp_path / "audit.jsonl"
        run_audit(realistic_signals, output, empty_db)
        for line in output.read_text().strip().split("\n"):
            rec = json.loads(line)
            # Required fields per acceptance criteria
            assert "signal_id" in rec
            assert "timestamp" in rec
            assert "instrument" in rec
            assert "direction" in rec
            assert "timeframe" in rec
            assert "timing_status" in rec
            assert "spread_at_entry" in rec
            # Values
            assert rec["instrument"] == "EURUSD"
            assert rec["direction"] in ("LONG", "SHORT")
            assert rec["timeframe"] == "H1"
            assert rec["timing_status"] == "VALID"
            assert rec["spread_at_entry"] == 1.5  # EURUSD spread

    def test_summary_with_strategies(self, realistic_signals, empty_db, tmp_path):
        output = tmp_path / "audit.jsonl"
        summary = run_audit(realistic_signals, output, empty_db, print_summary=True)
        assert "killzone_momentum" in summary.by_strategy
        assert "solo" in summary.by_strategy
        assert summary.by_strategy["killzone_momentum"]["VALID"] == 3
        assert summary.by_strategy["solo"]["VALID"] == 2

    def test_realistic_input_table(self, realistic_signals, empty_db, tmp_path):
        """Document realistic input → output mapping."""
        output = tmp_path / "audit.jsonl"
        run_audit(realistic_signals, output, empty_db)
        results = [json.loads(l) for l in output.read_text().strip().split("\n")]

        # Sample 1: killzone_momentum at 07:00:00 → VALID
        r1 = results[0]
        assert r1["timestamp"] == "2025-01-06T07:00:00+00:00"
        assert r1["timing_status"] == "VALID"

        # Sample 2: solo at 07:00:00 → VALID
        r4 = results[3]
        assert r4["timestamp"] == "2025-01-06T07:00:00+00:00"
        assert r4["timing_status"] == "VALID"
        assert (
            r1["signal_id"] != r4["signal_id"]
        )  # different IDs despite same timestamp
