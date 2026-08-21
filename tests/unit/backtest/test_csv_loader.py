"""Unit tests for CSV timestamp parsing in ``backtest.data_loader``.

Covers the ISO 8601 + legacy format support added for the CSV loader's
``_parse_csv_timestamp`` and ``CsvDataLoader._parse_datetime`` helpers
(card e372945c). The previous implementation only accepted the legacy
``%Y-%m-%d %H:%M:%S`` / ``%Y-%m-%d %H:%M`` formats and stamped every input
as ``America/New_York`` before converting to UTC. That broke two real-world
cases:

  * ISO 8601 inputs (``T`` separator, ``Z`` suffix, explicit ``+HH:MM``)
    raised ``ValueError``.
  * ISO-Z strings (already UTC) were incorrectly shifted by ~4 hours
    because they were treated as Eastern before the UTC conversion.

The fix routes both helpers through the same parser, which tries ISO first
and falls back to the legacy ``strptime`` formats. Naive inputs are stamped
as Eastern (preserving historical behaviour); tz-aware inputs are kept as
supplied and only converted to UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from backtest.data_loader import CsvDataLoader, _parse_csv_timestamp

_UTC = timezone.utc
_EASTERN = ZoneInfo("America/New_York")


class TestParseCsvTimestamp:
    """Direct tests for the module-level ``_parse_csv_timestamp`` helper."""

    def test_legacy_format_with_seconds(self):
        """Legacy ``%Y-%m-%d %H:%M:%S`` is preserved (stamped as Eastern)."""
        result = _parse_csv_timestamp("2025-01-09 15:30:00")
        # January is EST (UTC-5), so 15:30 ET -> 20:30 UTC.
        assert result == datetime(2025, 1, 9, 20, 30, 0, tzinfo=_UTC)
        assert result.tzinfo == _UTC

    def test_legacy_format_without_seconds(self):
        """Legacy ``%Y-%m-%d %H:%M`` is preserved (stamped as Eastern)."""
        result = _parse_csv_timestamp("2025-01-09 15:30")
        assert result == datetime(2025, 1, 9, 20, 30, 0, tzinfo=_UTC)
        assert result.tzinfo == _UTC

    def test_iso_t_naive(self):
        """ISO 8601 with ``T`` separator and no offset is stamped as Eastern."""
        result = _parse_csv_timestamp("2025-01-09T15:30:00")
        # Same instant as the legacy case (no offset -> treated as Eastern).
        assert result == datetime(2025, 1, 9, 20, 30, 0, tzinfo=_UTC)
        assert result.tzinfo == _UTC

    def test_iso_z_suffix_is_utc(self):
        """ISO-Z strings are UTC and must NOT be shifted to Eastern."""
        result = _parse_csv_timestamp("2025-01-09T15:30:00Z")
        # Pre-fix this came out as 2025-01-09T20:30:00+00:00 (5h shift).
        assert result == datetime(2025, 1, 9, 15, 30, 0, tzinfo=_UTC)
        assert result.tzinfo == _UTC

    def test_iso_with_explicit_utc_offset(self):
        """ISO with ``+00:00`` offset is UTC, not Eastern."""
        result = _parse_csv_timestamp("2025-01-09T15:30:00+00:00")
        assert result == datetime(2025, 1, 9, 15, 30, 0, tzinfo=_UTC)
        assert result.tzinfo == _UTC

    def test_iso_with_non_utc_offset(self):
        """ISO with a non-UTC offset (e.g. ``-05:00`` EST) is converted to UTC."""
        result = _parse_csv_timestamp("2025-01-09T15:30:00-05:00")
        # 15:30 EST (UTC-5) -> 20:30 UTC.
        assert result == datetime(2025, 1, 9, 20, 30, 0, tzinfo=_UTC)
        assert result.tzinfo == _UTC

    def test_iso_with_microseconds_and_z(self):
        """ISO with fractional seconds and ``Z`` suffix preserves precision."""
        result = _parse_csv_timestamp("2025-01-09T15:30:00.123456Z")
        assert result == datetime(2025, 1, 9, 15, 30, 0, 123456, tzinfo=_UTC)

    def test_invalid_string_raises(self):
        """Garbage input still raises ``ValueError`` (no silent zero-dates)."""
        with pytest.raises(ValueError):
            _parse_csv_timestamp("not a date at all")

    def test_empty_string_raises(self):
        """Empty input raises ``ValueError``."""
        with pytest.raises(ValueError):
            _parse_csv_timestamp("")

    def test_legacy_with_dst_offset(self):
        """July (EDT, UTC-4) is converted using the Eastern DST offset."""
        result = _parse_csv_timestamp("2025-07-04 12:00:00")
        # July is EDT (UTC-4), so 12:00 ET -> 16:00 UTC.
        assert result == datetime(2025, 7, 4, 16, 0, 0, tzinfo=_UTC)


class TestParseDatetimeStaticMethod:
    """The ``CsvDataLoader._parse_datetime`` static method must mirror the
    module-level helper so internal call sites stay in lock-step."""

    def test_delegates_to_helper_legacy(self):
        """Legacy format yields the same UTC result as ``_parse_csv_timestamp``."""
        assert CsvDataLoader._parse_datetime("2025-01-09 15:30:00") == _parse_csv_timestamp("2025-01-09 15:30:00")

    def test_delegates_to_helper_iso_z(self):
        """ISO-Z format also matches (this is the regression case)."""
        assert CsvDataLoader._parse_datetime("2025-01-09T15:30:00Z") == _parse_csv_timestamp("2025-01-09T15:30:00Z")
        # And it must not be Eastern-shifted.
        result = CsvDataLoader._parse_datetime("2025-01-09T15:30:00Z")
        assert result == datetime(2025, 1, 9, 15, 30, 0, tzinfo=_UTC)

    def test_delegates_to_helper_iso_offset(self):
        """ISO with explicit offset matches the helper."""
        assert CsvDataLoader._parse_datetime("2025-01-09T15:30:00+00:00") == _parse_csv_timestamp(
            "2025-01-09T15:30:00+00:00"
        )

    def test_invalid_string_raises(self):
        """Static method still raises on garbage."""
        with pytest.raises(ValueError):
            CsvDataLoader._parse_datetime("garbage")


class TestCsvDataLoaderLoadIntegration:
    """End-to-end check that ``CsvDataLoader.load`` accepts ISO 8601 rows.

    The loader is the public entry point used by the backtest engine; if it
    still drops ISO-8601 rows after the helper fix, the regression is not
    actually closed at the call-site level.
    """

    def test_load_accepts_iso_z_rows(self, tmp_path):
        csv = tmp_path / "iso_z.csv"
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2025-01-09T15:30:00Z,1.1000,1.1050,1.0995,1.1045,100\n"
            "2025-01-09T15:31:00Z,1.1045,1.1060,1.1040,1.1055,150\n"
        )
        bars = CsvDataLoader().load(str(csv))
        assert len(bars) == 2
        assert bars[0].time == datetime(2025, 1, 9, 15, 30, 0, tzinfo=_UTC)
        assert bars[1].time == datetime(2025, 1, 9, 15, 31, 0, tzinfo=_UTC)

    def test_load_mixed_legacy_and_iso_rows(self, tmp_path):
        """A single file can mix legacy and ISO-Z rows (real export shape)."""
        csv = tmp_path / "mixed.csv"
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2025-01-09 15:30:00,1.1000,1.1050,1.0995,1.1045,100\n"
            "2025-01-09T15:31:00Z,1.1045,1.1060,1.1040,1.1055,150\n"
        )
        bars = CsvDataLoader().load(str(csv))
        assert len(bars) == 2
        # Legacy row -> stamped as Eastern -> 20:30 UTC.
        assert bars[0].time == datetime(2025, 1, 9, 20, 30, 0, tzinfo=_UTC)
        # ISO-Z row -> kept as UTC -> 15:31 UTC (NOT shifted).
        assert bars[1].time == datetime(2025, 1, 9, 15, 31, 0, tzinfo=_UTC)
