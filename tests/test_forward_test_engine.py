"""Tests for the ForwardTestEngine — cTrader live data → PaperTrader integration."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from adapters.ctrader.forward_test_engine import (
    ForwardTestConfig,
    ForwardTestEngine,
    ForwardTestHealth,
)
from adapters.ctrader.market_data_feed import SymbolInfo, Tick
from adapters.ctrader.models import cTraderCredentials


@pytest.fixture
def quote_credentials():
    return cTraderCredentials(
        host="live-uk-eqx-01.p.c-trader.com",
        port=5211,
        use_ssl=True,
        sender_comp_id="test.sender",
        target_comp_id="cServer",
        sender_sub_id="QUOTE",
        username="12345",
        password="test_pass",
    )


@pytest.fixture
def mock_strategy():
    strategy = MagicMock()
    strategy.name = "test_strategy"
    strategy.evaluate.return_value = None
    return strategy


@pytest.fixture
def config():
    return ForwardTestConfig(
        symbol="GBPUSD",
        min_confidence=0.50,
        max_bars_per_symbol=100,
        min_bars_for_evaluation=5,
        log_dir="/tmp/test_forward_trades",
    )


@pytest.fixture
def engine(config, mock_strategy, quote_credentials):
    return ForwardTestEngine(
        config=config,
        strategies=[mock_strategy],
        credentials=quote_credentials,
    )


@pytest.fixture
def gbpusd_symbol_info():
    return SymbolInfo(symbol_id=2, name="GBP/USD")


def _make_tick(
    symbol_id: int = 2,
    bid: float = 1.25000,
    ask: float = 1.25002,
    timestamp: datetime | None = None,
) -> Tick:
    return Tick(
        symbol_id=symbol_id,
        bid=bid,
        ask=ask,
        timestamp=timestamp or datetime.now(timezone.utc),
    )


def _setup_running_engine(engine, gbpusd_symbol_info):
    engine._build_components()
    engine._trade_logger = MagicMock()
    engine._market_feed = MagicMock()
    engine._market_feed.symbols = {2: gbpusd_symbol_info}
    engine._market_feed.is_running = True
    engine._running = True


class TestForwardTestConfig:
    def test_defaults(self):
        cfg = ForwardTestConfig()
        assert cfg.symbol == "GBPUSD"
        assert cfg.starting_balance == 100_000.0
        assert cfg.min_confidence == 0.50
        assert cfg.max_bars_per_symbol == 500
        assert cfg.min_bars_for_evaluation == 50
        assert cfg.quote_host == "live-uk-eqx-01.p.c-trader.com"
        assert cfg.quote_port == 5211
        assert cfg.use_ssl is True
        assert cfg.live_mode is False

    def test_custom_values(self):
        cfg = ForwardTestConfig(
            symbol="EURUSD",
            starting_balance=10_000.0,
            min_confidence=0.60,
        )
        assert cfg.symbol == "EURUSD"
        assert cfg.starting_balance == 10_000.0
        assert cfg.min_confidence == 0.60


class TestForwardTestHealth:
    def test_defaults(self):
        health = ForwardTestHealth()
        assert health.connected is False
        assert health.last_tick_at is None
        assert health.ticks_received == 0
        assert health.ticks_per_second == 0.0
        assert health.signals_generated == 0
        assert health.signals_traded == 0
        assert health.signals_rejected == 0
        assert health.uptime_sec == 0.0


class TestForwardTestEngine:
    def test_initialization(self, engine, config):
        assert engine.is_running is False
        assert engine.paper_trader is None

    def test_build_components_creates_paper_trader(self, engine):
        engine._build_components()
        assert engine.paper_trader is not None
        assert engine._live_adapter is not None
        assert engine._trade_logger is not None

    def test_start_without_connection_returns_false(self, engine):
        with patch.object(engine, "_build_components"), patch.object(
            engine, "_wire_callbacks"
        ), patch.object(engine, "_start_market_feed", return_value=False):
            result = engine.start()
            assert result is False
            assert engine.is_running is False

    def test_start_success(self, engine):
        with patch.object(engine, "_build_components"), patch.object(
            engine, "_wire_callbacks"
        ), patch.object(engine, "_start_market_feed", return_value=True):
            result = engine.start()
            assert result is True
            assert engine.is_running is True

    def test_start_idempotent(self, engine):
        with patch.object(engine, "_build_components"), patch.object(
            engine, "_wire_callbacks"
        ), patch.object(engine, "_start_market_feed", return_value=True) as mock_feed:
            engine.start()
            engine.start()
            assert mock_feed.call_count == 1

    def test_stop(self, engine):
        engine._market_feed = MagicMock()
        engine._paper_trader = MagicMock()
        engine._paper_trader.get_stats.return_value = MagicMock(
            current_balance=100_000.0,
            trades_executed=0,
            starting_balance=100_000.0,
        )
        engine._running = True

        engine.stop()

        assert engine.is_running is False
        engine._market_feed.stop.assert_called_once()

    def test_stop_when_not_running(self, engine):
        engine.stop()
        assert engine.is_running is False

    def test_on_tick_ignores_unknown_symbol(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)

        tick = _make_tick(symbol_id=99, bid=1.0, ask=1.0)
        engine._on_tick(tick)

        assert engine.health.ticks_received == 1
        assert len(engine._bars) == 0

    def test_on_tick_accumulates_bars(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999

        for i in range(10):
            tick = _make_tick(bid=1.25000 + i * 0.00001, ask=1.25002 + i * 0.00001)
            engine._on_tick(tick)

        assert engine.health.ticks_received == 10
        assert "GBPUSD" in engine._bars
        assert len(engine._bars["GBPUSD"]) == 10

    def test_on_tick_trims_bars_to_max(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.max_bars_per_symbol = 5
        engine._config.min_bars_for_evaluation = 999

        for i in range(10):
            tick = _make_tick(bid=1.25000 + i * 0.00001, ask=1.25002 + i * 0.00001)
            engine._on_tick(tick)

        assert len(engine._bars["GBPUSD"]) == 5

    def test_on_tick_updates_paper_trader_prices(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999

        mock_pt = MagicMock()
        engine._paper_trader = mock_pt

        tick = _make_tick(bid=1.25000, ask=1.25002)
        engine._on_tick(tick)

        mock_pt.update_market_prices.assert_called_with(
            {"GBPUSD": 1.25001}
        )

    def test_on_tick_updates_health_last_tick_at(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999

        before = datetime.now(timezone.utc)
        tick = _make_tick()
        engine._on_tick(tick)

        assert engine.health.last_tick_at is not None
        assert engine.health.last_tick_at >= before

    def test_on_tick_calculates_tick_rate(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999

        for _ in range(5):
            tick = _make_tick()
            engine._on_tick(tick)

        assert engine.health.ticks_received == 5
        assert engine.health.ticks_per_second > 0

    def test_evaluate_strategies_called_when_enough_bars(
        self, engine, mock_strategy, gbpusd_symbol_info
    ):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 3

        for i in range(5):
            tick = _make_tick(bid=1.25000 + i * 0.00001, ask=1.25002 + i * 0.00001)
            engine._on_tick(tick)

        assert mock_strategy.evaluate.call_count >= 2

    def test_evaluate_strategies_skips_below_min_bars(
        self, engine, mock_strategy, gbpusd_symbol_info
    ):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 50

        for i in range(10):
            tick = _make_tick(bid=1.25000 + i * 0.00001, ask=1.25002 + i * 0.00001)
            engine._on_tick(tick)

        mock_strategy.evaluate.assert_not_called()

    def test_register_callback(self, engine):
        cb = MagicMock()
        engine.register_callback("on_signal_traded", cb)
        assert len(engine._callbacks) == 1

    def test_get_stats(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)

        mock_pt = MagicMock()
        mock_pt.get_stats.return_value = MagicMock(
            current_balance=100_000.0,
            trades_executed=5,
            trades_rejected=1,
            signals_blocked_by_risk=2,
            realized_pnl=500.0,
            unrealized_pnl=200.0,
            starting_balance=100_000.0,
        )
        engine._paper_trader = mock_pt

        stats = engine.get_stats()

        assert "health" in stats
        assert "trading" in stats
        assert stats["health"]["connected"] is True
        assert stats["trading"]["trades_executed"] == 5

    def test_health_reflects_disconnected(self, engine):
        engine._build_components()
        engine._market_feed = None
        engine._running = True

        health = engine.health
        assert health.connected is False

    def test_resolve_feed_symbol_name_with_slash(self, engine):
        engine._market_feed = MagicMock()
        engine._market_feed.name_to_id = {"GBP/USD": 2, "EUR/USD": 1}

        result = engine._resolve_feed_symbol_name("GBPUSD")
        assert result == "GBP/USD"

    def test_resolve_feed_symbol_name_no_match(self, engine):
        engine._market_feed = MagicMock()
        engine._market_feed.name_to_id = {"EUR/USD": 1}

        result = engine._resolve_feed_symbol_name("GBPUSD")
        assert result is None

    def test_full_lifecycle(self, engine, mock_strategy, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._market_feed.start.return_value = True
        engine._config.min_bars_for_evaluation = 3

        engine._start_time = datetime.now(timezone.utc)

        for i in range(5):
            tick = _make_tick(bid=1.25000 + i * 0.00001, ask=1.25002 + i * 0.00001)
            engine._on_tick(tick)

        assert engine.health.ticks_received == 5
        assert engine.paper_trader is not None

        mock_pt = MagicMock()
        mock_pt.get_stats.return_value = MagicMock(
            current_balance=100_000.0,
            trades_executed=0,
            starting_balance=100_000.0,
        )
        engine._paper_trader = mock_pt
        engine.stop()

        assert engine.is_running is False
        assert engine.health.uptime_sec > 0


class TestForwardTestEngineCallbacks:
    def test_on_trade_executed_callback(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)

        cb = MagicMock()
        engine.register_callback("on_trade_executed", cb)

        result = MagicMock()
        result.order = MagicMock()
        result.position = MagicMock()
        engine._on_trade_executed(result)

        cb.assert_called_once_with(result)

    def test_on_position_closed_callback(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)

        cb = MagicMock()
        engine.register_callback("on_position_closed", cb)

        position = MagicMock()
        engine._on_position_closed(position)

        cb.assert_called_once_with(position)

    def test_callback_error_does_not_crash(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)

        bad_cb = MagicMock(side_effect=RuntimeError("boom"))
        engine.register_callback("on_trade_executed", bad_cb)

        result = MagicMock()
        result.order = MagicMock()
        result.position = MagicMock()
        engine._on_trade_executed(result)

        bad_cb.assert_called_once()
