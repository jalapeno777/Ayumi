"""Unit tests for GridConfig.ftmo — FTMO-constrained grid preset factory.

Card: 78904868-9802-4e08-8768-4f7261104dbc (Bug 2).

The .ftmo() classmethod is the preset factory named for the FTMO funding
program. It pulls spacing/levels/atr/position-cap from GRID_PRESETS, falls
back to EURUSD when an unknown pair is requested, and locks the spacing
and sizing to the conservative fixed/equal choices that match FTMO risk
rules. The other 15 call sites (runner.py x2, builtin_strategies.py:74,
portfolio_blend.py:1006, tests x11) import this method — those callers are
not edited here, they merely rely on GridConfig.ftmo being defined.
"""

from __future__ import annotations

import pytest
from backtest.grid_strategy import GRID_PRESETS, GridConfig


class TestGridConfigFtmo:
    """GridConfig.ftmo(pair) returns a conservative preset for known pairs."""

    def test_ftmo_xauusd_spacing_levels_positions(self):
        c = GridConfig.ftmo("XAUUSD")
        assert c.grid_spacing_pips == 150.0
        assert c.num_levels == 6
        assert c.max_concurrent_positions == 3

    def test_ftmo_eurusd_spacing_levels_positions(self):
        c = GridConfig.ftmo("EURUSD")
        assert c.grid_spacing_pips == 15.0
        assert c.num_levels == 10
        assert c.max_concurrent_positions == 5

    def test_ftmo_unknown_pair_falls_back_to_eurusd(self):
        c = GridConfig.ftmo("UNKNOWNPAIR")
        assert c.grid_spacing_pips == GRID_PRESETS["EURUSD"]["grid_spacing_pips"]
        assert c.num_levels == GRID_PRESETS["EURUSD"]["num_levels"]
        assert c.max_concurrent_positions == GRID_PRESETS["EURUSD"]["max_concurrent_positions"]

    def test_ftmo_locked_to_fixed_equal_sizing(self):
        """FTMO constraint: fixed spacing + equal sizing for every pair."""
        for pair in ("EURUSD", "GBPJPY", "USDJPY", "XAUUSD"):
            c = GridConfig.ftmo(pair)
            assert c.initial_spacing_type == "fixed"
            assert c.position_sizing_type == "equal"

    def test_ftmo_default_pair_is_eurusd(self):
        assert GridConfig.ftmo().grid_spacing_pips == GridConfig.ftmo("EURUSD").grid_spacing_pips

    def test_ftmo_returns_gridconfig_instance(self):
        assert isinstance(GridConfig.ftmo("EURUSD"), GridConfig)


class TestGridConfigFtmoAdapterConstruction:
    """GridStrategyAdapter(GridConfig.ftmo(...)) constructs when available.

    The strategies.grid package is archived (see tests/strategies/
    test_grid_trading.py module-level skip "strategies.grid module
    removed"); runner.py:28, builtin_strategies.py:4, portfolio_blend.py:966
    all do a defensive try/except for GridStrategyAdapter. This test mirrors
    that pattern — if the adapter is importable, the construction must
    succeed; otherwise we skip cleanly so the FTMO preset factory can be
    verified independently of the archived adapter.
    """

    def test_grid_strategy_adapter_construction(self):
        try:
            from strategies.grid.adapter import GridStrategyAdapter
        except ImportError:
            pytest.skip("strategies.grid.adapter unavailable (archived)")
        adapter = GridStrategyAdapter(GridConfig.ftmo("EURUSD"))
        assert adapter is not None
