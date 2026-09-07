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
    entry: float = 3355.30,
    stop: float = 3350.37,
    target: float = 3365.00,
) -> dict:
    return {
        "strategy_id": "srmr_plus",
        "symbol": "XAUUSD",
        "direction": "LONG",
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
