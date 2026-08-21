"""Unit tests for PositionMonitor TP2/TP3 ratcheting (Sprint Task 1.5, card a7b8e896).

Tests cover F5 fix — when price crosses TP2/TP3 on a position the broker TP must
be ratcheted (advance to the crossed level) and SL moved accordingly:

  - LONG TP2 crossed : amend SL=entry_price (breakeven), TP=tp2
  - LONG TP3 crossed : amend SL=tp2 (lock in), TP=tp3
  - SHORT TP2 crossed: amend SL=entry_price, TP=tp2
  - SHORT TP3 crossed: amend SL=tp2, TP=tp3

Idempotency comes from ``Position.tp_levels_fired`` (appended only when the
broker amend returns True) so transient broker failures retry next tick.

What we DO NOT cover here (pre-existing, separate cards):
  - ProtoOAAmendPositionSLTPReq single-TP constraint (F4)
  - position_monitor.update_positions MAE/MFE / water marks (covered in
    tests/unit/execution/test_position_monitor.py)
"""

from unittest.mock import MagicMock

import pytest
from adapters.ctrader.models import (
    Position,
    TradeDirection,
)
from adapters.ctrader.order_manager import OrderManager, PositionSizeConfig
from adapters.ctrader.position_monitor import PositionMonitor, TpRatchetAction
from adapters.ctrader.risk_guard import FTMOConfig, RiskGuard

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def order_manager():
    return OrderManager(position_config=PositionSizeConfig())


@pytest.fixture
def risk_guard():
    return RiskGuard(ftmo_config=FTMOConfig(), starting_balance=100000.0)


@pytest.fixture
def kill_switch():
    ks = MagicMock()
    ks.is_globally_killed.return_value = False
    ks.is_globally_frozen.return_value = False
    ks.is_active.return_value = False
    return ks


@pytest.fixture
def mock_market_feed():
    """A MagicMock that satisfies PositionMonitor._market_feed usage:

    - resolve_symbol_id(name) -> int
    - amend_sl_tp(position_id, sl, tp, *, symbol_id=None) -> bool

    Both attributes are MagicMocks so tests can assert calls and stub
    return values.
    """
    feed = MagicMock()
    feed.resolve_symbol_id.return_value = 12345
    feed.amend_sl_tp.return_value = True
    return feed


@pytest.fixture
def monitor(order_manager, kill_switch, mock_market_feed):
    return PositionMonitor(
        order_manager=order_manager,
        risk_guard=None,
        kill_switch=kill_switch,
        market_feed=mock_market_feed,
    )


def _make_long_position_with_tps(
    order_manager,
    symbol: str = "EURUSD",
    entry: float = 1.1000,
    tp1: float = 1.1100,
    tp2: float = 1.1150,
    tp3: float = 1.1200,
    sl: float = 1.0950,
    volume: float = 0.1,
) -> Position:
    """Create a long position with TP1/TP2/TP3 via the paper order path.

    The OrderManager picks tp2/tp3 off the Order and stashes them on the
    Position dataclass — exactly what B4 wired for live fills.
    """
    result = order_manager.execute_paper_order(
        symbol=symbol,
        direction=TradeDirection.LONG,
        volume=volume,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        comment="ratchet_test",
    )
    return result.position


def _make_short_position_with_tps(
    order_manager,
    symbol: str = "EURUSD",
    entry: float = 1.1000,
    tp1: float = 1.0900,
    tp2: float = 1.0850,
    tp3: float = 1.0800,
    sl: float = 1.1050,
    volume: float = 0.1,
) -> Position:
    """Create a short position with TP1/TP2/TP3 via the paper order path."""
    result = order_manager.execute_paper_order(
        symbol=symbol,
        direction=TradeDirection.SHORT,
        volume=volume,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        comment="ratchet_test",
    )
    return result.position


# ── 1. check_tp_levels exists and returns AmendAction-shaped records ──────────


class TestCheckTpLevelsSignature:
    def test_method_present(self, monitor):
        assert hasattr(monitor, "check_tp_levels")
        assert callable(monitor.check_tp_levels)

    def test_returns_list(self, monitor, order_manager):
        # No positions → empty list, never None, never raises
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1000})
        assert isinstance(result, list)
        assert result == []

    def test_returns_tp_ratchet_action_records(self, monitor, order_manager):
        _make_long_position_with_tps(order_manager, tp2=1.1050, tp3=1.1100)
        # Mid price is well below TP2 — no action.
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1020})
        assert result == []


