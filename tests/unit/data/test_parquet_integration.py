import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtest.data_loader import (
    CsvDataLoader,
    _compute_spread_pips,
    _detect_ask_columns,
)
from backtest.engine import Bar as LegacyBar
from core.spread import RealisticSpreadModel, SpreadModel
from core.types import Bar
from core.pip import PipCalculator


class TestComputeSpreadPips(unittest.TestCase):
    def test_eurusd_spread(self):
        spread = _compute_spread_pips(1.10000, 1.10015)
        self.assertAlmostEqual(spread, 1.5, places=1)

    def test_usdjpy_spread(self):
        spread = _compute_spread_pips(150.000, 150.015)
        self.assertAlmostEqual(spread, 1.5, places=1)

    def test_zero_spread(self):
        spread = _compute_spread_pips(1.10000, 1.10000)
        self.assertAlmostEqual(spread, 0.0, places=5)

    def test_wide_spread(self):
        spread = _compute_spread_pips(1.10000, 1.10050)
        self.assertAlmostEqual(spread, 5.0, places=1)

    def test_negative_returns_positive(self):
        spread = _compute_spread_pips(1.10015, 1.10000)
        self.assertAlmostEqual(spread, 1.5, places=1)


class TestDetectAskColumns(unittest.TestCase):
    def test_bid_only_df(self):
        df = pd.DataFrame({"Open": [1.0], "Close": [1.0]})
        self.assertFalse(_detect_ask_columns(df))

    def test_bid_ask_df(self):
        df = pd.DataFrame(
            {
                "Open": [1.0],
                "Close": [1.0],
                "ask_open": [1.0001],
                "ask_close": [1.0001],
            }
        )
        self.assertTrue(_detect_ask_columns(df))

    def test_partial_ask_df(self):
        df = pd.DataFrame(
            {
                "Open": [1.0],
                "Close": [1.0],
                "ask_open": [1.0001],
            }
        )
        self.assertFalse(_detect_ask_columns(df))


class TestLoadParquetBidOnly(unittest.TestCase):
    def setUp(self):
        self.loader = CsvDataLoader()

    def test_loads_bid_only_parquet(self):
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC"),
                "Open": [1.09, 1.10, 1.11],
                "High": [1.095, 1.105, 1.115],
                "Low": [1.085, 1.095, 1.105],
                "Close": [1.10, 1.11, 1.12],
                "Volume": [100, 200, 300],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.to_parquet(f.name, index=False)
            bars = self.loader.load_parquet(f.name)
            Path(f.name).unlink()

        self.assertEqual(len(bars), 3)
        self.assertEqual(bars[0].open, 1.09)
        self.assertEqual(bars[0].close, 1.10)
        self.assertEqual(bars[0].spread_pips, 0.0)
        self.assertEqual(bars[1].volume, 200.0)

    def test_bid_only_all_bars_have_zero_spread(self):
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC"),
                "Open": [1.0] * 5,
                "High": [1.01] * 5,
                "Low": [0.99] * 5,
                "Close": [1.005] * 5,
                "Volume": [0] * 5,
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.to_parquet(f.name, index=False)
            bars = self.loader.load_parquet(f.name)
            Path(f.name).unlink()

        for bar in bars:
            self.assertEqual(bar.spread_pips, 0.0)


