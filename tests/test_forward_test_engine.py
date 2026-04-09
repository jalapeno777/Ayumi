"""Tests for the ForwardTestEngine — cTrader live data → PaperTrader integration."""

import threading
import time
from datetime import datetime, timedelta, timezone
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
def empty_credentials():
    return cTraderCredentials(
        host="",
        port=5211,
        use_ssl=True,
        sender_comp_id="",
        target_comp_id="cServer",
        sender_sub_id="QUOTE",
        username="",
        password="",
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
        evaluation_interval_sec=0.0,
        bar_period_minutes=60,
        stale_tick_threshold_sec=15.0,
        health_monitor_interval_sec=0.1,
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


def _make_ticks_in_period(
    symbol_id: int = 2,
    base_bid: float = 1.25000,
    base_ask: float = 1.25002,
    count: int = 10,
    period_minutes: int = 60,
) -> list[Tick]:
    base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    ticks = []
    for i in range(count):
        offset_sec = i * (period_minutes * 60 // count)
        ts = base_time + timedelta(seconds=offset_sec)
        ticks.append(
            Tick(
                symbol_id=symbol_id,
                bid=base_bid + i * 0.00001,
                ask=base_ask + i * 0.00001,
                timestamp=ts,
            )
        )
    return ticks


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
        assert cfg.evaluation_interval_sec == 1.0
        assert cfg.bar_period_minutes == 60

    def test_custom_values(self):
        cfg = ForwardTestConfig(
            symbol="EURUSD",
            starting_balance=10_000.0,
            min_confidence=0.60,
            evaluation_interval_sec=0.5,
            bar_period_minutes=15,
        )
        assert cfg.symbol == "EURUSD"
        assert cfg.starting_balance == 10_000.0
        assert cfg.min_confidence == 0.60
        assert cfg.evaluation_interval_sec == 0.5
        assert cfg.bar_period_minutes == 15


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
        assert health.evaluation_errors == 0
        assert health.reconnection_attempts == 0
        assert health.reconnection_successes == 0
        assert health.bars_built == 0


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
        with (
            patch.object(engine, "_build_components"),
            patch.object(engine, "_wire_callbacks"),
            patch.object(engine, "_start_market_feed", return_value=False),
        ):
            result = engine.start()
            assert result is False
            assert engine.is_running is False

    def test_start_success(self, engine):
        with (
            patch.object(engine, "_build_components"),
            patch.object(engine, "_wire_callbacks"),
            patch.object(engine, "_start_market_feed", return_value=True),
        ):
            result = engine.start()
            assert result is True
            assert engine.is_running is True
            engine.stop()

    def test_start_idempotent(self, engine):
        with (
            patch.object(engine, "_build_components"),
            patch.object(engine, "_wire_callbacks"),
            patch.object(engine, "_start_market_feed", return_value=True) as mock_feed,
        ):
            engine.start()
            engine.start()
            assert mock_feed.call_count == 1
            engine.stop()

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

    def test_on_tick_aggregates_into_bars(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999
        engine._config.bar_period_minutes = 60

        ticks = _make_ticks_in_period(count=10, period_minutes=60)
        for tick in ticks:
            engine._on_tick(tick)

        assert engine.health.ticks_received == 10
        current_bar = engine._current_bar.get("GBPUSD")
        assert current_bar is not None
        assert current_bar.open == pytest.approx(1.25001, abs=1e-5)
        assert current_bar.close == pytest.approx(1.25009, abs=1e-5)
        assert current_bar.high >= current_bar.open
        assert current_bar.low <= current_bar.open
        assert current_bar.volume == 10

    def test_on_tick_trims_bars_to_max(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.max_bars_per_symbol = 3
        engine._config.min_bars_for_evaluation = 999
        engine._config.bar_period_minutes = 1

        base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        for period in range(6):
            period_start = base_time + timedelta(minutes=period)
            for j in range(3):
                ts = period_start + timedelta(seconds=j * 20)
                tick = _make_tick(
                    bid=1.25000 + period * 0.001,
                    ask=1.25002 + period * 0.001,
                    timestamp=ts,
                )
                engine._on_tick(tick)

        assert len(engine._bars["GBPUSD"]) == 3

    def test_on_tick_updates_paper_trader_prices(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999

        mock_pt = MagicMock()
        engine._paper_trader = mock_pt

        tick = _make_tick(bid=1.25000, ask=1.25002)
        engine._on_tick(tick)

        mock_pt.update_market_prices.assert_called_with({"GBPUSD": 1.25001})

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
        engine._config.bar_period_minutes = 1
        engine._config.evaluation_interval_sec = 0.0

        base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        for period in range(5):
            period_start = base_time + timedelta(minutes=period)
            for j in range(3):
                ts = period_start + timedelta(seconds=j * 20)
                tick = _make_tick(
                    bid=1.25000 + period * 0.001,
                    ask=1.25002 + period * 0.001,
                    timestamp=ts,
                )
                engine._on_tick(tick)

        assert mock_strategy.evaluate.call_count >= 1

    def test_evaluate_strategies_skips_below_min_bars(
        self, engine, mock_strategy, gbpusd_symbol_info
    ):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 50
        engine._config.bar_period_minutes = 60

        ticks = _make_ticks_in_period(count=10, period_minutes=60)
        for tick in ticks:
            engine._on_tick(tick)

        mock_strategy.evaluate.assert_not_called()

    def test_evaluation_throttle(self, engine, mock_strategy, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 1
        engine._config.bar_period_minutes = 1
        engine._config.evaluation_interval_sec = 1.0

        base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        for period in range(3):
            period_start = base_time + timedelta(minutes=period)
            for j in range(3):
                ts = period_start + timedelta(seconds=j * 20)
                tick = _make_tick(
                    bid=1.25000 + period * 0.001,
                    ask=1.25002 + period * 0.001,
                    timestamp=ts,
                )
                engine._on_tick(tick)

        mock_strategy.evaluate.call_count <= 1

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
        engine._config.bar_period_minutes = 1
        engine._config.evaluation_interval_sec = 0.0

        engine._start_time = datetime.now(timezone.utc)

        base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        for period in range(5):
            period_start = base_time + timedelta(minutes=period)
            for j in range(3):
                ts = period_start + timedelta(seconds=j * 20)
                tick = _make_tick(
                    bid=1.25000 + period * 0.001,
                    ask=1.25002 + period * 0.001,
                    timestamp=ts,
                )
                engine._on_tick(tick)

        assert engine.health.ticks_received == 15
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


class TestBarConstruction:
    def test_bar_ohlc_from_ticks(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999
        engine._config.bar_period_minutes = 60

        base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        ticks = [
            Tick(symbol_id=2, bid=1.25000, ask=1.25002, timestamp=base_time),
            Tick(
                symbol_id=2,
                bid=1.25100,
                ask=1.25102,
                timestamp=base_time + timedelta(minutes=5),
            ),
            Tick(
                symbol_id=2,
                bid=1.24900,
                ask=1.24902,
                timestamp=base_time + timedelta(minutes=10),
            ),
            Tick(
                symbol_id=2,
                bid=1.25050,
                ask=1.25052,
                timestamp=base_time + timedelta(minutes=30),
            ),
        ]
        for tick in ticks:
            engine._on_tick(tick)

        finalized = engine._finalize_current_bar("GBPUSD")
        assert finalized is not None
        assert finalized.open == pytest.approx(1.25001, abs=1e-5)
        assert finalized.high == pytest.approx(1.25102, abs=1e-5)
        assert finalized.low == pytest.approx(1.24900, abs=1e-5)
        assert finalized.close == pytest.approx(1.25051, abs=1e-5)
        assert finalized.volume == 4

    def test_multiple_bar_periods(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999
        engine._config.bar_period_minutes = 60

        base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        for period in range(3):
            period_start = base_time + timedelta(hours=period)
            for j in range(5):
                ts = period_start + timedelta(minutes=j * 10)
                tick = Tick(
                    symbol_id=2,
                    bid=1.25000 + period * 0.01 + j * 0.0001,
                    ask=1.25002 + period * 0.01 + j * 0.0001,
                    timestamp=ts,
                )
                engine._on_tick(tick)

        assert len(engine._bars["GBPUSD"]) == 2
        assert engine._current_bar.get("GBPUSD") is not None

    def test_current_bar_updates_ohlc(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999
        engine._config.bar_period_minutes = 60

        base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        engine._on_tick(
            Tick(symbol_id=2, bid=1.25000, ask=1.25002, timestamp=base_time)
        )
        engine._on_tick(
            Tick(
                symbol_id=2,
                bid=1.26000,
                ask=1.26002,
                timestamp=base_time + timedelta(minutes=5),
            )
        )
        engine._on_tick(
            Tick(
                symbol_id=2,
                bid=1.24000,
                ask=1.24002,
                timestamp=base_time + timedelta(minutes=10),
            )
        )

        current = engine._current_bar.get("GBPUSD")
        assert current is not None
        assert current.high == pytest.approx(1.26002, abs=1e-5)
        assert current.low == pytest.approx(1.24000, abs=1e-5)
        assert current.volume == 3

    def test_bar_finalization_on_shutdown(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999
        engine._config.bar_period_minutes = 60

        ticks = _make_ticks_in_period(count=5, period_minutes=60)
        for tick in ticks:
            engine._on_tick(tick)

        assert engine._current_bar.get("GBPUSD") is not None
        bars_before = len(engine._bars.get("GBPUSD", []))

        engine._market_feed = MagicMock()
        mock_pt = MagicMock()
        mock_pt.get_stats.return_value = MagicMock(
            current_balance=100_000.0,
            trades_executed=0,
            starting_balance=100_000.0,
        )
        engine._paper_trader = mock_pt

        engine.stop()

        assert engine._current_bar.get("GBPUSD") is None
        assert len(engine._bars.get("GBPUSD", [])) == bars_before + 1

    def test_concurrent_tick_bar_safety(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 999
        engine._config.bar_period_minutes = 60

        errors = []

        def tick_worker(tick_id):
            try:
                for _ in range(100):
                    tick = _make_tick(
                        bid=1.25000 + tick_id * 0.00001,
                        ask=1.25002 + tick_id * 0.00001,
                    )
                    engine._on_tick(tick)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=tick_worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0
        assert engine.health.ticks_received == 400


class TestReconnection:
    def test_health_monitor_detects_stale_ticks(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.stale_tick_threshold_sec = 0.05
        engine._config.health_monitor_interval_sec = 0.05
        engine._config.reconnect_delay_sec = 0.01

        tick = _make_tick()
        engine._on_tick(tick)

        engine._health.last_tick_at = datetime.now(timezone.utc) - timedelta(seconds=30)

        with patch.object(engine, "_attempt_reconnect") as mock_reconnect:
            engine._check_connection_health()
            mock_reconnect.assert_called_once()

    def test_health_monitor_skips_when_healthy(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.stale_tick_threshold_sec = 60.0

        tick = _make_tick()
        engine._on_tick(tick)

        with patch.object(engine, "_attempt_reconnect") as mock_reconnect:
            engine._check_connection_health()
            mock_reconnect.assert_not_called()

    def test_reconnect_attempts_with_backoff(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.reconnect_delay_sec = 0.01
        engine._config.max_reconnect_delay_sec = 1.0
        engine._reconnect_delay = 0.01

        with patch.object(engine, "_start_market_feed", return_value=False):
            engine._attempt_reconnect()
            assert engine._health.reconnection_attempts == 1
            assert engine._reconnect_delay == pytest.approx(0.02, abs=1e-3)

            engine._attempt_reconnect()
            assert engine._health.reconnection_attempts == 2
            assert engine._reconnect_delay == pytest.approx(0.04, abs=1e-3)

    def test_reconnect_non_blocking(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.reconnect_delay_sec = 60.0

        with (
            patch.object(engine, "_start_market_feed", return_value=False),
            patch("adapters.ctrader.forward_test_engine.time.sleep") as mock_sleep,
        ):
            engine._attempt_reconnect()
            mock_sleep.assert_not_called()

    def test_reconnect_respects_backoff_timing(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.stale_tick_threshold_sec = 0.05
        engine._config.health_monitor_interval_sec = 0.05
        engine._config.reconnect_delay_sec = 0.1
        engine._config.max_reconnect_delay_sec = 1.0

        tick = _make_tick()
        engine._on_tick(tick)
        engine._health.last_tick_at = datetime.now(timezone.utc) - timedelta(seconds=30)

        with patch.object(engine, "_attempt_reconnect") as mock_reconnect:
            engine._check_connection_health()
            mock_reconnect.assert_called_once()

            mock_reconnect.reset_mock()
            engine._check_connection_health()
            mock_reconnect.assert_not_called()

    def test_reconnect_resets_delay_on_success(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.reconnect_delay_sec = 0.01

        engine._reconnect_delay = 0.1

        with patch.object(engine, "_start_market_feed", return_value=True):
            engine._attempt_reconnect()

        assert engine._health.reconnection_successes == 1
        assert engine._reconnect_delay == 0.01

    def test_health_monitor_loop_stops_on_signal(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.health_monitor_interval_sec = 0.01

        with patch.object(engine, "_attempt_reconnect"):
            engine._stop_health_monitor.set()
            engine._health_monitor_loop()

            engine._stop_health_monitor.clear()
            t = threading.Thread(target=engine._health_monitor_loop)
            t.start()
            time.sleep(0.05)
            engine._stop_health_monitor.set()
            t.join(timeout=2.0)
            assert not t.is_alive()


class TestCredentialValidation:
    def test_start_rejects_empty_host(self, engine, empty_credentials):
        empty_credentials.host = ""
        engine._credentials = empty_credentials

        result = engine._validate_credentials()
        assert result is False

    def test_start_rejects_empty_username(self, engine, empty_credentials):
        empty_credentials.host = "valid-host.com"
        empty_credentials.username = ""
        engine._credentials = empty_credentials

        result = engine._validate_credentials()
        assert result is False

    def test_start_rejects_empty_password(self, engine, empty_credentials):
        empty_credentials.host = "valid-host.com"
        empty_credentials.username = "12345"
        empty_credentials.password = ""
        engine._credentials = empty_credentials

        result = engine._validate_credentials()
        assert result is False

    def test_valid_credentials_pass(self, engine, quote_credentials):
        engine._credentials = quote_credentials

        result = engine._validate_credentials()
        assert result is True


class TestErrorHandling:
    def test_evaluation_error_tracked_in_health(self, engine, gbpusd_symbol_info):
        _setup_running_engine(engine, gbpusd_symbol_info)
        engine._config.min_bars_for_evaluation = 1
        engine._config.bar_period_minutes = 1
        engine._config.evaluation_interval_sec = 0.0

        mock_adapter = MagicMock()
        mock_adapter.evaluate_all_strategies.side_effect = RuntimeError("boom")
        engine._live_adapter = mock_adapter

        base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        for j in range(3):
            ts = base_time + timedelta(seconds=j * 20)
            tick = _make_tick(bid=1.25000, ask=1.25002, timestamp=ts)
            engine._on_tick(tick)

        assert engine.health.evaluation_errors > 0

    def test_evaluation_semaphore_prevents_concurrent_eval(
        self, engine, gbpusd_symbol_info
    ):
        _setup_running_engine(engine, gbpusd_symbol_info)

        assert engine._eval_semaphore.acquire(blocking=False)
        assert not engine._eval_semaphore.acquire(blocking=False)

        engine._eval_semaphore.release()
        assert engine._eval_semaphore.acquire(blocking=False)
        engine._eval_semaphore.release()


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