# ── 2. LONG: TP2 crossing ────────────────────────────────────────────────────


class TestLongTp2Crossing:
    def test_long_bid_crosses_tp2_amends_breakeven(self, monitor, order_manager, mock_market_feed):
        pos = _make_long_position_with_tps(
            order_manager,
            entry=1.1000,
            tp1=1.1050,
            tp2=1.1100,
            tp3=1.1150,
        )
        # Paper-order applies slippage to the fill price; the breakeven SL
        # the ratchet uses is the actual stored entry_price, not the
        # requested signal entry.
        entry_after_slippage = pos.entry_price
        # Mid price reaches TP2 (>= 1.1100) → fire TP2 ratchet.
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1110})

        assert len(result) == 1
        action = result[0]
        assert isinstance(action, TpRatchetAction)
        assert action.position_id == pos.position_id
        assert action.level == 2
        assert action.amend_status == "fired"
        # SL must be the original entry (breakeven), not the current price.
        assert action.new_sl == pytest.approx(entry_after_slippage)
        # TP must equal the TP2 level we set.
        assert action.new_tp == pos.take_profit_2
        assert action.new_tp == pytest.approx(1.1100)
        # Broker amend called with (position_id, sl=breakeven, tp=tp2)
        mock_market_feed.amend_sl_tp.assert_called_once()
        args, kwargs = mock_market_feed.amend_sl_tp.call_args
        # Positional: (position_id, sl, tp)
        assert args[0] == pos.position_id
        assert args[1] == pytest.approx(entry_after_slippage)
        assert args[2] == pytest.approx(pos.take_profit_2)
        # symbol_id resolved from market_feed
        assert kwargs.get("symbol_id") == 12345

    def test_long_tp2_appended_to_tp_levels_fired(self, monitor, order_manager, mock_market_feed):
        pos = _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)
        assert pos.tp_levels_fired == []
        monitor.check_tp_levels(prices={"EURUSD": 1.1110})
        assert pos.tp_levels_fired == [2]


# ── 3. LONG: TP3 crossing ────────────────────────────────────────────────────


class TestLongTp3Crossing:
    def test_long_bid_crosses_tp3_amends_sl_tp2(self, monitor, order_manager, mock_market_feed):
        pos = _make_long_position_with_tps(
            order_manager,
            entry=1.1000,
            tp1=1.1050,
            tp2=1.1100,
            tp3=1.1150,
        )
        # Pre-seed TP2 fired so this call isolates TP3.
        pos.tp_levels_fired = [2]
        mock_market_feed.amend_sl_tp.reset_mock()
        # Mid price above TP3 → fire TP3 ratchet (SL locked to TP2).
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1160})

        assert len(result) == 1
        action = result[0]
        assert action.position_id == pos.position_id
        assert action.level == 3
        assert action.amend_status == "fired"
        # SL must equal take_profit_2 (lock in TP1 profit), not breakeven.
        assert action.new_sl == pos.take_profit_2
        assert action.new_tp == pos.take_profit_3

        mock_market_feed.amend_sl_tp.assert_called_once()
        args, kwargs = mock_market_feed.amend_sl_tp.call_args
        assert args[0] == pos.position_id
        assert args[1] == pytest.approx(pos.take_profit_2)
        assert args[2] == pytest.approx(pos.take_profit_3)
        assert kwargs.get("symbol_id") == 12345

    def test_long_tp3_appended_to_tp_levels_fired(self, monitor, order_manager, mock_market_feed):
        pos = _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)
        # Pre-seed tp_levels_fired so we can isolate TP3 ratchet behavior.
        pos.tp_levels_fired = [2]
        monitor.check_tp_levels(prices={"EURUSD": 1.1160})
        assert pos.tp_levels_fired == [2, 3]


# ── 4. SHORT: TP2 crossing ───────────────────────────────────────────────────


