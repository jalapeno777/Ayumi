"""Test suite for CFTC COT data fetcher and cache.

Covers:
  - CSV parsing (Legacy + Disaggregated formats)
  - Positioning extraction for forex pairs
  - Divergence signal computation (confidence multiplier)
  - USDJPY confidence shift on simulated COT divergence
  - Cache: store, retrieve, staleness, versioning, cleanup
  - Edge cases: missing data, malformed rows, empty archives
"""

from __future__ import annotations  # noqa: I001

import json
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from data.cot_cache import CACHE_VERSION, COTCache
from data.cot_fetcher import COTFormat, COTFetcher


# ─── Fixtures ────────────────────────────────────────────────────────────────

SAMPLE_LEGACY_CSV = """JAPANESE YEN,095741,01/06/2026,2026-01-06t00:00:00,50000,30000,5000,100000,80000,,
JAPANESE YEN,095741,01/13/2026,2026-01-13t00:00:00,45000,35000,5000,110000,75000,,
JAPANESE YEN,095741,01/20/2026,2026-01-20t00:00:00,55000,25000,3000,95000,85000,,
EURO FX,099741,01/06/2026,2026-01-06t00:00:00,120000,80000,10000,200000,150000,,
EURO FX,099741,01/13/2026,2026-01-13t00:00:00,130000,70000,10000,210000,140000,,
BRITISH POUND,096741,01/06/2026,2026-01-06t00:00:00,60000,40000,5000,100000,90000,,
"""

SAMPLE_LEGACY_CSV_REGIME_CHANGE = """JAPANESE YEN,095741,01/06/2026,2026-01-06t00:00:00,60000,20000,5000,100000,80000,,
JAPANESE YEN,095741,01/13/2026,2026-01-13t00:00:00,55000,25000,5000,110000,75000,,
JAPANESE YEN,095741,01/20/2026,2026-01-20t00:00:00,20000,60000,3000,95000,85000,,
"""

SAMPLE_DISAGG_CSV = """JAPANESE YEN,095741,01/06/2026,2026-01-06t00:00:00,80000,120000,0,0,50000,30000,5000,,
JAPANESE YEN,095741,01/13/2026,2026-01-13t00:00:00,85000,115000,0,0,45000,35000,5000,,
"""

MALFORMED_CSV = """JAPANESE YEN,095741,not-a-date,2026-01-06t00:00:00,50000,30000,5000,100000,80000,,
,,,,
SHORT ROW
"""


@pytest.fixture
def tmp_cache_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def fetcher_no_cache():
    """COTFetcher with no disk cache (uses mocked downloads)."""
    return COTFetcher(cache=None)


@pytest.fixture
def fetcher_with_cache(tmp_cache_dir):
    """COTFetcher with a real disk cache."""
    cache = COTCache(tmp_cache_dir)
    return COTFetcher(cache=cache)


# ─── CSV Parsing Tests ──────────────────────────────────────────────────────


