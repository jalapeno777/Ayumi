"""Tests for multi-symbol forward test engine (AYU-BUILD-003)."""

import pytest  # noqa: I001
from datetime import datetime, timezone
from unittest.mock import MagicMock

from adapters.ctrader.forward_test_engine import ForwardTestConfig, ForwardTestEngine


# ── AC1: Multi-symbol config validation ──────────────────────────────────────


class TestForwardTestConfig:
    def test_single_symbol_defaults_to_list(self):
        cfg = ForwardTestConfig(symbol="GBPUSD")
        assert cfg.symbols == ["GBPUSD"]

    def test_explicit_symbols_list(self):
        cfg = ForwardTestConfig(symbol="GBPUSD", symbols=["GBPUSD", "USDJPY"])
        assert cfg.symbols == ["GBPUSD", "USDJPY"]

    def test_backward_compat_symbol_field(self):
        cfg = ForwardTestConfig(symbol="EURUSD")
        assert cfg.symbol == "EURUSD"
        assert cfg.symbols == ["EURUSD"]


# ── AC5: H4 in allowed timeframes ────────────────────────────────────────────


class TestAllowedTimeframes:
    def test_h4_in_allowed(self):
        assert 240 in ForwardTestEngine._ALLOWED_TIMEFRAMES

    def test_h1_still_allowed(self):
        assert 60 in ForwardTestEngine._ALLOWED_TIMEFRAMES

    def test_m15_still_allowed(self):
        assert 15 in ForwardTestEngine._ALLOWED_TIMEFRAMES

    def test_invalid_tf_rejected(self):
        cfg = ForwardTestConfig(symbol="GBPUSD", bar_period_minutes=30)
        with pytest.raises(AssertionError, match="not in allowed whitelist"):
            ForwardTestEngine(config=cfg, strategies=[])

    def test_h4_accepted(self):
        cfg = ForwardTestConfig(symbol="GBPUSD", bar_period_minutes=240)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        assert engine is not None


# ── AC2/AC3: Tick routing and bar building ───────────────────────────────────


def _make_tick(symbol_id=1, bid=1.0, ask=1.0001, timestamp=None):
    from adapters.ctrader.market_data_feed import Tick

    return Tick(
        symbol_id=symbol_id,
        bid=bid,
        ask=ask,
        timestamp=timestamp or datetime.now(timezone.utc),
    )


def _make_engine(config, strategies=None):
    engine = ForwardTestEngine(config=config, strategies=strategies or [])
    engine._market_feed = MagicMock()
    engine._market_feed.is_running = True
    engine._market_feed.symbols = {
        1: type("SymInfo", (), {"name": "GBP/USD"})(),
        2: type("SymInfo", (), {"name": "USD/JPY"})(),
    }
    engine._market_feed.name_to_id = {"GBP/USD": 1, "USD/JPY": 2}
    return engine


class TestMultiSymbolTickRouting:
    def test_tick_routes_to_correct_symbol(self):
        cfg = ForwardTestConfig(symbol="GBPUSD", symbols=["GBPUSD", "USDJPY"])
        engine = _make_engine(cfg)

        # GBPUSD tick should resolve
        tick = _make_tick(symbol_id=1)
        assert engine._resolve_symbol_name(tick) == "GBPUSD"

        # USDJPY tick should resolve
        tick2 = _make_tick(symbol_id=2)
        assert engine._resolve_symbol_name(tick2) == "USDJPY"

    def test_tick_from_unconfigured_symbol_ignored(self):
        cfg = ForwardTestConfig(symbol="GBPUSD", symbols=["GBPUSD"])
        engine = _make_engine(cfg)

        tick = _make_tick(symbol_id=2)  # USDJPY
        assert engine._resolve_symbol_name(tick) is None


# ── AC4/AC9: Strategy-pair matching ──────────────────────────────────────────


class TestStrategyPairMatching:
    def test_strategy_only_evaluates_registered_pairs(self):
        from adapters.ctrader.signal_adapter import cTraderLiveAdapter
        from backtest.strategies import ISignalStrategy

        # Strategy that declares symbols
        strat = MagicMock(spec=ISignalStrategy)
        strat.name = "TestStrat"
        strat.symbols = ["GBPUSD"]

        adapter = cTraderLiveAdapter(
            paper_trader=MagicMock(),
            strategies=[strat],
            symbols=["GBPUSD", "USDJPY"],
        )

        # Should have adapter for GBPUSD but not USDJPY
        assert adapter.get_adapter("TestStrat", "GBPUSD") is not None
        assert adapter.get_adapter("TestStrat", "USDJPY") is None

    def test_strategy_without_symbols_attr_creates_all(self):
        from adapters.ctrader.signal_adapter import cTraderLiveAdapter
        from backtest.strategies import ISignalStrategy

        strat = MagicMock(spec=ISignalStrategy)
        strat.name = "UniversalStrat"
        # No .symbols attribute — should create for all

        adapter = cTraderLiveAdapter(
            paper_trader=MagicMock(),
            strategies=[strat],
            symbols=["GBPUSD", "USDJPY"],
        )

        assert adapter.get_adapter("UniversalStrat", "GBPUSD") is not None
        assert adapter.get_adapter("UniversalStrat", "USDJPY") is not None


# ── AC7: Regression — single GBPUSD still works ─────────────────────────────


class TestRegressionSingleSymbol:
    def test_single_gbpusd_config(self):
        cfg = ForwardTestConfig(symbol="GBPUSD")
        engine = ForwardTestEngine(config=cfg, strategies=[])
        assert engine._config.symbols == ["GBPUSD"]

    def test_single_symbol_tick_routing(self):
        cfg = ForwardTestConfig(symbol="GBPUSD")
        engine = _make_engine(cfg)

        tick = _make_tick(symbol_id=1)
        assert engine._resolve_symbol_name(tick) == "GBPUSD"

    def test_bar_key_format(self):
        assert ForwardTestEngine._bar_key("GBPUSD", 60) == "GBPUSD:60"
        assert ForwardTestEngine._bar_key("USDJPY", 15) == "USDJPY:15"