class TestShortTp2Crossing:
    def test_short_ask_crosses_tp2_amends_breakeven(self, monitor, order_manager, mock_market_feed):
        pos = _make_short_position_with_tps(
            order_manager,
            entry=1.1000,
            tp1=1.0950,
            tp2=1.0900,
            tp3=1.0850,
        )
        entry_after_slippage = pos.entry_price
        # Mid price drops to TP2 (<= 1.0900) → fire SHORT TP2 ratchet.
        result = monitor.check_tp_levels(prices={"EURUSD": 1.0890})

        assert len(result) == 1
        action = result[0]
        assert action.position_id == pos.position_id
        assert action.level == 2
        assert action.amend_status == "fired"
        # SL must move to breakeven (entry), not current price.
        assert action.new_sl == pytest.approx(entry_after_slippage)
        assert action.new_tp == pos.take_profit_2

        mock_market_feed.amend_sl_tp.assert_called_once()
        args, kwargs = mock_market_feed.amend_sl_tp.call_args
        assert args[0] == pos.position_id
        assert args[1] == pytest.approx(entry_after_slippage)
        assert args[2] == pytest.approx(pos.take_profit_2)


# ── 5. SHORT: TP3 crossing ───────────────────────────────────────────────────


class TestShortTp3Crossing:
    def test_short_ask_crosses_tp3_amends_sl_tp2(self, monitor, order_manager, mock_market_feed):
        pos = _make_short_position_with_tps(
            order_manager,
            entry=1.1000,
            tp1=1.0950,
            tp2=1.0900,
            tp3=1.0850,
        )
        # Pre-seed TP2 fired so this call isolates TP3.
        pos.tp_levels_fired = [2]
        mock_market_feed.amend_sl_tp.reset_mock()
        # Mid price drops to TP3 (<= 1.0850) → fire SHORT TP3 ratchet.
        result = monitor.check_tp_levels(prices={"EURUSD": 1.0840})

        assert len(result) == 1
        action = result[0]
        assert action.position_id == pos.position_id
        assert action.level == 3
        assert action.amend_status == "fired"
        # SL = tp2 (lock in TP1 profit).
        assert action.new_sl == pos.take_profit_2
        assert action.new_tp == pos.take_profit_3

        mock_market_feed.amend_sl_tp.assert_called_once()
        args, kwargs = mock_market_feed.amend_sl_tp.call_args
        assert args[0] == pos.position_id
        assert args[1] == pytest.approx(pos.take_profit_2)
        assert args[2] == pytest.approx(pos.take_profit_3)


# ── 6. Idempotency ───────────────────────────────────────────────────────────


class TestIdempotency:
    def test_tp2_only_fires_once_when_price_remains_above(self, monitor, order_manager, mock_market_feed):
        pos = _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)
        # First tick: crosses TP2 → fire.
        monitor.check_tp_levels(prices={"EURUSD": 1.1110})
        assert pos.tp_levels_fired == [2]
        # Second tick: still above TP2 → no re-fire, no amend call.
        mock_market_feed.amend_sl_tp.reset_mock()
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1120})
        assert result == []
        mock_market_feed.amend_sl_tp.assert_not_called()
        assert pos.tp_levels_fired == [2]

    def test_tp3_only_fires_once_when_price_remains_above(self, monitor, order_manager, mock_market_feed):
        pos = _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)
        # Pre-fire TP2 so we can isolate TP3.
        pos.tp_levels_fired = [2]
        mock_market_feed.amend_sl_tp.reset_mock()
        monitor.check_tp_levels(prices={"EURUSD": 1.1160})
        assert pos.tp_levels_fired == [2, 3]
        # Next tick above TP3 → silent.
        mock_market_feed.amend_sl_tp.reset_mock()
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1170})
        assert result == []
        mock_market_feed.amend_sl_tp.assert_not_called()


# ── 7. None TP2 / TP3 graceful skip ──────────────────────────────────────────