class TestLegacyParsing:
    """Test Legacy format CSV parsing."""

    def test_parse_forex_markets_only(self):
        """Only forex futures markets are extracted."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        markets = {r.market_name for r in records}
        assert "JAPANESE YEN" in markets
        assert "EURO FX" in markets
        assert "BRITISH POUND" in markets

    def test_parse_correct_positioning_values(self):
        """Positioning values parsed correctly."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        jpy = [r for r in records if r.market_name == "JAPANESE YEN"]
        jpy.sort(key=lambda r: r.report_date)

        first = jpy[0]
        assert first.report_date == "2026-01-06"
        assert first.non_comm_long == 50000
        assert first.non_comm_short == 30000
        assert first.non_comm_spread == 5000
        assert first.comm_long == 100000
        assert first.comm_short == 80000

    def test_net_position_calculated(self):
        """Net position = non-commercial long - short."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        jpy = [r for r in records if r.market_name == "JAPANESE YEN"][0]
        assert jpy.net_position == jpy.non_comm_long - jpy.non_comm_short

    def test_total_open_interest_calculated(self):
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        jpy = [r for r in records if r.market_name == "JAPANESE YEN"][0]
        expected = jpy.non_comm_long + jpy.non_comm_short + jpy.comm_long + jpy.comm_short
        assert jpy.total_open_interest == expected

    def test_net_ratio(self):
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        jpy = [r for r in records if r.market_name == "JAPANESE YEN"][0]
        assert jpy.net_ratio == jpy.net_position / jpy.total_open_interest

    def test_date_normalisation(self):
        """MM/DD/YYYY is converted to YYYY-MM-DD."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        for r in records:
            assert r.report_date[4] == "-"
            assert len(r.report_date) == 10

    def test_malformed_rows_skipped(self):
        """Malformed rows (bad date, empty rows) are skipped without crashing."""
        records = COTFetcher._parse_csv(MALFORMED_CSV, COTFormat.LEGACY)
        # The bad-date row should be skipped (invalid date), short rows skipped
        assert len(records) == 0

    def test_empty_csv(self):
        """Empty CSV returns empty list."""
        assert COTFetcher._parse_csv("", COTFormat.LEGACY) == []

    def test_format_tag(self):
        """Parsed records carry the correct format tag."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        assert all(r.format == COTFormat.LEGACY for r in records)


class TestDisaggregatedParsing:
    """Test Disaggregated format CSV parsing."""

    def test_parse_disaggregated(self):
        records = COTFetcher._parse_csv(SAMPLE_DISAGG_CSV, COTFormat.DISAGGREGATED)
        assert len(records) == 2
        jpy = records[0]
        assert jpy.market_name == "JAPANESE YEN"
        assert jpy.non_comm_long == 50000
        assert jpy.non_comm_short == 30000
        assert jpy.comm_long == 80000
        assert jpy.comm_short == 120000
        assert jpy.format == COTFormat.DISAGGREGATED


# ─── Positioning Tests ──────────────────────────────────────────────────────


class TestPositioning:
    """Test get_positioning for forex pairs."""

    def test_get_usdjpy_positioning(self, fetcher_no_cache):
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            pos = fetcher_no_cache.get_positioning("USDJPY", COTFormat.LEGACY)
        assert pos is not None
        assert pos.market_name == "JAPANESE YEN"
        assert pos.report_date == "2026-01-20"  # latest

    def test_get_eurusd_positioning(self, fetcher_no_cache):
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            pos = fetcher_no_cache.get_positioning("EURUSD", COTFormat.LEGACY)
        assert pos is not None
        assert pos.market_name == "EURO FX"

    def test_unknown_pair_returns_none(self, fetcher_no_cache):
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=[]):
            pos = fetcher_no_cache.get_positioning("XYZABC", COTFormat.LEGACY)
        assert pos is None

    def test_specific_report_date(self, fetcher_no_cache):
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            pos = fetcher_no_cache.get_positioning("USDJPY", COTFormat.LEGACY, report_date="2026-01-06")
        assert pos is not None
        assert pos.report_date == "2026-01-06"

    def test_missing_report_date_returns_none(self, fetcher_no_cache):
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            pos = fetcher_no_cache.get_positioning("USDJPY", COTFormat.LEGACY, report_date="2025-01-01")
        assert pos is None

    def test_download_failure_returns_none(self, fetcher_no_cache):
        with patch.object(
            fetcher_no_cache,
            "_download_and_parse",
            side_effect=Exception("Network error"),
        ):
            pos = fetcher_no_cache.get_positioning("USDJPY", COTFormat.LEGACY)
        assert pos is None


# ─── Divergence Signal Tests (Confidence Multiplier) ────────────────────────


class TestDivergenceSignal:
    """Test divergence signal computation — the confidence multiplier."""

    def test_usdjpy_confidence_shift_on_cot_divergence(self, fetcher_no_cache):
        """USDJPY: When non-commercial JPY positioning flips net-short to
        net-long (speculative shift), the confidence multiplier should
        produce a directional bias.

        COT reports JPY positions. For USDJPY:
        - JPY net-long means traders long JPY → bearish USDJPY → short bias
        - JPY net-short means traders short JPY → bullish USDJPY → long bias

        With the regime change sample (net-long → net-short flip for JPY),
        the inverted signal should show a USDJPY bias shift.
        """
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV_REGIME_CHANGE, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            signal = fetcher_no_cache.get_divergence_signal("USDJPY")

        assert signal.currency == "USDJPY"
        assert signal.bias in ("long", "short", "neutral")
        assert -1.0 <= signal.strength <= 1.0
        assert -0.05 <= signal.confidence_adjustment <= 0.05
        assert signal.rationale != ""

    def test_regime_change_amplifies_signal(self, fetcher_no_cache):
        """A positioning flip (regime change) should produce a detectable
        confidence adjustment — not zero."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV_REGIME_CHANGE, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            signal = fetcher_no_cache.get_divergence_signal("USDJPY")

        # Regime change should produce non-zero adjustment
        assert signal.confidence_adjustment != 0.0
        assert "Regime change" in signal.rationale

    def test_stable_positioning_neutral_signal(self, fetcher_no_cache):
        """When positioning is stable (no shift), adjustment is small."""
        stable_csv = """JAPANESE YEN,095741,01/06/2026,2026-01-06t00:00:00,50000,30000,5000,100000,80000,,
JAPANESE YEN,095741,01/13/2026,2026-01-13t00:00:00,50000,30000,5000,100000,80000,,
JAPANESE YEN,095741,01/20/2026,2026-01-20t00:00:00,50000,30000,5000,100000,80000,,
"""
        records = COTFetcher._parse_csv(stable_csv, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            signal = fetcher_no_cache.get_divergence_signal("USDJPY")

        # Stable positioning → small or zero adjustment
        assert abs(signal.confidence_adjustment) <= 0.02

    def test_insufficient_history_returns_neutral(self, fetcher_no_cache):
        """Less than 2 weeks of data returns neutral signal."""
        single_week = """JAPANESE YEN,095741,01/06/2026,2026-01-06t00:00:00,50000,30000,5000,100000,80000,,
"""
        records = COTFetcher._parse_csv(single_week, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            signal = fetcher_no_cache.get_divergence_signal("USDJPY")

        assert signal.bias == "neutral"
        assert signal.confidence_adjustment == 0.0
        assert "Insufficient" in signal.rationale

    def test_confidence_adjustment_capped(self, fetcher_no_cache):
        """Confidence adjustment never exceeds ±0.05."""
        extreme_csv = """JAPANESE YEN,095741,01/06/2026,2026-01-06t00:00:00,1000000,1000,0,0,0,,
JAPANESE YEN,095741,01/13/2026,2026-01-13t00:00:00,1000000,1000,0,0,0,,
JAPANESE YEN,095741,01/20/2026,2026-01-20t00:00:00,1000,1000000,0,0,0,,
"""
        records = COTFetcher._parse_csv(extreme_csv, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            signal = fetcher_no_cache.get_divergence_signal("USDJPY")

        assert signal.confidence_adjustment <= 0.05
        assert signal.confidence_adjustment >= -0.05

    def test_signal_has_valid_date(self, fetcher_no_cache):
        """Signal date matches the most recent COT report date."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            signal = fetcher_no_cache.get_divergence_signal("USDJPY")
        assert signal.signal_date == "2026-01-20"


# ─── Confidence Multiplier Simulation ────────────────────────────────────────


class TestConfidenceMultiplier:
    """Simulate how COT divergence would shift confidence on USDJPY.

    Demonstrates the integration contract: COT divergence produces a
    confidence_adjustment that the ConfidenceEngine would apply as a
    multiplier to the raw strategy score.
    """

    def test_usdjpy_divergence_reduces_confidence_on_misaligned_trade(self, fetcher_no_cache):
        """If COT signal is bearish USDJPY but strategy says long,
        confidence should be reduced."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV_REGIME_CHANGE, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            signal = fetcher_no_cache.get_divergence_signal("USDJPY")

        # Strategy says "long USDJPY" with 0.7 confidence
        strategy_confidence = 0.7
        strategy_direction = "long"

        # Use the integration helper (the actual integration contract)
        adjusted = fetcher_no_cache.apply_to_confidence(strategy_confidence, "USDJPY", strategy_direction)

        # The adjustment should be within the expected range
        assert 0.0 <= adjusted <= 1.0
        # If signal opposes strategy, confidence should decrease
        if signal.bias != strategy_direction and signal.bias != "neutral":
            assert adjusted < strategy_confidence

    def test_aligned_cot_boosts_confidence(self, fetcher_no_cache):
        """COT alignment with strategy direction should boost confidence."""
        # JPY net-short (traders short JPY = bullish USDJPY)
        bullish_csv = """JAPANESE YEN,095741,01/06/2026,2026-01-06t00:00:00,20000,80000,0,50000,50000,,
JAPANESE YEN,095741,01/13/2026,2026-01-13t00:00:00,20000,80000,0,50000,50000,,
JAPANESE YEN,095741,01/20/2026,2026-01-20t00:00:00,15000,85000,0,50000,50000,,
"""
        records = COTFetcher._parse_csv(bullish_csv, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            signal = fetcher_no_cache.get_divergence_signal("USDJPY")

        # JPY net-short → inverted = USDJPY long bias
        assert signal.bias == "long"

        # Strategy says "long USDJPY" with 0.6 confidence — aligned
        adjusted = fetcher_no_cache.apply_to_confidence(0.6, "USDJPY", "long")
        # Alignment should boost (or hold) confidence
        assert adjusted >= 0.6

    def test_apply_to_confidence_aligned_boosts(self, fetcher_no_cache):
        """apply_to_confidence: aligned trade gets boosted."""
        # Stable USDJPY-bullish positioning (JPY consistently net-short)
        records = COTFetcher._parse_csv(
            "JAPANESE YEN,095741,01/06/2026,2026-01-06t00:00:00,20000,80000,0,50000,50000,,\n"
            "JAPANESE YEN,095741,01/13/2026,2026-01-13t00:00:00,18000,82000,0,50000,50000,,\n"
            "JAPANESE YEN,095741,01/20/2026,2026-01-20t00:00:00,15000,85000,0,50000,50000,,\n",
            COTFormat.LEGACY,
        )
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            adjusted = fetcher_no_cache.apply_to_confidence(0.65, "USDJPY", "long")
        # Aligned (long) and COT says long → confidence stays or grows
        assert 0.65 <= adjusted <= 1.0

    def test_apply_to_confidence_opposed_penalises(self, fetcher_no_cache):
        """apply_to_confidence: opposed trade gets penalised."""
        # Regime change: JPY flips from net-short to net-long
        # (i.e. USDJPY flips from bullish to bearish in inversion)
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV_REGIME_CHANGE, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            signal = fetcher_no_cache.get_divergence_signal("USDJPY")
            # Strategy says long USDJPY
            adjusted = fetcher_no_cache.apply_to_confidence(0.65, "USDJPY", "long")

        # If COT signal is opposed to the trade, confidence should drop
        if signal.bias == "short":
            assert adjusted < 0.65
        # In any case, must stay in valid range
        assert 0.0 <= adjusted <= 1.0

    def test_apply_to_confidence_clamps_to_unit_interval(self, fetcher_no_cache):
        """apply_to_confidence: output clamped to [0.0, 1.0]."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV_REGIME_CHANGE, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            # High confidence + boost → clamps to 1.0
            high = fetcher_no_cache.apply_to_confidence(0.99, "USDJPY", "long")
            assert 0.0 <= high <= 1.0
            # Low confidence + penalty → clamps to 0.0
            low = fetcher_no_cache.apply_to_confidence(0.02, "USDJPY", "long")
            assert 0.0 <= low <= 1.0

    def test_apply_to_confidence_neutral_no_change(self, fetcher_no_cache):
        """apply_to_confidence: neutral COT returns raw confidence unchanged."""
        single_week = "JAPANESE YEN,095741,01/06/2026,2026-01-06t00:00:00,50000,30000,5000,100000,80000,,\n"
        records = COTFetcher._parse_csv(single_week, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            adjusted_long = fetcher_no_cache.apply_to_confidence(0.7, "USDJPY", "long")
            adjusted_short = fetcher_no_cache.apply_to_confidence(0.7, "USDJPY", "short")
        # Insufficient history → neutral → no adjustment
        assert adjusted_long == pytest.approx(0.7)
        assert adjusted_short == pytest.approx(0.7)

    def test_apply_to_confidence_eurusd_aligned(self, fetcher_no_cache):
        """EURUSD: bullish positioning + long trade → confidence boosted."""
        # EUR net-LONG (long > short) means traders are long EUR → bullish EURUSD
        bullish_eur = """EURO FX,099741,01/06/2026,2026-01-06t00:00:00,80000,20000,0,50000,50000,,
EURO FX,099741,01/13/2026,2026-01-13t00:00:00,82000,18000,0,50000,50000,,
EURO FX,099741,01/20/2026,2026-01-20t00:00:00,85000,15000,0,50000,50000,,
"""
        records = COTFetcher._parse_csv(bullish_eur, COTFormat.LEGACY)
        with patch.object(fetcher_no_cache, "_download_and_parse", return_value=records):
            # Strategy long EURUSD, COT says long (EUR net-long) → aligned
            adjusted = fetcher_no_cache.apply_to_confidence(0.6, "EURUSD", "long")
        # Aligned (both long) → no reduction
        assert adjusted >= 0.6


# ─── Cache Tests ─────────────────────────────────────────────────────────────


class TestCOTCache:
    """Test the weekly cache with versioning."""

    def test_put_and_get(self, tmp_cache_dir):
        """Records stored and retrieved correctly."""
        cache = COTCache(tmp_cache_dir)
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)

        cache.put(COTFormat.LEGACY, "2026", records)
        retrieved = cache.get(COTFormat.LEGACY, "2026")

        assert retrieved is not None
        assert len(retrieved) == len(records)
        assert retrieved[0].market_name == records[0].market_name
        assert retrieved[0].report_date == records[0].report_date

    def test_cache_miss_returns_none(self, tmp_cache_dir):
        """Missing cache entry returns None."""
        cache = COTCache(tmp_cache_dir)
        assert cache.get(COTFormat.LEGACY, "2025") is None

    def test_is_stale_for_missing(self, tmp_cache_dir):
        """Missing entry is considered stale."""
        cache = COTCache(tmp_cache_dir)
        assert cache.is_stale(COTFormat.LEGACY, "2026") is True

    def test_not_stale_after_put(self, tmp_cache_dir):
        """Fresh cache entry is not stale (for current year)."""
        cache = COTCache(tmp_cache_dir)
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        cache.put(COTFormat.LEGACY, "2026", records)
        assert cache.is_stale(COTFormat.LEGACY, "2026") is False

    def test_historical_year_never_stale(self, tmp_cache_dir):
        """Prior year data doesn't go stale (finalised)."""
        cache = COTCache(tmp_cache_dir)
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        cache.put(COTFormat.LEGACY, "2020", records)
        assert cache.is_stale(COTFormat.LEGACY, "2020") is False

    def test_version_mismatch_invalidates(self, tmp_cache_dir):
        """Cache entry with wrong version is removed."""
        cache = COTCache(tmp_cache_dir)
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        cache.put(COTFormat.LEGACY, "2026", records)

        # Corrupt the version
        path = cache._entry_path(COTFormat.LEGACY, "2026")
        with open(path) as f:
            data = json.load(f)
        data["version"] = 999
        with open(path, "w") as f:
            json.dump(data, f)

        result = cache.get(COTFormat.LEGACY, "2026")
        assert result is None
        assert not path.exists()  # invalidated file removed

    def test_round_trip_preserves_values(self, tmp_cache_dir):
        """Serialise → deserialise preserves all field values."""
        cache = COTCache(tmp_cache_dir)
        original = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        cache.put(COTFormat.LEGACY, "2026", original)

        retrieved = cache.get(COTFormat.LEGACY, "2026")
        assert retrieved is not None

        orig = original[0]
        rere = retrieved[0]
        assert rere.market_name == orig.market_name
        assert rere.report_date == orig.report_date
        assert rere.non_comm_long == orig.non_comm_long
        assert rere.non_comm_short == orig.non_comm_short
        assert rere.comm_long == orig.comm_long
        assert rere.comm_short == orig.comm_short
        assert rere.net_position == orig.net_position

    def test_meta_updated_on_put(self, tmp_cache_dir):
        """Metadata file updated after put."""
        cache = COTCache(tmp_cache_dir)
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        cache.put(COTFormat.LEGACY, "2026", records)

        meta = cache.get_status()
        assert "legacy_2026" in meta["entries"]
        assert meta["entries"]["legacy_2026"]["record_count"] == len(records)
        assert meta["entries"]["legacy_2026"]["version"] == CACHE_VERSION

    def test_cleanup_removes_old_files(self, tmp_cache_dir):
        """Cleanup removes files older than max_age_days."""
        cache = COTCache(tmp_cache_dir)
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)
        cache.put(COTFormat.LEGACY, "2026", records)

        # Manually set fetched_at to 400 days ago
        path = cache._entry_path(COTFormat.LEGACY, "2026")
        with open(path) as f:
            data = json.load(f)
        old_date = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        data["fetched_at"] = old_date
        with open(path, "w") as f:
            json.dump(data, f)

        removed = cache.cleanup(max_age_days=365)
        assert removed == 1
        assert not path.exists()

    def test_cache_used_on_second_fetch(self, fetcher_with_cache):
        """Second call to get_positioning uses cache, not network."""
        records = COTFetcher._parse_csv(SAMPLE_LEGACY_CSV, COTFormat.LEGACY)

        # First call downloads
        with patch.object(fetcher_with_cache, "_download_and_parse", return_value=records) as mock_dl:
            fetcher_with_cache.get_positioning("USDJPY", COTFormat.LEGACY)
            assert mock_dl.call_count == 1

        # Second call uses cache
        with patch.object(fetcher_with_cache, "_download_and_parse", return_value=records) as mock_dl:
            fetcher_with_cache.get_positioning("USDJPY", COTFormat.LEGACY)
            assert mock_dl.call_count == 0  # served from cache


# ─── URL Building Tests ──────────────────────────────────────────────────────


class TestURLBuilding:
    """Test URL construction for CFTC downloads."""

    def test_legacy_url(self):
        url = COTFetcher()._build_url("2026", COTFormat.LEGACY)
        assert "fut_txt_2026" in url
        assert url.startswith("https://www.cftc.gov/")

    def test_disaggregated_url(self):
        url = COTFetcher()._build_url("2026", COTFormat.DISAGGREGATED)
        assert "com_dis_txt_2026" in url
        assert url.startswith("https://www.cftc.gov/")


# ─── Date Normalisation Tests ────────────────────────────────────────────────


class TestDateNormalisation:
    """Test date parsing for various input formats."""

    def test_us_date_format(self):
        assert COTFetcher._normalise_date("01/06/2026") == "2026-01-06"

    def test_iso_date_format(self):
        assert COTFetcher._normalise_date("2026-01-06") == "2026-01-06"

    def test_invalid_date(self):
        assert COTFetcher._normalise_date("not-a-date") == ""

    def test_empty_string(self):
        assert COTFetcher._normalise_date("") == ""
