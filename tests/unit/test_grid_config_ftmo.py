"""Unit tests for GridConfig.ftmo pair forward (card d8b13347).

Bug: ``GridConfig.ftmo(pair='GBPUSD')`` returned a config whose ``pair``
field was the dataclass default ``'EURUSD'`` instead of the caller-supplied
symbol, because the ``cls(...)`` call omitted ``pair=pair``. The spacing /
levels / position-cap preset values were already correctly pulled from
``GRID_PRESETS[pair]``, so the failure was narrow but dangerous in a
live-trading preset factory: any caller passing a non-EURUSD pair got a
config marked as EURUSD on the dataclass side.

Fix: forward ``pair`` to ``cls(...)`` explicitly; fall back to ``"EURUSD"``
when the caller omits the argument or passes a falsy value (``""`` /
``None``) so the dataclass default semantics are preserved.

These tests exist alongside ``tests/unit/backtest/test_grid_config_ftmo.py``
(scope: spacing/levels/positions/fallback behaviour) and pin the pair
forward specifically.
"""

from __future__ import annotations

import pytest  # noqa: F401
from backtest.grid_strategy import GRID_PRESETS, GridConfig


class TestGridConfigFtmoPairForward:
    """Card d8b13347 — the ``pair`` field is forwarded to the returned config."""

    def test_ftmo_known_pair_pair_field_is_the_supplied_symbol(self):
        """The primary bug fix: ftmo('GBPUSD').pair == 'GBPUSD'."""
        c = GridConfig.ftmo("GBPUSD")
        assert c.pair == "GBPUSD"

    def test_ftmo_xauusd_pair_field_is_xauusd(self):
        c = GridConfig.ftmo("XAUUSD")
        assert c.pair == "XAUUSD"

    def test_ftmo_gbpjpy_pair_field_is_gbpjpy(self):
        c = GridConfig.ftmo("GBPJPY")
        assert c.pair == "GBPJPY"

    def test_ftmo_eurusd_pair_field_is_eurusd(self):
        c = GridConfig.ftmo("EURUSD")
        assert c.pair == "EURUSD"

    def test_ftmo_unknown_pair_preserves_caller_symbol(self):
        """Unknown pair: caller symbol is preserved on the config, spacing
        falls back to EURUSD preset (consistent with existing semantics in
        ``tests/unit/backtest/test_grid_config_ftmo.py::test_ftmo_unknown_pair_falls_back_to_eurusd``)."""
        c = GridConfig.ftmo("UNKNOWNPAIR")
        assert c.pair == "UNKNOWNPAIR"
        # spacing/levels still come from the EURUSD fallback
        assert c.grid_spacing_pips == GRID_PRESETS["EURUSD"]["grid_spacing_pips"]

    def test_ftmo_default_pair_is_eurusd(self):
        """Default-call pair is preserved as 'EURUSD'."""
        assert GridConfig.ftmo().pair == "EURUSD"

    def test_ftmo_empty_string_pair_falls_back_to_eurusd(self):
        """Empty string is treated as omitted and defaults to EURUSD."""
        assert GridConfig.ftmo("").pair == "EURUSD"

    def test_ftmo_none_pair_falls_back_to_eurusd(self):
        """None is treated as omitted and defaults to EURUSD (defensive)."""
        assert GridConfig.ftmo(None).pair == "EURUSD"

    def test_ftmo_pair_and_preset_values_are_consistent(self):
        """Pair forward must not change the preset-derived fields."""
        c = GridConfig.ftmo("GBPJPY")
        # spacing/levels come from GRID_PRESETS["GBPJPY"], not EURUSD
        assert c.grid_spacing_pips == GRID_PRESETS["GBPJPY"]["grid_spacing_pips"]
        assert c.num_levels == GRID_PRESETS["GBPJPY"]["num_levels"]
        assert c.max_concurrent_positions == GRID_PRESETS["GBPJPY"]["max_concurrent_positions"]
        # pair forward is independent of spacing lookup
        assert c.pair == "GBPJPY"

    def test_ftmo_returns_gridconfig_instance(self):
        """Sanity guard: the factory still returns a GridConfig."""
        assert isinstance(GridConfig.ftmo("GBPUSD"), GridConfig)
        assert isinstance(GridConfig.ftmo(), GridConfig)


class TestGridConfigFtmoKeywordArgument:
    """Card d8b13347 — the explicit KW form called out in the task spec."""

    def test_ftmo_keyword_pair_gbpusd_returns_gbpusd(self):
        """The exact assertion from the task spec: ftmo(pair='GBPUSD').pair == 'GBPUSD'."""
        assert GridConfig.ftmo(pair="GBPUSD").pair == "GBPUSD"

    def test_ftmo_keyword_pair_eurusd_returns_eurusd(self):
        assert GridConfig.ftmo(pair="EURUSD").pair == "EURUSD"