class TestNoneTpLevels:
    def test_position_without_tp2_or_tp3_is_skipped(self, monitor, order_manager, mock_market_feed):
        """No TP2/TP3 → no ratchet, no amend call, no exception."""
        result = order_manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            comment="no_multi_tp",
        )
        pos = result.position
        assert pos.take_profit_2 is None
        assert pos.take_profit_3 is None

        actions = monitor.check_tp_levels(prices={"EURUSD": 1.2000})
        assert actions == []
        mock_market_feed.amend_sl_tp.assert_not_called()

    def test_position_with_only_tp2_no_tp3(self, monitor, order_manager, mock_market_feed):
        pos_result = order_manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            take_profit_2=1.1150,
            take_profit_3=None,
            comment="tp2_only",
        )
        pos = pos_result.position
        assert pos.take_profit_2 == 1.1150
        assert pos.take_profit_3 is None

        # Mid way above both tp2 and the "would-be" tp3 — tp3 skipped, tp2 fires.
        actions = monitor.check_tp_levels(prices={"EURUSD": 1.1200})
        assert len(actions) == 1
        assert actions[0].level == 2
        assert pos.tp_levels_fired == [2]

    def test_position_with_only_tp3_no_tp2_is_skipped(self, monitor, order_manager, mock_market_feed):
        """TP3 without TP2 cannot safely ratchet — log + skip.

        The SL anchor for TP3 is TP2 (lock-in). Without TP2 we don't know
        the right SL, so we skip rather than guess.
        """
        pos_result = order_manager.execute_paper_order(
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            volume=0.1,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1050,
            take_profit_2=None,
            take_profit_3=1.1150,
            comment="tp3_only",
        )
        pos = pos_result.position
        assert pos.take_profit_2 is None
        assert pos.take_profit_3 == 1.1150

        actions = monitor.check_tp_levels(prices={"EURUSD": 1.2000})
        # TP3 can't anchor (no TP2) — level 3 iteration bails out on the
        # ``if tp2 is None: continue`` branch and never produces an action.
        # (No TP2 also means no TP2 fire, obviously.)
        assert actions == []
        mock_market_feed.amend_sl_tp.assert_not_called()


# ── 8. Multi-position batch ──────────────────────────────────────────────────


class TestMultiplePositions:
    def test_two_long_positions_each_at_different_levels(self, monitor, order_manager, mock_market_feed):
        # Position A — has only crossed TP1, TP2 not yet.
        pos_a = _make_long_position_with_tps(order_manager, symbol="EURUSD", entry=1.1000, tp2=1.1150, tp3=1.1200)
        # Position B — already past TP3.
        pos_b = _make_long_position_with_tps(order_manager, symbol="GBPUSD", entry=1.2500, tp2=1.2650, tp3=1.2700)

        # Mid prices above TP2 only for EURUSD; GBPUSD still below.
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1160, "GBPUSD": 1.2600})

        # Only one action: EURUSD TP2 ratchet. GBPUSD fires nothing.
        assert len(result) == 1
        assert result[0].position_id == pos_a.position_id
        assert result[0].level == 2
        assert pos_a.tp_levels_fired == [2]
        # GBPUSD is not yet at its TP2 (1.2650), so untouched.
        assert pos_b.tp_levels_fired == []
        # Only one broker amend call.
        assert mock_market_feed.amend_sl_tp.call_count == 1

    def test_long_and_short_in_same_tick(self, monitor, order_manager, mock_market_feed):
        pos_long = _make_long_position_with_tps(order_manager, symbol="EURUSD", entry=1.1000, tp2=1.1100, tp3=1.1150)
        pos_short = _make_short_position_with_tps(order_manager, symbol="GBPUSD", entry=1.3000, tp2=1.2900, tp3=1.2850)

        # Long on EURUSD hits TP2; short on GBPUSD hits TP2.
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1110, "GBPUSD": 1.2895})

        # Two actions, one per position, both level 2.
        by_pos = {a.position_id: a for a in result}
        assert pos_long.position_id in by_pos
        assert pos_short.position_id in by_pos
        assert by_pos[pos_long.position_id].level == 2
        assert by_pos[pos_short.position_id].level == 2
        # Two broker amend calls (one per position).
        assert mock_market_feed.amend_sl_tp.call_count == 2


# ── 9. update_positions integration ─────────────────────────────────────────


