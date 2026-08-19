"""Unit tests for ``utils.pip_value.pip_value_for_symbol``.

These tests pin the canonical pip-size lookup that replaces the
old price-based heuristic (which mis-classified XAUUSD as JPY).

Also includes regression tests for strategy files that were migrated
from broken heuristics to ``pip_value_for_symbol``.
"""

from __future__ import annotations

import unittest

from utils.pip_value import (
    CRYPTO_PIP,
    DEFAULT_PIP,
    JPY_PIP,
    XAU_PIP,
    pip_value_for_symbol,
)


class TestForexNonJpy(unittest.TestCase):
    """Standard 5-digit forex pairs."""

    def test_eurusd(self):
        self.assertEqual(pip_value_for_symbol("EURUSD"), 0.0001)

    def test_gbpusd(self):
        self.assertEqual(pip_value_for_symbol("GBPUSD"), 0.0001)

    def test_audusd(self):
        self.assertEqual(pip_value_for_symbol("AUDUSD"), 0.0001)

    def test_usdcad(self):
        self.assertEqual(pip_value_for_symbol("USDCAD"), 0.0001)

    def test_nzdusd(self):
        self.assertEqual(pip_value_for_symbol("NZDUSD"), 0.0001)


class TestForexJpy(unittest.TestCase):
    """3-digit JPY pairs."""

    def test_usdjpy(self):
        self.assertEqual(pip_value_for_symbol("USDJPY"), 0.01)

    def test_eurjpy(self):
        self.assertEqual(pip_value_for_symbol("EURJPY"), 0.01)

    def test_gbpjpy(self):
        self.assertEqual(pip_value_for_symbol("GBPJPY"), 0.01)

    def test_audjpy(self):
        self.assertEqual(pip_value_for_symbol("AUDJPY"), 0.01)


class TestPreciousMetals(unittest.TestCase):
    """Gold and silver — the primary bug-fix targets."""

    def test_xauusd_is_not_jpy(self):
        """REGRESSION: the old price heuristic returned 0.01 (JPY) for gold
        because price >= 50. Gold's standard cTrader pip is 0.1."""
        result = pip_value_for_symbol("XAUUSD")
        self.assertEqual(result, 0.1)
        self.assertNotEqual(result, 0.01, "XAUUSD must NOT be classified as JPY")

    def test_xauusd_value(self):
        self.assertEqual(pip_value_for_symbol("XAUUSD"), XAU_PIP)
        self.assertEqual(pip_value_for_symbol("XAUUSD"), 0.1)

    def test_gold_alias(self):
        self.assertEqual(pip_value_for_symbol("GOLD"), 0.1)

    def test_xau_alias(self):
        self.assertEqual(pip_value_for_symbol("XAU"), 0.1)

    def test_xagusd(self):
        self.assertEqual(pip_value_for_symbol("XAGUSD"), 0.001)

    def test_silver_alias(self):
        self.assertEqual(pip_value_for_symbol("SILVER"), 0.001)


class TestCryptoMajors(unittest.TestCase):
    """Crypto pairs use whole-dollar pips."""

    def test_btcusd(self):
        self.assertEqual(pip_value_for_symbol("BTCUSD"), CRYPTO_PIP)
        self.assertEqual(pip_value_for_symbol("BTCUSD"), 1.0)

    def test_ethusd(self):
        self.assertEqual(pip_value_for_symbol("ETHUSD"), 1.0)


class TestCaseInsensitive(unittest.TestCase):
    """Symbol matching must be case-insensitive."""

    def test_lowercase_eurusd(self):
        self.assertEqual(pip_value_for_symbol("eurusd"), DEFAULT_PIP)

    def test_lowercase_xauusd(self):
        self.assertEqual(pip_value_for_symbol("xauusd"), XAU_PIP)
        self.assertEqual(pip_value_for_symbol("xauusd"), 0.1)

    def test_mixed_case_gbpjpy(self):
        self.assertEqual(pip_value_for_symbol("GbpJpy"), JPY_PIP)

    def test_whitespace_stripped(self):
        self.assertEqual(pip_value_for_symbol("  XAUUSD  "), XAU_PIP)