class TestLoadParquetBidAsk(unittest.TestCase):
    def setUp(self):
        self.loader = CsvDataLoader()

    def test_loads_bid_ask_parquet_with_spread(self):
        timestamps = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "Open": [1.10000, 1.10100, 1.10200],
                "High": [1.10050, 1.10150, 1.10250],
                "Low": [1.09950, 1.10050, 1.10150],
                "Close": [1.10030, 1.10130, 1.10230],
                "Volume": [100, 200, 300],
                "ask_open": [1.10015, 1.10115, 1.10218],
                "ask_high": [1.10065, 1.10165, 1.10268],
                "ask_low": [1.09965, 1.10065, 1.10168],
                "ask_close": [1.10045, 1.10145, 1.10248],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.to_parquet(f.name, index=False)
            bars = self.loader.load_parquet(f.name)
            Path(f.name).unlink()

        self.assertEqual(len(bars), 3)
        self.assertAlmostEqual(bars[0].spread_pips, 1.5, places=1)
        self.assertAlmostEqual(bars[1].spread_pips, 1.5, places=1)
        self.assertGreater(bars[2].spread_pips, 0.0)

    def test_spread_values_vary_across_bars(self):
        timestamps = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "Open": [1.10000, 1.10000, 1.10000],
                "High": [1.10100, 1.10100, 1.10100],
                "Low": [1.09900, 1.09900, 1.09900],
                "Close": [1.10050, 1.10050, 1.10050],
                "Volume": [0, 0, 0],
                "ask_open": [1.10010, 1.10030, 1.10050],
                "ask_high": [1.10110, 1.10130, 1.10150],
                "ask_low": [1.09910, 1.09930, 1.09950],
                "ask_close": [1.10060, 1.10080, 1.10100],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.to_parquet(f.name, index=False)
            bars = self.loader.load_parquet(f.name)
            Path(f.name).unlink()

        self.assertAlmostEqual(bars[0].spread_pips, 1.0, places=1)
        self.assertAlmostEqual(bars[1].spread_pips, 3.0, places=1)
        self.assertAlmostEqual(bars[2].spread_pips, 5.0, places=1)

    def test_ohlc_values_from_bid_columns(self):
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=1, freq="h", tz="UTC"),
                "Open": [1.10000],
                "High": [1.10050],
                "Low": [1.09950],
                "Close": [1.10030],
                "Volume": [42],
                "ask_open": [1.10015],
                "ask_close": [1.10045],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.to_parquet(f.name, index=False)
            bars = self.loader.load_parquet(f.name)
            Path(f.name).unlink()

        self.assertEqual(len(bars), 1)
        self.assertAlmostEqual(bars[0].open, 1.10000)
        self.assertAlmostEqual(bars[0].high, 1.10050)
        self.assertAlmostEqual(bars[0].low, 1.09950)
        self.assertAlmostEqual(bars[0].close, 1.10030)
        self.assertAlmostEqual(bars[0].volume, 42.0)


class TestRealisticSpreadModel(unittest.TestCase):
    def test_default_spread_used_when_no_bar_spread(self):
        model = RealisticSpreadModel(default_spread_pips=1.5, slippage_pips=0.5)
        self.assertAlmostEqual(model.current_spread_pips(), 1.5)

    def test_set_bar_spread_updates_spread(self):
        model = RealisticSpreadModel(default_spread_pips=1.5)
        model.set_bar_spread(2.0)
        self.assertAlmostEqual(model.current_spread_pips(), 2.0)

    def test_zero_bar_spread_falls_back_to_default(self):
        model = RealisticSpreadModel(default_spread_pips=1.5)
        model.set_bar_spread(0.0)
        self.assertAlmostEqual(model.current_spread_pips(), 1.5)

    def test_negative_bar_spread_falls_back_to_default(self):
        model = RealisticSpreadModel(default_spread_pips=1.5)
        model.set_bar_spread(-1.0)
        self.assertAlmostEqual(model.current_spread_pips(), 1.5)

    def test_adjust_entry_long_uses_bar_spread(self):
        model = RealisticSpreadModel(default_spread_pips=1.5, slippage_pips=0.5)
        model.set_bar_spread(2.0)
        adjusted = model.adjust_entry_long(1.1000)
        expected = 1.1000 + PipCalculator.pips_to_price(1.1000, 2.5)
        self.assertAlmostEqual(adjusted, expected)

    def test_adjust_entry_short_uses_bar_spread(self):
        model = RealisticSpreadModel(default_spread_pips=1.5, slippage_pips=0.5)
        model.set_bar_spread(3.0)
        adjusted = model.adjust_entry_short(1.1000)
        expected = 1.1000 - PipCalculator.pips_to_price(1.1000, 3.5)
        self.assertAlmostEqual(adjusted, expected)

    def test_spread_changes_per_bar(self):
        model = RealisticSpreadModel(default_spread_pips=1.5, slippage_pips=0.0)

        model.set_bar_spread(1.0)
        long1 = model.adjust_entry_long(1.0)

        model.set_bar_spread(3.0)
        long2 = model.adjust_entry_long(1.0)

        self.assertGreater(long2, long1)

    def test_spread_pips_property(self):
        model = RealisticSpreadModel(default_spread_pips=2.0)
        self.assertEqual(model.spread_pips, 2.0)
        model.set_bar_spread(4.0)
        self.assertEqual(model.spread_pips, 4.0)

    def test_slippage_pips_property(self):
        model = RealisticSpreadModel(default_spread_pips=1.5, slippage_pips=0.5)
        self.assertEqual(model.slippage_pips, 0.5)


