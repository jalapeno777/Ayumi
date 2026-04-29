"""Tests for StrategyRegistry."""

from __future__ import annotations

from strategies.registry import StrategyConfig, StrategyRegistry, default_registry


def _sample_config(**overrides) -> StrategyConfig:
    defaults = dict(
        strategy_id="test_strat",
        name="Test Strategy",
        strategy_type="momentum",
        symbols=["EURUSD"],
        timeframes=["H1"],
        typical_confidence_range=(0.4, 0.8),
    )
    defaults.update(overrides)
    return StrategyConfig(**defaults)


class TestStrategyRegistry:
    def test_register_and_get(self):
        reg = StrategyRegistry()
        cfg = _sample_config()
        reg.register(cfg)
        assert reg.get("test_strat") is cfg

    def test_get_missing_returns_none(self):
        reg = StrategyRegistry()
        assert reg.get("nonexistent") is None

    def test_register_duplicate_overwrites(self):
        reg = StrategyRegistry()
        reg.register(_sample_config())
        new_cfg = _sample_config(name="Updated Name")
        reg.register(new_cfg)
        assert reg.get("test_strat").name == "Updated Name"

    def test_get_for_symbol(self):
        reg = StrategyRegistry()
        reg.register(_sample_config(strategy_id="s1", symbols=["EURUSD", "GBPUSD"]))
        reg.register(_sample_config(strategy_id="s2", symbols=["USDJPY"]))
        result = reg.get_for_symbol("eurusd")
        assert len(result) == 1
        assert result[0].strategy_id == "s1"

    def test_get_all_returns_all(self):
        reg = StrategyRegistry()
        reg.register(_sample_config(strategy_id="a"))
        reg.register(_sample_config(strategy_id="b"))
        assert len(reg.get_all()) == 2

    def test_get_all_active_filters_inactive(self):
        reg = StrategyRegistry()
        reg.register(_sample_config(strategy_id="a", active=True))
        reg.register(_sample_config(strategy_id="b", active=False))
        assert len(reg.get_all_active()) == 1
        assert reg.get_all_active()[0].strategy_id == "a"

    def test_get_for_symbol_inactive_excluded(self):
        reg = StrategyRegistry()
        reg.register(_sample_config(strategy_id="a", symbols=["EURUSD"], active=True))
        reg.register(_sample_config(strategy_id="b", symbols=["EURUSD"], active=False))
        assert len(reg.get_for_symbol("EURUSD")) == 1

    def test_symbol_matching_is_case_insensitive(self):
        reg = StrategyRegistry()
        reg.register(_sample_config(strategy_id="a", symbols=["EURUSD"]))
        assert len(reg.get_for_symbol("eurusd")) == 1


class TestDefaultRegistry:
    def test_has_all_eight_strategies(self):
        reg = default_registry()
        assert len(reg.get_all()) >= 8

    def test_all_have_required_fields(self):
        reg = default_registry()
        for s in reg.get_all():
            assert s.strategy_id
            assert s.strategy_type in ("mean_reversion", "momentum", "trend", "breakout")
            assert len(s.symbols) > 0
            assert len(s.timeframes) > 0

    def test_usdjpy_d1_trend_only_trades_usdjpy(self):
        reg = default_registry()
        cfg = reg.get("usdjpy_d1_trend")
        assert cfg.symbols == ["USDJPY"]
        assert cfg.timeframes == ["D1"]