class TestInputValidation(unittest.TestCase):
    """Defensive: invalid inputs raise clearly."""

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            pip_value_for_symbol("")

    def test_whitespace_only_raises(self):
        with self.assertRaises(ValueError):
            pip_value_for_symbol("   ")

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            pip_value_for_symbol(None)  # type: ignore[arg-type]

    def test_non_string_raises(self):
        with self.assertRaises(ValueError):
            pip_value_for_symbol(123)  # type: ignore[arg-type]


class TestConsistency(unittest.TestCase):
    """Pip values must be stable across calls (no caching bugs)."""

    def test_xauusd_repeatable(self):
        for _ in range(100):
            self.assertEqual(pip_value_for_symbol("XAUUSD"), 0.1)

    def test_unknown_symbol_defaults_to_forex_pip(self):
        """Unknown symbols (e.g. exotic pairs) fall back to DEFAULT_PIP
        rather than raising — this preserves behavior for symbols the
        lookup table doesn't know about."""
        # SGD is exotic but uses standard forex pip
        self.assertEqual(pip_value_for_symbol("SGDUSD"), DEFAULT_PIP)


class TestSessionBreakoutPipSize(unittest.TestCase):
    """Regression: session_breakout._pip_size_for_symbol must use
    pip_value_for_symbol, not the old price-based heuristic.

    The old ``_pip_size(price)`` returned 0.01 for XAUUSD because
    gold's ~2000 price triggers the ``price >= 50`` JPY branch.
    """

    def test_xauusd_returns_gold_pip(self):
        """XAUUSD must return 0.1, not the old 0.01."""
        from strategies.session_breakout import _pip_size_for_symbol

        self.assertEqual(_pip_size_for_symbol("XAUUSD"), 0.1)

    def test_eurusd_returns_forex_pip(self):
        from strategies.session_breakout import _pip_size_for_symbol

        self.assertEqual(_pip_size_for_symbol("EURUSD"), 0.0001)

    def test_usdjpy_returns_jpy_pip(self):
        from strategies.session_breakout import _pip_size_for_symbol

        self.assertEqual(_pip_size_for_symbol("USDJPY"), 0.01)

    def test_empty_symbol_falls_back_to_default(self):
        from strategies.session_breakout import _pip_size_for_symbol

        self.assertEqual(_pip_size_for_symbol(""), DEFAULT_PIP)


class TestGridStrategyPipSize(unittest.TestCase):
    """Regression: GridState._get_pip_size and GridStrategy._get_pip_size
    must use pip_value_for_symbol, not the old JPY-only heuristic.

    The old code returned 0.0001 for XAUUSD (wrong; should be 0.1).
    """

    def test_grid_state_xauusd(self):
        from backtest.grid_strategy import GridConfig, GridState

        state = GridState(GridConfig(pair="XAUUSD"))
        self.assertEqual(state.pip_size, 0.1)

    def test_grid_state_eurusd(self):
        from backtest.grid_strategy import GridConfig, GridState

        state = GridState(GridConfig(pair="EURUSD"))
        self.assertEqual(state.pip_size, 0.0001)

    def test_grid_state_usdjpy(self):
        from backtest.grid_strategy import GridConfig, GridState

        state = GridState(GridConfig(pair="USDJPY"))
        self.assertEqual(state.pip_size, 0.01)

    def test_grid_strategy_get_pip_size_xauusd(self):
        from backtest.grid_strategy import GridStrategy

        gs = GridStrategy(pair="XAUUSD")
        self.assertEqual(gs._get_pip_size("XAUUSD"), 0.1)


if __name__ == "__main__":
    unittest.main()