class TestSpreadModelCompatibility(unittest.TestCase):
    def test_spread_model_has_current_spread_pips(self):
        model = SpreadModel(spread_pips=1.5)
        self.assertEqual(model.current_spread_pips(), 1.5)

    def test_spread_model_adjust_entry_unchanged(self):
        model = SpreadModel(spread_pips=1.5, slippage_pips=0.5)
        self.assertAlmostEqual(
            model.adjust_entry_long(1.1000),
            1.1000 + PipCalculator.pips_to_price(1.1000, 2.0),
        )


class TestBarSpreadPipsField(unittest.TestCase):
    def test_core_bar_has_spread_pips(self):
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1,
            high=1.11,
            low=1.09,
            close=1.105,
        )
        self.assertEqual(bar.spread_pips, 0.0)

    def test_core_bar_custom_spread(self):
        bar = Bar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1,
            high=1.11,
            low=1.09,
            close=1.105,
            spread_pips=1.5,
        )
        self.assertEqual(bar.spread_pips, 1.5)

    def test_legacy_bar_has_spread_pips(self):
        bar = LegacyBar(
            time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.1,
            high=1.11,
            low=1.09,
            close=1.105,
        )
        self.assertEqual(bar.spread_pips, 0.0)


class TestEndToEndParquetPipeline(unittest.TestCase):
    def test_load_parquet_and_run_with_realistic_spread(self):
        n_bars = 100
        timestamps = pd.date_range("2024-01-01", periods=n_bars, freq="h", tz="UTC")
        bid_opens = [1.1000 + i * 0.0001 for i in range(n_bars)]
        ask_opens = [o + 0.00015 for o in bid_opens]

        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "Open": bid_opens,
                "High": [o + 0.0005 for o in bid_opens],
                "Low": [o - 0.0005 for o in bid_opens],
                "Close": [o + 0.0002 for o in bid_opens],
                "Volume": [100] * n_bars,
                "ask_open": ask_opens,
                "ask_high": [a + 0.0005 for a in ask_opens],
                "ask_low": [a - 0.0005 for a in ask_opens],
                "ask_close": [a + 0.0002 for a in ask_opens],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            df.to_parquet(f.name, index=False)
            loader = CsvDataLoader()
            bars = loader.load_parquet(f.name)
            Path(f.name).unlink()

        self.assertEqual(len(bars), n_bars)
        for bar in bars:
            self.assertGreater(bar.spread_pips, 0.0)

        model = RealisticSpreadModel(default_spread_pips=1.5)
        for bar in bars:
            model.set_bar_spread(bar.spread_pips)
            adjusted = model.adjust_entry_long(bar.open)
            self.assertGreater(adjusted, bar.open)


if __name__ == "__main__":
    unittest.main()
