import unittest

from core.spread import SpreadModel
from core.pip import PipCalculator


class TestSpreadModel(unittest.TestCase):
    def test_is_frozen(self):
        model = SpreadModel(spread_pips=1.5)
        with self.assertRaises(AttributeError):
            model.spread_pips = 2.0

    def test_default_slippage(self):
        model = SpreadModel(spread_pips=1.5)
        self.assertEqual(model.slippage_pips, 0.0)

    def test_custom_slippage(self):
        model = SpreadModel(spread_pips=1.5, slippage_pips=0.5)
        self.assertEqual(model.slippage_pips, 0.5)

    def test_adjust_entry_long_eurusd(self):
        model = SpreadModel(spread_pips=1.5, slippage_pips=0.5)
        adjusted = model.adjust_entry_long(1.1000)
        expected = 1.1000 + PipCalculator.pips_to_price(1.1000, 2.0)
        self.assertAlmostEqual(adjusted, expected)

    def test_adjust_entry_short_eurusd(self):
        model = SpreadModel(spread_pips=1.5, slippage_pips=0.5)
        adjusted = model.adjust_entry_short(1.1000)
        expected = 1.1000 - PipCalculator.pips_to_price(1.1000, 2.0)
        self.assertAlmostEqual(adjusted, expected)

    def test_adjust_entry_long_usdjpy(self):
        model = SpreadModel(spread_pips=1.5)
        adjusted = model.adjust_entry_long(150.00)
        expected = 150.00 + PipCalculator.pips_to_price(150.00, 1.5)
        self.assertAlmostEqual(adjusted, expected)

    def test_adjust_entry_short_usdjpy(self):
        model = SpreadModel(spread_pips=1.5)
        adjusted = model.adjust_entry_short(150.00)
        expected = 150.00 - PipCalculator.pips_to_price(150.00, 1.5)
        self.assertAlmostEqual(adjusted, expected)

    def test_adjust_entry_long_xauusd(self):
        model = SpreadModel(spread_pips=2.5, slippage_pips=0.5)
        adjusted = model.adjust_entry_long(2000.0)
        expected = 2000.0 + PipCalculator.pips_to_price(2000.0, 3.0)
        self.assertAlmostEqual(adjusted, expected)

    def test_spread_only_no_slippage(self):
        model = SpreadModel(spread_pips=1.0)
        adjusted_long = model.adjust_entry_long(1.0)
        adjusted_short = model.adjust_entry_short(1.0)
        spread_price = PipCalculator.pips_to_price(1.0, 1.0)
        self.assertAlmostEqual(adjusted_long, 1.0 + spread_price)
        self.assertAlmostEqual(adjusted_short, 1.0 - spread_price)

    def test_long_always_higher_than_raw(self):
        model = SpreadModel(spread_pips=1.5, slippage_pips=0.5)
        self.assertGreater(model.adjust_entry_long(1.0), 1.0)

    def test_short_always_lower_than_raw(self):
        model = SpreadModel(spread_pips=1.5, slippage_pips=0.5)
        self.assertLess(model.adjust_entry_short(1.0), 1.0)

    def test_spread_widens_with_slippage(self):
        base = SpreadModel(spread_pips=1.5)
        with_slip = SpreadModel(spread_pips=1.5, slippage_pips=0.5)
        self.assertGreater(
            with_slip.adjust_entry_long(1.0),
            base.adjust_entry_long(1.0),
        )
