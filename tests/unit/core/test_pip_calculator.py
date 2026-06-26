import unittest

from core.pip import PipCalculator


class TestPipValue(unittest.TestCase):
    def test_non_jpy_major(self):
        self.assertAlmostEqual(PipCalculator.pip_value(1.0), 0.0001)
        self.assertAlmostEqual(PipCalculator.pip_value(1.5), 0.0001)
        self.assertAlmostEqual(PipCalculator.pip_value(0.9), 0.00000001)

    def test_jpy_pair(self):
        self.assertAlmostEqual(PipCalculator.pip_value(150.0), 0.01)
        self.assertAlmostEqual(PipCalculator.pip_value(50.0), 0.01)

    def test_commodity(self):
        self.assertAlmostEqual(PipCalculator.pip_value(2000.0), 0.01)

    def test_exotic(self):
        self.assertAlmostEqual(PipCalculator.pip_value(0.05), 0.00000001)

    def test_boundary_jpy(self):
        self.assertAlmostEqual(PipCalculator.pip_value(49.99), 0.0001)
        self.assertAlmostEqual(PipCalculator.pip_value(50.0), 0.01)

    def test_boundary_major(self):
        self.assertAlmostEqual(PipCalculator.pip_value(0.99), 0.00000001)
        self.assertAlmostEqual(PipCalculator.pip_value(1.0), 0.0001)


class TestPipsToPrice(unittest.TestCase):
    def test_eurusd(self):
        result = PipCalculator.pips_to_price(1.0, 10.0)
        self.assertAlmostEqual(result, 0.001)

    def test_usdjpy(self):
        result = PipCalculator.pips_to_price(150.0, 10.0)
        self.assertAlmostEqual(result, 0.1)

    def test_xauusd(self):
        result = PipCalculator.pips_to_price(2000.0, 10.0)
        self.assertAlmostEqual(result, 0.1)

    def test_zero_pips(self):
        result = PipCalculator.pips_to_price(1.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_negative_pips(self):
        result = PipCalculator.pips_to_price(1.0, -5.0)
        self.assertAlmostEqual(result, -0.0005)


class TestPriceToPips(unittest.TestCase):
    def test_eurusd(self):
        result = PipCalculator.price_to_pips(1.0, 0.001)
        self.assertAlmostEqual(result, 10.0)

    def test_usdjpy(self):
        result = PipCalculator.price_to_pips(150.0, 0.1)
        self.assertAlmostEqual(result, 10.0)

    def test_xauusd(self):
        result = PipCalculator.price_to_pips(2000.0, 0.1)
        self.assertAlmostEqual(result, 10.0)

    def test_zero_diff(self):
        result = PipCalculator.price_to_pips(1.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_roundtrip(self):
        price = 1.1050
        pips = 25.0
        converted = PipCalculator.pips_to_price(price, pips)
        back = PipCalculator.price_to_pips(price, converted)
        self.assertAlmostEqual(back, pips)

    def test_roundtrip_jpy(self):
        price = 148.50
        pips = 30.0
        converted = PipCalculator.pips_to_price(price, pips)
        back = PipCalculator.price_to_pips(price, converted)
        self.assertAlmostEqual(back, pips)
