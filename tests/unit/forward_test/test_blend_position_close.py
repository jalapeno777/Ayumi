"""Regression coverage for blend position mirroring and SL/TP closure.

The blend runner registers risk under a canonical strategy/timestamp identity.  A
paper execution callback can carry a synthetic default identity; the mapping
boundary must still resolve the canonical identity and make the position
visible to the paper order manager's price loop.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from adapters.ctrader.models import Position, PositionStatus, TradeDirection
from adapters.ctrader.paper_trader import PaperTrader
from forward_test.blend_runner import BlendForwardTestRunner


def _runner(tmp_path) -> BlendForwardTestRunner:
    return BlendForwardTestRunner(
        config={
            "account_balance": 10_000.0,
            "risk_per_trade_pct": 0.005,
            "daily_risk_cap_pct": 0.05,
            "spread_pips": {},
            "state_path": str(tmp_path / "blend-risk.json"),
            "stats_log_path": str(tmp_path / "blend-stats.jsonl"),
        }
    )


def _signal_data(
    timestamp: datetime,
    *,
    direction: str = "LONG",
    entry: float = 3355.30,
    stop: float = 3350.37,
    target: float = 3365.00,
) -> dict:
    return {
        "strategy_id": "srmr_plus",
        "symbol": "XAUUSD",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": target,
        "confidence": 0.65,
        "spread": 0.5,
        "timestamp": timestamp,
    }


def test_blend_accepted_position_is_mirrored_and_closes_on_stop(tmp_path):
    """A synthetic callback identity still closes the accepted blend position."""
    runner = _runner(tmp_path)
    timestamp = datetime(2026, 9, 7, 17, 20, tzinfo=timezone.utc)
    order = runner.on_signal("srmr_plus", _signal_data(timestamp))
    assert not order.rejected

    adapted = runner._adapter.adapt_signal("srmr_plus", _signal_data(timestamp))
    canonical_id = runner.make_signal_id(adapted)
    position_id = "POS_PAPER_SYNTHETIC"
    paper_trader = PaperTrader(
        starting_balance=10_000.0,
        state_path=str(tmp_path / "paper-risk.json"),
        stats_log_path=str(tmp_path / "paper-stats.jsonl"),
    )

    runner.register_position_mapping(
        position_id,
        "_1788812400.0",
        paper_trader=paper_trader,
    )

    assert runner._position_id_to_signal_id[position_id] == canonical_id
    mirrored = paper_trader._order_manager.get_position(position_id)
    assert mirrored is not None
    assert mirrored.symbol == "XAUUSD"
    assert mirrored.direction == TradeDirection.LONG
    assert mirrored.volume == pytest.approx(order.lots)
    assert mirrored.entry_price == pytest.approx(3355.30)
    assert mirrored.stop_loss == pytest.approx(3350.37)
    assert mirrored.take_profit == pytest.approx(3365.00)

    paper_trader.update_market_prices({"XAUUSD": 3340.0})
    closed = paper_trader._order_manager.get_position(position_id)
    assert closed is not None
    assert closed.status is PositionStatus.CLOSED

    runner.close_position(position_id, pnl=closed.closed_pnl)
    assert runner._sizer.open_risk == pytest.approx(0.0)
    assert canonical_id not in runner._open_positions


def test_mapping_skips_cancelled_signal_when_synthetic_identity_arrives(tmp_path):
    """A rejected/cancelled older signal is not selected for a later fill."""
    runner = _runner(tmp_path)
    first_ts = datetime(2026, 9, 7, 17, 20, tzinfo=timezone.utc)
    second_ts = datetime(2026, 9, 7, 17, 21, tzinfo=timezone.utc)
    first = runner.on_signal("srmr_plus", _signal_data(first_ts))
    second = runner.on_signal("srmr_plus", _signal_data(second_ts))
    assert not first.rejected
    assert not second.rejected

    first_id = runner.make_signal_id(runner._adapter.adapt_signal("srmr_plus", _signal_data(first_ts)))
    second_id = runner.make_signal_id(runner._adapter.adapt_signal("srmr_plus", _signal_data(second_ts)))
    runner.cancel_risk(first_id, risk_amount=first.risk_amount)

    runner.register_position_mapping("POS_PAPER_ONLY_OPEN", "_1788812460.0")
    assert runner._position_id_to_signal_id["POS_PAPER_ONLY_OPEN"] == second_id
    assert first_id in runner._open_positions
    assert second_id in runner._open_positions
    assert first_id not in runner._sizer.open_positions

    runner.on_fill(second_id, fill_price=3355.30, pnl=0.0)
    assert second_id not in runner._open_positions
    assert runner._sizer.open_risk == pytest.approx(0.0)


def test_display_alias_cancel_risk_resolves_canonical_signal_id(tmp_path):
    """Launcher display-name aliases still release the canonical risk slot."""
    runner = _runner(tmp_path)
    timestamp = datetime(2026, 9, 7, 17, 20, tzinfo=timezone.utc)
    runner.on_signal("srmr_plus", _signal_data(timestamp))
    canonical_id = runner.make_signal_id(runner._adapter.adapt_signal("srmr_plus", _signal_data(timestamp)))
    display_id = f"SRMR Plus_{timestamp.timestamp()}"

    runner.cancel_risk(display_id, risk_amount=25.0)

    assert canonical_id not in runner._sizer.open_positions
    # The runner entry remains as a historical close record; future
    # resolution filters it because the sizer no longer reserves it.


def test_existing_paper_position_is_not_overwritten(tmp_path):
    """A normal paper fill retains its fill price and position identity."""
    runner = _runner(tmp_path)
    timestamp = datetime(2026, 9, 7, 17, 20, tzinfo=timezone.utc)
    runner.on_signal("srmr_plus", _signal_data(timestamp))

    paper_trader = PaperTrader(
        starting_balance=10_000.0,
        state_path=str(tmp_path / "paper-risk.json"),
        stats_log_path=str(tmp_path / "paper-stats.jsonl"),
    )
    existing = Position(
        position_id="POS_PAPER_EXISTING",
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        volume=0.07,
        entry_price=3356.25,
        current_price=3356.25,
        stop_loss=3350.37,
        take_profit=3365.00,
    )
    paper_trader._order_manager._positions[existing.position_id] = existing

    runner.bind_paper_trader(paper_trader)
    canonical_id = runner.make_signal_id(runner._adapter.adapt_signal("srmr_plus", _signal_data(timestamp)))
    runner.register_position_mapping(existing.position_id, "_1788812400.0")

    assert runner._position_id_to_signal_id[existing.position_id] == canonical_id
    assert paper_trader._order_manager.get_position(existing.position_id) is existing


# ---------------------------------------------------------------------------
# SHORT-mirroring regression (card aa2d0a90-7940-4022-af35-6ad6e47d8352,
# Rin REWORK verdict): the previous direction derivation did
#     str(signal.direction).upper()  ->  TradeDirection(value)
# but ``OrchestratorTradeSignal.direction`` is the uppercase string
# ``"LONG"``/``"SHORT"`` and ``TradeDirection`` is a ``StrEnum`` with
# lowercase members, so every branch raised ValueError and the fallback
# silently produced ``TradeDirection.LONG``.  Mirrored SHORT positions were
# therefore registered as LONG, with SL/TP semantics reversed and the
# eventual PnL sign inverted.  These tests pin the corrected mapping.
# ---------------------------------------------------------------------------


def test_resolve_mirror_direction_accepts_short_string():
    """The helper maps 'SHORT' to TradeDirection.SHORT, not LONG."""
    from forward_test.blend_runner import BlendForwardTestRunner

    sentinel_signal = type("S", (), {"direction": "SHORT"})()
    resolved = BlendForwardTestRunner._resolve_mirror_direction(
        sentinel_signal, TradeDirection, type("D", (), {"LONG": "L", "SHORT": "S"})
    )
    assert resolved is TradeDirection.SHORT

    long_signal = type("S", (), {"direction": "LONG"})()
    resolved_long = BlendForwardTestRunner._resolve_mirror_direction(
        long_signal, TradeDirection, type("D", (), {"LONG": "L", "SHORT": "S"})
    )
    assert resolved_long is TradeDirection.LONG

    # Lower-case strings must also be accepted (defensive against future
    # adapters that bypass the strategy_adapter upper-casing).
    lower_signal = type("S", (), {"direction": "short"})()
    resolved_lower = BlendForwardTestRunner._resolve_mirror_direction(
        lower_signal, TradeDirection, type("D", (), {"LONG": "L", "SHORT": "S"})
    )
    assert resolved_lower is TradeDirection.SHORT


def test_blend_short_position_is_mirrored_as_short_and_closes_on_take_profit(tmp_path):
    """A SHORT blend-accepted order mirrors as SHORT and closes on TP hit.

    Pin against the regression where every mirrored SHORT silently became
    LONG (reversed SL/TP semantics + inverted PnL).  The mirrored position
    must carry TradeDirection.SHORT, and a price move below the TP must
    close the position with a positive realized PnL.
    """
    runner = _runner(tmp_path)
    timestamp = datetime(2026, 9, 7, 17, 30, tzinfo=timezone.utc)
    # SHORT entry: SL above, TP below.  The earlier test only covered the
    # LONG case; this is the canonical SHORT geometry.
    order = runner.on_signal(
        "srmr_plus",
        _signal_data(
            timestamp,
            direction="SHORT",
            entry=3355.30,
            stop=3360.00,
            target=3345.00,
        ),
    )
    assert not order.rejected

    adapted = runner._adapter.adapt_signal(
        "srmr_plus",
        _signal_data(
            timestamp,
            direction="SHORT",
            entry=3355.30,
            stop=3360.00,
            target=3345.00,
        ),
    )
    canonical_id = runner.make_signal_id(adapted)
    position_id = "POS_PAPER_SYNTHETIC_SHORT"
    paper_trader = PaperTrader(
        starting_balance=10_000.0,
        state_path=str(tmp_path / "paper-risk.json"),
        stats_log_path=str(tmp_path / "paper-stats.jsonl"),
    )

    runner.register_position_mapping(
        position_id,
        "_1788814200.0",
        paper_trader=paper_trader,
    )

    assert runner._position_id_to_signal_id[position_id] == canonical_id
    mirrored = paper_trader._order_manager.get_position(position_id)
    assert mirrored is not None
    # Critical: direction must be SHORT, not LONG.  This is the regression
    # that the previous round-trip silently inverted.
    assert mirrored.direction is TradeDirection.SHORT
    assert mirrored.symbol == "XAUUSD"
    assert mirrored.volume == pytest.approx(order.lots)
    assert mirrored.entry_price == pytest.approx(3355.30)
    # SL/TP semantics for SHORT preserved: stop above entry, target below.
    assert mirrored.stop_loss == pytest.approx(3360.00)
    assert mirrored.take_profit == pytest.approx(3345.00)
    # Sanity: the mirrored SL/TP must NOT match the LONG geometry of the
    # same entry — otherwise the bug has reappeared.
    assert mirrored.stop_loss > mirrored.entry_price
    assert mirrored.take_profit < mirrored.entry_price

    # Drive the price below the SHORT take-profit and assert closure with
    # a positive realized PnL.  If the bug had returned, the position
    # would be tagged LONG with TP=3345 above entry, so 3340 would have
    # been below the (mirrored LONG) SL and produced a negative PnL.
    paper_trader.update_market_prices({"XAUUSD": 3340.0})
    closed = paper_trader._order_manager.get_position(position_id)
    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.closed_pnl > 0.0, (
        f"SHORT TP-hit must yield positive PnL; got {closed.closed_pnl}. "
        "Direction likely inverted back to LONG."
    )

    runner.close_position(position_id, pnl=closed.closed_pnl)
    assert runner._sizer.open_risk == pytest.approx(0.0)
    assert canonical_id not in runner._open_positions


def test_blend_short_position_closes_with_negative_pnl_on_stop_loss(tmp_path):
    """A SHORT hit on its SL must close with negative realized PnL.

    Complements the TP test by exercising the other side of the SL/TP
    asymmetry.  If the mirrored direction were silently flipped to LONG,
    a price above the (mirrored) SL would NOT trigger and the position
    would remain open, or the realized PnL would be positive.
    """
    runner = _runner(tmp_path)
    timestamp = datetime(2026, 9, 7, 17, 31, tzinfo=timezone.utc)
    order = runner.on_signal(
        "srmr_plus",
        _signal_data(
            timestamp,
            direction="SHORT",
            entry=3355.30,
            stop=3360.00,
            target=3345.00,
        ),
    )
    assert not order.rejected

    paper_trader = PaperTrader(
        starting_balance=10_000.0,
        state_path=str(tmp_path / "paper-risk-short-sl.json"),
        stats_log_path=str(tmp_path / "paper-stats-short-sl.jsonl"),
    )
    runner.register_position_mapping(
        "POS_PAPER_SHORT_SL",
        "_1788814260.0",
        paper_trader=paper_trader,
    )

    mirrored = paper_trader._order_manager.get_position("POS_PAPER_SHORT_SL")
    assert mirrored is not None
    assert mirrored.direction is TradeDirection.SHORT

    # Drive price above the SHORT stop-loss — should trigger closure with
    # negative PnL for a genuine SHORT.
    paper_trader.update_market_prices({"XAUUSD": 3365.0})
    closed = paper_trader._order_manager.get_position("POS_PAPER_SHORT_SL")
    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.closed_pnl < 0.0, (
        f"SHORT SL-hit must yield negative PnL; got {closed.closed_pnl}."
    )