class TestUpdatePositionsIntegration:
    def test_update_positions_calls_check_tp_levels(self, monitor, order_manager, mock_market_feed):
        """update_positions() must invoke check_tp_levels every tick so
        ratcheting is wired into the existing lifecycle loop."""
        # Spy on check_tp_levels.
        original = monitor.check_tp_levels
        calls = []

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        monitor.check_tp_levels = spy

        pos = _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1200)

        # Use a price strictly between tp2 and tp3 so only one level fires.
        monitor.update_positions(
            prices={"EURUSD": 1.1120},
            bids={"EURUSD": 1.1119},
            asks={"EURUSD": 1.1121},
        )
        # Spy should have been called once via update_positions.
        assert len(calls) == 1
        # Exactly one amend_sl_tp call (TP2 ratchet only).
        mock_market_feed.amend_sl_tp.assert_called_once()
        assert pos.tp_levels_fired == [2]  # TP3 didn't fire

    def test_update_positions_ratchets_through_loop(self, monitor, order_manager, mock_market_feed):
        pos = _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)

        # Tick 1: price at TP2 (but well below TP3) → fires TP2 only,
        # SL moves to breakeven.
        monitor.update_positions(
            prices={"EURUSD": 1.1110},
            bids={"EURUSD": 1.1109},
            asks={"EURUSD": 1.1111},
        )
        assert pos.tp_levels_fired == [2]
        first_call_args = mock_market_feed.amend_sl_tp.call_args_list[-1]
        assert first_call_args.args[1] == pytest.approx(pos.entry_price)
        assert first_call_args.args[2] == pytest.approx(pos.take_profit_2)

        # Tick 2: price at TP3 → fires TP3, SL moves to TP2.
        mock_market_feed.amend_sl_tp.reset_mock()
        monitor.update_positions(
            prices={"EURUSD": 1.1160},
            bids={"EURUSD": 1.1159},
            asks={"EURUSD": 1.1161},
        )
        assert pos.tp_levels_fired == [2, 3]
        assert mock_market_feed.amend_sl_tp.call_count == 1
        last_call_args = mock_market_feed.amend_sl_tp.call_args
        assert last_call_args.args[1] == pytest.approx(pos.take_profit_2)
        assert last_call_args.args[2] == pytest.approx(pos.take_profit_3)


# ── 10. amend_cb failure semantics ──────────────────────────────────────────


class TestAmendFailures:
    def test_broker_amend_failure_does_not_set_idempotency(self, monitor, order_manager, mock_market_feed):
        """Transient broker failure must NOT mark the level as fired.

        If we appended, a stuck amend would silently disable the ratchet.
        The next tick should retry.
        """
        mock_market_feed.amend_sl_tp.return_value = False
        pos = _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)

        result = monitor.check_tp_levels(prices={"EURUSD": 1.1110})
        assert len(result) == 1
        assert result[0].amend_status == "amend_failed"
        # tp_levels_fired NOT updated → next tick will retry.
        assert pos.tp_levels_fired == []

        # Next tick: retry still fires.
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1120})
        assert len(result) == 1
        assert result[0].amend_status == "amend_failed"
        assert pos.tp_levels_fired == []

    def test_broker_amend_success_does_set_idempotency(self, monitor, order_manager, mock_market_feed):
        mock_market_feed.amend_sl_tp.return_value = True
        pos = _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)

        monitor.check_tp_levels(prices={"EURUSD": 1.1110})
        assert pos.tp_levels_fired == [2]
        # Subsequent tick should be silent.
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1120})
        assert result == []

    def test_no_market_feed_returns_no_feed_status(self, order_manager):
        """Without a market_feed, we still detect crossings and surface them
        as ``no_feed`` actions — caller can route to a manual fix-up path."""
        # No market_feed wired this time.
        monitor = PositionMonitor(
            order_manager=order_manager,
            market_feed=None,
        )
        _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1110})
        assert len(result) == 1
        assert result[0].amend_status == "no_feed"


# ── 11. Price below TP2 / no cross ───────────────────────────────────────────


class TestNoCross:
    def test_long_price_below_tp2_no_action(self, monitor, order_manager, mock_market_feed):
        _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1020})
        assert result == []
        mock_market_feed.amend_sl_tp.assert_not_called()

    def test_short_price_above_tp2_no_action(self, monitor, order_manager, mock_market_feed):
        _make_short_position_with_tps(order_manager, entry=1.1000, tp2=1.0900, tp3=1.0850)
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1050})
        assert result == []
        mock_market_feed.amend_sl_tp.assert_not_called()

    def test_price_exactly_at_tp2_triggers(self, monitor, order_manager, mock_market_feed):
        """Boundary: at-or-above is a cross (using >= for LONG / <= for SHORT)."""
        _make_long_position_with_tps(order_manager, entry=1.1000, tp2=1.1100, tp3=1.1150)
        result = monitor.check_tp_levels(prices={"EURUSD": 1.1100})
        assert len(result) == 1
        assert result[0].level == 2
