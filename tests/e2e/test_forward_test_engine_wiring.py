"""Tests for T4 — wire ``OpenApiSpotFeed`` into ``PaperTrader`` as ``api_client``.

After T4:

* ``engine._build_components`` (with valid live credentials) creates a
  ``cTraderAPIClient`` wrapper and passes it to ``PaperTrader``.
* ``PaperTrader._live_mode_enabled`` flips True (so OrderManager takes
  the live execution branch if it ever fires).
* The OrderManager constructed inside ``PaperTrader.__init__`` receives
  the same ``api_client`` reference (so ``_wire_live_callbacks`` runs).
* ``_calculate_live_volume`` works even when ``self._paper_trader`` is
  None (the live-only path), because the helper falls back to
  ``PositionSizeConfig`` defaults.
* ``_execute_signal_live`` returns a non-None outcome for a well-formed
  signal even when ``self._paper_trader`` is set to ``None`` after the
  engine has been built.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from adapters.ctrader.api_client import cTraderAPIClient
from adapters.ctrader.forward_test_engine import (
    ForwardTestConfig,
    ForwardTestEngine,
    LiveExecutionStatus,
)
from adapters.ctrader.models import (
    CTraderTradeSignal,
    Order,
    OrderStatus,
    TradeDirection,
)
from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed


def _live_creds_dict() -> dict:
    return {
        "ctid_account_id": 12345,
        "client_id": "test_client",
        "client_secret": "***",
        "access_token": "***",
        "refresh_token": None,
        "host": "demo.ctraderapi.com",
        "port": 5035,
        "token_lifecycle": MagicMock(),
    }


def _make_signal() -> CTraderTradeSignal:
    return CTraderTradeSignal(
        symbol="EURUSD",
        direction=TradeDirection.LONG,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        take_profit_3=1.1150,
        volume=0.1,
        confidence=0.8,
        rationale="unit_test",
        strategy_id="test_strategy",
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def live_engine(tmp_path):
    """Build a forward test engine with live mode, mocked live creds, and isolated kill switch state."""
    from adapters.ctrader.kill_switch import KillSwitchManager

    isolated_dir = tmp_path / "kill_switches"
    isolated_dir.mkdir(parents=True, exist_ok=True)
    cfg = ForwardTestConfig(live_mode=True, starting_balance=10000.0)
    engine = ForwardTestEngine(config=cfg, strategies=[])
    engine._kill_switch = KillSwitchManager(state_dir=str(isolated_dir))
    return engine


class TestOpenApiSpotFeedIsReachableFromPaperTrader:
    """Reachable means ``api_client`` is no longer None in live mode."""

    def test_engine_api_client_is_none_in_paper_mode(self):
        """Paper mode must NOT touch the OpenAPI env vars or build a feed."""
        cfg = ForwardTestConfig(live_mode=False)
        engine = ForwardTestEngine(config=cfg, strategies=[])
        engine._build_components()
        assert engine._api_client is None
        assert engine._market_feed is None
        assert engine._paper_trader is not None
        # PaperTrader also has its _api_client=None
        assert engine._paper_trader._api_client is None
        # PaperTrader.is_live_mode is False
        assert engine._paper_trader.is_live_mode is False

    def test_engine_api_client_is_cTraderAPIClient_in_live_mode(self, live_engine):
        """In live mode, engine._api_client is a cTraderAPIClient instance."""
        with patch.object(live_engine, "_build_live_credentials", return_value=_live_creds_dict()):
            live_engine._build_components()
        assert live_engine._api_client is not None
        assert isinstance(live_engine._api_client, cTraderAPIClient)
        # And still an OpenApiSpotFeed (subclass)
        assert isinstance(live_engine._api_client, OpenApiSpotFeed)

    def test_paper_trader_receives_api_client_in_live_mode(self, live_engine):
        """PaperTrader.api_client is the same cTraderAPIClient instance."""
        with patch.object(live_engine, "_build_live_credentials", return_value=_live_creds_dict()):
            live_engine._build_components()
        assert live_engine._paper_trader._api_client is live_engine._api_client
        # And is_live_mode is True because the api_client is not in paper mode
        assert live_engine._paper_trader.is_live_mode is True

    def test_order_manager_receives_api_client_in_live_mode(self, live_engine):
        """OrderManager (constructed inside PaperTrader) gets the api_client."""
        with patch.object(live_engine, "_build_live_credentials", return_value=_live_creds_dict()):
            live_engine._build_components()
        # OrderManager._api_client should be the live client
        om = live_engine._paper_trader._order_manager
        assert om._api_client is live_engine._api_client


class TestCalculateLiveVolumeIndependentOfPaperTrader:
    """``_calculate_live_volume`` must work even when ``_paper_trader is None``."""

    def test_volume_positive_with_no_paper_trader(self, live_engine):
        """If the engine is live-only, volume still computes from PositionSizeConfig."""
        live_engine._paper_trader = None
        sig = _make_signal()
        v = live_engine._calculate_live_volume(sig)
        assert v > 0.0, f"expected positive volume, got {v}"

    def test_volume_uses_paper_trader_when_available(self, live_engine):
        """If paper_trader is present, use its OrderManager.calculate_position_size."""
        live_engine._paper_trader = MagicMock()
        live_engine._paper_trader.balance = 10000.0
        live_engine._paper_trader._order_manager.calculate_position_size.return_value = 0.25
        sig = _make_signal()
        v = live_engine._calculate_live_volume(sig)
        assert v == 0.25

    def test_volume_zero_when_sl_is_none(self, live_engine):
        """A signal with stop_loss=None should yield volume=0.0 (pre-flight fail)."""
        live_engine._paper_trader = None
        sig = _make_signal()
        sig.stop_loss = None
        v = live_engine._calculate_live_volume(sig)
        assert v == 0.0

    def test_volume_default_when_sl_distance_is_zero(self, live_engine):
        """SL == entry_price → distance=0 → fallback to default_lot_size."""
        from adapters.ctrader.order_manager import PositionSizeConfig

        live_engine._paper_trader = None
        live_engine._position_config = PositionSizeConfig(default_lot_size=0.42)
        sig = _make_signal()
        sig.stop_loss = sig.entry_price  # distance = 0
        v = live_engine._calculate_live_volume(sig)
        assert v == 0.42


class TestExecuteSignalLiveWorksWithoutPaperTrader:
    """``_execute_signal_live`` returns a non-None outcome even if ``_paper_trader is None``."""

    def test_outcome_filled_when_paper_trader_is_none(self, live_engine):
        """Simulate the post-T4 state: live engine, no paper trader.

        A well-formed signal returns a non-None ``LiveExecutionOutcome``
        (FILLED, in this case) because ``_calculate_live_volume`` works
        without PaperTrader.
        """
        with patch.object(live_engine, "_build_live_credentials", return_value=_live_creds_dict()):
            live_engine._build_components()

        # Pretend the PaperTrader was never built (post-T4 race or test scenario).
        live_engine._paper_trader = None

        sig = _make_signal()
        filled_order = Order(
            order_id="ord_filled",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type="MARKET",
            volume=10000,
            status=OrderStatus.FILLED,
        )
        filled_order.reason = "order_filled"

        feed = live_engine._market_feed
        # The spot feed's _state_mgr uses an enum from
        # archive.legacy_ctrader._pkg.connection_state.  Patch the
        # ``is_operational`` property directly to True so the not-connected
        # branch in ``_execute_signal_live`` doesn't short-circuit.
        type(feed._state_mgr).is_operational = property(lambda self: True)
        feed.resolve_symbol_id = MagicMock(return_value=1)
        feed.lots_to_volume = MagicMock(return_value=10000)
        feed.new_order = MagicMock(return_value=filled_order)

        outcome = live_engine._execute_signal_live(sig, strategy_id="test")

        assert outcome is not None
        assert outcome.status is LiveExecutionStatus.FILLED
        # The new_order call used the volume from the live-only sizing path
        call_kwargs = feed.new_order.call_args.kwargs
        assert call_kwargs["volume"] > 0

    def test_outcome_sent_when_feed_acknowledges_but_no_fill(self, live_engine):
        """PENDING order → SENT outcome — works without paper_trader too."""
        with patch.object(live_engine, "_build_live_credentials", return_value=_live_creds_dict()):
            live_engine._build_components()
        live_engine._paper_trader = None

        sig = _make_signal()
        pending_order = Order(
            order_id="ord_pending",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            order_type="MARKET",
            volume=10000,
            status=OrderStatus.PENDING,
        )

        feed = live_engine._market_feed
        type(feed._state_mgr).is_operational = property(lambda self: True)
        feed.resolve_symbol_id = MagicMock(return_value=1)
        feed.lots_to_volume = MagicMock(return_value=10000)
        feed.new_order = MagicMock(return_value=pending_order)

        outcome = live_engine._execute_signal_live(sig, strategy_id="test")

        assert outcome is not None
        assert outcome.status is LiveExecutionStatus.SENT
