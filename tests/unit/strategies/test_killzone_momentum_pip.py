"""Tests for Killzone Momentum pip-value migration (card 5143fd9f).

Verifies that KillzoneMomentumStrategy uses the canonical
``utils.pip_value.pip_value_for_symbol`` lookup instead of the old
price-based heuristic that mis-classified XAUUSD as a JPY pair.

Covers:
- XAUUSD → 0.1 (gold pip, the primary bug)
- EURUSD → 0.0001 (standard forex)
- GBPUSD → 0.0001 (standard forex)
- USDJPY → 0.01 (JPY pair)
- Config symbol field defaults to XAUUSD
- _pip_for_price and _PIP removed from the module
"""

from __future__ import annotations

from strategies.killzone_momentum import KillzoneMomentumConfig
from utils.pip_value import pip_value_for_symbol


class TestKzMomentumPipMigration:
    """Verify pip_value_for_symbol migration is correct."""

    def test_xauusd_uses_gold_pip(self):
        """XAUUSD must resolve to 0.1 pip (gold), not 0.01 (JPY)."""
        assert pip_value_for_symbol("XAUUSD") == 0.1

    def test_eurusd_uses_standard_pip(self):
        """EURUSD must resolve to 0.0001 pip."""
        assert pip_value_for_symbol("EURUSD") == 0.0001

    def test_gbpusd_uses_standard_pip(self):
        """GBPUSD must resolve to 0.0001 pip."""
        assert pip_value_for_symbol("GBPUSD") == 0.0001

    def test_usdjpy_uses_jpy_pip(self):
        """USDJPY must resolve to 0.01 pip."""
        assert pip_value_for_symbol("USDJPY") == 0.01

    def test_config_symbol_defaults_to_xauusd(self):
        """KillzoneMomentumConfig.symbol must default to 'XAUUSD'."""
        config = KillzoneMomentumConfig()
        assert config.symbol == "XAUUSD"

    def test_config_symbol_can_be_overridden(self):
        """Symbol can be overridden via constructor."""
        config = KillzoneMomentumConfig(symbol="EURUSD")
        assert config.symbol == "EURUSD"

    def test_pip_for_price_removed(self):
        """The old _pip_for_price function must no longer exist."""
        import strategies.killzone_momentum as kzm

        assert not hasattr(kzm, "_pip_for_price"), (
            "_pip_for_price must be removed — replaced by pip_value_for_symbol lookup"
        )

    def test_pip_alias_removed(self):
        """The deprecated _PIP alias must no longer exist."""
        import strategies.killzone_momentum as kzm

        assert not hasattr(kzm, "_PIP"), "_PIP deprecated alias must be removed"

    def test_no_old_heuristic_references_in_source(self):
        """Source must not contain _pip_for_price or _JPY_PIP references."""
        import strategies.killzone_momentum as kzm

        source = open(kzm.__file__).read()
        assert "_pip_for_price" not in source
        assert "_JPY_PIP" not in source
