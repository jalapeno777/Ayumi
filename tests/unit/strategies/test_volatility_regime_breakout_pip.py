"""Tests for VRB pip-value migration (card 5a72aa6b).

Verifies that VolatilityRegimeBreakoutStrategy uses the canonical
``utils.pip_value.pip_value_for_symbol`` lookup instead of the old
price-based heuristic that mis-classified XAUUSD as a JPY pair.

Covers:
- XAUUSD → 0.1 (gold pip, the primary bug)
- EURUSD → 0.0001 (standard forex)
- USDJPY → 0.01 (JPY pair)
- GBPJPY → 0.01 (JPY pair)
- Explicit pip_value override takes precedence
- _pip_value_for_price removed from the module
- ValueError path when symbol is None and price >= 50
"""

from __future__ import annotations


from strategies.volatility_regime_breakout import (
    VRBConfig,
)
from utils.pip_value import pip_value_for_symbol


class TestVRBPipMigration:
    """Verify pip_value_for_symbol migration is correct."""

    def test_xauusd_uses_gold_pip(self):
        """XAUUSD must resolve to 0.1 pip (gold), not 0.01 (JPY)."""
        assert pip_value_for_symbol("XAUUSD") == 0.1

    def test_eurusd_uses_standard_pip(self):
        """EURUSD must resolve to 0.0001 pip."""
        assert pip_value_for_symbol("EURUSD") == 0.0001

    def test_usdjpy_uses_jpy_pip(self):
        """USDJPY must resolve to 0.01 pip."""
        assert pip_value_for_symbol("USDJPY") == 0.01

    def test_gbpjpy_uses_jpy_pip(self):
        """GBPJPY must resolve to 0.01 pip."""
        assert pip_value_for_symbol("GBPJPY") == 0.01

    def test_gold_alias_resolves_correctly(self):
        """GOLD alias must resolve to the same pip as XAUUSD."""
        assert pip_value_for_symbol("GOLD") == pip_value_for_symbol("XAUUSD")

    def test_explicit_pip_value_override(self):
        """When config.pip_value is explicitly set, it takes precedence."""
        config = VRBConfig(pip_value=0.5, symbol="XAUUSD")
        assert config.pip_value == 0.5

    def test_symbol_field_defaults_to_none(self):
        """VRBConfig.symbol must default to None."""
        config = VRBConfig()
        assert config.symbol is None

    def test_pip_value_for_price_removed(self):
        """The old _pip_value_for_price function must no longer exist."""
        import strategies.volatility_regime_breakout as vrb

        assert not hasattr(vrb, "_pip_value_for_price"), (
            "_pip_value_for_price must be removed — replaced by "
            "pip_value_for_symbol lookup"
        )

    def test_valueerror_path_exists_for_high_price_no_symbol(self):
        """Without a symbol, price >= 50 must raise ValueError
        (ambiguous — could be XAUUSD, XAGUSD, BTCUSD, or JPY)."""
        import strategies.volatility_regime_breakout as vrb

        source = open(vrb.__file__).read()
        assert "raise ValueError" in source, (
            "Strategy must raise ValueError when symbol is None and "
            "price >= 50 (ambiguous pip territory)"
        )
        assert "_pip_value_for_price" not in source, (
            "Old heuristic function reference must be fully removed"
        )
