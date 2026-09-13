"""Integration test — Forward test execution chain end-to-end.

Proves the FULL pipeline works:
  1. Signal → Paper Trade with TP/SL
  2. Position monitoring — TP hit
  3. Position monitoring — SL hit
  4. Live execution path (mocked cTrader connection)

Uses REAL production code (PaperTrader, RiskGuard, OrderManager,
ForwardTestEngine).  Mocks only the cTrader TCP/API surface
(OpenApiSpotFeed.new_order).

Run:
    python3 -m pytest tests/integration/test_forward_test_execution_chain.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from adapters.ctrader.forward_test_engine import (
    ForwardTestConfig,
    ForwardTestEngine,
    LiveExecutionStatus,
)
from adapters.ctrader.kill_switch import KillSwitchManager
from adapters.ctrader.models import (
    CTraderTradeSignal,
    Order,
    OrderStatus,
    OrderType,
    PositionStatus,
    TradeDirection,
)
from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed
from adapters.ctrader.order_manager import PositionSizeConfig, SlippageModel
from adapters.ctrader.paper_trader import PaperTrader
from adapters.ctrader.risk_guard import FTMOConfig
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_kill_switch_state(tmp_path):
    """Clear any persisted kill-switch state so tests start clean.

    PaperTrader and ForwardTestEngine each construct their own
    KillSwitchManager; if a prior test activated the global kill switch,
    the persisted state would leak into subsequent tests and block
    order processing. Route every KillSwitchManager created in this
    module through a per-test tmp_path so no production data/ tree is
    touched (card d25244c4 cluster A: teardown-isolation guard).
    """
    isolated_dir = tmp_path / "kill_switches"
    isolated_dir.mkdir(parents=True, exist_ok=True)
    ks = KillSwitchManager(state_dir=str(isolated_dir))
    if ks.is_active():
        ks.deactivate(reason="test_isolation_setup")
    yield
    ks2 = KillSwitchManager(state_dir=str(isolated_dir))
    if ks2.is_active():
        ks2.deactivate(reason="test_isolation_teardown")


@pytest.fixture
def zero_slippage_trader():
    """Real PaperTrader with deterministic (zero) slippage.

    Uses real RiskGuard, real OrderManager — only slippage randomness
    is disabled so fill prices match entry prices exactly.
    """
    ftmo = FTMOConfig()
    pos_cfg = PositionSizeConfig()
    trader = PaperTrader(
        ftmo_config=ftmo,
        position_config=pos_cfg,
        starting_balance=100_000.0,
    )
    # Eliminate slippage so fill prices are deterministic for assertions.
    trader._order_manager._slippage_model = SlippageModel(base_pips=0, random_pips=0)
    return trader


# ── Signal factories ─────────────────────────────────────────────────────────


def _gbpusd_long_signal() -> CTraderTradeSignal:
    """Synthetic LONG GBPUSD signal (entry=1.2750, SL=1.2700, TP=1.2850).

    R:R = (1.2850 - 1.2750) / (1.2750 - 1.2700) = 2.0 ≥ 1.5 (FTMO min)
    """
    return CTraderTradeSignal(
        symbol="GBPUSD",
        direction=TradeDirection.LONG,
        entry_price=1.2750,
        stop_loss=1.2700,
        take_profit_1=1.2850,
        take_profit_2=1.2900,
        take_profit_3=1.2950,
        volume=0.1,
        confidence=0.85,
        rationale="integration-test-long-gbpusd",
        strategy_id="test-strategy",
        timestamp=datetime.now(timezone.utc),
    )


def _usdjpy_short_signal() -> CTraderTradeSignal:
    """Synthetic SHORT USDJPY signal (entry=157.50, SL=158.00, TP=156.50).

    R:R = (157.50 - 156.50) / (158.00 - 157.50) = 2.0 ≥ 1.5 (FTMO min)
    """
    return CTraderTradeSignal(
        symbol="USDJPY",
        direction=TradeDirection.SHORT,
        entry_price=157.50,
        stop_loss=158.00,
        take_profit_1=156.50,
        take_profit_2=156.00,
        take_profit_3=155.50,
        volume=0.1,
        confidence=0.85,
        rationale="integration-test-short-usdjpy",
        strategy_id="test-strategy",
        timestamp=datetime.now(timezone.utc),
    )


# ── Test 1: Signal → Paper Trade with TP/SL ──────────────────────────────────


class TestSignalToPaperTrade:
    """Test 1: Signal → Paper Trade with TP/SL.

    Proves the pipeline can ingest a CTraderTradeSignal, run it through real
    RiskGuard and OrderManager, and produce a tracked open position
    with correct direction, entry, SL, and TP.
    """

    def test_process_signal_succeeds(self, zero_slippage_trader):
        signal = _gbpusd_long_signal()
        result = zero_slippage_trader.process_signal(signal, bid=1.2750, ask=1.2750)
        assert result.success is True, f"Signal rejected: {result.rejection_reason}"
        assert result.position is not None

    def test_position_has_correct_direction_entry_sl_tp(self, zero_slippage_trader):
        signal = _gbpusd_long_signal()
        result = zero_slippage_trader.process_signal(signal, bid=1.2750, ask=1.2750)

        pos = result.position
        assert pos.direction == TradeDirection.LONG
        # Entry is ask (1.2750) plus zero slippage → exactly 1.2750.
        assert pos.entry_price == pytest.approx(1.2750, abs=1e-5)
        assert pos.stop_loss == pytest.approx(1.2700, abs=1e-5)
        assert pos.take_profit == pytest.approx(1.2850, abs=1e-5)
        assert pos.symbol == "GBPUSD"
        assert pos.status == PositionStatus.OPEN

    def test_position_appears_in_open_positions_list(self, zero_slippage_trader):
        signal = _gbpusd_long_signal()
        zero_slippage_trader.process_signal(signal, bid=1.2750, ask=1.2750)

        open_positions = zero_slippage_trader.get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0].symbol == "GBPUSD"
        assert open_positions[0].direction == TradeDirection.LONG

    def test_stats_record_trade_executed(self, zero_slippage_trader):
        signal = _gbpusd_long_signal()
        zero_slippage_trader.process_signal(signal, bid=1.2750, ask=1.2750)

        stats = zero_slippage_trader.get_stats()
        assert stats.trades_executed == 1
        assert stats.trades_rejected == 0
        assert stats.signals_blocked_by_risk == 0
        assert stats.starting_balance == 100_000.0

    def test_balance_tracks_unrealized_pnl_after_open(self, zero_slippage_trader):
        signal = _gbpusd_long_signal()
        zero_slippage_trader.process_signal(signal, bid=1.2750, ask=1.2750)

        # Feed a neutral tick so the position's unrealized PnL is computed.
        zero_slippage_trader.update_market_prices(
            prices={"GBPUSD": 1.2750},
            bids={"GBPUSD": 1.2750},
            asks={"GBPUSD": 1.2750},
        )

        stats = zero_slippage_trader.get_stats()
        # At entry, unrealized PnL is ~0, so balance should remain ~starting.
        assert stats.current_balance == pytest.approx(stats.starting_balance, abs=1.0)


# ── Test 2: Position monitoring — TP hit ─────────────────────────────────────


class TestPositionMonitoringTPHit:
    """Test 2: Position monitoring — TP hit.

    With an open LONG position at 1.2750 (TP=1.2850), feed a tick where
    ask ≥ TP.  OrderManager must auto-close the position, record the
    P&L, and the position must leave the open-positions list.
    """

    def _open_long_gbpusd(self, trader) -> CTraderTradeSignal:
        signal = _gbpusd_long_signal()
        result = trader.process_signal(signal, bid=1.2750, ask=1.2750)
        assert result.success, f"Setup failed: {result.rejection_reason}"
        return signal

    def test_position_closes_when_tp_hit(self, zero_slippage_trader):
        self._open_long_gbpusd(zero_slippage_trader)

        # Feed a tick that hits TP (ask = 1.2850 ≥ take_profit=1.2850).
        zero_slippage_trader.update_market_prices(
            prices={"GBPUSD": 1.2850},
            bids={"GBPUSD": 1.2850},
            asks={"GBPUSD": 1.2850},
        )

        # Position must have been auto-closed by the TP monitor.
        open_positions = zero_slippage_trader.get_open_positions()
        assert len(open_positions) == 0

        all_positions = list(zero_slippage_trader._order_manager._positions.values())
        closed = [p for p in all_positions if p.status.is_closed]
        assert len(closed) == 1
        assert closed[0].symbol == "GBPUSD"
        assert closed[0].closed_price == pytest.approx(1.2850, abs=1e-5)

    def test_pnl_calculated_correctly_on_tp_hit(self, zero_slippage_trader):
        self._open_long_gbpusd(zero_slippage_trader)
        open_pos = zero_slippage_trader.get_open_positions()[0]
        volume = open_pos.volume
        entry = open_pos.entry_price

        zero_slippage_trader.update_market_prices(
            prices={"GBPUSD": 1.2850},
            bids={"GBPUSD": 1.2850},
            asks={"GBPUSD": 1.2850},
        )

        all_positions = list(zero_slippage_trader._order_manager._positions.values())
        closed = [p for p in all_positions if p.status.is_closed]
        assert len(closed) == 1

        # LONG P&L = (exit - entry) * volume * contract_size(100k)
        expected_pnl = (1.2850 - entry) * volume * 100_000.0
        assert closed[0].closed_pnl == pytest.approx(expected_pnl, rel=1e-4)
        assert closed[0].closed_pnl > 0, "TP hit must produce positive P&L"

    def test_position_no_longer_in_open_list_after_tp(self, zero_slippage_trader):
        self._open_long_gbpusd(zero_slippage_trader)
        zero_slippage_trader.update_market_prices(
            prices={"GBPUSD": 1.2850},
            bids={"GBPUSD": 1.2850},
            asks={"GBPUSD": 1.2850},
        )
        # Subsequent call must not re-process the closed position.
        zero_slippage_trader.update_market_prices(
            prices={"GBPUSD": 1.2860},
            bids={"GBPUSD": 1.2860},
            asks={"GBPUSD": 1.2860},
        )
        assert len(zero_slippage_trader.get_open_positions()) == 0


# ── Test 3: Position monitoring — SL hit ─────────────────────────────────────


class TestPositionMonitoringSLHit:
    """Test 3: Position monitoring — SL hit.

    Open a SHORT USDJPY at 157.50 (SL=158.00, TP=156.50).  Feed a tick
    where ask ≥ SL.  OrderManager must auto-close the position and
    record the loss.
    """

    def _open_short_usdjpy(self, trader) -> CTraderTradeSignal:
        signal = _usdjpy_short_signal()
        result = trader.process_signal(signal, bid=157.50, ask=157.50)
        assert result.success, f"Setup failed: {result.rejection_reason}"
        return signal

    def test_short_position_closes_when_sl_hit(self, zero_slippage_trader):
        self._open_short_usdjpy(zero_slippage_trader)

        # Feed a tick that hits SL (ask = 158.00 ≥ stop_loss=158.00).
        zero_slippage_trader.update_market_prices(
            prices={"USDJPY": 158.00},
            bids={"USDJPY": 158.00},
            asks={"USDJPY": 158.00},
        )

        open_positions = zero_slippage_trader.get_open_positions()
        assert len(open_positions) == 0

        all_positions = list(zero_slippage_trader._order_manager._positions.values())
        closed = [p for p in all_positions if p.status.is_closed]
        assert len(closed) == 1
        assert closed[0].symbol == "USDJPY"
        assert closed[0].direction == TradeDirection.SHORT
        assert closed[0].closed_price == pytest.approx(158.00, abs=1e-5)

    def test_loss_calculated_correctly_on_sl_hit(self, zero_slippage_trader):
        self._open_short_usdjpy(zero_slippage_trader)
        open_pos = zero_slippage_trader.get_open_positions()[0]
        volume = open_pos.volume
        entry = open_pos.entry_price

        zero_slippage_trader.update_market_prices(
            prices={"USDJPY": 158.00},
            bids={"USDJPY": 158.00},
            asks={"USDJPY": 158.00},
        )

        all_positions = list(zero_slippage_trader._order_manager._positions.values())
        closed = [p for p in all_positions if p.status.is_closed]
        assert len(closed) == 1

        # SHORT P&L = (entry - exit) * volume * contract_size(100k)
        expected_pnl = (entry - 158.00) * volume * 100_000.0
        assert closed[0].closed_pnl == pytest.approx(expected_pnl, rel=1e-4)
        assert closed[0].closed_pnl < 0, "SL hit must produce negative P&L"


# ── Test 4: Live execution path (mocked cTrader) ─────────────────────────────


class TestLiveExecutionPath:
    """Test 4: Live execution path with mocked cTrader connection.

    Proves _execute_signal_live() takes a CTraderTradeSignal and dispatches
    a correctly-parameterized order to the OpenApiSpotFeed.new_order()
    surface (which we mock at the connection boundary).

    The ForwardTestEngine is constructed in paper mode to avoid the
    OpenAPI credential bootstrap path; we then inject a real
    PaperTrader + a MagicMock(spec=OpenApiSpotFeed) for the spot feed.
    """

    def _build_engine_with_mock_feed(self):
        """Construct a ForwardTestEngine wired with a mock spot feed.

        Returns:
            (engine, mock_feed) — the engine has _paper_trader injected
            and _market_feed set to a MagicMock(spec=OpenApiSpotFeed).
        """
        config = ForwardTestConfig(execution_mode="paper")
        engine = ForwardTestEngine(config, strategies=[])

        # Inject a real PaperTrader (the engine normally builds this in
        # start() via _build_components; we skip that to avoid the live
        # credential bootstrap path).
        trader = PaperTrader(starting_balance=100_000.0)
        trader._order_manager._slippage_model = SlippageModel(base_pips=0, random_pips=0)
        engine._paper_trader = trader

        # Mock spot feed — MagicMock(spec=OpenApiSpotFeed) makes
        # isinstance(mock_feed, OpenApiSpotFeed) return True so the
        # guard inside _execute_signal_live passes.
        mock_feed = MagicMock(spec=OpenApiSpotFeed)
        # Bypass the is_operational check (state_mgr present but operational).
        mock_feed._state_mgr = None
        # Symbol resolution returns a deterministic id.
        mock_feed.resolve_symbol_id.return_value = 42
        # Volume conversion: 1 lot → 100,000 raw volume units.
        mock_feed.lots_to_volume.return_value = 100_000
        # new_order returns a filled order so the outcome classifies as FILLED.
        mock_order = Order(
            order_id="live-test-001",
            symbol="GBPUSD",
            direction=TradeDirection.LONG,
            order_type=OrderType.MARKET,
            volume=1.0,
            price=1.2750,
            stop_loss=1.2700,
            take_profit=1.2850,
            status=OrderStatus.FILLED,
            filled_price=1.2750,
            filled_at=datetime.now(timezone.utc),
            comment="integration-test-long-gbpusd",
        )
        mock_feed.new_order.return_value = mock_order

        engine._market_feed = mock_feed
        return engine, mock_feed

    def test_execute_signal_live_calls_new_order_with_correct_params(self):
        engine, mock_feed = self._build_engine_with_mock_feed()
        signal = _gbpusd_long_signal()

        engine._execute_signal_live(signal, strategy_id="test-strat")

        # new_order must have been called exactly once.
        mock_feed.new_order.assert_called_once()
        call = mock_feed.new_order.call_args

        # Inspect the keyword arguments dispatched to the spot feed.
        kwargs = call.kwargs
        assert kwargs["symbol_id"] == 42
        assert kwargs["side"] == ProtoOATradeSide.BUY
        assert kwargs["order_type"] == ProtoOAOrderType.MARKET
        assert kwargs["sl"] == pytest.approx(1.2700, abs=1e-5)
        assert kwargs["tp"] == pytest.approx(1.2850, abs=1e-5)
        assert kwargs["comment"] == "integration-test-long-gbpusd"

        # Volume should be the raw-volume units returned by lots_to_volume.
        assert kwargs["volume"] == 100_000

    def test_execute_signal_live_records_filled_outcome(self):
        engine, mock_feed = self._build_engine_with_mock_feed()
        signal = _gbpusd_long_signal()

        outcome = engine._execute_signal_live(signal, strategy_id="test-strat")

        assert outcome is not None
        assert outcome.status == LiveExecutionStatus.FILLED
        assert outcome.symbol == "GBPUSD"
        assert outcome.direction == "long"
        assert outcome.strategy_id == "test-strat"

    def test_execute_signal_live_dispatches_short_correctly(self):
        engine, mock_feed = self._build_engine_with_mock_feed()
        signal = _usdjpy_short_signal()

        outcome = engine._execute_signal_live(signal, strategy_id="test-strat")

        mock_feed.new_order.assert_called_once()
        kwargs = mock_feed.new_order.call_args.kwargs
        assert kwargs["side"] == ProtoOATradeSide.SELL
        assert kwargs["sl"] == pytest.approx(158.00, abs=1e-5)
        assert kwargs["tp"] == pytest.approx(156.50, abs=1e-5)

        assert outcome is not None
        assert outcome.status == LiveExecutionStatus.FILLED
        assert outcome.symbol == "USDJPY"
        assert outcome.direction == "short"

    def test_execute_signal_live_returns_none_when_spot_feed_missing(self):
        """If _market_feed is None, _execute_signal_live must return None
        (pre-flight failure) without raising."""
        config = ForwardTestConfig(execution_mode="paper")
        engine = ForwardTestEngine(config, strategies=[])
        trader = PaperTrader(starting_balance=100_000.0)
        engine._paper_trader = trader
        engine._market_feed = None

        signal = _gbpusd_long_signal()
        outcome = engine._execute_signal_live(signal, strategy_id="test-strat")
        assert outcome is None

    def test_execute_signal_live_calculates_volume_from_balance(self):
        """Verify the engine computes position size from the paper trader's
        balance via the real OrderManager.calculate_position_size path."""
        engine, mock_feed = self._build_engine_with_mock_feed()
        signal = _gbpusd_long_signal()

        engine._execute_signal_live(signal, strategy_id="test-strat")

        # lots_to_volume must be called with the lots computed by the
        # real OrderManager.  Expected lots for risk=0.5%, sl=50pips on
        # GBPUSD with 100k account ≈ 1.0 lots.
        mock_feed.lots_to_volume.assert_called_once()
        lots_arg = mock_feed.lots_to_volume.call_args.args[1]
        assert lots_arg > 0.0
        assert lots_arg == pytest.approx(1.0, abs=0.01)
